"""Testing target — framework-agnostic compilation for direct invocation.

Target compilation via WrapPhase — same pattern as schema compilation.

    from emergent.wire.compile.targets.testing import testing_compile

    test = testing_compile(app)
    result = await test.routes[0].call({"name": "Alice", "age": 30})
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Protocol, TYPE_CHECKING

from nodnod import Scope

from emergent.wire.axis.surface.codecs.delegate import DelegateCodec
from emergent.wire.axis.surface.codecs.immediate import ImmediateCodec, ImmediateFactoryCodec
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec
from emergent.wire.compile._core import Axes, fold
from emergent.wire.compile._execute import (
    ScopeInjector,
    execute_delegate_unified,
    execute_immediate_unified,
    execute_rrc_unified,
)
from emergent.wire.compile._target import CodecBinding, TargetCompiler

if TYPE_CHECKING:
    from emergent.graph._family import ScopeFamily
    from emergent.wire.axis.surface._app import Application
    from emergent.wire.axis.surface._handler import Handler
    from emergent.wire.compile._lifetime import Tier


# ═══════════════════════════════════════════════════════════════════════════════
# TestingWrapContext
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TestingWrapContext:
    """Wrap context for Testing target."""

    execute: Callable[..., Any] | None = None
    trigger: object | None = None


from typing import runtime_checkable


@runtime_checkable
class TestingPipelineCompilable(Protocol):
    """Capability that configures Testing pipeline."""

    def compile_testing_pipeline(
        self, ctx: TestingWrapContext,
    ) -> TestingWrapContext: ...


# ═══════════════════════════════════════════════════════════════════════════════
# Route type
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TestRoute:
    """Compiled route for testing — call with a plain dict, get response."""

    trigger: object
    _invoke: Callable[[Mapping[str, object], ScopeInjector | None], Awaitable[object]]

    async def call(
        self,
        fields: Mapping[str, object] | None = None,
        inject: ScopeInjector | None = None,
    ) -> object:
        return await self._invoke(fields or {}, inject)


# ═══════════════════════════════════════════════════════════════════════════════
# TestApp
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class TestApp:
    """Collection of compiled test routes with optional app scope lifecycle."""

    routes: tuple[TestRoute, ...]
    _app_scope: Scope | None = None
    _app_compose: frozenset[type] = frozenset()

    async def __aenter__(self) -> TestApp:
        if self._app_scope is not None:
            await self._app_scope.__aenter__()
            if self._app_compose:
                from emergent.graph._compose import Composer
                composer = Composer.create(self._app_scope)
                await composer.compose_batch(set(self._app_compose))
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._app_scope is not None:
            await self._app_scope.__aexit__(exc_type, exc_val, exc_tb)


# ═══════════════════════════════════════════════════════════════════════════════
# from_codec functions
# ═══════════════════════════════════════════════════════════════════════════════


_NOOP_INJECT: ScopeInjector = lambda _scope: None


def rrc_from_codec_testing(
    codec: RequestResponseCodec,
    trigger: object,
) -> TestingWrapContext:
    """Seed TestingWrapContext from RRC codec."""
    return TestingWrapContext(execute=_rrc_execute_testing, trigger=trigger)


def delegate_from_codec_testing(
    codec: DelegateCodec,
    trigger: object,
) -> TestingWrapContext:
    """Seed TestingWrapContext from DelegateCodec."""
    return TestingWrapContext(execute=_delegate_execute_testing, trigger=trigger)


def immediate_from_codec_testing(
    codec: ImmediateCodec | ImmediateFactoryCodec,
    trigger: object,
) -> TestingWrapContext:
    """Seed TestingWrapContext from ImmediateCodec."""
    return TestingWrapContext(execute=_immediate_execute_testing, trigger=trigger)


# ═══════════════════════════════════════════════════════════════════════════════
# Execute functions
# ═══════════════════════════════════════════════════════════════════════════════


async def _rrc_execute_testing(
    handler: Handler[RequestResponseCodec],
    fields: Mapping[str, object],
    inject: ScopeInjector | None,
    axes: Axes,
) -> object:
    return await execute_rrc_unified(
        handler=handler,
        axes=axes,
        get_value=fields.get,
        inject_scope=inject or _NOOP_INJECT,
    )


async def _delegate_execute_testing(
    handler: Handler[DelegateCodec],
    fields: Mapping[str, object],
    inject: ScopeInjector | None,
    axes: Axes,
) -> object:
    return await execute_delegate_unified(
        handler=handler,
        inject_scope=inject or _NOOP_INJECT,
        axes=axes,
    )


async def _immediate_execute_testing(
    handler: Handler[Any],
    fields: Mapping[str, object],
    inject: ScopeInjector | None,
    axes: Axes,
) -> object:
    return execute_immediate_unified(handler)


# ═══════════════════════════════════════════════════════════════════════════════
# Assembler
# ═══════════════════════════════════════════════════════════════════════════════


def assemble_testing_route(
    ctx: TestingWrapContext,
    handler: Handler[Any],
    axes: Axes,
) -> TestRoute:
    """Assemble TestRoute from compiled WrapContext."""
    execute_fn = ctx.execute

    async def invoke(fields: Mapping[str, object], inject: ScopeInjector | None) -> object:
        return await execute_fn(handler, fields, inject, axes)

    return TestRoute(trigger=ctx.trigger, _invoke=invoke)


# ═══════════════════════════════════════════════════════════════════════════════
# Compiler
# ═══════════════════════════════════════════════════════════════════════════════


TESTING_COMPILER: TargetCompiler[object] = TargetCompiler(
    trigger_type=object,  # isinstance(any_trigger, object) → always True
    adapters=(
        CodecBinding(RequestResponseCodec, rrc_from_codec_testing),
        CodecBinding(ImmediateCodec, immediate_from_codec_testing),
        CodecBinding(ImmediateFactoryCodec, immediate_from_codec_testing),
        CodecBinding(DelegateCodec, delegate_from_codec_testing),
    ),
    pipeline_protocol=TestingPipelineCompilable,
    pipeline_method="compile_testing_pipeline",
    assemble=assemble_testing_route,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Compile function
# ═══════════════════════════════════════════════════════════════════════════════


def testing_compile(
    app: Application,
    axes: Axes | None = None,
    compiler: TargetCompiler[object] | None = None,
    family: ScopeFamily[Tier] | None = None,
) -> TestApp:
    """Compile wire Application to callable test routes."""
    base_axes = axes or Axes.default()

    app_scope: Scope | None = None
    app_compose: frozenset[type] = frozenset()

    if family is not None:
        from types import MappingProxyType
        from emergent.wire.compile._lifetime import App, Request, ScopeLayer

        app_scope = Scope(detail="test-app")
        layer = ScopeLayer(
            scopes=MappingProxyType({App: app_scope}),
            family=family,
            leaf=Request,
        )
        base_axes = base_axes.with_scope_layer(layer)
        app_compose = family.types_for(App)

    actual_compiler = compiler or TESTING_COMPILER

    routes: list[TestRoute] = []
    for _trigger, _handler, wrapped in actual_compiler.scan_and_wrap(app, base_axes):
        routes.append(wrapped)

    return TestApp(
        routes=tuple(routes),
        _app_scope=app_scope,
        _app_compose=app_compose,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Backward-compat wrappers
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_rrc_testing(
    handler: Handler[RequestResponseCodec],
    trigger: object,
    axes: Axes,
) -> TestRoute:
    ctx = rrc_from_codec_testing(handler.codec, trigger)
    ctx = fold(handler.capabilities, ctx, TestingPipelineCompilable, "compile_testing_pipeline", trace=axes.trace)
    return assemble_testing_route(ctx, handler, axes)


def wrap_delegate_testing(
    handler: Handler[DelegateCodec],
    trigger: object,
    axes: Axes,
) -> TestRoute:
    ctx = delegate_from_codec_testing(handler.codec, trigger)
    ctx = fold(handler.capabilities, ctx, TestingPipelineCompilable, "compile_testing_pipeline", trace=axes.trace)
    return assemble_testing_route(ctx, handler, axes)


def wrap_immediate_testing(
    handler: Handler[ImmediateCodec],
    trigger: object,
    axes: Axes,
) -> TestRoute:
    ctx = immediate_from_codec_testing(handler.codec, trigger)
    ctx = fold(handler.capabilities, ctx, TestingPipelineCompilable, "compile_testing_pipeline", trace=axes.trace)
    return assemble_testing_route(ctx, handler, axes)


def wrap_immediate_factory_testing(
    handler: Handler[ImmediateFactoryCodec],
    trigger: object,
    axes: Axes,
) -> TestRoute:
    ctx = immediate_from_codec_testing(handler.codec, trigger)
    ctx = fold(handler.capabilities, ctx, TestingPipelineCompilable, "compile_testing_pipeline", trace=axes.trace)
    return assemble_testing_route(ctx, handler, axes)


__all__ = (
    "TestRoute",
    "TestApp",
    "TestingWrapContext",
    "TestingPipelineCompilable",
    "testing_compile",
    "TESTING_COMPILER",
    "rrc_from_codec_testing",
    "delegate_from_codec_testing",
    "immediate_from_codec_testing",
    "assemble_testing_route",
    "wrap_rrc_testing",
    "wrap_delegate_testing",
    "wrap_immediate_testing",
    "wrap_immediate_factory_testing",
)
