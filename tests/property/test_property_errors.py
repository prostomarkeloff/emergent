# pyright: reportPrivateUsage=false
"""Property-based tests for error paths — verifying errors are raised correctly.

Uses hypothesis for random field names and negative integers to exercise
validation in Field.evaluate, Limit, Offset, compile_fields,
TargetCompiler, SchemaCompiler, fold_expr, and expr_from_dict.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
import hypothesis.strategies as st
from hypothesis import given, settings

from emergent.wire.axis.query._expr import (
    Field,
    Const,
    Eq,
    fold_expr,
)
from emergent.wire.axis.query._relational import Limit, Offset
from emergent.wire.axis.query._serialize import expr_from_dict
from emergent.wire.compile._phase import (
    compile_fields,
    CompilationPhase,
    SchemaCompiler,
)
from emergent.wire.compile._target import TargetCompiler


# ─── Test entity ──────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Point:
    x: int
    y: int


# ─── Strategies ───────────────────────────────────────────────────────────────

# Field names that will NOT be present on Point
missing_field_names = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvw"),
    min_size=1,
    max_size=20,
).filter(lambda s: s not in ("x", "y"))

negative_ints = st.integers(max_value=-1)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Field("missing").evaluate(obj) raises AttributeError
# ═══════════════════════════════════════════════════════════════════════════════


@given(name=missing_field_names)
@settings(max_examples=30)
def test_field_evaluate_missing_raises_attribute_error(name: str) -> None:
    """Field.evaluate raises AttributeError for objects without that field."""
    obj = Point(x=1, y=2)
    with pytest.raises(AttributeError, match=f"Field {name!r} not found"):
        Field(name).evaluate(obj)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Limit(-1) raises ValueError
# ═══════════════════════════════════════════════════════════════════════════════


@given(n=negative_ints)
@settings(max_examples=30)
def test_limit_negative_raises_value_error(n: int) -> None:
    """Limit with negative count raises ValueError."""
    with pytest.raises(ValueError, match="LIMIT must be non-negative"):
        Limit(n)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Offset(-1) raises ValueError
# ═══════════════════════════════════════════════════════════════════════════════


@given(n=negative_ints)
@settings(max_examples=30)
def test_offset_negative_raises_value_error(n: int) -> None:
    """Offset with negative count raises ValueError."""
    with pytest.raises(ValueError, match="OFFSET must be non-negative"):
        Offset(n)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. compile_fields with duplicate context_type raises ValueError
# ═══════════════════════════════════════════════════════════════════════════════


def test_compile_fields_duplicate_context_type() -> None:
    """compile_fields raises ValueError when two phases share context_type."""
    from typing import Protocol

    class _DummyCtx:
        pass

    class _DummyCompilable(Protocol):
        def compile_dummy(self, ctx: _DummyCtx) -> _DummyCtx: ...

    phase_a = CompilationPhase(
        _DummyCtx, _DummyCompilable,
        initial=lambda name, tp: _DummyCtx(),
    )
    phase_b = CompilationPhase(
        _DummyCtx, _DummyCompilable,
        initial=lambda name, tp: _DummyCtx(),
    )

    from emergent.wire.compile._core import Axes
    from emergent.wire.axis.schema import inspect_type

    @dataclass(frozen=True, slots=True)
    class Dummy:
        name: str = ""

    axes = Axes(schema=inspect_type)

    with pytest.raises(ValueError, match="Duplicate context_type"):
        compile_fields(Dummy, axes, [phase_a, phase_b])


# ═══════════════════════════════════════════════════════════════════════════════
# 5. TargetCompiler + TargetCompiler with different trigger_types raises TypeError
# ═══════════════════════════════════════════════════════════════════════════════


def test_target_compiler_add_different_trigger_types() -> None:
    """Adding TargetCompilers with different trigger_types raises TypeError."""

    class TriggerA:
        pass

    class TriggerB:
        pass

    compiler_a: TargetCompiler[TriggerA] = TargetCompiler(
        trigger_type=TriggerA, adapters=()
    )
    compiler_b: TargetCompiler[TriggerB] = TargetCompiler(
        trigger_type=TriggerB, adapters=()
    )

    with pytest.raises(TypeError, match="Cannot combine TargetCompilers"):
        compiler_a + compiler_b  # type: ignore[operator]


# ═══════════════════════════════════════════════════════════════════════════════
# 6. SchemaCompiler.with_phase for existing context_type raises ValueError
# ═══════════════════════════════════════════════════════════════════════════════


def test_schema_compiler_with_phase_duplicate() -> None:
    """with_phase raises ValueError if context_type already present."""
    from typing import Protocol

    class _Ctx:
        pass

    class _Compilable(Protocol):
        def compile_test(self, ctx: _Ctx) -> _Ctx: ...

    phase = CompilationPhase(
        _Ctx, _Compilable,
        initial=lambda name, tp: _Ctx(),
    )

    compiler = SchemaCompiler(phases=(phase,))

    with pytest.raises(ValueError, match="already present"):
        compiler.with_phase(phase)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. SchemaCompiler.replace_phase for missing context_type raises KeyError
# ═══════════════════════════════════════════════════════════════════════════════


def test_schema_compiler_replace_phase_missing() -> None:
    """replace_phase raises KeyError if context_type not found."""
    from typing import Protocol

    class _CtxA:
        pass

    class _CompilableA(Protocol):
        def compile_a(self, ctx: _CtxA) -> _CtxA: ...

    class _CtxB:
        pass

    class _CompilableB(Protocol):
        def compile_b(self, ctx: _CtxB) -> _CtxB: ...

    phase_a = CompilationPhase(
        _CtxA, _CompilableA,
        initial=lambda name, tp: _CtxA(),
    )
    phase_b = CompilationPhase(
        _CtxB, _CompilableB,
        initial=lambda name, tp: _CtxB(),
    )

    compiler = SchemaCompiler(phases=(phase_a,))

    with pytest.raises(KeyError, match="No phase with context_type"):
        compiler.replace_phase(phase_b, phase_b)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. fold_expr with no handler and no default raises TypeError
# ═══════════════════════════════════════════════════════════════════════════════


def test_fold_expr_no_handler_no_default_raises_type_error() -> None:
    """fold_expr raises TypeError when no handler matches and no default is set."""
    expr = Eq(Field("x"), Const(1))

    # Empty handler map, no default
    with pytest.raises(TypeError, match="No handler for Eq"):
        fold_expr(expr, {})


# ═══════════════════════════════════════════════════════════════════════════════
# 9. expr_from_dict({"op": "nonexistent"}) raises ValueError
# ═══════════════════════════════════════════════════════════════════════════════


@given(op_name=st.text(min_size=1, max_size=30).filter(
    lambda s: s not in {
        "field", "const", "eq", "ne", "lt", "le", "gt", "ge",
        "and", "or", "not", "in", "contains", "startswith", "endswith",
        "is_null", "is_not_null", "between", "like", "ilike", "regex",
        "array_contains", "array_any", "array_all", "array_overlap",
        "json_extract", "json_contains", "json_has_key",
    }
))
@settings(max_examples=30)
def test_expr_from_dict_unknown_op_raises_value_error(op_name: str) -> None:
    """expr_from_dict raises ValueError for unknown operation names."""
    with pytest.raises(ValueError, match="Unknown operation"):
        expr_from_dict({"op": op_name})


# ═══════════════════════════════════════════════════════════════════════════════
# 10. SchemaCompiler[missing_type] raises KeyError
# ═══════════════════════════════════════════════════════════════════════════════


def test_schema_compiler_getitem_missing_raises_key_error() -> None:
    """SchemaCompiler.__getitem__ raises KeyError for missing context_type."""
    compiler = SchemaCompiler(phases=())

    class _Missing:
        pass

    with pytest.raises(KeyError):
        compiler[_Missing]


# ═══════════════════════════════════════════════════════════════════════════════
# 11. TargetCompiler[missing_codec] raises KeyError
# ═══════════════════════════════════════════════════════════════════════════════


def test_target_compiler_getitem_missing_raises_key_error() -> None:
    """TargetCompiler.__getitem__ raises KeyError for missing codec_type."""

    class _Trigger:
        pass

    class _MissingCodec:
        pass

    compiler: TargetCompiler[_Trigger] = TargetCompiler(
        trigger_type=_Trigger, adapters=()
    )

    with pytest.raises(KeyError):
        compiler[_MissingCodec]
