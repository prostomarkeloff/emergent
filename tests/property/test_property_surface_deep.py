# pyright: reportPrivateUsage=false
"""Property-based & unit tests for Surface axis deep coverage.

Covers:
1. enrichers/_impl.py — Timeout, Delay, Retry, RateLimit, Provide, Inject,
   Validate, Cached, Passthrough, When, chain_enrichers, execute_with_enrichers
2. transforms/_response.py — AsDict, AsStr, Transform, TransformAsync,
   protocol checks, to_dict_from_protocol, try_convert_to_dict,
   is_dict_convertible, convert_dataclass_to_dict
3. codecs/stateful.py — StatefulCodec, StatefulBuilder, Done, Cancelled,
   transition, get_transitions, has_transitions, parse_transition_result
4. codecs/delegate.py — DelegateCodec, delegate
5. codecs/immediate.py — ImmediateCodec, ImmediateFactoryCodec,
   immediate, immediate_factory, Producing
6. enrichers/_base.py — ScopeEnricher, compile_handler_runtime,
   FastAPIEnrichable, CLIEnrichable, TelegrinderEnrichable, DjangoEnrichable
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import FrozenInstanceError, dataclass
from typing import cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from kungfu import Some, Nothing

from nodnod import Scope

from emergent.wire.axis.surface.enrichers._impl import (
    Timeout,
    Delay,
    Retry,
    RateLimit,
    Inject,
    Validate,
    Passthrough,
    When,
    chain_enrichers,
    execute_with_enrichers,
    _resolve_enrich,
)
from emergent.wire.axis.surface.enrichers._base import (
    ScopeEnricher,
    EnricherNext,
    FastAPIEnrichable,
    CLIEnrichable,
    TelegrinderEnrichable,
    DjangoEnrichable,
)
from emergent.wire.axis.surface.transforms._response import (
    HasToDict,
    HasAsDict,
    HasModelDump,
    HasDict,
    DataclassInstance,
    to_dict_from_protocol,
    try_convert_to_dict,
    is_dict_convertible,
    convert_dataclass_to_dict,
    AsDict,
    AsStr,
    Transform,
    TransformAsync,
)
from emergent.wire.axis.surface.codecs.stateful import (
    StatefulCodec,
    StatefulBuilder,
    Done,
    Cancelled,
    TransitionResult,
    transition,
    get_transitions,
    has_transitions,
    parse_transition_result,
    stateful,
)
from emergent.wire.axis.surface.codecs.delegate import (
    DelegateCodec,
    delegate,
)
from emergent.wire.axis.surface.codecs.immediate import (
    ImmediateCodec,
    ImmediateFactoryCodec,
    immediate,
    immediate_factory,
)
from emergent.wire.axis._capability import HandlerRuntimeContext
from emergent.ops._graph import ops, Op
from combinators.control import RetryPolicy
from combinators.concurrency import RateLimitPolicy
from kungfu import Ok, Error, Result
from kungfu.library.lazy.lazy_coro_result import LazyCoroResult


# ═══════════════════════════════════════════════════════════════════════════════
# Test-local helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_scope() -> Scope:
    """Create a fresh nodnod Scope for testing."""
    return Scope()


async def _identity_handler(scope: Scope) -> str:
    """Simple handler returning 'ok'."""
    return "ok"



@dataclass(frozen=True, slots=True)
class _TracingEnricher:
    """Enricher that records its name in a list via scope for tracing."""
    name: str

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        result = await call(scope)
        return cast(R, f"{self.name}({result})")

    def compile_handler_runtime(self, ctx: HandlerRuntimeContext) -> HandlerRuntimeContext:
        from dataclasses import replace as _replace
        return _replace(ctx, enrichers=(*ctx.enrichers, self))


@dataclass(frozen=True, slots=True)
class _FastAPISpecific:
    """Enricher with target-specific method for fastapi."""
    label: str

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        result = await call(scope)
        return cast(R, f"generic:{self.label}({result})")

    async def enrich_fastapi[R](self, call: EnricherNext[R], scope: Scope) -> R:
        result = await call(scope)
        return cast(R, f"fastapi:{self.label}({result})")

    def compile_handler_runtime(self, ctx: HandlerRuntimeContext) -> HandlerRuntimeContext:
        from dataclasses import replace as _replace
        return _replace(ctx, enrichers=(*ctx.enrichers, self))


# Protocol test types for _response.py
class _ObjWithToDict:
    def to_dict(self) -> dict[str, object]:
        return {"source": "to_dict"}


class _ObjWithAsDict:
    def asdict(self) -> dict[str, object]:
        return {"source": "asdict"}


class _ObjWithModelDump:
    def model_dump(self) -> dict[str, object]:
        return {"source": "model_dump"}


class _ObjWithDict:
    def dict(self) -> dict[str, object]:
        return {"source": "dict"}


@dataclass
class _SimpleDataclass:
    name: str
    value: int


class _PlainObject:
    """Not dict-convertible."""
    pass


# Op types for Provide enricher tests — must be module-level for get_type_hints
@dataclass(frozen=True, slots=True)
class _GetAuth(Op[str, str]):
    token: str


@dataclass(frozen=True, slots=True)
class _GetAuth2(Op[str, str]):
    token: str


@dataclass(frozen=True, slots=True)
class _DummyOp(Op[str, str]):
    pass


async def _handle_get_auth(op: _GetAuth) -> Result[str, str]:
    return Ok(f"user_for_{op.token}")


async def _handle_get_auth2(op: _GetAuth2) -> Result[str, str]:
    return Error("invalid_token")


async def _handle_dummy_op(op: _DummyOp) -> Result[str, str]:
    return Ok("x")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Enricher Implementations — Frozen & Construction
# ═══════════════════════════════════════════════════════════════════════════════


@given(seconds=st.floats(min_value=0.01, max_value=100.0))
def test_timeout_is_frozen_and_preserves_seconds(seconds: float) -> None:
    t = Timeout(seconds=seconds)
    assert t.seconds == seconds
    with pytest.raises(FrozenInstanceError):
        t.seconds = 99.0  # type: ignore[misc]


@given(seconds=st.floats(min_value=0.01, max_value=100.0))
def test_delay_is_frozen_and_preserves_seconds(seconds: float) -> None:
    d = Delay(seconds=seconds)
    assert d.seconds == seconds
    with pytest.raises(FrozenInstanceError):
        d.seconds = 99.0  # type: ignore[misc]


def test_retry_is_frozen_and_preserves_policy() -> None:
    policy = RetryPolicy[Exception].fixed(times=3, delay_seconds=0.1)
    r = Retry(policy=policy)
    assert r.policy is policy
    with pytest.raises(FrozenInstanceError):
        r.policy = policy  # type: ignore[misc]


def test_rate_limit_is_frozen_and_preserves_policy() -> None:
    policy = RateLimitPolicy(max_per_second=10.0, burst=5)
    rl = RateLimit(policy=policy)
    assert rl.policy is policy
    with pytest.raises(FrozenInstanceError):
        rl.policy = policy  # type: ignore[misc]


def test_passthrough_is_frozen() -> None:
    p = Passthrough()
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        p.new_attr = "test"  # type: ignore[misc]


def test_inject_is_frozen_with_value() -> None:
    inj = Inject(type=str, value="hello")
    assert inj.type is str
    assert inj.value == "hello"
    assert inj.factory is None
    with pytest.raises(FrozenInstanceError):
        inj.value = "other"  # type: ignore[misc]


def test_inject_is_frozen_with_factory() -> None:
    factory: Callable[[Scope], str] = lambda s: "computed"
    inj = Inject(type=str, factory=factory)
    assert inj.factory is factory
    assert inj.value is None


def test_validate_is_frozen_and_preserves_fields() -> None:
    extract: Callable[[Scope], int] = lambda s: 42
    predicate: Callable[[int], bool] = lambda v: v > 0
    on_invalid: Callable[[int], str] = lambda v: "bad"
    v = Validate(extract=extract, predicate=predicate, on_invalid=on_invalid)
    assert v.extract is extract
    assert v.predicate is predicate
    assert v.on_invalid is on_invalid
    with pytest.raises(FrozenInstanceError):
        v.extract = extract  # type: ignore[misc]


def test_when_is_frozen_and_preserves_fields() -> None:
    cond: Callable[[Scope], bool] = lambda s: True
    inner = Passthrough()
    w = When(condition=cond, then=inner)
    assert w.condition is cond
    assert w.then is inner
    assert isinstance(w.otherwise, Passthrough)
    with pytest.raises(FrozenInstanceError):
        w.then = inner  # type: ignore[misc]


def test_when_otherwise_defaults_to_passthrough() -> None:
    w = When(condition=lambda s: True, then=Passthrough())
    assert isinstance(w.otherwise, Passthrough)


def test_when_with_explicit_otherwise() -> None:
    otherwise = _TracingEnricher(name="else")
    w = When(
        condition=lambda s: False,
        then=_TracingEnricher(name="then"),
        otherwise=otherwise,
    )
    assert w.otherwise is otherwise


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Enricher Implementations — isinstance checks (ScopeEnricher protocol)
# ═══════════════════════════════════════════════════════════════════════════════


def test_timeout_is_scope_enricher() -> None:
    assert isinstance(Timeout(seconds=1.0), ScopeEnricher)


def test_delay_is_scope_enricher() -> None:
    assert isinstance(Delay(seconds=1.0), ScopeEnricher)


def test_retry_is_scope_enricher() -> None:
    policy = RetryPolicy[Exception].fixed(times=1, delay_seconds=0.01)
    assert isinstance(Retry(policy=policy), ScopeEnricher)


def test_rate_limit_is_scope_enricher() -> None:
    assert isinstance(RateLimit(policy=RateLimitPolicy(max_per_second=10.0, burst=1)), ScopeEnricher)


def test_passthrough_is_scope_enricher() -> None:
    assert isinstance(Passthrough(), ScopeEnricher)


def test_inject_is_scope_enricher() -> None:
    assert isinstance(Inject(type=str, value="x"), ScopeEnricher)


def test_validate_is_scope_enricher() -> None:
    assert isinstance(
        Validate(extract=lambda s: 1, predicate=lambda v: True, on_invalid=lambda v: "err"),
        ScopeEnricher,
    )


def test_when_is_scope_enricher() -> None:
    assert isinstance(When(condition=lambda s: True, then=Passthrough()), ScopeEnricher)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Enricher Execution — Passthrough, When, Inject, Validate
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_passthrough_calls_through() -> None:
    scope = _make_scope()
    result = await Passthrough().enrich(_identity_handler, scope)
    assert result == "ok"


@pytest.mark.asyncio
async def test_inject_value_into_scope() -> None:
    scope = _make_scope()
    inj = Inject(type=str, value="injected")

    async def check_handler(s: Scope) -> str:
        res = s.retrieve(str)
        match res:
            case Some(v):
                return v.unbox()
            case _:
                return "missing"

    result = await inj.enrich(check_handler, scope)
    assert result == "injected"


@pytest.mark.asyncio
async def test_inject_factory_into_scope() -> None:
    scope = _make_scope()
    inj = Inject(type=int, factory=lambda s: 42)

    async def check_handler(s: Scope) -> int:
        res = s.retrieve(int)
        match res:
            case Some(v):
                return v.unbox()
            case _:
                return -1

    result = await inj.enrich(check_handler, scope)
    assert result == 42


@pytest.mark.asyncio
async def test_inject_neither_value_nor_factory() -> None:
    """When neither value nor factory, handler still called."""
    scope = _make_scope()
    inj = Inject(type=str)
    result = await inj.enrich(_identity_handler, scope)
    assert result == "ok"


@pytest.mark.asyncio
async def test_validate_passes_when_predicate_true() -> None:
    scope = _make_scope()
    v = Validate(
        extract=lambda s: 10,
        predicate=lambda val: val > 0,
        on_invalid=lambda val: "invalid",
    )
    result = await v.enrich(_identity_handler, scope)
    assert result == "ok"


@pytest.mark.asyncio
async def test_validate_short_circuits_when_predicate_false() -> None:
    scope = _make_scope()
    v = Validate(
        extract=lambda s: -5,
        predicate=lambda val: val > 0,
        on_invalid=lambda val: f"invalid:{val}",
    )
    result = await v.enrich(_identity_handler, scope)
    assert result == "invalid:-5"


@pytest.mark.asyncio
async def test_when_true_branch() -> None:
    scope = _make_scope()
    then_enricher = _TracingEnricher(name="then")
    w = When(condition=lambda s: True, then=then_enricher)
    result = await w.enrich(_identity_handler, scope)
    assert result == "then(ok)"


@pytest.mark.asyncio
async def test_when_false_branch_passthrough() -> None:
    scope = _make_scope()
    then_enricher = _TracingEnricher(name="then")
    w = When(condition=lambda s: False, then=then_enricher)
    result = await w.enrich(_identity_handler, scope)
    # Default otherwise is Passthrough, so just "ok"
    assert result == "ok"


@pytest.mark.asyncio
async def test_when_false_branch_explicit_otherwise() -> None:
    scope = _make_scope()
    w = When(
        condition=lambda s: False,
        then=_TracingEnricher(name="then"),
        otherwise=_TracingEnricher(name="else"),
    )
    result = await w.enrich(_identity_handler, scope)
    assert result == "else(ok)"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. chain_enrichers & execute_with_enrichers
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_chain_enrichers_empty_tuple() -> None:
    """Empty enrichers = handler called directly."""
    scope = _make_scope()
    chained = chain_enrichers((), _identity_handler)
    result = await chained(scope)
    assert result == "ok"


@pytest.mark.asyncio
async def test_chain_enrichers_single() -> None:
    scope = _make_scope()
    chained = chain_enrichers((_TracingEnricher(name="a"),), _identity_handler)
    result = await chained(scope)
    assert result == "a(ok)"


@pytest.mark.asyncio
async def test_chain_enrichers_ordering() -> None:
    """First enricher in tuple is outermost (runs first)."""
    scope = _make_scope()
    enrichers = (
        _TracingEnricher(name="outer"),
        _TracingEnricher(name="inner"),
    )
    chained = chain_enrichers(enrichers, _identity_handler)
    result = await chained(scope)
    # outer wraps inner wraps handler: outer(inner(ok))
    assert result == "outer(inner(ok))"


@given(n=st.integers(min_value=1, max_value=5))
@settings(max_examples=10)
def test_chain_enrichers_n_deep(n: int) -> None:
    """N enrichers produce N layers of wrapping."""
    scope = _make_scope()
    enrichers = tuple(_TracingEnricher(name=f"e{i}") for i in range(n))
    chained = chain_enrichers(enrichers, _identity_handler)

    async def _run() -> str:
        return await chained(scope)

    result = asyncio.run(_run())
    # Build expected: e0(e1(...(ok)...))
    expected = "ok"
    for i in reversed(range(n)):
        expected = f"e{i}({expected})"
    assert result == expected


@pytest.mark.asyncio
async def test_execute_with_enrichers_combines_chain_and_call() -> None:
    scope = _make_scope()
    enrichers = (_TracingEnricher(name="x"),)
    result = await execute_with_enrichers(enrichers, _identity_handler, scope)
    assert result == "x(ok)"


@pytest.mark.asyncio
async def test_execute_with_enrichers_empty() -> None:
    scope = _make_scope()
    result = await execute_with_enrichers((), _identity_handler, scope)
    assert result == "ok"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. _resolve_enrich — target dispatch
# ═══════════════════════════════════════════════════════════════════════════════


def test_resolve_enrich_no_target() -> None:
    enricher = Passthrough()
    fn = _resolve_enrich(enricher, None)
    assert fn == enricher.enrich


def test_resolve_enrich_target_specific_found() -> None:
    enricher = _FastAPISpecific(label="test")
    fn = _resolve_enrich(enricher, "fastapi")
    assert fn == enricher.enrich_fastapi


def test_resolve_enrich_target_fallback_to_generic() -> None:
    enricher = Passthrough()
    fn = _resolve_enrich(enricher, "fastapi")
    # Passthrough has no enrich_fastapi, falls back to enrich
    assert fn == enricher.enrich


@pytest.mark.asyncio
async def test_chain_enrichers_with_target_dispatch() -> None:
    """chain_enrichers with target uses target-specific method when available."""
    scope = _make_scope()
    enricher = _FastAPISpecific(label="api")
    chained = chain_enrichers((enricher,), _identity_handler, target="fastapi")
    result = await chained(scope)
    assert result == "fastapi:api(ok)"


@pytest.mark.asyncio
async def test_chain_enrichers_without_target_uses_generic() -> None:
    scope = _make_scope()
    enricher = _FastAPISpecific(label="api")
    chained = chain_enrichers((enricher,), _identity_handler, target=None)
    result = await chained(scope)
    assert result == "generic:api(ok)"


@pytest.mark.asyncio
async def test_execute_with_enrichers_target() -> None:
    scope = _make_scope()
    enricher = _FastAPISpecific(label="ep")
    result = await execute_with_enrichers(
        (enricher,), _identity_handler, scope, target="fastapi"
    )
    assert result == "fastapi:ep(ok)"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Timeout/Delay enrichers — async execution
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_timeout_enricher_succeeds_within_limit() -> None:
    scope = _make_scope()
    t = Timeout(seconds=5.0)
    result = await t.enrich(_identity_handler, scope)
    assert result == "ok"


@pytest.mark.asyncio
async def test_timeout_enricher_raises_on_timeout() -> None:
    scope = _make_scope()
    t = Timeout(seconds=0.01)

    async def slow_handler(s: Scope) -> str:
        await asyncio.sleep(1.0)
        return "slow"

    with pytest.raises(Exception):
        await t.enrich(slow_handler, scope)


@pytest.mark.asyncio
async def test_delay_enricher_calls_handler() -> None:
    scope = _make_scope()
    d = Delay(seconds=0.01)
    result = await d.enrich(_identity_handler, scope)
    assert result == "ok"


@pytest.mark.asyncio
async def test_timeout_enricher_propagates_handler_exception() -> None:
    scope = _make_scope()
    t = Timeout(seconds=5.0)

    async def failing_handler(s: Scope) -> str:
        raise ValueError("handler failed")

    with pytest.raises(ValueError, match="handler failed"):
        await t.enrich(failing_handler, scope)


@pytest.mark.asyncio
async def test_delay_enricher_propagates_handler_exception() -> None:
    scope = _make_scope()
    d = Delay(seconds=0.01)

    async def failing_handler(s: Scope) -> str:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await d.enrich(failing_handler, scope)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Retry enricher — async execution
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_retry_enricher_succeeds_first_try() -> None:
    scope = _make_scope()
    policy = RetryPolicy[Exception].fixed(times=3, delay_seconds=0.0)
    r = Retry(policy=policy)
    result = await r.enrich(_identity_handler, scope)
    assert result == "ok"


@pytest.mark.asyncio
async def test_retry_enricher_retries_on_failure() -> None:
    scope = _make_scope()
    call_count = 0

    async def flaky_handler(s: Scope) -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError("flaky")
        return "recovered"

    policy = RetryPolicy[Exception].fixed(times=5, delay_seconds=0.0)
    r = Retry(policy=policy)
    result = await r.enrich(flaky_handler, scope)
    assert result == "recovered"
    assert call_count == 3


# ═══════════════════════════════════════════════════════════════════════════════
# 8. RateLimit enricher — async execution
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rate_limit_enricher_allows_within_limit() -> None:
    scope = _make_scope()
    policy = RateLimitPolicy(max_per_second=100.0, burst=10)
    rl = RateLimit(policy=policy)
    result = await rl.enrich(_identity_handler, scope)
    assert result == "ok"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Response Transforms — Protocol checks
# ═══════════════════════════════════════════════════════════════════════════════


def test_has_to_dict_protocol() -> None:
    assert isinstance(_ObjWithToDict(), HasToDict)
    assert not isinstance(_PlainObject(), HasToDict)


def test_has_as_dict_protocol() -> None:
    assert isinstance(_ObjWithAsDict(), HasAsDict)
    assert not isinstance(_PlainObject(), HasAsDict)


def test_has_model_dump_protocol() -> None:
    assert isinstance(_ObjWithModelDump(), HasModelDump)
    assert not isinstance(_PlainObject(), HasModelDump)


def test_has_dict_protocol() -> None:
    assert isinstance(_ObjWithDict(), HasDict)
    assert not isinstance(_PlainObject(), HasDict)


def test_dataclass_instance_protocol() -> None:
    assert isinstance(_SimpleDataclass(name="x", value=1), DataclassInstance)
    assert not isinstance(_PlainObject(), DataclassInstance)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Response Transforms — Conversion functions
# ═══════════════════════════════════════════════════════════════════════════════


def test_to_dict_from_protocol_to_dict() -> None:
    result = to_dict_from_protocol(_ObjWithToDict())
    assert result == {"source": "to_dict"}


def test_to_dict_from_protocol_as_dict() -> None:
    result = to_dict_from_protocol(_ObjWithAsDict())
    assert result == {"source": "asdict"}


def test_to_dict_from_protocol_model_dump() -> None:
    result = to_dict_from_protocol(_ObjWithModelDump())
    assert result == {"source": "model_dump"}


def test_to_dict_from_protocol_dict_method() -> None:
    result = to_dict_from_protocol(_ObjWithDict())
    assert result == {"source": "dict"}


def test_to_dict_from_protocol_plain_dict() -> None:
    d: dict[str, object] = {"key": "value"}
    result = to_dict_from_protocol(d)
    assert result == {"key": "value"}
    assert result is d  # Same reference for plain dicts


def test_try_convert_to_dict_delegates() -> None:
    result = try_convert_to_dict(_ObjWithToDict())
    assert result == {"source": "to_dict"}


def test_is_dict_convertible_always_true() -> None:
    assert is_dict_convertible(_ObjWithToDict()) is True
    assert is_dict_convertible(_ObjWithAsDict()) is True
    assert is_dict_convertible(_ObjWithModelDump()) is True
    assert is_dict_convertible(_ObjWithDict()) is True


def test_convert_dataclass_to_dict_success() -> None:
    obj = _SimpleDataclass(name="test", value=42)
    result = convert_dataclass_to_dict(obj)
    assert result == {"name": "test", "value": 42}


def test_convert_dataclass_to_dict_raises_for_type() -> None:
    with pytest.raises(TypeError, match="is not a dataclass instance"):
        convert_dataclass_to_dict(_SimpleDataclass)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Response Transforms — AsDict
# ═══════════════════════════════════════════════════════════════════════════════


def test_as_dict_is_frozen() -> None:
    ad = AsDict()
    with pytest.raises(FrozenInstanceError):
        ad.skip = True  # type: ignore[misc]


def test_as_dict_from_plain_dict() -> None:
    d = {"a": 1}
    result = AsDict().apply_response(d)
    assert result == {"a": 1}


def test_as_dict_from_to_dict_protocol() -> None:
    result = AsDict().apply_response(_ObjWithToDict())
    assert result == {"source": "to_dict"}


def test_as_dict_from_as_dict_protocol() -> None:
    result = AsDict().apply_response(_ObjWithAsDict())
    assert result == {"source": "asdict"}


def test_as_dict_from_model_dump_protocol() -> None:
    result = AsDict().apply_response(_ObjWithModelDump())
    assert result == {"source": "model_dump"}


def test_as_dict_from_dict_method_protocol() -> None:
    result = AsDict().apply_response(_ObjWithDict())
    assert result == {"source": "dict"}


def test_as_dict_from_dataclass() -> None:
    obj = _SimpleDataclass(name="hi", value=7)
    result = AsDict().apply_response(obj)
    assert result == {"name": "hi", "value": 7}


def test_as_dict_strict_raises_for_plain_object() -> None:
    with pytest.raises(ValueError, match="Cannot convert"):
        AsDict().apply_response(_PlainObject())


def test_as_dict_skip_wraps_plain_object() -> None:
    obj = _PlainObject()
    result = AsDict(skip=True).apply_response(obj)
    assert result == {"value": obj}


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Response Transforms — AsStr
# ═══════════════════════════════════════════════════════════════════════════════


def test_as_str_is_frozen() -> None:
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        AsStr().new_attr = "test"  # type: ignore[misc]


@given(value=st.text(min_size=0, max_size=50))
def test_as_str_converts_to_string(value: str) -> None:
    result = AsStr().apply_response(value)
    assert result == value


@given(value=st.integers())
def test_as_str_converts_int_to_string(value: int) -> None:
    result = AsStr().apply_response(value)
    assert result == str(value)


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Response Transforms — Transform, TransformAsync
# ═══════════════════════════════════════════════════════════════════════════════


def test_transform_is_frozen() -> None:
    fn: Callable[[int], int] = lambda x: x * 2
    t = Transform(fn=fn)
    with pytest.raises(FrozenInstanceError):
        t.fn = lambda x: x  # type: ignore[misc]


@given(value=st.integers(min_value=-1000, max_value=1000))
def test_transform_applies_fn(value: int) -> None:
    fn: Callable[[int], int] = lambda x: x * 2
    t = Transform(fn=fn)
    assert t.apply_response(value) == value * 2


def test_transform_async_is_frozen() -> None:
    async def fn(x: int) -> int:
        return x
    ta = TransformAsync(fn=fn)
    with pytest.raises(FrozenInstanceError):
        ta.fn = fn  # type: ignore[misc]


@pytest.mark.asyncio
async def test_transform_async_applies_fn() -> None:
    async def double(x: int) -> int:
        return x * 2
    ta = TransformAsync(fn=double)
    result = await ta.apply_response(5)
    assert result == 10


# ═══════════════════════════════════════════════════════════════════════════════
# 14. StatefulCodec — Done, Cancelled
# ═══════════════════════════════════════════════════════════════════════════════


def test_done_is_frozen() -> None:
    d = Done()
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        d.new_attr = "test"  # type: ignore[misc]


def test_cancelled_is_done_subclass() -> None:
    c = Cancelled()
    assert isinstance(c, Done)
    assert isinstance(c, Cancelled)


def test_cancelled_is_frozen() -> None:
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        Cancelled().new_attr = "test"  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# 15. StatefulCodec — transition, get_transitions, has_transitions
# ═══════════════════════════════════════════════════════════════════════════════


def test_transition_decorator_sets_marker() -> None:
    @transition
    async def some_method(self: object) -> None:
        pass
    assert getattr(some_method, "__is_transition__", False) is True


def test_get_transitions_classic() -> None:
    @dataclass
    class Flow:
        async def __transition__(self):
            return Done()
        def to_domain(self):
            return None
    ts = get_transitions(Flow)
    assert len(ts) == 1


def test_get_transitions_decorated() -> None:
    @dataclass
    class Flow:
        @transition
        async def http(self):
            return Done()
        @transition
        async def telegram(self):
            return Done()
        def to_domain(self):
            return None
    ts = get_transitions(Flow)
    assert len(ts) == 2


def test_get_transitions_empty() -> None:
    @dataclass
    class Empty:
        pass
    ts = get_transitions(Empty)
    assert len(ts) == 0


def test_has_transitions_true() -> None:
    @dataclass
    class Flow:
        async def __transition__(self):
            return Done()
    assert has_transitions(Flow) is True


def test_has_transitions_false() -> None:
    @dataclass
    class Empty:
        pass
    assert has_transitions(Empty) is False


# ═══════════════════════════════════════════════════════════════════════════════
# 16. StatefulCodec — parse_transition_result
# ═══════════════════════════════════════════════════════════════════════════════


def test_parse_transition_result_done() -> None:
    result: TransitionResult[Done, object] = parse_transition_result(Done())
    assert result.is_terminal is True
    assert isinstance(result.state_or_done, Done)
    assert result.response == Nothing()


def test_parse_transition_result_cancelled() -> None:
    result: TransitionResult[Cancelled, object] = parse_transition_result(Cancelled())
    assert result.is_terminal is True
    assert isinstance(result.state_or_done, Cancelled)


def test_parse_transition_result_state() -> None:
    state = "some_state"
    result: TransitionResult[str, object] = parse_transition_result(state)
    assert result.is_terminal is False
    assert result.state_or_done == "some_state"
    assert result.response == Nothing()


def test_parse_transition_result_tuple_with_response() -> None:
    state = "state"
    result = parse_transition_result((state, "resp"))
    assert result.is_terminal is False
    assert result.state_or_done == "state"
    assert result.response == Some("resp")


def test_parse_transition_result_done_with_response() -> None:
    result = parse_transition_result((Done(), "final_msg"))
    assert result.is_terminal is True
    assert isinstance(result.state_or_done, Done)
    assert result.response == Some("final_msg")


def test_transition_result_is_frozen() -> None:
    tr: TransitionResult[str, object] = TransitionResult(state_or_done="s", response=Nothing(), is_terminal=False)
    with pytest.raises(FrozenInstanceError):
        tr.is_terminal = True  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# 17. StatefulCodec — StatefulBuilder & stateful()
# ═══════════════════════════════════════════════════════════════════════════════


def _make_good_flow() -> type:
    @dataclass
    class GoodFlow:
        val: int = 0
        async def __transition__(self):
            return Done()
        def to_domain(self):
            return self.val
    return GoodFlow


def _make_response() -> type:
    class Resp:
        @classmethod
        def from_domain(cls, result: object) -> Resp:
            return cls()
    return Resp


class _KeyNode:
    pass


def test_stateful_returns_builder() -> None:
    builder = stateful(_make_good_flow(), _make_response())
    assert isinstance(builder, StatefulBuilder)


def test_stateful_builder_build_success() -> None:
    codec = stateful(_make_good_flow(), _make_response()).key(_KeyNode).build()
    assert isinstance(codec, StatefulCodec)
    assert codec.flow is not None
    assert codec.key_node is _KeyNode


def test_stateful_builder_missing_key_raises() -> None:
    with pytest.raises(ValueError, match="key_node is required"):
        stateful(_make_good_flow(), _make_response()).build()


def test_stateful_builder_missing_transition_raises() -> None:
    @dataclass
    class NoTransition:
        def to_domain(self):
            return None
    with pytest.raises(ValueError, match="must define __transition__"):
        stateful(NoTransition, _make_response()).key(_KeyNode).build()


def test_stateful_builder_missing_to_domain_raises() -> None:
    @dataclass
    class NoToDomain:
        async def __transition__(self):
            return Done()
    with pytest.raises(ValueError, match="must define to_domain"):
        stateful(NoToDomain, _make_response()).key(_KeyNode).build()


def test_stateful_codec_is_frozen() -> None:
    codec = stateful(_make_good_flow(), _make_response()).key(_KeyNode).build()
    with pytest.raises(FrozenInstanceError):
        codec.flow = object  # type: ignore[misc]


def test_stateful_builder_store_sets_store() -> None:
    from emergent.wire.axis.storage import MemoryStorage
    store = MemoryStorage[str, object]()
    codec = stateful(_make_good_flow(), _make_response()).key(_KeyNode).store(store).build()
    assert codec.store is store


def test_stateful_builder_agent_sets_agent_cls() -> None:
    from nodnod.agent.event_loop.agent import EventLoopAgent

    class CustomAgent(EventLoopAgent):
        pass

    codec = stateful(_make_good_flow(), _make_response()).key(_KeyNode).agent(CustomAgent).build()
    assert codec.agent_cls is CustomAgent


# ═══════════════════════════════════════════════════════════════════════════════
# 18. DelegateCodec
# ═══════════════════════════════════════════════════════════════════════════════


def test_delegate_codec_is_frozen() -> None:
    dc = DelegateCodec(handler=lambda: None)
    with pytest.raises(FrozenInstanceError):
        dc.handler = lambda: None  # type: ignore[misc]


def test_delegate_codec_preserves_handler() -> None:
    fn = lambda: "hello"
    dc = DelegateCodec(handler=fn)
    assert dc.handler is fn


def test_delegate_codec_default_response_nothing() -> None:
    dc = DelegateCodec(handler=lambda: None)
    assert dc.response == Nothing()


def test_delegate_function_no_response() -> None:
    fn = lambda: "result"
    dc = delegate(fn)
    assert isinstance(dc, DelegateCodec)
    assert dc.handler is fn
    assert dc.response == Nothing()


def test_delegate_function_with_response() -> None:
    fn = lambda: "result"
    dc = delegate(fn, response=str)
    assert isinstance(dc, DelegateCodec)
    assert dc.response == Some(str)


def test_delegate_function_response_none_gives_nothing() -> None:
    dc = delegate(lambda: None, response=None)
    assert dc.response == Nothing()


# ═══════════════════════════════════════════════════════════════════════════════
# 19. ImmediateCodec
# ═══════════════════════════════════════════════════════════════════════════════


def test_immediate_codec_is_frozen() -> None:
    @dataclass
    class Resp:
        @classmethod
        def produce(cls) -> Resp:
            return cls()
    ic = ImmediateCodec(response=Resp)
    with pytest.raises(FrozenInstanceError):
        ic.response = Resp  # type: ignore[misc]


def test_immediate_codec_preserves_response() -> None:
    @dataclass
    class Resp:
        @classmethod
        def produce(cls) -> Resp:
            return cls()
    ic = ImmediateCodec(response=Resp)
    assert ic.response is Resp


def test_immediate_factory_codec_is_frozen() -> None:
    ifc = ImmediateFactoryCodec(factory=lambda: "hi")
    with pytest.raises(FrozenInstanceError):
        ifc.factory = lambda: "bye"  # type: ignore[misc]


def test_immediate_function_creates_codec() -> None:
    @dataclass
    class Resp:
        text: str
        @classmethod
        def produce(cls) -> Resp:
            return cls(text="hello")
    ic = immediate(Resp)
    assert isinstance(ic, ImmediateCodec)
    assert ic.response is Resp


def test_immediate_factory_function_creates_codec() -> None:
    factory = lambda: {"text": "hello"}
    ifc = immediate_factory(factory)
    assert isinstance(ifc, ImmediateFactoryCodec)
    assert ifc.factory is factory


def test_immediate_factory_codec_factory_callable() -> None:
    ifc = ImmediateFactoryCodec(factory=lambda: 42)
    assert ifc.factory() == 42


def test_producing_protocol_structural() -> None:
    """Producing protocol is structurally satisfied by class with produce()."""
    @dataclass
    class GoodProducer:
        @classmethod
        def produce(cls) -> GoodProducer:
            return cls()
    # Producing is not runtime_checkable, so verify structural conformance
    # by calling produce directly
    result = GoodProducer.produce()
    assert isinstance(result, GoodProducer)


def test_producing_protocol_used_with_immediate() -> None:
    """immediate() accepts Producing-conformant types."""
    @dataclass
    class GoodProducer:
        text: str = "default"
        @classmethod
        def produce(cls) -> GoodProducer:
            return cls(text="produced")
    ic = immediate(GoodProducer)
    assert ic.response is GoodProducer


# ═══════════════════════════════════════════════════════════════════════════════
# 20. Enricher _base.py — compile_handler_runtime
# ═══════════════════════════════════════════════════════════════════════════════


def test_scope_enricher_compile_handler_runtime() -> None:
    """ScopeEnricher.compile_handler_runtime adds self to enrichers tuple."""
    p = Passthrough()
    ctx = HandlerRuntimeContext()
    new_ctx = p.compile_handler_runtime(ctx)
    assert len(new_ctx.enrichers) == 1
    assert new_ctx.enrichers[0] is p
    # Original unchanged
    assert ctx.enrichers == ()


def test_scope_enricher_compile_handler_runtime_accumulates() -> None:
    p1 = Passthrough()
    p2 = Passthrough()
    ctx = HandlerRuntimeContext()
    ctx = p1.compile_handler_runtime(ctx)
    ctx = p2.compile_handler_runtime(ctx)
    assert len(ctx.enrichers) == 2
    assert ctx.enrichers[0] is p1
    assert ctx.enrichers[1] is p2


def test_response_transform_compile_handler_runtime() -> None:
    """ResponseTransform.compile_handler_runtime adds self to response_transforms."""
    t = AsStr()
    ctx = HandlerRuntimeContext()
    new_ctx = t.compile_handler_runtime(ctx)
    assert len(new_ctx.response_transforms) == 1
    assert new_ctx.response_transforms[0] is t


# ═══════════════════════════════════════════════════════════════════════════════
# 21. Enricher _base.py — protocol isinstance checks
# ═══════════════════════════════════════════════════════════════════════════════


def test_scope_enricher_is_runtime_checkable() -> None:
    assert isinstance(Passthrough(), ScopeEnricher)


def test_plain_object_not_scope_enricher() -> None:
    assert not isinstance(_PlainObject(), ScopeEnricher)


def test_fastapi_enrichable_protocol() -> None:
    @dataclass(frozen=True, slots=True)
    class MyFastAPIEnricher:
        async def enrich_fastapi(self, call: EnricherNext[str], scope: Scope) -> str:
            return await call(scope)
        def compile_handler_runtime(self, ctx: HandlerRuntimeContext) -> HandlerRuntimeContext:
            from dataclasses import replace
            return replace(ctx, enrichers=(*ctx.enrichers, self))
    assert isinstance(MyFastAPIEnricher(), FastAPIEnrichable)


def test_cli_enrichable_protocol() -> None:
    @dataclass(frozen=True, slots=True)
    class MyCLIEnricher:
        async def enrich_cli(self, call: EnricherNext[str], scope: Scope) -> str:
            return await call(scope)
        def compile_handler_runtime(self, ctx: HandlerRuntimeContext) -> HandlerRuntimeContext:
            from dataclasses import replace
            return replace(ctx, enrichers=(*ctx.enrichers, self))
    assert isinstance(MyCLIEnricher(), CLIEnrichable)


def test_telegrinder_enrichable_protocol() -> None:
    @dataclass(frozen=True, slots=True)
    class MyTGEnricher:
        async def enrich_telegrinder(self, call: EnricherNext[str], scope: Scope) -> str:
            return await call(scope)
        def compile_handler_runtime(self, ctx: HandlerRuntimeContext) -> HandlerRuntimeContext:
            from dataclasses import replace
            return replace(ctx, enrichers=(*ctx.enrichers, self))
    assert isinstance(MyTGEnricher(), TelegrinderEnrichable)


def test_django_enrichable_protocol() -> None:
    @dataclass(frozen=True, slots=True)
    class MyDjangoEnricher:
        async def enrich_django(self, call: EnricherNext[str], scope: Scope) -> str:
            return await call(scope)
        def compile_handler_runtime(self, ctx: HandlerRuntimeContext) -> HandlerRuntimeContext:
            from dataclasses import replace
            return replace(ctx, enrichers=(*ctx.enrichers, self))
    assert isinstance(MyDjangoEnricher(), DjangoEnrichable)


# ═══════════════════════════════════════════════════════════════════════════════
# 22. Edge cases & cross-cutting
# ═══════════════════════════════════════════════════════════════════════════════


def test_as_dict_skip_false_by_default() -> None:
    ad = AsDict()
    assert ad.skip is False


@given(n=st.integers())
def test_as_str_for_numeric(n: int) -> None:
    assert AsStr().apply_response(n) == str(n)


def test_transform_with_dict_wrapping() -> None:
    fn: Callable[[str], dict[str, str]] = lambda r: {"data": r, "status": "ok"}
    t = Transform(fn=fn)
    result = t.apply_response("hello")
    assert result == {"data": "hello", "status": "ok"}


def test_chain_enrichers_returns_callable() -> None:
    chained = chain_enrichers((), _identity_handler)
    assert callable(chained)


@pytest.mark.asyncio
async def test_validate_extract_receives_scope() -> None:
    """Validate extract function receives scope, not request."""
    scope = _make_scope()
    scope.inject(str, "from_scope")
    received: list[Scope] = []
    v = Validate(
        extract=lambda s: (received.append(s), s)[1],
        predicate=lambda val: True,
        on_invalid=lambda val: "err",
    )
    await v.enrich(_identity_handler, scope)
    assert len(received) == 1
    assert received[0] is scope


# ═══════════════════════════════════════════════════════════════════════════════
# 23. Provide enricher — Ok and Error paths
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_provide_enricher_ok_injects_and_continues() -> None:
    """Provide: on Ok, injects result into scope and calls handler."""
    from emergent.wire.axis.surface.enrichers._impl import Provide

    runner = ops().on(_GetAuth, _handle_get_auth).compile()
    scope = _make_scope()

    provide = Provide(
        type=str,
        runner=runner,
        op=lambda s: _GetAuth(token="abc"),
        on_error=lambda r: "auth_failed",
    )

    async def check_handler(s: Scope) -> str:
        res = s.retrieve(str)
        match res:
            case Some(v):
                return v.unbox()
            case _:
                return "not_found"

    result = await provide.enrich(check_handler, scope)
    assert result == "user_for_abc"


@pytest.mark.asyncio
async def test_provide_enricher_error_short_circuits() -> None:
    """Provide: on Error, short-circuits with on_error response."""
    from emergent.wire.axis.surface.enrichers._impl import Provide

    runner = ops().on(_GetAuth2, _handle_get_auth2).compile()
    scope = _make_scope()

    provide = Provide(
        type=str,
        runner=runner,
        op=lambda s: _GetAuth2(token="bad"),
        on_error=lambda r: "auth_failed",
    )

    result = await provide.enrich(_identity_handler, scope)
    assert result == "auth_failed"


def test_provide_is_frozen() -> None:
    """Provide enricher is frozen dataclass."""
    from emergent.wire.axis.surface.enrichers._impl import Provide

    runner = ops().on(_DummyOp, _handle_dummy_op).compile()
    p = Provide(
        type=str,
        runner=runner,
        op=lambda s: _DummyOp(),
        on_error=lambda r: "err",
    )
    with pytest.raises(FrozenInstanceError):
        p.type = int  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# 24. Retry/RateLimit — Error propagation paths
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_retry_enricher_exhausts_retries_and_raises() -> None:
    """Retry: when all retries fail, raises last error."""
    scope = _make_scope()

    async def always_fail(s: Scope) -> str:
        raise ValueError("always fails")

    policy = RetryPolicy[Exception].fixed(times=2, delay_seconds=0.0)
    r = Retry(policy=policy)
    with pytest.raises(ValueError, match="always fails"):
        await r.enrich(always_fail, scope)


@pytest.mark.asyncio
async def test_rate_limit_enricher_propagates_error() -> None:
    """RateLimit: when handler raises, error propagates through."""
    scope = _make_scope()

    async def failing_handler(s: Scope) -> str:
        raise RuntimeError("rate_limit_fail")

    policy = RateLimitPolicy(max_per_second=100.0, burst=10)
    rl = RateLimit(policy=policy)
    with pytest.raises(RuntimeError, match="rate_limit_fail"):
        await rl.enrich(failing_handler, scope)


# ═══════════════════════════════════════════════════════════════════════════════
# 25. Target-specific enrichable compile_handler_runtime defaults
# ═══════════════════════════════════════════════════════════════════════════════


def test_fastapi_enrichable_compile_handler_runtime() -> None:
    """FastAPIEnrichable.compile_handler_runtime adds self to enrichers."""

    @dataclass(frozen=True, slots=True)
    class FAPIEnricher:
        async def enrich_fastapi(self, call: EnricherNext[str], scope: Scope) -> str:
            return await call(scope)

        def compile_handler_runtime(self, ctx: HandlerRuntimeContext) -> HandlerRuntimeContext:
            from dataclasses import replace as dc_replace
            return dc_replace(ctx, enrichers=(*ctx.enrichers, self))

    enricher = FAPIEnricher()
    ctx = HandlerRuntimeContext()
    new_ctx = enricher.compile_handler_runtime(ctx)
    assert len(new_ctx.enrichers) == 1
    assert new_ctx.enrichers[0] is enricher


def test_cli_enrichable_compile_handler_runtime() -> None:
    """CLIEnrichable.compile_handler_runtime adds self to enrichers."""

    @dataclass(frozen=True, slots=True)
    class CLIEnricher:
        async def enrich_cli(self, call: EnricherNext[str], scope: Scope) -> str:
            return await call(scope)

        def compile_handler_runtime(self, ctx: HandlerRuntimeContext) -> HandlerRuntimeContext:
            from dataclasses import replace as dc_replace
            return dc_replace(ctx, enrichers=(*ctx.enrichers, self))

    enricher = CLIEnricher()
    ctx = HandlerRuntimeContext()
    new_ctx = enricher.compile_handler_runtime(ctx)
    assert len(new_ctx.enrichers) == 1
    assert new_ctx.enrichers[0] is enricher


def test_telegrinder_enrichable_compile_handler_runtime() -> None:
    """TelegrinderEnrichable.compile_handler_runtime adds self to enrichers."""

    @dataclass(frozen=True, slots=True)
    class TGEnricher:
        async def enrich_telegrinder(self, call: EnricherNext[str], scope: Scope) -> str:
            return await call(scope)

        def compile_handler_runtime(self, ctx: HandlerRuntimeContext) -> HandlerRuntimeContext:
            from dataclasses import replace as dc_replace
            return dc_replace(ctx, enrichers=(*ctx.enrichers, self))

    enricher = TGEnricher()
    ctx = HandlerRuntimeContext()
    new_ctx = enricher.compile_handler_runtime(ctx)
    assert len(new_ctx.enrichers) == 1
    assert new_ctx.enrichers[0] is enricher


def test_django_enrichable_compile_handler_runtime() -> None:
    """DjangoEnrichable.compile_handler_runtime adds self to enrichers."""

    @dataclass(frozen=True, slots=True)
    class DjEnricher:
        async def enrich_django(self, call: EnricherNext[str], scope: Scope) -> str:
            return await call(scope)

        def compile_handler_runtime(self, ctx: HandlerRuntimeContext) -> HandlerRuntimeContext:
            from dataclasses import replace as dc_replace
            return dc_replace(ctx, enrichers=(*ctx.enrichers, self))

    enricher = DjEnricher()
    ctx = HandlerRuntimeContext()
    new_ctx = enricher.compile_handler_runtime(ctx)
    assert len(new_ctx.enrichers) == 1
    assert new_ctx.enrichers[0] is enricher


# ═══════════════════════════════════════════════════════════════════════════════
# 26. Cached enricher
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cached_enricher_miss_then_hit() -> None:
    """Cached: first call is a miss (executes handler), second is a hit."""
    from emergent.wire.axis.surface.enrichers._impl import Cached
    from emergent import cache as C

    def _key(k: str) -> str:
        return f"key:{k}"

    def _fetch(k: str) -> LazyCoroResult[str, str]:
        return LazyCoroResult.pure(k)

    executor = (
        C.cache(key=_key, fetch=_fetch)
        .tier(C.LocalTier(max_size=100))
        .build()
    )

    call_count = 0

    async def counting_handler(s: Scope) -> str:
        nonlocal call_count
        call_count += 1
        return f"result_{call_count}"

    cached = Cached(
        executor=executor,
        key=lambda s: "test_scope_key",
    )

    scope = _make_scope()

    # First call: cache miss, handler executes
    result1 = await cached.enrich(counting_handler, scope)
    assert result1 == "result_1"
    assert call_count == 1

    # Second call: cache hit, handler NOT called again
    result2 = await cached.enrich(counting_handler, scope)
    assert result2 == "result_1"  # Same cached result
    assert call_count == 1  # Handler not called again


@pytest.mark.asyncio
async def test_cached_enricher_different_keys() -> None:
    """Cached: different keys produce different cache entries."""
    from emergent.wire.axis.surface.enrichers._impl import Cached
    from emergent import cache as C

    def _key(k: str) -> str:
        return f"key:{k}"

    def _fetch(k: str) -> LazyCoroResult[str, str]:
        return LazyCoroResult.pure(k)

    executor = (
        C.cache(key=_key, fetch=_fetch)
        .tier(C.LocalTier(max_size=100))
        .build()
    )

    call_count = 0

    async def counting_handler(s: Scope) -> str:
        nonlocal call_count
        call_count += 1
        return f"result_{call_count}"

    # Key based on injected int
    cached = Cached(
        executor=executor,
        key=lambda s: s.retrieve(int).unwrap().unbox(),
    )

    scope1 = _make_scope()
    scope1.inject(int, 1)
    scope2 = _make_scope()
    scope2.inject(int, 2)

    result1 = await cached.enrich(counting_handler, scope1)
    assert result1 == "result_1"

    result2 = await cached.enrich(counting_handler, scope2)
    assert result2 == "result_2"  # Different key, handler called again

    assert call_count == 2


def test_cached_enricher_is_frozen() -> None:
    """Cached enricher is frozen."""
    from emergent.wire.axis.surface.enrichers._impl import Cached
    from emergent import cache as C

    def _key(k: str) -> str:
        return f"key:{k}"

    def _fetch(k: str) -> LazyCoroResult[str, str]:
        return LazyCoroResult.pure(k)

    executor = (
        C.cache(key=_key, fetch=_fetch)
        .tier(C.LocalTier(max_size=100))
        .build()
    )

    c = Cached(executor=executor, key=lambda s: "x")
    with pytest.raises(FrozenInstanceError):
        c.executor = executor  # type: ignore[misc]
