"""Tests for enricher/transform base classes and execution helpers.

Covers:
- ScopeEnricher.compile_handler_runtime() default implementation
- ResponseTransform.compile_handler_runtime() default implementation
- chain_enrichers() ordering semantics
- execute_with_enrichers() convenience wrapper
- Passthrough enricher
- When enricher (conditional dispatch)
- Inject enricher (static value + factory)
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from nodnod import Scope

from emergent.wire.axis._capability import HandlerRuntimeContext
from emergent.wire.axis.surface.enrichers import (
    chain_enrichers,
    execute_with_enrichers,
    Passthrough,
    When,
    Inject,
)
from emergent.wire.axis.surface.enrichers._base import ScopeEnricher, EnricherNext
from emergent.wire.axis.surface.transforms._base import ResponseTransform


# ═══════════════════════════════════════════════════════════════════════════════
# Concrete test implementations
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class _NoopEnricher(ScopeEnricher):
    """Minimal ScopeEnricher that passes straight through — used to test compile_handler_runtime."""

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        return await call(scope)


@dataclass(frozen=True, slots=True)
class _UpperTransform(ResponseTransform):
    """ResponseTransform that uppercases string responses — used to test compile_handler_runtime."""

    def apply_response(self, response: str) -> str:
        return response.upper()


@dataclass(frozen=True, slots=True)
class _RecordingEnricher(ScopeEnricher):
    """Enricher that records entry/exit into a shared list for ordering tests."""

    label: str
    log: list[str]

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        self.log.append(f"enter:{self.label}")
        result = await call(scope)
        self.log.append(f"exit:{self.label}")
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# Shared handler
# ═══════════════════════════════════════════════════════════════════════════════


async def _ok_handler(scope: Scope) -> str:
    return "ok"


# ═══════════════════════════════════════════════════════════════════════════════
# ScopeEnricher.compile_handler_runtime
# ═══════════════════════════════════════════════════════════════════════════════


class TestScopeEnricherCompileHandlerRuntime:
    def test_adds_self_to_empty_enrichers(self) -> None:
        enricher = _NoopEnricher()
        ctx = HandlerRuntimeContext()
        result = enricher.compile_handler_runtime(ctx)
        assert result.enrichers == (enricher,)

    def test_appends_to_existing_enrichers(self) -> None:
        first = _NoopEnricher()
        second = _NoopEnricher()
        ctx = HandlerRuntimeContext(enrichers=(first,))
        result = second.compile_handler_runtime(ctx)
        assert result.enrichers == (first, second)

    def test_does_not_mutate_original_ctx(self) -> None:
        enricher = _NoopEnricher()
        ctx = HandlerRuntimeContext()
        enricher.compile_handler_runtime(ctx)
        # Original must be untouched (frozen dataclass, replace returns new instance)
        assert ctx.enrichers == ()

    def test_response_transforms_unaffected(self) -> None:
        transform = _UpperTransform()
        enricher = _NoopEnricher()
        ctx = HandlerRuntimeContext(response_transforms=(transform,))
        result = enricher.compile_handler_runtime(ctx)
        assert result.response_transforms == (transform,)


# ═══════════════════════════════════════════════════════════════════════════════
# ResponseTransform.compile_handler_runtime
# ═══════════════════════════════════════════════════════════════════════════════


class TestResponseTransformCompileHandlerRuntime:
    def test_adds_self_to_empty_transforms(self) -> None:
        transform = _UpperTransform()
        ctx = HandlerRuntimeContext()
        result = transform.compile_handler_runtime(ctx)
        assert result.response_transforms == (transform,)

    def test_appends_to_existing_transforms(self) -> None:
        first = _UpperTransform()
        second = _UpperTransform()
        ctx = HandlerRuntimeContext(response_transforms=(first,))
        result = second.compile_handler_runtime(ctx)
        assert result.response_transforms == (first, second)

    def test_enrichers_unaffected(self) -> None:
        enricher = _NoopEnricher()
        transform = _UpperTransform()
        ctx = HandlerRuntimeContext(enrichers=(enricher,))
        result = transform.compile_handler_runtime(ctx)
        assert result.enrichers == (enricher,)


# ═══════════════════════════════════════════════════════════════════════════════
# chain_enrichers — ordering semantics
# ═══════════════════════════════════════════════════════════════════════════════


class TestChainEnrichers:
    @pytest.mark.asyncio
    async def test_empty_tuple_returns_handler_directly(self) -> None:
        chained = chain_enrichers((), _ok_handler)
        async with Scope() as scope:
            result = await chained(scope)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_first_enricher_runs_outermost(self) -> None:
        log: list[str] = []
        a = _RecordingEnricher(label="A", log=log)
        b = _RecordingEnricher(label="B", log=log)
        chained = chain_enrichers((a, b), _ok_handler)
        async with Scope() as scope:
            result = await chained(scope)
        assert result == "ok"
        # A wraps B: A enters first, B enters second, B exits first, A exits last
        assert log == ["enter:A", "enter:B", "exit:B", "exit:A"]

    @pytest.mark.asyncio
    async def test_single_enricher_wraps_handler(self) -> None:
        log: list[str] = []
        a = _RecordingEnricher(label="X", log=log)
        chained = chain_enrichers((a,), _ok_handler)
        async with Scope() as scope:
            await chained(scope)
        assert log == ["enter:X", "exit:X"]


# ═══════════════════════════════════════════════════════════════════════════════
# execute_with_enrichers
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecuteWithEnrichers:
    @pytest.mark.asyncio
    async def test_runs_handler_through_enrichers(self) -> None:
        enricher = Inject(type=int, value=7)
        async with Scope() as scope:
            result = await execute_with_enrichers((enricher,), _ok_handler, scope)
            assert result == "ok"
            wrapper = scope.get(int)
            assert wrapper is not None
            assert wrapper.value == 7

    @pytest.mark.asyncio
    async def test_empty_enrichers_runs_handler(self) -> None:
        async with Scope() as scope:
            result = await execute_with_enrichers((), _ok_handler, scope)
        assert result == "ok"


# ═══════════════════════════════════════════════════════════════════════════════
# Passthrough
# ═══════════════════════════════════════════════════════════════════════════════


class TestPassthrough:
    @pytest.mark.asyncio
    async def test_passthrough_does_not_alter_result(self) -> None:
        enricher = Passthrough()
        async with Scope() as scope:
            result = await enricher.enrich(_ok_handler, scope)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_passthrough_compile_handler_runtime_adds_self(self) -> None:
        enricher = Passthrough()
        ctx = HandlerRuntimeContext()
        result = enricher.compile_handler_runtime(ctx)
        assert result.enrichers == (enricher,)


# ═══════════════════════════════════════════════════════════════════════════════
# When
# ═══════════════════════════════════════════════════════════════════════════════


class TestWhen:
    @pytest.mark.asyncio
    async def test_condition_true_routes_to_then(self) -> None:
        async with Scope() as scope:
            enricher = When(
                condition=lambda _: True,
                then=Inject(type=int, value=100),
            )
            result = await enricher.enrich(_ok_handler, scope)
            assert result == "ok"
            wrapper = scope.get(int)
            assert wrapper is not None
            assert wrapper.value == 100

    @pytest.mark.asyncio
    async def test_condition_false_routes_to_otherwise(self) -> None:
        async with Scope() as scope:
            enricher = When(
                condition=lambda _: False,
                then=Inject(type=int, value=100),
                otherwise=Inject(type=str, value="branch_otherwise"),
            )
            result = await enricher.enrich(_ok_handler, scope)
            assert result == "ok"
            # `then` branch must NOT have run
            assert scope.get(int) is None
            # `otherwise` branch must have run
            str_wrapper = scope.get(str)
            assert str_wrapper is not None
            assert str_wrapper.value == "branch_otherwise"

    @pytest.mark.asyncio
    async def test_condition_false_with_default_otherwise_is_passthrough(self) -> None:
        """When condition is False and no `otherwise` is given, default Passthrough runs."""
        async with Scope() as scope:
            enricher = When(
                condition=lambda _: False,
                then=Inject(type=int, value=42),
            )
            result = await enricher.enrich(_ok_handler, scope)
            assert result == "ok"
            # The Inject(then) must not have run
            assert scope.get(int) is None


# ═══════════════════════════════════════════════════════════════════════════════
# Inject
# ═══════════════════════════════════════════════════════════════════════════════


class TestInject:
    @pytest.mark.asyncio
    async def test_inject_static_value_available_in_scope(self) -> None:
        enricher = Inject(type=float, value=3.14)
        async with Scope() as scope:
            result = await enricher.enrich(_ok_handler, scope)
            assert result == "ok"
            wrapper = scope.get(float)
            assert wrapper is not None
            assert isinstance(wrapper.value, float)
            assert abs(wrapper.value - 3.14) < 1e-9

    @pytest.mark.asyncio
    async def test_inject_factory_called_with_scope(self) -> None:
        call_log: list[bool] = []

        def _factory(s: Scope) -> str:
            call_log.append(True)
            return "from_factory"

        enricher = Inject(type=str, factory=_factory)
        async with Scope() as scope:
            result = await enricher.enrich(_ok_handler, scope)
            assert result == "ok"
            assert len(call_log) == 1
            wrapper = scope.get(str)
            assert wrapper is not None
            assert wrapper.value == "from_factory"

    @pytest.mark.asyncio
    async def test_inject_neither_value_nor_factory_does_not_inject(self) -> None:
        """Inject with no value and no factory leaves scope untouched."""
        enricher = Inject(type=int)
        async with Scope() as scope:
            result = await enricher.enrich(_ok_handler, scope)
            assert result == "ok"
            assert scope.get(int) is None
