"""CLI adapter — functional compiler for argparse.

Target compilation via WrapPhase — same pattern as schema compilation:
    from_codec(codec, trigger) → WrapCtx → fold(capabilities) → WrapCtx → assemble → Route

    from emergent.wire.compile import Axes
    from emergent.wire.compile.targets.cli import cli_compile

    axes = Axes.default()
    parser = cli_compile(wire_app, axes, prog="my-tool")

Supports compose.* capabilities for node composition in CLI context.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import types
from dataclasses import dataclass
from typing import Any, Callable, Protocol

type StrAnyMap = dict[str, Any]


def _ns_get(ns: argparse.Namespace | None, name: str) -> Any:
    """Read an argparse.Namespace attribute by name, returning None if absent.

    Centralises the type erasure: argparse populates Namespace dynamically,
    so pyright has no way to type the attributes — vars() returns dict[str, Any]
    which gets widened to Unknown under strict mode. We narrow once here.
    """
    if ns is None:
        return None
    return vars(ns).get(name)

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

from emergent.wire.compile._core import Axes, fold
from emergent.wire.compile._target import CodecBinding, TargetCompiler
from emergent.wire.compile._capabilities import apply_response_capabilities
from emergent.wire.compile._execute import execute_rrc_unified, execute_immediate_unified
from emergent.wire.compile._stateful import execute_stateful_turn, execute_stateful_done
from emergent.wire.compile._generate import to_argparse_args, ArgSpec
from emergent.wire.compile._lifetime import ScopeLayer, Tier, App, Request
from emergent.wire.compile.targets.pure import app_scope_lifespan
from emergent.graph._family import ScopeFamily

from emergent.wire.axis._capability import CoercionSpec


# ═══════════════════════════════════════════════════════════════════════════════
# CLIWrapContext — seeded by from_codec, refined by capabilities
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class CLIWrapContext:
    """Wrap context for CLI — seeded by from_codec, refined by capabilities."""

    request_type: type | None = None
    response_type: type | types.UnionType | None = None
    execute: Callable[..., Any] | None = None
    trigger: CLITrigger | None = None
    arg_specs: tuple[ArgSpec, ...] = ()
    coercion: CoercionSpec | None = None


from typing import runtime_checkable


@runtime_checkable
class CLIPipelineCompilable(Protocol):
    """Capability that configures CLI request pipeline."""

    def compile_cli_pipeline(
        self, ctx: CLIWrapContext,
    ) -> CLIWrapContext: ...


# ═══════════════════════════════════════════════════════════════════════════════
# CLIRoute — structured wrap result (NO heuristics in registration)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class CLIRoute:
    """Structured result of wrapping a handler for CLI."""

    handler: Callable[[argparse.Namespace], object]
    arg_specs: tuple[ArgSpec, ...] = ()


# ═══════════════════════════════════════════════════════════════════════════════
# Execute functions — codec-specific
# ═══════════════════════════════════════════════════════════════════════════════


async def _rrc_execute_cli(
    handler: Handler[RequestResponseCodec],
    scope: Scope,
    get_value: Callable[[str], Any] | None,
) -> Any:
    """RRC execution for CLI."""
    ns_wrapper = scope.get(argparse.Namespace)
    ns = ns_wrapper.value if ns_wrapper is not None else None
    return await execute_rrc_unified(
        handler=handler,
        axes=Axes.default(),
        get_value=get_value or (lambda name: _ns_get(ns, name)),
        inject_scope=lambda s: s.inject(argparse.Namespace, ns) if ns else None,
        target="cli",
    )


async def _stateful_execute_cli(
    handler: Handler[StatefulCodec],
    scope: Scope,
    get_value: Callable[[str], Any] | None,
) -> Any:
    """Stateful execution for CLI (interactive)."""
    ns_wrapper = scope.get(argparse.Namespace)
    ns = ns_wrapper.value if ns_wrapper is not None else argparse.Namespace()

    codec = handler.codec
    transitions = get_transitions(codec.flow)
    cli_args = {k: v for k, v in vars(ns).items() if not k.startswith("_")}
    state = codec.flow()

    while True:
        method = transitions[0] if transitions else None
        if method is None:
            raise RuntimeError("No transitions defined")

        params = get_method_params(method)
        inner_scope = scope.create_child("cli-stateful")
        async with inner_scope:
            inner_scope.inject(argparse.Namespace, ns)
            composed: StrAnyMap = {}
            for name, (orig, comp) in params.items():
                composed[name] = await _compose_cli_param(
                    name, orig, comp, cli_args, inner_scope, EventLoopAgent
                )

        new_state, response, is_terminal = await execute_stateful_turn(
            handler, state, method, composed
        )

        if not is_terminal:
            state = new_state
            if response is not None:
                response = apply_response_capabilities(response, handler.capabilities)
                print(response)
            continue

        done_scope = scope.create_child("cli-stateful-done")
        async with done_scope:
            done_scope.inject(argparse.Namespace, ns)
            final = await execute_stateful_done(handler, new_state, done_scope)

        final = apply_response_capabilities(final, handler.capabilities)
        return str(final)


async def _immediate_execute_cli(
    handler: Handler[Any],
    scope: Scope,
    get_value: Callable[[str], Any] | None,
) -> Any:
    """Immediate execution for CLI."""
    return str(execute_immediate_unified(handler))


async def _delegate_execute_cli(
    handler: Handler[DelegateCodec],
    scope: Scope,
    get_value: Callable[[str], Any] | None,
) -> Any:
    """Delegate execution for CLI."""
    ns_wrapper = scope.get(argparse.Namespace)
    ns = ns_wrapper.value if ns_wrapper is not None else argparse.Namespace()

    delegate_handler = handler.codec.handler
    args = _build_delegate_args(delegate_handler, ns)

    result = delegate_handler(**args)
    if inspect.isawaitable(result):
        result = await result

    result = apply_response_capabilities(result, handler.capabilities)
    return str(result)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI param helpers (for stateful)
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
    cli_args: StrAnyMap,
    scope: Scope,
    agent_cls: type[Agent],
) -> Any:
    """Compose single CLI param with node support."""
    from emergent.graph._compose import Composer
    from emergent.wire.axis.surface.codecs.resolve import wrap

    is_node = hasattr(compose_type, "__dependencies__")

    if is_node:
        composer = Composer.create(scope, agent_cls)
        # compose_type is bare `type` (no parameter), so compose returns Unknown;
        # we widen to object | str which is all wrap() needs
        compose_result: tuple[bool, Any | str] = await composer.compose(
            compose_type,
        )
        success, value = compose_result
        return wrap(original_type, success, value if success else f"Node {compose_type.__name__} not composed")

    if name in cli_args and cli_args[name] is not None:
        return wrap(original_type, True, cli_args[name])

    raw = _prompt_value(name, compose_type)
    if raw is not None:
        return wrap(original_type, True, raw)

    return wrap(original_type, False, "no input")


# ═══════════════════════════════════════════════════════════════════════════════
# Delegate helpers
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
    """Extract argparse specs from handler signature using schema axis."""
    specs: list[ArgSpec] = []
    params = _inspect_handler_params(handler)

    for name, param_type, has_default in params:
        try:
            specs.extend(to_argparse_args(param_type, axes))
        except TypeError:
            cli_name = f"--{name.replace('_', '-')}"
            kwargs: StrAnyMap = {}

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


def _build_delegate_args(handler: Any, ns: argparse.Namespace) -> StrAnyMap:
    """Build handler arguments from parsed namespace."""
    from emergent.wire.axis.schema._inspect import inspect_dataclass

    result: StrAnyMap = {}
    params = _inspect_handler_params(handler)

    for name, param_type, _has_default in params:
        try:
            fields = inspect_dataclass(param_type)
            kwargs = {
                field_name: _ns_get(ns, field_name)
                for field_name in fields
                if _ns_get(ns, field_name) is not None
            }
            result[name] = param_type(**kwargs)
        except TypeError:
            value = _ns_get(ns, name)
            if value is not None:
                result[name] = value

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# from_codec functions — read codec data into context
# ═══════════════════════════════════════════════════════════════════════════════


def rrc_from_codec_cli(
    codec: RequestResponseCodec,
    trigger: CLITrigger,
) -> CLIWrapContext:
    """Seed CLIWrapContext from RRC codec."""
    return CLIWrapContext(
        request_type=codec.request,
        response_type=codec.response,
        execute=_rrc_execute_cli,
        trigger=trigger,
        arg_specs=tuple(to_argparse_args(codec.request, Axes.default())),
    )


def stateful_from_codec_cli(
    codec: StatefulCodec,
    trigger: CLITrigger,
) -> CLIWrapContext:
    """Seed CLIWrapContext from StatefulCodec."""
    return CLIWrapContext(
        response_type=codec.response,
        execute=_stateful_execute_cli,
        trigger=trigger,
    )


def immediate_from_codec_cli(
    codec: ImmediateCodec | ImmediateFactoryCodec,
    trigger: CLITrigger,
) -> CLIWrapContext:
    """Seed CLIWrapContext from ImmediateCodec."""
    return CLIWrapContext(
        execute=_immediate_execute_cli,
        trigger=trigger,
    )


def delegate_from_codec_cli(
    codec: DelegateCodec,
    trigger: CLITrigger,
) -> CLIWrapContext:
    """Seed CLIWrapContext from DelegateCodec."""
    return CLIWrapContext(
        execute=_delegate_execute_cli,
        trigger=trigger,
        arg_specs=tuple(_get_delegate_arg_specs(codec.handler, Axes.default())),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Assembler
# ═══════════════════════════════════════════════════════════════════════════════


def assemble_cli_route(
    ctx: CLIWrapContext,
    handler: Handler[Any],
    axes: Axes,
) -> CLIRoute:
    """Assemble CLIRoute from compiled WrapContext."""
    execute_fn = ctx.execute
    if execute_fn is None:
        raise ValueError("CLIWrapContext.execute must be set before assembly")

    async def _handler(ns: argparse.Namespace) -> str:
        # Create scope manually for CLI (no pipeline extraction)
        layer = axes.scope_layer
        scope = layer.parent.create_child("cli") if layer else Scope()
        async with scope:
            scope.inject(argparse.Namespace, ns)
            get_value: Callable[[str], Any] = lambda name: _ns_get(ns, name)
            result = await execute_fn(handler, scope, get_value)
        return str(result) if result is not None else ""

    return CLIRoute(handler=_handler, arg_specs=ctx.arg_specs)


def register_handler(
    subparsers: Any,
    trigger: CLITrigger,
    handler: Handler[Any],
    route: CLIRoute,
    axes: Axes | None = None,
) -> None:
    """Register pre-wrapped handler on subparsers."""
    from emergent.wire.axis._capability import CLICompilable, CLICommandContext

    ctx = CLICommandContext(
        name=trigger.command,
        help=trigger.description,
    )

    trace = axes.trace if axes else None
    ctx = fold(
        handler.capabilities, ctx,
        CLICompilable, "compile_cli",
        trace=trace,
    )

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
# CLI_COMPILER — open-world codec binding set
# ═══════════════════════════════════════════════════════════════════════════════


CLI_COMPILER: TargetCompiler[CLITrigger] = TargetCompiler(
    trigger_type=CLITrigger,
    adapters=(
        CodecBinding(RequestResponseCodec, rrc_from_codec_cli),
        CodecBinding(StatefulCodec, stateful_from_codec_cli),
        CodecBinding(ImmediateCodec, immediate_from_codec_cli),
        CodecBinding(ImmediateFactoryCodec, immediate_from_codec_cli),
        CodecBinding(DelegateCodec, delegate_from_codec_cli),
    ),
    pipeline_protocol=CLIPipelineCompilable,
    pipeline_method="compile_cli_pipeline",
    assemble=assemble_cli_route,
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
    """Compile wire Application to argparse parser."""
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
        parser._scope_app = app_scope
        parser._scope_app_types = family.types_for(App)

    for trigger, handler, route in _compiler.scan_and_wrap(app, request_axes):
        register_handler(subparsers, trigger, handler, route, request_axes)

    return parser


def _wrap_for_stack(
    handler: Handler[Any],
    trigger: CLITrigger,
    axes: Axes,
    compiler: TargetCompiler[CLITrigger],
) -> CLIRoute:
    """Find the right binding and wrap handler for stack compilation."""
    if compiler.assemble is None:
        raise ValueError("Compiler has no assemble function")
    for binding in compiler.bindings:
        if isinstance(handler.codec, binding.codec_type):
            ctx = binding.from_codec(handler.codec, trigger)
            ctx = fold(
                handler.capabilities, ctx,
                compiler.pipeline_protocol, compiler.pipeline_method,
                trace=axes.trace,
            )
            return compiler.assemble(ctx, handler, axes)
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
    app_types: frozenset[type] = getattr(parser, "_scope_app_types", frozenset[type]())

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
    """Coerce raw CLI string values through Pydantic."""
    from emergent.wire.compile._generate import to_pydantic

    model = to_pydantic(req_cls, axes)
    raw = {
        name: get_value(name)
        for name in model.model_fields
        if get_value(name) is not None
    }
    coerced = model(**raw).model_dump()
    return lambda name: coerced.get(name)



def typed_rrc_from_codec_cli(
    codec: RequestResponseCodec,
    trigger: CLITrigger,
) -> CLIWrapContext:
    """RRC from_codec with Pydantic type coercion for CLI string args."""
    async def _typed_execute(
        handler: Handler[RequestResponseCodec],
        scope: Scope,
        get_value: Callable[[str], Any] | None,
    ) -> Any:
        ns_wrapper = scope.get(argparse.Namespace)
        ns = ns_wrapper.value if ns_wrapper is not None else argparse.Namespace()
        typed_get = coerce_cli_values(
            codec.request, Axes.default(),
            get_value or (lambda name: _ns_get(ns, name)),
        )
        return await execute_rrc_unified(
            handler=handler,
            axes=Axes.default(),
            get_value=typed_get,
            inject_scope=lambda s: s.inject(argparse.Namespace, ns),
            target="cli",
        )

    return CLIWrapContext(
        request_type=codec.request,
        response_type=codec.response,
        execute=_typed_execute,
        trigger=trigger,
        arg_specs=tuple(to_argparse_args(codec.request, Axes.default())),
    )


TYPED_CLI: TargetCompiler[CLITrigger] = CLI_COMPILER.replace_binding(
    RequestResponseCodec, typed_rrc_from_codec_cli
)


__all__ = (
    "CLIRoute",
    "CLIWrapContext",
    "CLIPipelineCompilable",
    "CLI_COMPILER",
    "TYPED_CLI",
    "cli_compile",
    "cli_compile_stack",
    "cli_run",
    "rrc_from_codec_cli",
    "stateful_from_codec_cli",
    "immediate_from_codec_cli",
    "delegate_from_codec_cli",
    "assemble_cli_route",
    "coerce_cli_values",
    "register_handler",
)


# ═══════════════════════════════════════════════════════════════════════════════
# Backward-compat wrappers
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_rrc_cli(
    handler: Handler[RequestResponseCodec],
    trigger: CLITrigger,
    axes: Axes,
) -> CLIRoute:
    ctx = rrc_from_codec_cli(handler.codec, trigger)
    ctx = fold(handler.capabilities, ctx, CLIPipelineCompilable, "compile_cli_pipeline", trace=axes.trace)
    return assemble_cli_route(ctx, handler, axes)


def wrap_stateful_cli(
    handler: Handler[StatefulCodec],
    trigger: CLITrigger,
    axes: Axes,
) -> CLIRoute:
    ctx = stateful_from_codec_cli(handler.codec, trigger)
    ctx = fold(handler.capabilities, ctx, CLIPipelineCompilable, "compile_cli_pipeline", trace=axes.trace)
    return assemble_cli_route(ctx, handler, axes)


def wrap_immediate_cli(
    handler: Handler[Any],
    trigger: CLITrigger,
    axes: Axes,
) -> CLIRoute:
    ctx = immediate_from_codec_cli(handler.codec, trigger)
    ctx = fold(handler.capabilities, ctx, CLIPipelineCompilable, "compile_cli_pipeline", trace=axes.trace)
    return assemble_cli_route(ctx, handler, axes)


wrap_immediate_factory_cli = wrap_immediate_cli


def wrap_delegate_cli(
    handler: Handler[DelegateCodec],
    trigger: CLITrigger,
    axes: Axes,
) -> CLIRoute:
    ctx = delegate_from_codec_cli(handler.codec, trigger)
    ctx = fold(handler.capabilities, ctx, CLIPipelineCompilable, "compile_cli_pipeline", trace=axes.trace)
    return assemble_cli_route(ctx, handler, axes)


def wrap_rrc_cli_typed(
    handler: Handler[RequestResponseCodec],
    trigger: CLITrigger,
    axes: Axes,
) -> CLIRoute:
    ctx = typed_rrc_from_codec_cli(handler.codec, trigger)
    ctx = fold(handler.capabilities, ctx, CLIPipelineCompilable, "compile_cli_pipeline", trace=axes.trace)
    return assemble_cli_route(ctx, handler, axes)


# Alias for cleaner API
compile = cli_compile
compile_stack = cli_compile_stack
