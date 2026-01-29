"""CLI compiler — compile wire Application/AppStack to argparse.

    from emergent.wire.contrib import cli

    parser = cli.from_application(app, prog="my-tool")
    cli.run_parser(parser)

Supports two codec types:

1. RequestResponseCodec:
   Arguments derived from request dataclass fields via cli_field().
   If request has __compose__, nodnod compose is used (enables DI).

2. StatefulCodec:
   Interactive multi-step flow. Prompts user until Done.
   No persistent store needed — state lives in memory during session.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import sys
from typing import Any, get_type_hints

from nodnod import Scope
from nodnod.agent.event_loop.agent import EventLoopAgent

from kungfu import Some, Nothing

from emergent.wire._app import Application
from emergent.wire._endpoint import Endpoint
from emergent.wire._handler import Handler
from emergent.wire._scan import StackView, scan, scan_endpoint, scan_stack
from emergent.wire._stack import AppStack
from emergent.wire.codecs.rrc import RequestResponseCodec, execute as rrc_execute
from emergent.wire.codecs.resolve import get_transition_params, wrap
from emergent.wire.codecs.stateful import (
    StatefulCodec,
    parse_transition_result,
    run_middlewares,
)
from emergent.wire.triggers.cli import CLIMeta, CLITrigger, get_cli_meta


# ─── Request Parsing ───────────────────────────────────────────────────────────


def _args_from_request(
    req_cls: type[Any],
) -> tuple[tuple[str, dict[str, Any]], ...]:
    """Derive argparse arguments from request type's dataclass fields.

    If request has __compose__:
    - Only fields with cli_field metadata become CLI args
    - Other fields are composed via nodnod

    If request has no __compose__:
    - All fields become CLI args (original behavior)
    """
    args: list[tuple[str, dict[str, Any]]] = []
    has_compose = hasattr(req_cls, "__compose__")

    for f in dataclasses.fields(req_cls):
        meta: CLIMeta | None = get_cli_meta(f)

        # If request uses compose, skip fields without cli_field
        # (they will be composed via nodnod)
        if has_compose and meta is None:
            continue

        meta = meta or CLIMeta()

        kwargs: dict[str, Any] = {}
        if meta.help:
            kwargs["help"] = meta.help
        if meta.choices is not None:
            kwargs["choices"] = list(meta.choices)

        has_default = f.default is not dataclasses.MISSING

        if meta.cli_action:
            name = meta.cli_name or f"--{f.name.replace('_', '-')}"
            kwargs["action"] = meta.cli_action
            kwargs["dest"] = f.name
            if has_default:
                kwargs["default"] = f.default
        elif f.default is False:
            name = meta.cli_name or f"--{f.name.replace('_', '-')}"
            kwargs["action"] = "store_true"
            kwargs["default"] = False
        elif has_default:
            name = meta.cli_name or f"--{f.name.replace('_', '-')}"
            kwargs["default"] = f.default
        else:
            name = meta.cli_name or f.name

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
        await agent.run(local_scope=scope, mapped_scopes={})

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


def _compose_cli_param(
    name: str,
    original_type: type,
    compose_type: type,
    cli_args: dict[str, Any],
) -> Any:
    """Compose a single __transition__ parameter for CLI.

    Strategy:
    1. Check if value provided in cli_args
    2. If compose_type has __compose__, try to call it with available data
    3. Otherwise prompt user interactively
    """
    # Check if provided in CLI args
    if name in cli_args and cli_args[name] is not None:
        return wrap(original_type, True, cli_args[name])

    # Check if it's a scalar_node with simple __compose__
    compose_fn = getattr(compose_type, "__compose__", None)
    if compose_fn is not None:
        # For CLI nodes, prompt and try to compose
        raw_value = _prompt_for_value(name, str)
        if raw_value is not None:
            try:
                # Try calling __compose__ with raw string
                result = compose_fn(raw_value)
                return wrap(original_type, True, result)
            except Exception:
                pass
        return wrap(original_type, False, "composition failed")

    # Direct prompt
    raw_value = _prompt_for_value(name, compose_type)
    if raw_value is not None:
        return wrap(original_type, True, raw_value)

    return wrap(original_type, False, "no input")


def _compose_cli_params(
    params: dict[str, tuple[type, type]],
    cli_args: dict[str, Any],
) -> dict[str, Any]:
    """Compose all __transition__ parameters for CLI."""
    composed: dict[str, Any] = {}

    for name, (original_type, compose_type) in params.items():
        composed[name] = _compose_cli_param(name, original_type, compose_type, cli_args)

    return composed


async def _run_stateful_flow(
    handler: Handler[StatefulCodec],
    cli_args: dict[str, Any],
) -> str:
    """Run stateful flow interactively until Done."""
    codec = handler.codec
    params = get_transition_params(codec.flow)
    state = codec.flow()

    while True:
        # Compose params and call transition
        composed = _compose_cli_params(params, cli_args)
        raw_result = await state.__transition__(**composed)
        result = parse_transition_result(raw_result)

        # Handle continue
        if not result.is_terminal:
            new_state = result.state_or_done
            if new_state is not state:
                state = new_state

            match result.response:
                case Some(resp):
                    print(resp)
                case Nothing():
                    pass
            continue

        # Done — run middlewares, execute op
        scope_extras, rejection = await run_middlewares(codec.middlewares, state)
        if isinstance(rejection, Some):
            return str(rejection.unwrap())

        op = state.to_domain()
        op_result = await handler.runner.run(op, scope_extras=scope_extras)
        final_response = codec.response.from_domain(op_result)

        return str(final_response)


def _wrap_stateful_handler(handler: Handler[StatefulCodec]) -> Any:
    """Wrap StatefulCodec Handler in CLI-compatible async function."""

    async def _handler(args: argparse.Namespace) -> str:
        cli_args = {k: v for k, v in vars(args).items() if not k.startswith("_")}
        return await _run_stateful_flow(handler, cli_args)

    return _handler


# ─── Registration ──────────────────────────────────────────────────────────────


def _register_rrc(
    subparsers: Any,
    trigger: CLITrigger,
    handler: Handler[RequestResponseCodec],
) -> None:
    """Register RRC handler as argparse subcommand."""
    sub = subparsers.add_parser(trigger.command, help=trigger.description)
    for name, kwargs in _args_from_request(handler.codec.request):
        sub.add_argument(name, **kwargs)
    sub.set_defaults(_handler=_wrap_rrc_handler(handler))


def _register_stateful(
    subparsers: Any,
    trigger: CLITrigger,
    handler: Handler[StatefulCodec],
) -> None:
    """Register StatefulCodec handler as argparse subcommand.

    Stateful flows are interactive — minimal CLI args, prompts for rest.
    """
    sub = subparsers.add_parser(trigger.command, help=trigger.description)
    # Could add optional args here for initial values
    sub.set_defaults(_handler=_wrap_stateful_handler(handler))


def _register(
    subparsers: Any,
    trigger: CLITrigger,
    handler: Handler[Any],
) -> None:
    """Register handler based on codec type."""
    if isinstance(handler.codec, RequestResponseCodec):
        _register_rrc(subparsers, trigger, handler)
    elif isinstance(handler.codec, StatefulCodec):
        _register_stateful(subparsers, trigger, handler)


# ─── Compilation ───────────────────────────────────────────────────────────────


def compile_to_argparse(
    endp: Endpoint,
) -> list[tuple[CLITrigger, tuple[tuple[str, dict[str, Any]], ...], Any]]:
    """Compile endpoint RRC exposures into (trigger, arguments, handler) tuples."""
    return [
        (trigger, _args_from_request(handler.codec.request), _wrap_rrc_handler(handler))
        for trigger, handler in scan_endpoint(endp, CLITrigger, RequestResponseCodec)
    ]


def add_endpoint_to_parser(
    subparsers: Any,
    endp: Endpoint,
) -> None:
    """Register endpoint's CLI exposures as argparse subcommands."""
    for trigger, handler in scan_endpoint(endp, CLITrigger, RequestResponseCodec):
        _register_rrc(subparsers, trigger, handler)

    for trigger, handler in scan_endpoint(endp, CLITrigger, StatefulCodec):
        _register_stateful(subparsers, trigger, handler)


