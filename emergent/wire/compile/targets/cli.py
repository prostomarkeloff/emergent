"""CLI adapter — functional compiler for argparse.

    from emergent.wire.compile import Axes, cli_compile

    axes = Axes.default()
    parser = cli_compile(wire_app, axes, prog="my-tool")

Supports compose.* capabilities for node composition in CLI context.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from typing import Any, Callable

from nodnod import Scope
from nodnod.agent.base import Agent
from nodnod.agent.event_loop.agent import EventLoopAgent

from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface._scan import scan_stack, StackView
from emergent.wire.axis.surface._app import Application
from emergent.wire.axis.surface._stack import AppStack
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec
from emergent.wire.axis.surface.codecs.stateful import StatefulCodec, get_transitions
from emergent.wire.axis.surface.codecs.immediate import ImmediateCodec, ImmediateFactoryCodec
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec
from emergent.wire.axis.surface.codecs.resolve import get_method_params, TypeForm
from emergent.wire.axis.surface.triggers.cli import CLITrigger

from emergent.wire.compile._core import Axes
from emergent.wire.compile._target import CodecAdapter, TargetCompiler
from emergent.wire.compile._capabilities import apply_response_capabilities
from emergent.wire.compile._execute import execute_rrc_unified, execute_immediate_unified
from emergent.wire.compile._stateful import execute_stateful_turn, execute_stateful_done
from emergent.wire.compile._generate import to_argparse_args, ArgSpec
from emergent.wire.compile._lifetime import ScopeLayer, Tier, App, Request
from emergent.wire.compile.targets.pure import app_scope_lifespan
from emergent.graph._family import ScopeFamily


# ═══════════════════════════════════════════════════════════════════════════════
# CLIRoute — structured wrap result (NO heuristics in registration)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class CLIRoute:
    """Structured result of wrapping a handler for CLI.

    The wrap function knows its codec and fills ALL metadata.
    register_handler reads ONLY from this — zero isinstance on codec.
    """

    handler: Callable[[argparse.Namespace], object]
    arg_specs: tuple[ArgSpec, ...] = ()


# ═══════════════════════════════════════════════════════════════════════════════
# RRC Handler
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_rrc_cli(
    handler: Handler[RequestResponseCodec],
    trigger: CLITrigger,
    axes: Axes,
) -> CLIRoute:
    """Wrap RRC handler for CLI — trivial with unified execution."""
    req_cls = handler.codec.request
    arg_specs = to_argparse_args(req_cls, axes)

    async def _handler(ns: argparse.Namespace) -> str:
        response = await execute_rrc_unified(
            handler=handler,
            axes=axes,
            get_value=lambda name: getattr(ns, name, None),
            inject_scope=lambda scope: scope.inject(argparse.Namespace, ns),
        )
        return str(response)

    return CLIRoute(handler=_handler, arg_specs=tuple(arg_specs))


# ═══════════════════════════════════════════════════════════════════════════════
# Stateful Handler
# ═══════════════════════════════════════════════════════════════════════════════


def _prompt_value(name: str, type_hint: type) -> Any:
    """Prompt user for value."""
    try:
        raw = input(f"{name}: ").strip()
        if not raw:
            return None
        if type_hint is int:
            return int(raw)
        if type_hint is float:
            return float(raw)
        if type_hint is bool:
            return raw.lower() in ("true", "yes", "1", "y")
        return raw
    except (ValueError, EOFError, KeyboardInterrupt):
        return None


async def _compose_cli_param(
    name: str,
    original_type: TypeForm,
    compose_type: type,
    cli_args: dict[str, Any],
    scope: Scope,
    agent_cls: type[Agent],
) -> Any:
    """Compose single CLI param with node support."""
    from emergent.graph._compose import Composer
    from emergent.wire.axis.surface.codecs.resolve import wrap

    # Check if compose_type is a nodnod node
    is_node = hasattr(compose_type, "__dependencies__")

    if is_node:
        composer = Composer.create(scope, agent_cls)
        success, value = await composer.compose(compose_type)
        return wrap(original_type, success, value if success else f"Node {compose_type.__name__} not composed")

    # From CLI args
    if name in cli_args and cli_args[name] is not None:
        return wrap(original_type, True, cli_args[name])

    # Prompt
    raw = _prompt_value(name, compose_type)
    if raw is not None:
        return wrap(original_type, True, raw)

    return wrap(original_type, False, "no input")


def wrap_stateful_cli(
    handler: Handler[StatefulCodec],
    trigger: CLITrigger,
    axes: Axes,
) -> CLIRoute:
    """Wrap StatefulCodec for CLI (interactive).

    Supports node composition for transition parameters.
    """
    codec = handler.codec
    transitions = get_transitions(codec.flow)

    async def _handler(ns: argparse.Namespace) -> str:
        cli_args = {k: v for k, v in vars(ns).items() if not k.startswith("_")}
        state = codec.flow()
        layer = axes.scope_layer

        while True:
            # Use first transition for CLI
            method = transitions[0] if transitions else None
            if method is None:
                raise RuntimeError("No transitions defined")

            params = get_method_params(method)

            # Create scope for node composition
            scope = layer.parent.create_child("cli-stateful") if layer else Scope()
            async with scope:
                scope.inject(argparse.Namespace, ns)

                composed: dict[str, Any] = {}
                for name, (orig, comp) in params.items():
                    composed[name] = await _compose_cli_param(
                        name, orig, comp, cli_args, scope, EventLoopAgent
                    )

            new_state, response, is_terminal = await execute_stateful_turn(
                handler, state, method, composed
            )

            if not is_terminal:
                state = new_state
                if response is not None:
                    # Apply response capabilities
                    response = apply_response_capabilities(response, handler.capabilities)
                    print(response)
                continue

            # Done — execute with enrichers
            done_scope = layer.parent.create_child("cli-stateful-done") if layer else Scope()
            async with done_scope:
                done_scope.inject(argparse.Namespace, ns)
                final = await execute_stateful_done(handler, new_state, done_scope)

            # Apply response capabilities
            final = apply_response_capabilities(final, handler.capabilities)
            return str(final)

    return CLIRoute(handler=_handler)


# ═══════════════════════════════════════════════════════════════════════════════
# Immediate Handler
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_immediate_cli(
    handler: Handler[Any],
    trigger: CLITrigger,
    axes: Axes,
) -> CLIRoute:
    """Wrap Immediate codecs for CLI — trivial with unified execution."""
    async def _handler(ns: argparse.Namespace) -> str:
        return str(execute_immediate_unified(handler))
    return CLIRoute(handler=_handler)


# Alias for backwards compatibility
wrap_immediate_factory_cli = wrap_immediate_cli


# ═══════════════════════════════════════════════════════════════════════════════
# Delegate Handler
# ═══════════════════════════════════════════════════════════════════════════════


def _inspect_handler_params(handler: Any) -> list[tuple[str, type, bool]]:
    """Extract (name, type, has_default) from handler signature."""
    import inspect
    from typing import get_type_hints

    result: list[tuple[str, type, bool]] = []
    try:
        sig = inspect.signature(handler)
        hints = get_type_hints(handler)
    except Exception:
        return result

    for name, param in sig.parameters.items():
        param_type = hints.get(name)
        if param_type is None:
            continue
        has_default = param.default is not inspect.Parameter.empty
        result.append((name, param_type, has_default))

    return result


def _get_delegate_arg_specs(handler: Any, axes: Axes) -> list[ArgSpec]:
    """Extract argparse specs from handler signature using schema axis.

    For structured types (dataclasses, Pydantic): uses axes.schema for introspection.
    For simple types: generates simple --name flags.
    """
    specs: list[ArgSpec] = []
    params = _inspect_handler_params(handler)

    for name, param_type, has_default in params:
        # Structured type — use schema axis (supports dataclasses + Pydantic)
        try:
            specs.extend(to_argparse_args(param_type, axes))
        except TypeError:
            # Not a supported structured type — single flag
            cli_name = f"--{name.replace('_', '-')}"
            kwargs: dict[str, Any] = {}

            if param_type in (str, int, float):
                kwargs["type"] = param_type
            elif param_type is bool:
                kwargs["action"] = "store_true"
            else:
                kwargs["type"] = str

            if not has_default:
                kwargs["required"] = True

            specs.append(ArgSpec(
                name=cli_name, dest=name, kwargs=kwargs, is_positional=False
            ))

    return specs


def _build_delegate_args(handler: Any, ns: argparse.Namespace) -> dict[str, Any]:
    """Build handler arguments from parsed namespace.

    Reconstructs structured types (dataclasses, Pydantic) from fields.
    """
    from emergent.wire.axis.schema._inspect import inspect_dataclass

    result: dict[str, Any] = {}
    params = _inspect_handler_params(handler)

    for name, param_type, _has_default in params:
        # Structured type (dataclass or Pydantic) — reconstruct from fields
        try:
            fields = inspect_dataclass(param_type)
            kwargs = {
                field_name: getattr(ns, field_name, None)
                for field_name in fields
                if getattr(ns, field_name, None) is not None
            }
            result[name] = param_type(**kwargs)
        except TypeError:
            # Simple value
            value = getattr(ns, name, None)
            if value is not None:
                result[name] = value

    return result


def wrap_delegate_cli(
    handler: Handler[DelegateCodec],
    trigger: CLITrigger,
    axes: Axes,
) -> CLIRoute:
    """Wrap DelegateCodec handler for CLI using schema axis."""
    delegate_handler = handler.codec.handler
    arg_specs = _get_delegate_arg_specs(delegate_handler, axes)

    async def _handler(ns: argparse.Namespace) -> str:
        args = _build_delegate_args(delegate_handler, ns)

        # Call handler (may be sync or async)
        result = delegate_handler(**args)
        if hasattr(result, "__await__"):
            result = await result

        # Apply response capabilities
        result = apply_response_capabilities(result, handler.capabilities)
        return str(result)

    return CLIRoute(handler=_handler, arg_specs=tuple(arg_specs))


def register_handler(
    subparsers: Any,
    trigger: CLITrigger,
    handler: Handler[Any],
    route: CLIRoute,
    axes: Axes | None = None,
) -> None:
    """Register pre-wrapped handler on subparsers.

    Folds handler capabilities through CLICompilable for command metadata.
    Reads argument specs from CLIRoute — zero codec sniffing.
    """
    from emergent.wire.axis._capability import CLICompilable, CLICommandContext
    from emergent.wire.compile._core import fold

    # Start with trigger defaults
    ctx = CLICommandContext(
        name=trigger.command,
        help=trigger.description,
    )

    # Fold capabilities (Tag, Help, Hidden, etc.)
    trace = axes.trace if axes else None
    ctx = fold(
        handler.capabilities, ctx,
        CLICompilable, "compile_cli",
        trace=trace,
    )

    # Register — hidden commands use argparse.SUPPRESS
    help_text = argparse.SUPPRESS if ctx.hidden else ctx.help
    sub = subparsers.add_parser(
        ctx.name,
        help=help_text,
        description=ctx.description,
        epilog=ctx.epilog,
    )
    for spec in route.arg_specs:
        if spec.is_positional:
            sub.add_argument(spec.name, **spec.kwargs)
        else:
            sub.add_argument(spec.name, dest=spec.dest, **spec.kwargs)
    sub.set_defaults(_handler=route.handler)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI_COMPILER — open-world codec adapter set
# ═══════════════════════════════════════════════════════════════════════════════


CLI_COMPILER: TargetCompiler[CLITrigger] = TargetCompiler(
    trigger_type=CLITrigger,
    adapters=(
        CodecAdapter(RequestResponseCodec, wrap_rrc_cli),
        CodecAdapter(StatefulCodec, wrap_stateful_cli),
        CodecAdapter(ImmediateCodec, wrap_immediate_cli),
        CodecAdapter(ImmediateFactoryCodec, wrap_immediate_factory_cli),
        CodecAdapter(DelegateCodec, wrap_delegate_cli),
    ),
)


# ═══════════════════════════════════════════════════════════════════════════════
# Compilation
# ═══════════════════════════════════════════════════════════════════════════════


def cli_compile(
    app: Application,
    axes: Axes | None = None,
    compiler: TargetCompiler[CLITrigger] | None = None,
    prog: str = "cli",
    family: ScopeFamily[Tier] | None = None,
) -> argparse.ArgumentParser:
    """Compile wire Application to argparse parser.

    Args:
        app: Wire application
        axes: Axes context (default: Axes.default())
        compiler: TargetCompiler (default: CLI_COMPILER). Pass custom
                  compiler to add/swap/remove codec adapters.
        prog: Program name for argparse
        family: Optional ScopeFamily for tiered scope management. When provided,
                an App scope is composed once at startup and Request scopes
                inherit from it.

    Returns:
        argparse ArgumentParser
    """
    base_axes = axes or Axes.default()
    _compiler = compiler or CLI_COMPILER
    request_axes = base_axes

    parser = argparse.ArgumentParser(prog=prog)
    subparsers = parser.add_subparsers(dest="command", required=True)

    if family is not None:
        from types import MappingProxyType

        app_scope = Scope(detail="cli-app")
        layer = ScopeLayer(
            scopes=MappingProxyType({App: app_scope}),
            family=family,
            leaf=Request,
        )
        request_axes = base_axes.with_scope_layer(layer)
        parser._scope_app = app_scope  # type: ignore[attr-defined]
        parser._scope_app_types = family.types_for(App)  # type: ignore[attr-defined]

    for trigger, handler, route in _compiler.scan_and_wrap(app, request_axes):
        register_handler(subparsers, trigger, handler, route, request_axes)

    return parser


def _wrap_for_stack(
    handler: Handler[Any],
    trigger: CLITrigger,
    axes: Axes,
    compiler: TargetCompiler[CLITrigger],
) -> CLIRoute:
    """Find the right adapter and wrap handler for stack compilation."""
    for adapter in compiler.adapters:
        if isinstance(handler.codec, adapter.codec_type):
            return adapter.wrap(handler, trigger, axes)
    raise ValueError(f"No adapter for codec type: {type(handler.codec)}")


def cli_compile_stack(
    stack: AppStack,
    axes: Axes | None = None,
    compiler: TargetCompiler[CLITrigger] | None = None,
    prog: str = "cli",
) -> argparse.ArgumentParser:
    """Compile AppStack to argparse with nested subcommands."""
    axes = axes or Axes.default()
    _compiler = compiler or CLI_COMPILER
    parser = argparse.ArgumentParser(prog=prog)
    subparsers = parser.add_subparsers(dest="command", required=True)

    view = scan_stack(stack, CLITrigger)

    def _register(
        sp: Any,
        trigger: CLITrigger,
        handler: Handler[Any],
    ) -> None:
        route = _wrap_for_stack(handler, trigger, axes, _compiler)
        register_handler(sp, trigger, handler, route, axes)

    def build_tree(sp: Any, v: StackView[CLITrigger], depth: int = 0) -> None:
        for trigger, handler in v.root:
            _register(sp, trigger, handler)

        for prefix, child in v.mounts.items():
            sub = sp.add_parser(prefix, help=f"{prefix} commands")
            nested_sp = sub.add_subparsers(
                dest=f"{'_' * depth}subcommand_{prefix}",
                required=True,
            )
            if isinstance(child, StackView):
                build_tree(nested_sp, child, depth + 1)
            else:
                for trigger, handler in child:
                    _register(nested_sp, trigger, handler)

    build_tree(subparsers, view)
    return parser


def cli_run(parser: argparse.ArgumentParser, args: list[str] | None = None) -> int:
    """Run CLI: parse args, execute handler, print output."""
    import sys

    parsed = parser.parse_args(args)
    handler = getattr(parsed, "_handler", None)

    if handler is None:
        parser.print_help()
        return 1

    app_scope: Scope | None = getattr(parser, "_scope_app", None)
    app_types = getattr(parser, "_scope_app_types", frozenset())

    async def _run() -> str:
        if app_scope is not None:
            async with app_scope_lifespan(app_scope, list(app_types)):
                return await handler(parsed)
        return await handler(parsed)

    try:
        output = asyncio.run(_run())
        print(output)
        return 0
    except KeyboardInterrupt:
        print("\nAborted.")
        return 130
    except Exception as e:
        print(f"{e}", file=sys.stderr)
        return 1


# ═══════════════════════════════════════════════════════════════════════════════
# Typed CLI — Pydantic coercion for argparse string values
# ═══════════════════════════════════════════════════════════════════════════════


def coerce_cli_values(
    req_cls: type,
    axes: Axes,
    get_value: Callable[[str], Any],
) -> Callable[[str], Any]:
    """Coerce raw CLI string values through Pydantic.

    CLI args come as strings — this coerces them to proper types
    via a Pydantic model derived from the request class.

        typed_get = coerce_cli_values(req_cls, axes, lambda name: getattr(ns, name, None))
        response = await execute_rrc_unified(handler=h, axes=axes, get_value=typed_get, ...)
    """
    from emergent.wire.compile._generate import to_pydantic

    model = to_pydantic(req_cls, axes)
    raw = {
        name: get_value(name)
        for name in model.model_fields
        if get_value(name) is not None
    }
    coerced = model(**raw).model_dump()
    return lambda name: coerced.get(name)


def wrap_rrc_cli_typed(
    handler: Handler[RequestResponseCodec],
    trigger: CLITrigger,
    axes: Axes,
) -> CLIRoute:
    """RRC CLI adapter with Pydantic type coercion.

    Like wrap_rrc_cli but coerces string args through Pydantic first.
    Use with TYPED_CLI compiler for proper int/float/bool handling.
    """
    req_cls = handler.codec.request
    arg_specs = to_argparse_args(req_cls, axes)

    async def _handler(ns: argparse.Namespace) -> str:
        typed_get = coerce_cli_values(
            req_cls, axes,
            lambda name: getattr(ns, name, None),
        )
        response = await execute_rrc_unified(
            handler=handler, axes=axes,
            get_value=typed_get,
            inject_scope=lambda scope: scope.inject(argparse.Namespace, ns),
        )
        return str(response)

    return CLIRoute(handler=_handler, arg_specs=tuple(arg_specs))


TYPED_CLI: TargetCompiler[CLITrigger] = CLI_COMPILER.replace_codec(
    RequestResponseCodec, wrap_rrc_cli_typed
)


__all__ = (
    "CLIRoute",
    "CLI_COMPILER",
    "TYPED_CLI",
    "cli_compile",
    "cli_compile_stack",
    "cli_run",
    "wrap_rrc_cli",
    "wrap_rrc_cli_typed",
    "coerce_cli_values",
    "wrap_stateful_cli",
    "wrap_immediate_cli",
    "wrap_immediate_factory_cli",
    "wrap_delegate_cli",
    "register_handler",
)


# Alias for cleaner API
compile = cli_compile
compile_stack = cli_compile_stack
