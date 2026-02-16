"""Testing target — framework-agnostic compilation for direct invocation.

Compiles wire Application to callable routes without framework dependencies.
Useful for unit/integration testing of wire endpoints.

    from emergent.wire.compile.targets.testing import testing_compile

    test = testing_compile(app)
    result = await test.routes[0].call({"name": "Alice", "age": 30})

    # With family (App-tier scope lifecycle)
    test = testing_compile(app, family=my_family)
    async with test:
        result = await test.routes[0].call({"name": "Alice"})

    # With scope injection (e.g. inject a mock DB)
    result = await test.routes[0].call(
        {"name": "Alice"},
        inject=lambda scope: scope.inject(DBPool, mock_pool),
    )
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING

from nodnod import Scope

from emergent.wire.axis.surface.codecs.delegate import DelegateCodec
from emergent.wire.axis.surface.codecs.immediate import ImmediateCodec, ImmediateFactoryCodec
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec
from emergent.wire.compile._core import Axes
from emergent.wire.compile._execute import (
    ScopeInjector,
    execute_delegate_unified,
    execute_immediate_unified,
    execute_rrc_unified,
)
from emergent.wire.compile._target import CodecAdapter, TargetCompiler

if TYPE_CHECKING:
    from emergent.graph._family import ScopeFamily
    from emergent.wire.axis.surface._app import Application
    from emergent.wire.axis.surface._handler import Handler
    from emergent.wire.compile._lifetime import Tier


# ═══════════════════════════════════════════════════════════════════════════════
# Route type — callable test route
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TestRoute:
    """Compiled route for testing — call with a plain dict, get response.

    Attributes:
        trigger: Original trigger (HTTPRouteTrigger, CLITrigger, etc.) for identification.
    """

    trigger: object
    _invoke: Callable[[Mapping[str, object], ScopeInjector | None], Awaitable[object]]

    async def call(
        self,
        fields: Mapping[str, object] | None = None,
        inject: ScopeInjector | None = None,
    ) -> object:
        """Call this route with optional field values and scope injector.

        Args:
            fields: Dict of field values for RRC request building. Ignored by
                    Delegate/Immediate codecs.
            inject: Optional scope injector for testing with mocked dependencies.

        Returns:
            Response object (type depends on codec's response class).
        """
        return await self._invoke(fields or {}, inject)


# ═══════════════════════════════════════════════════════════════════════════════
# TestApp — route collection + optional scope lifecycle
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class TestApp:
    """Collection of compiled test routes with optional app scope lifecycle.

    Use as async context manager when a ScopeFamily is provided:

        test = testing_compile(app, family=my_family)
        async with test:
            result = await test.routes[0].call({"name": "Alice"})
    """

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
# Wrap functions — one per codec
# ═══════════════════════════════════════════════════════════════════════════════


_NOOP_INJECT: ScopeInjector = lambda _scope: None


def wrap_rrc_testing(
    handler: Handler[RequestResponseCodec],
    trigger: object,
    axes: Axes,
) -> TestRoute:
    """Wrap RRC handler for testing — call with a plain dict of field values."""

    async def invoke(fields: Mapping[str, object], inject: ScopeInjector | None) -> object:
        return await execute_rrc_unified(
            handler=handler,
            axes=axes,
            get_value=fields.get,
            inject_scope=inject or _NOOP_INJECT,
        )

    return TestRoute(trigger=trigger, _invoke=invoke)


def wrap_delegate_testing(
    handler: Handler[DelegateCodec],
    trigger: object,
    axes: Axes,
) -> TestRoute:
    """Wrap DelegateCodec handler for testing."""

    async def invoke(fields: Mapping[str, object], inject: ScopeInjector | None) -> object:
        return await execute_delegate_unified(
            handler=handler,
            inject_scope=inject or _NOOP_INJECT,
            axes=axes,
        )

    return TestRoute(trigger=trigger, _invoke=invoke)


def wrap_immediate_testing(
    handler: Handler[ImmediateCodec],
    trigger: object,
    axes: Axes,
) -> TestRoute:
    """Wrap ImmediateCodec handler for testing."""

    async def invoke(fields: Mapping[str, object], inject: ScopeInjector | None) -> object:
        return execute_immediate_unified(handler)

    return TestRoute(trigger=trigger, _invoke=invoke)


def wrap_immediate_factory_testing(
    handler: Handler[ImmediateFactoryCodec],
    trigger: object,
    axes: Axes,
) -> TestRoute:
    """Wrap ImmediateFactoryCodec handler for testing."""

    async def invoke(fields: Mapping[str, object], inject: ScopeInjector | None) -> object:
        return execute_immediate_unified(handler)

    return TestRoute(trigger=trigger, _invoke=invoke)


# ═══════════════════════════════════════════════════════════════════════════════
# Compiler — matches ALL triggers via object
# ═══════════════════════════════════════════════════════════════════════════════


TESTING_COMPILER: TargetCompiler[object] = TargetCompiler(
    trigger_type=object,  # isinstance(any_trigger, object) → always True
    adapters=(
        CodecAdapter(RequestResponseCodec, wrap_rrc_testing),
        CodecAdapter(ImmediateCodec, wrap_immediate_testing),
        CodecAdapter(ImmediateFactoryCodec, wrap_immediate_factory_testing),
        CodecAdapter(DelegateCodec, wrap_delegate_testing),
    ),
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
    """Compile wire Application to callable test routes.

    Args:
        app: Wire application
        axes: Axes context (default: Axes.default())
        compiler: TargetCompiler (default: TESTING_COMPILER). Pass custom
                  compiler to add/swap/remove codec adapters.
        family: Optional ScopeFamily for tiered scope management. When provided,
                an App scope is created and composed on __aenter__, and Request
                scopes inherit from it.

    Returns:
        TestApp with routes ready to call.
    """
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


__all__ = (
    "TestRoute",
    "TestApp",
    "testing_compile",
    "TESTING_COMPILER",
    "wrap_rrc_testing",
    "wrap_delegate_testing",
    "wrap_immediate_testing",
    "wrap_immediate_factory_testing",
)
