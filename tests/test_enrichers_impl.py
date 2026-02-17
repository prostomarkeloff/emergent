"""Tests for enrichers/_impl.py — Timeout, Delay, Retry, RateLimit, Provide, Inject, Validate, Cached, Passthrough, When."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from nodnod import Scope

from emergent.wire.axis.surface.enrichers._base import ScopeEnricher, EnricherNext
from emergent.wire.axis.surface.enrichers._impl import (
    Timeout,
    Delay,
    Retry,
    RateLimit,
    Provide,
    Inject,
    Validate,
    Passthrough,
    When,
    chain_enrichers,
    execute_with_enrichers,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


async def _simple_handler(scope: Scope) -> str:
    return "ok"


async def _failing_handler(scope: Scope) -> str:
    raise ValueError("boom")


# --- Provide test ops (module-level for type hint resolution) ---

from kungfu import Result, Ok, Error
from emergent.ops._graph import Op, ops


@dataclass(frozen=True, slots=True)
class _FetchOp(Op[str, str]):
    pass


async def _fetch_op_handler(req: _FetchOp) -> Result[str, str]:
    return Ok("fetched_value")


@dataclass(frozen=True, slots=True)
class _FailProvideOp(Op[str, str]):
    pass


async def _fail_provide_handler(req: _FailProvideOp) -> Result[str, str]:
    return Error("fail")


# ═══════════════════════════════════════════════════════════════════════════════
# Timeout
# ═══════════════════════════════════════════════════════════════════════════════


class TestTimeout:
    @pytest.mark.asyncio
    async def test_timeout_passes_when_fast(self) -> None:
        enricher = Timeout(seconds=5.0)
        async with Scope() as scope:
            result = await enricher.enrich(_simple_handler, scope)
            assert result == "ok"

    @pytest.mark.asyncio
    async def test_timeout_propagates_error(self) -> None:
        enricher = Timeout(seconds=5.0)
        async with Scope() as scope:
            with pytest.raises(ValueError, match="boom"):
                await enricher.enrich(_failing_handler, scope)


# ═══════════════════════════════════════════════════════════════════════════════
# Delay
# ═══════════════════════════════════════════════════════════════════════════════


class TestDelay:
    @pytest.mark.asyncio
    async def test_delay_executes_handler(self) -> None:
        enricher = Delay(seconds=0.001)
        async with Scope() as scope:
            result = await enricher.enrich(_simple_handler, scope)
            assert result == "ok"

    @pytest.mark.asyncio
    async def test_delay_propagates_error(self) -> None:
        enricher = Delay(seconds=0.001)
        async with Scope() as scope:
            with pytest.raises(ValueError, match="boom"):
                await enricher.enrich(_failing_handler, scope)


# ═══════════════════════════════════════════════════════════════════════════════
# Retry
# ═══════════════════════════════════════════════════════════════════════════════


class TestRetry:
    @pytest.mark.asyncio
    async def test_retry_passes_on_first_try(self) -> None:
        from combinators.control import RetryPolicy
        _fixed = RetryPolicy[Exception].fixed
        enricher = Retry(policy=_fixed(times=3, delay_seconds=0.001))
        async with Scope() as scope:
            result = await enricher.enrich(_simple_handler, scope)
            assert result == "ok"

    @pytest.mark.asyncio
    async def test_retry_eventually_raises(self) -> None:
        from combinators.control import RetryPolicy
        _fixed = RetryPolicy[Exception].fixed
        enricher = Retry(policy=_fixed(times=2, delay_seconds=0.001))
        async with Scope() as scope:
            with pytest.raises(ValueError, match="boom"):
                await enricher.enrich(_failing_handler, scope)


# ═══════════════════════════════════════════════════════════════════════════════
# RateLimit
# ═══════════════════════════════════════════════════════════════════════════════


class TestRateLimit:
    @pytest.mark.asyncio
    async def test_rate_limit_allows_under_limit(self) -> None:
        from combinators.concurrency import RateLimitPolicy
        enricher = RateLimit(policy=RateLimitPolicy(max_per_second=100.0, burst=10))
        async with Scope() as scope:
            result = await enricher.enrich(_simple_handler, scope)
            assert result == "ok"

    @pytest.mark.asyncio
    async def test_rate_limit_propagates_error(self) -> None:
        from combinators.concurrency import RateLimitPolicy
        enricher = RateLimit(policy=RateLimitPolicy(max_per_second=100.0, burst=10))
        async with Scope() as scope:
            with pytest.raises(ValueError, match="boom"):
                await enricher.enrich(_failing_handler, scope)


# ═══════════════════════════════════════════════════════════════════════════════
# Provide
# ═══════════════════════════════════════════════════════════════════════════════


class TestProvide:
    """Provide enricher — test Ok/Error paths."""

    @pytest.mark.asyncio
    async def test_provide_injects_on_ok(self) -> None:
        runner = ops().on(_FetchOp, _fetch_op_handler).compile()
        enricher = Provide(
            type=str,
            runner=runner,
            op=lambda scope: _FetchOp(),
            on_error=lambda _: "ERROR",
        )
        async with Scope() as scope:
            result = await enricher.enrich(_simple_handler, scope)
            assert result == "ok"
            wrapper = scope.get(str)
            assert wrapper is not None
            assert wrapper.value == "fetched_value"

    @pytest.mark.asyncio
    async def test_provide_short_circuits_on_error(self) -> None:
        runner = ops().on(_FailProvideOp, _fail_provide_handler).compile()
        enricher = Provide(
            type=str,
            runner=runner,
            op=lambda scope: _FailProvideOp(),
            on_error=lambda _: "BLOCKED",
        )
        async with Scope() as scope:
            result = await enricher.enrich(_simple_handler, scope)
            assert result == "BLOCKED"


# ═══════════════════════════════════════════════════════════════════════════════
# Inject
# ═══════════════════════════════════════════════════════════════════════════════


class TestInject:
    @pytest.mark.asyncio
    async def test_inject_static_value(self) -> None:
        enricher = Inject(type=int, value=42)
        async with Scope() as scope:
            result = await enricher.enrich(_simple_handler, scope)
            assert result == "ok"
            wrapper = scope.get(int)
            assert wrapper is not None
            assert wrapper.value == 42

    @pytest.mark.asyncio
    async def test_inject_factory(self) -> None:
        enricher = Inject(type=str, factory=lambda _: "computed")
        async with Scope() as scope:
            result = await enricher.enrich(_simple_handler, scope)
            assert result == "ok"
            wrapper = scope.get(str)
            assert wrapper is not None
            assert wrapper.value == "computed"


# ═══════════════════════════════════════════════════════════════════════════════
# Validate
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidate:
    @pytest.mark.asyncio
    async def test_validate_pass(self) -> None:
        enricher = Validate(
            extract=lambda _: 10,
            predicate=lambda x: x > 0,
            on_invalid=lambda _: "INVALID",
        )
        async with Scope() as scope:
            result = await enricher.enrich(_simple_handler, scope)
            assert result == "ok"

    @pytest.mark.asyncio
    async def test_validate_fail_short_circuits(self) -> None:
        enricher = Validate(
            extract=lambda _: -5,
            predicate=lambda x: x > 0,
            on_invalid=lambda x: f"INVALID:{x}",
        )
        async with Scope() as scope:
            result = await enricher.enrich(_simple_handler, scope)
            assert result == "INVALID:-5"


# ═══════════════════════════════════════════════════════════════════════════════
# Passthrough
# ═══════════════════════════════════════════════════════════════════════════════


class TestPassthrough:
    @pytest.mark.asyncio
    async def test_passthrough_does_nothing(self) -> None:
        enricher = Passthrough()
        async with Scope() as scope:
            result = await enricher.enrich(_simple_handler, scope)
            assert result == "ok"


# ═══════════════════════════════════════════════════════════════════════════════
# When
# ═══════════════════════════════════════════════════════════════════════════════


class TestWhen:
    @pytest.mark.asyncio
    async def test_when_true_applies_then(self) -> None:
        enricher = When(
            condition=lambda _: True,
            then=Inject(type=int, value=99),
        )
        async with Scope() as scope:
            result = await enricher.enrich(_simple_handler, scope)
            assert result == "ok"
            wrapper = scope.get(int)
            assert wrapper is not None

    @pytest.mark.asyncio
    async def test_when_false_applies_otherwise(self) -> None:
        enricher = When(
            condition=lambda _: False,
            then=Inject(type=int, value=99),
            otherwise=Inject(type=str, value="fallback"),
        )
        async with Scope() as scope:
            result = await enricher.enrich(_simple_handler, scope)
            assert result == "ok"
            assert scope.get(int) is None
            wrapper = scope.get(str)
            assert wrapper is not None
            assert wrapper.value == "fallback"


# ═══════════════════════════════════════════════════════════════════════════════
# chain_enrichers / execute_with_enrichers
# ═══════════════════════════════════════════════════════════════════════════════


class TestChainEnrichers:
    @pytest.mark.asyncio
    async def test_chain_ordering(self) -> None:
        order: list[str] = []

        @dataclass(frozen=True)
        class Recorder(ScopeEnricher):
            label: str

            async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
                order.append(f"enter:{self.label}")
                result = await call(scope)
                order.append(f"exit:{self.label}")
                return result

        enrichers = (Recorder(label="A"), Recorder(label="B"))
        chained = chain_enrichers(enrichers, _simple_handler)
        async with Scope() as scope:
            result = await chained(scope)
            assert result == "ok"
            assert order == ["enter:A", "enter:B", "exit:B", "exit:A"]

    @pytest.mark.asyncio
    async def test_execute_with_enrichers_convenience(self) -> None:
        enrichers = (Inject(type=int, value=42),)
        async with Scope() as scope:
            result = await execute_with_enrichers(enrichers, _simple_handler, scope)
            assert result == "ok"