def from_application(
    app: Application,
    prog: str = "cli",
) -> argparse.ArgumentParser:
    """Compile wire Application to argparse parser."""
    parser = argparse.ArgumentParser(prog=prog)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for trigger, handler in scan(app, CLITrigger, RequestResponseCodec):
        _register_rrc(subparsers, trigger, handler)

    for trigger, handler in scan(app, CLITrigger, StatefulCodec):
        _register_stateful(subparsers, trigger, handler)

    return parser


def _build_tree(
    subparsers: Any,
    rrc_view: StackView[CLITrigger],
    depth: int = 0,
) -> None:
    """Recursively build argparse subcommand tree from StackView."""
    for trigger, handler in rrc_view.root:
        _register(subparsers, trigger, handler)

    for prefix, child in rrc_view.mounts.items():
        sub_parser = subparsers.add_parser(prefix, help=f"{prefix} commands")
        nested_subparsers = sub_parser.add_subparsers(
            dest=f"{'_' * depth}subcommand_{prefix}",
            required=True,
        )

        if isinstance(child, StackView):
            _build_tree(nested_subparsers, child, depth + 1)
        else:
            for trigger, handler in child:
                _register(nested_subparsers, trigger, handler)


def from_app_stack(
    stack: AppStack,
    prog: str = "cli",
) -> argparse.ArgumentParser:
    """Compile AppStack to argparse parser with nested subcommands."""
    parser = argparse.ArgumentParser(prog=prog)
    subparsers = parser.add_subparsers(dest="command", required=True)

    _build_tree(subparsers, scan_stack(stack, CLITrigger, RequestResponseCodec))

    return parser


def run_parser(parser: argparse.ArgumentParser, args: list[str] | None = None) -> int:
    """Run CLI: parse args, execute handler, print output."""
    parsed = parser.parse_args(args)

    handler = getattr(parsed, "_handler", None)
    if handler is None:
        parser.print_help()
        return 1

    try:
        output = asyncio.run(handler(parsed))
        print(output)
        return 0
    except KeyboardInterrupt:
        print("\nAborted.")
        return 130
    except Exception as e:
        print(f"{e}", file=sys.stderr)
        return 1
