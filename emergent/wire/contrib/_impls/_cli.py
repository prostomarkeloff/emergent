"""CLI compiler — compile wire Application/AppStack to argparse.

    from emergent.wire.contrib import cli

    parser = cli.from_application(app, prog="my-tool")
    cli.run_parser(parser)

Supports two codec types:

1. RequestResponseCodec:
   Arguments derived from request dataclass fields.
   - Plain fields → CLI arguments (type inferred from annotation)
   - Fields with defaults → optional flags (--field-name)
   - Fields without defaults → positional arguments
   - bool with default=False → --flag (store_true)
   - list fields → nargs="*"

   For custom CLI behavior, use schema capabilities in Annotated:
   - cli.Help("text") → argparse help
   - cli.Flag("--name", "-n") → custom flag names
   - cli.Choices("a", "b") → allowed values
   - cli.Positional() → force positional

2. StatefulCodec:
   Interactive multi-step flow. Prompts user until Done.
   No persistent store needed — state lives in memory during session.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import sys
import types
from typing import Any, Union, get_type_hints, get_origin, get_args, Annotated

from nodnod import Scope
from nodnod.agent.event_loop.agent import EventLoopAgent

from kungfu import Some, Nothing

from emergent.wire.axis.surface._app import Application
from emergent.wire.axis.surface._endpoint import Endpoint
from emergent.wire._handler import Handler
from emergent.wire._scan import StackView, scan_endpoint, scan_stack
from emergent.wire.axis.surface._stack import AppStack
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec, execute as rrc_execute
from emergent.wire.axis.surface.codecs.resolve import get_method_params, wrap
from emergent.wire.axis.surface.codecs.stateful import (
    StatefulCodec,
    parse_transition_result,
    get_transitions,
)
from emergent.wire.axis.surface.scope import run_stateful_middlewares
from emergent.wire.axis.surface.triggers.cli import CLITrigger

# CLI schema capabilities
from emergent.wire.axis.schema.dialects import cli as cli_caps


# ─── Capability Extraction ────────────────────────────────────────────────────


def _get_cli_capabilities(field_type: Any) -> dict[str, Any]:
    """Extract CLI capabilities from Annotated type.

    Returns dict with argparse kwargs derived from capabilities.
    """
    result: dict[str, Any] = {}

    # Check if it's Annotated
    if get_origin(field_type) is not Annotated:
        return result

    args = get_args(field_type)
    if len(args) < 2:
        return result

    # args[0] is the actual type, args[1:] are annotations
    for annotation in args[1:]:
        if isinstance(annotation, cli_caps.Help):
            result["help"] = annotation.text
        elif isinstance(annotation, cli_caps.Flag):
            result["flag_names"] = annotation.names
        elif isinstance(annotation, cli_caps.Positional):
            result["positional"] = True
            if annotation.name:
                result["positional_name"] = annotation.name
        elif isinstance(annotation, cli_caps.Choices):
            result["choices"] = list(annotation.values)
        elif isinstance(annotation, cli_caps.Nargs):
            result["nargs"] = annotation.count
        elif isinstance(annotation, cli_caps.Action):
            result["action"] = annotation.action
        elif isinstance(annotation, cli_caps.Append):
            result["action"] = "append"
        elif isinstance(annotation, cli_caps.Count):
            result["action"] = "count"
        elif isinstance(annotation, cli_caps.Metavar):
            result["metavar"] = annotation.name
        elif isinstance(annotation, cli_caps.Required):
            result["required"] = True
        elif isinstance(annotation, cli_caps.Env):
            result["env_var"] = annotation.var

    return result


def _unwrap_annotated(field_type: Any) -> Any:
    """Get the actual type from Annotated[T, ...] → T."""
    if get_origin(field_type) is Annotated:
        args = get_args(field_type)
        return args[0] if args else field_type
    return field_type


# ─── Request Parsing ───────────────────────────────────────────────────────────


def _is_list_type(type_hint: Any) -> bool:
    """Check if type hint is list[...] or List[...]."""
    import typing
    unwrapped = _unwrap_annotated(type_hint)
    origin = getattr(unwrapped, "__origin__", None)
    return origin is list or origin is typing.List


def _args_from_request(
    req_cls: type[Any],
) -> tuple[tuple[str, dict[str, Any]], ...]:
    """Derive argparse arguments from request type's dataclass fields.

    Rules:
    - Plain fields → positional or --flag based on default
    - Annotated fields → use CLI capabilities for customization
    - If request has __compose__, only Annotated fields become CLI args
    """
    args: list[tuple[str, dict[str, Any]]] = []
    has_compose = hasattr(req_cls, "__compose__")
    hints = get_type_hints(req_cls, include_extras=True)

    for f in dataclasses.fields(req_cls):
        field_type = hints.get(f.name)
        caps = _get_cli_capabilities(field_type) if field_type else {}

        # If request uses __compose__, skip fields without CLI capabilities
        # (they will be composed via nodnod)
        if has_compose and not caps and get_origin(field_type) is not Annotated:
            continue

        kwargs: dict[str, Any] = {}

        # Apply capabilities
        if "help" in caps:
            kwargs["help"] = caps["help"]
        if "choices" in caps:
            kwargs["choices"] = caps["choices"]
        if "nargs" in caps:
            kwargs["nargs"] = caps["nargs"]
        if "action" in caps:
            kwargs["action"] = caps["action"]
        if "metavar" in caps:
            kwargs["metavar"] = caps["metavar"]
        if "required" in caps:
            kwargs["required"] = caps["required"]

        has_default = f.default is not dataclasses.MISSING
        has_default_factory = f.default_factory is not dataclasses.MISSING

        # Handle list types with nargs
        if field_type and _is_list_type(field_type):
            if "flag_names" in caps:
                name = caps["flag_names"][0]
                if len(caps["flag_names"]) > 1:
                    kwargs["aliases"] = list(caps["flag_names"][1:])
            else:
                name = f.name
            if "nargs" not in kwargs:
                kwargs["nargs"] = "*"  # zero or more by default
            if has_default:
                kwargs["default"] = f.default
            elif has_default_factory and callable(f.default_factory):
                kwargs["default"] = f.default_factory()
            args.append((name, kwargs))
            continue

        # Explicit flag names from capabilities
        if "flag_names" in caps:
            name = caps["flag_names"][0]
            kwargs["dest"] = f.name
            if has_default:
                kwargs["default"] = f.default
            args.append((name, kwargs))
            continue

        # Force positional
        if caps.get("positional"):
            name = caps.get("positional_name") or f.name
            args.append((name, kwargs))
            continue

        # Custom action
        if "action" in caps:
            name = f"--{f.name.replace('_', '-')}"
            kwargs["dest"] = f.name
            if has_default:
                kwargs["default"] = f.default
            args.append((name, kwargs))
            continue

        # Bool with False default → store_true flag
        if f.default is False:
            name = f"--{f.name.replace('_', '-')}"
            kwargs["action"] = "store_true"
            kwargs["default"] = False
            args.append((name, kwargs))
            continue

        # Has default → optional --flag
        if has_default:
            name = f"--{f.name.replace('_', '-')}"
            kwargs["default"] = f.default
            args.append((name, kwargs))
            continue

        # No default → positional
        name = f.name
        args.append((name, kwargs))

    return tuple(args)


def _construct_request(req_cls: type[Any], ns: argparse.Namespace) -> Any:
    """Construct request type from Namespace by matching dataclass fields."""
    ns_dict = vars(ns)
    hints = get_type_hints(req_cls)
    kwargs = {k: v for k, v in ns_dict.items() if k in hints}
    return req_cls(**kwargs)


async def _compose_request(req_cls: type[Any], ns: argparse.Namespace) -> Any:
    """Compose request via nodnod if __compose__ exists, else construct from namespace.

    This enables dependency injection for CLI requests:
    - Request can depend on CLISession node (for auth)
    - Request can depend on other nodes for config, etc.
    """
    if not hasattr(req_cls, "__compose__"):
        return _construct_request(req_cls, ns)

    # nodnod compose path
    async with Scope() as scope:
        # Inject CLI-specific context
        scope.inject(argparse.Namespace, ns)

        # Build and run agent for request type
        agent = EventLoopAgent.build({req_cls})
        await agent.run(local_scope=scope, mapped_scopes={})  # type: ignore[arg-type]

        # Retrieve composed request
        from kungfu import Some, Nothing

        result = scope.retrieve(req_cls)
        match result:
            case Some(value):
                return value.value
            case Nothing():
                raise RuntimeError(f"Failed to compose {req_cls.__name__}")


# ─── RRC Handler ───────────────────────────────────────────────────────────────


def _wrap_rrc_handler(handler: Handler[RequestResponseCodec]) -> Any:
    """Wrap RRC Handler in CLI-compatible async function.

    If request has __compose__, uses nodnod composition (enables DI).
    Otherwise falls back to simple dataclass construction from args.
    """
    req_cls = handler.codec.request

    async def _handler(args: argparse.Namespace) -> str:
        request = await _compose_request(req_cls, args)
        response = await rrc_execute(handler, request)
        return str(response)

    return _handler


# ─── StatefulCodec Handler ─────────────────────────────────────────────────────


def _call_from_domain(response_type: type | types.UnionType, result: Any) -> Any:
    """Call from_domain on response type, handling Union types."""
    # Direct type with from_domain
    if hasattr(response_type, "from_domain"):
        return response_type.from_domain(result)  # type: ignore[union-attr]

    # Union type — find member with from_domain
    origin = get_origin(response_type)
    if origin is Union or isinstance(response_type, types.UnionType):
        for member in get_args(response_type):
            if hasattr(member, "from_domain"):
                return member.from_domain(result)

    raise TypeError(f"Response type {response_type} has no from_domain method")


def _prompt_for_value(name: str, type_hint: type) -> Any:
    """Prompt user for a value. Returns parsed value or None on failure."""
    try:
        raw = input(f"{name}: ").strip()
        if not raw:
            return None

        # Basic type coercion
        if type_hint is int:
            return int(raw)
        if type_hint is float:
            return float(raw)
        if type_hint is bool:
            return raw.lower() in ("true", "yes", "1", "y")
        return raw
    except (ValueError, EOFError, KeyboardInterrupt):
        return None


async def _run_stateful_flow(
    handler: Handler[StatefulCodec],
    initial_args: argparse.Namespace,
) -> str:
    """Run stateful flow interactively until Done."""
    flow_cls = handler.codec.flow
    response_cls = handler.codec.response
    middlewares = handler.codec.middlewares
    agent_cls = handler.codec.agent_cls

    # Initialize flow state
    state = flow_cls()
    transitions = get_transitions(flow_cls)

    while True:
        # Try to resolve a transition
        async with Scope() as scope:
            # Inject initial args and state
            scope.inject(argparse.Namespace, initial_args)

            agent = agent_cls.build(set())  # type: ignore[var-annotated]

            # Try each transition method
            resolved_method = None
            resolved_params: dict[str, Any] = {}

            for method in transitions:
                params_spec = get_method_params(method)
                params: dict[str, Any] = {}
                all_resolved = True

                for param_name, (wrapper_type, compose_type) in params_spec.items():
                    # Try to get from initial args
                    if hasattr(initial_args, param_name):
                        val = getattr(initial_args, param_name)
                        if val is not None:
                            params[param_name] = wrap(wrapper_type, True, val)
                            continue

                    # Try to compose
                    try:
                        await agent.run(local_scope=scope, mapped_scopes={})  # type: ignore[arg-type]
                        result = scope.retrieve(compose_type)
                        match result:
                            case Some(v):
                                params[param_name] = wrap(wrapper_type, True, v.value)
                                continue
                            case Nothing():
                                pass
                    except Exception:
                        pass

                    # Prompt user
                    val = _prompt_for_value(param_name, compose_type)
                    if val is not None:
                        params[param_name] = wrap(wrapper_type, True, val)
                    else:
                        all_resolved = False
                        break

                if all_resolved:
                    resolved_method = method
                    resolved_params = params
                    break

            if resolved_method is None:
                return "Error: Could not resolve any transition"

            # Execute transition
            result = await resolved_method(state, **resolved_params)
            parsed = parse_transition_result(result)

            if parsed.is_terminal:
                # Run middlewares and execute
                scope_extras, _ = await run_stateful_middlewares(middlewares, state)
                op = state.to_domain()  # type: ignore[union-attr]
                run_result = await handler.runner.run(op, scope_extras)  # type: ignore[arg-type]
                final_response = _call_from_domain(response_cls, run_result)
                return str(final_response)
            else:
                # Continue — update state and optionally print response
                state = parsed.state_or_done  # type: ignore[assignment]
                match parsed.response:
                    case Some(resp):
                        print(str(resp))
                    case Nothing():
                        pass


def _wrap_stateful_handler(handler: Handler[StatefulCodec]) -> Any:
    """Wrap StatefulCodec Handler in CLI-compatible async function."""

    async def _handler(args: argparse.Namespace) -> str:
        return await _run_stateful_flow(handler, args)

    return _handler


# ─── Endpoint Registration ─────────────────────────────────────────────────────


def add_endpoint_to_parser(
    subparsers: Any,
    endp: Endpoint,
) -> None:
    """Add endpoint to argparse subparsers."""
    for trigger, handler in scan_endpoint(endp, CLITrigger):
        sub = subparsers.add_parser(
            trigger.command,
            help=trigger.description,
        )

        # Derive args from request type
        if isinstance(handler.codec, RequestResponseCodec):
            for name, kwargs in _args_from_request(handler.codec.request):
                sub.add_argument(name, **kwargs)
            sub.set_defaults(_handler=_wrap_rrc_handler(handler))

        elif isinstance(handler.codec, StatefulCodec):
            # Stateful flows get minimal initial args
            sub.set_defaults(_handler=_wrap_stateful_handler(handler))


# ─── Application/Stack Compilation ─────────────────────────────────────────────


def from_application(
    app: Application,
    prog: str = "cli",
) -> argparse.ArgumentParser:
    """Compile Application to argparse parser."""
    parser = argparse.ArgumentParser(prog=prog)
    subparsers = parser.add_subparsers(dest="_command")

    for endp in app.endpoints:
        add_endpoint_to_parser(subparsers, endp)

    return parser


def from_app_stack(
    stack: AppStack,
    prog: str = "cli",
) -> argparse.ArgumentParser:
    """Compile AppStack to argparse parser with nested subcommands."""
    parser = argparse.ArgumentParser(prog=prog)

    def add_stack_view(
        parent_parser: argparse.ArgumentParser,
        view: StackView[CLITrigger],
        prefix: str = "",
    ) -> None:
        subparsers = parent_parser.add_subparsers(dest="_command")

        # Add root trigger/handler pairs
        for trigger, handler in view.root:
            sub = subparsers.add_parser(
                trigger.command,
                help=trigger.description,
            )
            if isinstance(handler.codec, RequestResponseCodec):
                for name, kwargs in _args_from_request(handler.codec.request):
                    sub.add_argument(name, **kwargs)
                sub.set_defaults(_handler=_wrap_rrc_handler(handler))
            elif isinstance(handler.codec, StatefulCodec):
                sub.set_defaults(_handler=_wrap_stateful_handler(handler))

        # Add mounted stacks recursively
        for mount_prefix, child in view.mounts.items():
            child_parser = subparsers.add_parser(mount_prefix)
            if isinstance(child, StackView):
                add_stack_view(child_parser, child, f"{prefix}{mount_prefix}/")
            else:
                # child is list[tuple[CLITrigger, Handler]] - add to child's subparsers
                child_subparsers = child_parser.add_subparsers(dest="_command")
                for trigger, handler in child:
                    sub = child_subparsers.add_parser(
                        trigger.command,
                        help=trigger.description,
                    )
                    if isinstance(handler.codec, RequestResponseCodec):
                        for name, kwargs in _args_from_request(handler.codec.request):
                            sub.add_argument(name, **kwargs)
                        sub.set_defaults(_handler=_wrap_rrc_handler(handler))
                    elif isinstance(handler.codec, StatefulCodec):
                        sub.set_defaults(_handler=_wrap_stateful_handler(handler))

    view = scan_stack(stack, CLITrigger)
    add_stack_view(parser, view)

    return parser


def run_parser(
    parser: argparse.ArgumentParser,
    args: list[str] | None = None,
) -> int:
    """Run parser and execute matched handler."""
    try:
        parsed = parser.parse_args(args)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1

    handler = getattr(parsed, "_handler", None)
    if handler is None:
        parser.print_help()
        return 0

    try:
        output = asyncio.run(handler(parsed))
        print(output)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(str(e), file=sys.stderr)
        return 1


# Alias for backwards compatibility
compile_to_argparse = from_application
