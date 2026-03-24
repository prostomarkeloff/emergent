# pyright: reportPrivateUsage=false
"""Property-based and unit tests for _target.py, _phase.py, and ops/_graph.py.

Aggressively covers uncovered branches: lego operations, algebraic operators,
error paths, and edge cases.
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from emergent.wire.compile._target import CodecBinding, TargetCompiler
from emergent.wire.compile._phase import (
    EntityFold,
    CompilationPhase,
    FieldCompilation,
    EntityCompilation,
    SchemaCompiler,
    Compilation,
)
from emergent.wire.axis._capability import Capability, StorageFieldContext
from emergent.wire.axis.schema._inspect import FieldInfo
from emergent.ops._graph import Op, _CachedOp, _is_op_type, Runner, ops

from kungfu import Result, Ok, Error


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level Op types — must be at module level for get_type_hints resolution
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class _TestOpA(Op[int, str]):
    x: int


@dataclass(frozen=True, slots=True)
class _TestOpB(Op[str, str]):
    y: str


@dataclass(frozen=True, slots=True)
class _UnboundOp(Op[int, str]):
    x: int


# ═══════════════════════════════════════════════════════════════════════════════
# Test fixtures — dummy types and protocols for isolated testing
# ═══════════════════════════════════════════════════════════════════════════════


class TriggerA:
    """Dummy trigger type A."""


class TriggerB:
    """Dummy trigger type B — distinct from A for mismatch tests."""


class CodecAlpha:
    """Dummy codec type."""


class CodecBeta:
    """Another dummy codec type."""


class CodecGamma:
    """Third dummy codec type."""


def _wrap_alpha(*args: object) -> object:
    return "alpha_wrapped"


def _wrap_beta(*args: object) -> object:
    return "beta_wrapped"


def _wrap_replacement(*args: object) -> object:
    return "replaced"


@dataclass(frozen=True, slots=True)
class FakeCtxA:
    name: str
    typ: type


@dataclass(frozen=True, slots=True)
class FakeCtxB:
    name: str
    typ: type


@dataclass(frozen=True, slots=True)
class FakeCtxC:
    name: str
    typ: type


@dataclass(frozen=True, slots=True)
class FakeEntityCtxA:
    class_name: str


@dataclass(frozen=True, slots=True)
class FakeEntityCtxB:
    class_name: str


@runtime_checkable
class FakeCompilableA(Protocol):
    def compile_fake_a(self, ctx: FakeCtxA) -> FakeCtxA: ...


@runtime_checkable
class FakeCompilableB(Protocol):
    def compile_fake_b(self, ctx: FakeCtxB) -> FakeCtxB: ...


@runtime_checkable
class FakeCompilableC(Protocol):
    def compile_fake_c(self, ctx: FakeCtxC) -> FakeCtxC: ...


@runtime_checkable
class FakeEntityCompilableA(Protocol):
    def compile_entity_a(self, ctx: FakeEntityCtxA) -> FakeEntityCtxA: ...


@runtime_checkable
class FakeEntityCompilableB(Protocol):
    def compile_entity_b(self, ctx: FakeEntityCtxB) -> FakeEntityCtxB: ...


class NoCompileMethodProtocol(Protocol):
    """Protocol without compile_* method — used to test __post_init__ error."""
    def process(self, ctx: object) -> object: ...


# Phase factories
def _make_phase_a() -> CompilationPhase[FakeCtxA]:
    return CompilationPhase(
        FakeCtxA, FakeCompilableA,
        lambda n, t: FakeCtxA(n, t),
    )


def _make_phase_b() -> CompilationPhase[FakeCtxB]:
    return CompilationPhase(
        FakeCtxB, FakeCompilableB,
        lambda n, t: FakeCtxB(n, t),
    )


def _make_phase_c() -> CompilationPhase[FakeCtxC]:
    return CompilationPhase(
        FakeCtxC, FakeCompilableC,
        lambda n, t: FakeCtxC(n, t),
    )


def _make_entity_fold_a() -> EntityFold[FakeEntityCtxA]:
    return EntityFold(
        FakeEntityCtxA, FakeEntityCompilableA,
        lambda name: FakeEntityCtxA(class_name=name),
    )


def _make_target_compiler(
    *bindings: CodecBinding[TriggerA],
) -> TargetCompiler[TriggerA]:
    return TargetCompiler(
        trigger_type=TriggerA,
        adapters=bindings,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# _target.py — CodecBinding
# ═══════════════════════════════════════════════════════════════════════════════


class TestCodecBindingSameSlot:
    """CodecBinding.same_slot: same codec_type is True, different is False."""

    def test_same_codec_type_returns_true(self) -> None:
        a: CodecBinding[TriggerA] = CodecBinding(CodecAlpha, _wrap_alpha)
        b: CodecBinding[TriggerA] = CodecBinding(CodecAlpha, _wrap_beta)
        assert a.same_slot(b) is True

    def test_different_codec_type_returns_false(self) -> None:
        a: CodecBinding[TriggerA] = CodecBinding(CodecAlpha, _wrap_alpha)
        b: CodecBinding[TriggerA] = CodecBinding(CodecBeta, _wrap_beta)
        assert a.same_slot(b) is False


class TestCodecBindingLegacyProperty:
    """CodecBinding.legacy reflects _legacy flag."""

    def test_legacy_false_by_default(self) -> None:
        b: CodecBinding[TriggerA] = CodecBinding(CodecAlpha, _wrap_alpha)
        assert b.legacy is False

    def test_legacy_true_when_set(self) -> None:
        b: CodecBinding[TriggerA] = CodecBinding(CodecAlpha, _wrap_alpha, _legacy=True)
        assert b.legacy is True

    def test_wrap_property_returns_from_codec(self) -> None:
        b: CodecBinding[TriggerA] = CodecBinding(CodecAlpha, _wrap_alpha)
        assert b.wrap is b.from_codec


# ═══════════════════════════════════════════════════════════════════════════════
# _target.py — TargetCompiler lego operations
# ═══════════════════════════════════════════════════════════════════════════════


class TestTargetCompilerWithBinding:
    """with_binding raises on duplicate, succeeds on new."""

    def test_adds_new_binding(self) -> None:
        tc = _make_target_compiler()
        result = tc.with_binding(CodecAlpha, _wrap_alpha)
        assert len(result) == 1
        assert result[CodecAlpha].from_codec is _wrap_alpha

    def test_raises_on_duplicate(self) -> None:
        tc = _make_target_compiler(CodecBinding(CodecAlpha, _wrap_alpha))
        with pytest.raises(ValueError, match="already present"):
            tc.with_binding(CodecAlpha, _wrap_beta)


class TestTargetCompilerReplaceBinding:
    """replace_binding raises on missing, replaces on found."""

    def test_replaces_existing(self) -> None:
        tc = _make_target_compiler(CodecBinding(CodecAlpha, _wrap_alpha))
        result = tc.replace_binding(CodecAlpha, _wrap_replacement)
        assert result[CodecAlpha].from_codec is _wrap_replacement

    def test_raises_on_missing(self) -> None:
        tc = _make_target_compiler()
        with pytest.raises(KeyError, match="No binding"):
            tc.replace_binding(CodecAlpha, _wrap_replacement)


class TestTargetCompilerWithoutBinding:
    """without_binding removes codec_type."""

    def test_removes_present(self) -> None:
        tc = _make_target_compiler(
            CodecBinding(CodecAlpha, _wrap_alpha),
            CodecBinding(CodecBeta, _wrap_beta),
        )
        result = tc.without_binding(CodecAlpha)
        assert len(result) == 1
        assert CodecAlpha not in result
        assert CodecBeta in result

    def test_no_op_when_absent(self) -> None:
        tc = _make_target_compiler(CodecBinding(CodecAlpha, _wrap_alpha))
        result = tc.without_binding(CodecGamma)
        assert len(result) == 1


class TestTargetCompilerWithCodec:
    """with_codec raises on duplicate, uses legacy flag."""

    def test_adds_legacy_binding(self) -> None:
        tc = _make_target_compiler()
        result = tc.with_codec(CodecAlpha, _wrap_alpha)
        assert result[CodecAlpha].legacy is True

    def test_raises_on_duplicate(self) -> None:
        tc = _make_target_compiler(CodecBinding(CodecAlpha, _wrap_alpha))
        with pytest.raises(ValueError, match="already present"):
            tc.with_codec(CodecAlpha, _wrap_beta)


class TestTargetCompilerReplaceCodec:
    """replace_codec raises on missing, swaps to legacy."""

    def test_replaces_existing_with_legacy(self) -> None:
        tc = _make_target_compiler(CodecBinding(CodecAlpha, _wrap_alpha))
        result = tc.replace_codec(CodecAlpha, _wrap_replacement)
        assert result[CodecAlpha].legacy is True
        assert result[CodecAlpha].from_codec is _wrap_replacement

    def test_raises_on_missing(self) -> None:
        tc = _make_target_compiler()
        with pytest.raises(KeyError, match="No adapter"):
            tc.replace_codec(CodecAlpha, _wrap_replacement)


class TestTargetCompilerAlgebra:
    """Algebraic operations: +, |, -, &, in, len, iter, bool, getitem."""

    def test_add_type_mismatch_raises(self) -> None:
        tc_a: TargetCompiler[Any] = TargetCompiler(trigger_type=TriggerA, adapters=())
        tc_b: TargetCompiler[Any] = TargetCompiler(trigger_type=TriggerB, adapters=())
        with pytest.raises(TypeError, match="different trigger types"):
            _result = tc_a + tc_b

    def test_or_type_mismatch_raises(self) -> None:
        tc_a: TargetCompiler[Any] = TargetCompiler(trigger_type=TriggerA, adapters=())
        tc_b: TargetCompiler[Any] = TargetCompiler(trigger_type=TriggerB, adapters=())
        with pytest.raises(TypeError, match="different trigger types"):
            _result = tc_a | tc_b

    def test_add_left_biased(self) -> None:
        tc_a = _make_target_compiler(CodecBinding(CodecAlpha, _wrap_alpha))
        tc_b = _make_target_compiler(CodecBinding(CodecAlpha, _wrap_beta))
        result = tc_a + tc_b
        # Left-biased: tc_a's binding kept
        assert result[CodecAlpha].from_codec is _wrap_alpha

    def test_add_union(self) -> None:
        tc_a = _make_target_compiler(CodecBinding(CodecAlpha, _wrap_alpha))
        tc_b = _make_target_compiler(CodecBinding(CodecBeta, _wrap_beta))
        result = tc_a + tc_b
        assert len(result) == 2

    def test_or_right_biased(self) -> None:
        tc_a = _make_target_compiler(CodecBinding(CodecAlpha, _wrap_alpha))
        tc_b = _make_target_compiler(CodecBinding(CodecAlpha, _wrap_beta))
        result = tc_a | tc_b
        # Right-biased: tc_b's binding wins
        assert result[CodecAlpha].from_codec is _wrap_beta

    def test_sub_by_type(self) -> None:
        tc = _make_target_compiler(
            CodecBinding(CodecAlpha, _wrap_alpha),
            CodecBinding(CodecBeta, _wrap_beta),
        )
        result = tc - CodecAlpha
        assert len(result) == 1
        assert CodecAlpha not in result

    def test_sub_by_binding(self) -> None:
        tc = _make_target_compiler(
            CodecBinding(CodecAlpha, _wrap_alpha),
            CodecBinding(CodecBeta, _wrap_beta),
        )
        result = tc - CodecBinding(CodecAlpha, _wrap_alpha)
        assert len(result) == 1

    def test_and_intersection(self) -> None:
        tc_a = _make_target_compiler(
            CodecBinding(CodecAlpha, _wrap_alpha),
            CodecBinding(CodecBeta, _wrap_beta),
        )
        tc_b = _make_target_compiler(CodecBinding(CodecBeta, _wrap_beta))
        result = tc_a & tc_b
        assert len(result) == 1
        assert CodecBeta in result

    def test_contains_by_type(self) -> None:
        tc = _make_target_compiler(CodecBinding(CodecAlpha, _wrap_alpha))
        assert CodecAlpha in tc
        assert CodecBeta not in tc

    def test_contains_by_binding(self) -> None:
        binding: CodecBinding[TriggerA] = CodecBinding(CodecAlpha, _wrap_alpha)
        tc = _make_target_compiler(binding)
        assert binding in tc

    def test_contains_non_type_returns_false(self) -> None:
        tc = _make_target_compiler(CodecBinding(CodecAlpha, _wrap_alpha))
        assert "not_a_type" not in tc

    def test_iteration(self) -> None:
        bindings: tuple[CodecBinding[TriggerA], CodecBinding[TriggerA]] = (
            CodecBinding(CodecAlpha, _wrap_alpha),
            CodecBinding(CodecBeta, _wrap_beta),
        )
        tc = _make_target_compiler(*bindings)
        assert list(tc) == list(tc.adapters)

    def test_bool_empty_is_falsy(self) -> None:
        tc = _make_target_compiler()
        assert not tc

    def test_bool_nonempty_is_truthy(self) -> None:
        tc = _make_target_compiler(CodecBinding(CodecAlpha, _wrap_alpha))
        assert tc

    def test_getitem_raises_on_missing(self) -> None:
        tc = _make_target_compiler()
        with pytest.raises(KeyError):
            tc[CodecAlpha]

    def test_add_codec_binding_directly(self) -> None:
        tc = _make_target_compiler(CodecBinding(CodecAlpha, _wrap_alpha))
        binding: CodecBinding[TriggerA] = CodecBinding(CodecBeta, _wrap_beta)
        result = tc + binding
        assert len(result) == 2
        assert CodecBeta in result

    def test_or_codec_binding_directly(self) -> None:
        tc = _make_target_compiler(CodecBinding(CodecAlpha, _wrap_alpha))
        binding: CodecBinding[TriggerA] = CodecBinding(CodecAlpha, _wrap_beta)
        result = tc | binding
        # Right-biased: binding wins
        assert result[CodecAlpha].from_codec is _wrap_beta

    def test_bindings_property_alias(self) -> None:
        bindings: tuple[CodecBinding[TriggerA]] = (CodecBinding(CodecAlpha, _wrap_alpha),)
        tc = _make_target_compiler(*bindings)
        assert tc.bindings is tc.adapters


# ═══════════════════════════════════════════════════════════════════════════════
# _phase.py — EntityFold
# ═══════════════════════════════════════════════════════════════════════════════


class TestEntityFold:
    """EntityFold.__post_init__ extracts compile_* method name."""

    def test_extracts_method_name(self) -> None:
        ef = _make_entity_fold_a()
        assert ef.method == "compile_entity_a"

    def test_raises_on_no_compile_method(self) -> None:
        with pytest.raises(ValueError, match="No compile_\\* method"):
            EntityFold(
                FakeEntityCtxA,
                NoCompileMethodProtocol,
                lambda name: FakeEntityCtxA(class_name=name),
            )


# ═══════════════════════════════════════════════════════════════════════════════
# _phase.py — CompilationPhase
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompilationPhasePostInit:
    """CompilationPhase.__post_init__ extracts compile_* method name."""

    def test_extracts_method_name(self) -> None:
        phase = _make_phase_a()
        assert phase.method == "compile_fake_a"

    def test_raises_on_no_compile_method(self) -> None:
        with pytest.raises(ValueError, match="No compile_\\* method"):
            CompilationPhase(
                FakeCtxA,
                NoCompileMethodProtocol,
                lambda n, t: FakeCtxA(n, t),
            )


class TestCompilationPhaseWithHandlers:
    """with_handlers merges or returns same phase."""

    def test_with_handlers_none_returns_same(self) -> None:
        phase = _make_phase_a()
        result = phase.with_handlers(None)
        assert result is phase

    def test_with_handlers_merges(self) -> None:
        class DummyCap(Capability):
            ...

        def handler_fn(cap: Capability, ctx: FakeCtxA) -> FakeCtxA:
            return ctx

        phase = _make_phase_a()
        result = phase.with_handlers({DummyCap: handler_fn})
        assert result.handlers is not None
        assert DummyCap in result.handlers

    def test_with_handlers_merges_existing(self) -> None:
        class CapX(Capability):
            ...

        class CapY(Capability):
            ...

        def hx(cap: Capability, ctx: FakeCtxA) -> FakeCtxA:
            return ctx

        def hy(cap: Capability, ctx: FakeCtxA) -> FakeCtxA:
            return ctx

        phase = _make_phase_a().with_handlers({CapX: hx})
        result = phase.with_handlers({CapY: hy})
        assert result.handlers is not None
        assert CapX in result.handlers
        assert CapY in result.handlers


class TestCompilationPhaseEntity:
    """with_entity/without_entity attach/remove EntityFold."""

    def test_with_entity(self) -> None:
        phase = _make_phase_a()
        ef = _make_entity_fold_a()
        result = phase.with_entity(ef)
        assert result.entity is ef

    def test_without_entity(self) -> None:
        ef = _make_entity_fold_a()
        phase = _make_phase_a().with_entity(ef)
        result = phase.without_entity()
        assert result.entity is None


class TestCompilationPhaseSameSlot:
    """same_slot True for same context_type, False otherwise."""

    def test_same_context_type(self) -> None:
        a = _make_phase_a()
        b = CompilationPhase(
            FakeCtxA, FakeCompilableA,
            lambda n, t: FakeCtxA(n, t),
        )
        assert a.same_slot(b) is True

    def test_different_context_type(self) -> None:
        a = _make_phase_a()
        b = _make_phase_b()
        assert a.same_slot(b) is False


# ═══════════════════════════════════════════════════════════════════════════════
# _phase.py — CompilationPhase algebraic ops
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompilationPhaseAdd:
    """CompilationPhase + CompilationPhase = SchemaCompiler with 2 phases."""

    def test_phase_plus_phase(self) -> None:
        a = _make_phase_a()
        b = _make_phase_b()
        result = a + b
        assert isinstance(result, SchemaCompiler)
        assert len(result) == 2

    def test_phase_plus_schema_compiler(self) -> None:
        a = _make_phase_a()
        b = _make_phase_b()
        c = _make_phase_c()
        sc = SchemaCompiler(phases=(b, c))
        result = a + sc
        assert isinstance(result, SchemaCompiler)
        assert len(result) == 3

    def test_schema_compiler_plus_phase_via_radd(self) -> None:
        a = _make_phase_a()
        b = _make_phase_b()
        sc = SchemaCompiler(phases=(a,))
        result = sc + b
        assert isinstance(result, SchemaCompiler)
        assert len(result) == 2

    def test_radd_phase_plus_phase(self) -> None:
        a = _make_phase_a()
        b = _make_phase_b()
        # __radd__ is called when left operand is CompilationPhase
        # a + b triggers a.__add__(b) which is direct
        # b.__radd__(a) is called when a is CompilationPhase and doesn't have __add__
        # Test explicitly:
        result = b.__radd__(a)
        assert isinstance(result, SchemaCompiler)
        assert len(result) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# _phase.py — SchemaCompiler
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchemaCompilerWithPhase:
    """with_phase raises on duplicate, adds on new."""

    def test_adds_new_phase(self) -> None:
        sc = SchemaCompiler(phases=(_make_phase_a(),))
        result = sc.with_phase(_make_phase_b())
        assert len(result) == 2

    def test_raises_on_duplicate(self) -> None:
        sc = SchemaCompiler(phases=(_make_phase_a(),))
        with pytest.raises(ValueError, match="already present"):
            sc.with_phase(_make_phase_a())


class TestSchemaCompilerWithPhases:
    """with_phases raises on any duplicate."""

    def test_adds_multiple(self) -> None:
        sc = SchemaCompiler(phases=())
        result = sc.with_phases(_make_phase_a(), _make_phase_b())
        assert len(result) == 2

    def test_raises_on_duplicate_in_batch(self) -> None:
        sc = SchemaCompiler(phases=(_make_phase_a(),))
        with pytest.raises(ValueError, match="already present"):
            sc.with_phases(_make_phase_a(), _make_phase_b())


class TestSchemaCompilerWithoutPhase:
    """without_phase removes by phase or by type."""

    def test_remove_by_phase(self) -> None:
        pa = _make_phase_a()
        pb = _make_phase_b()
        sc = SchemaCompiler(phases=(pa, pb))
        result = sc.without_phase(pa)
        assert len(result) == 1
        assert FakeCtxA not in result

    def test_remove_by_type(self) -> None:
        pa = _make_phase_a()
        pb = _make_phase_b()
        sc = SchemaCompiler(phases=(pa, pb))
        result = sc.without_phase(FakeCtxA)
        assert len(result) == 1
        assert FakeCtxA not in result


class TestSchemaCompilerReplacePhase:
    """replace_phase raises on missing, replaces correctly."""

    def test_raises_on_missing(self) -> None:
        sc = SchemaCompiler(phases=(_make_phase_a(),))
        with pytest.raises(KeyError, match="No phase"):
            sc.replace_phase(FakeCtxB, _make_phase_b())

    def test_replaces_by_phase(self) -> None:
        pa = _make_phase_a()
        new_pa = CompilationPhase(
            FakeCtxA, FakeCompilableA,
            lambda n, t: FakeCtxA("replaced", t),
        )
        sc = SchemaCompiler(phases=(pa, _make_phase_b()))
        result = sc.replace_phase(pa, new_pa)
        assert len(result) == 2
        assert result[FakeCtxA] is new_pa

    def test_replaces_by_type(self) -> None:
        pa = _make_phase_a()
        new_pa = CompilationPhase(
            FakeCtxA, FakeCompilableA,
            lambda n, t: FakeCtxA("replaced", t),
        )
        sc = SchemaCompiler(phases=(pa,))
        result = sc.replace_phase(FakeCtxA, new_pa)
        assert result[FakeCtxA] is new_pa


class TestSchemaCompilerAlgebra:
    """SchemaCompiler algebraic operations: +, |, -, &, in, len, iter, bool, []."""

    def test_add_left_biased(self) -> None:
        sc_a = SchemaCompiler(phases=(_make_phase_a(),))
        sc_b = SchemaCompiler(phases=(_make_phase_a(), _make_phase_b()))
        result = sc_a + sc_b
        # Left-biased: sc_a's phase_a kept, sc_b's phase_b added
        assert len(result) == 2

    def test_or_right_biased(self) -> None:
        pa1 = _make_phase_a()
        pa2 = CompilationPhase(
            FakeCtxA, FakeCompilableA,
            lambda n, t: FakeCtxA("overridden", t),
        )
        sc_a = SchemaCompiler(phases=(pa1,))
        sc_b = SchemaCompiler(phases=(pa2,))
        result = sc_a | sc_b
        assert result[FakeCtxA] is pa2

    def test_or_with_phase(self) -> None:
        pa1 = _make_phase_a()
        pa2 = CompilationPhase(
            FakeCtxA, FakeCompilableA,
            lambda n, t: FakeCtxA("overridden", t),
        )
        sc = SchemaCompiler(phases=(pa1,))
        result = sc | pa2
        assert result[FakeCtxA] is pa2

    def test_ror_with_phase(self) -> None:
        pa = _make_phase_a()
        pb = _make_phase_b()
        sc = SchemaCompiler(phases=(pb,))
        # pa | sc triggers pa.__or__(sc) which fails, then sc.__ror__(pa)
        result = pa.__radd__(sc)
        # This is __radd__, not __ror__. Let's test __ror__ directly.
        result = sc.__ror__(pa)
        assert isinstance(result, SchemaCompiler)
        assert FakeCtxA in result

    def test_sub_by_compiler(self) -> None:
        sc_full = SchemaCompiler(phases=(_make_phase_a(), _make_phase_b()))
        sc_remove = SchemaCompiler(phases=(_make_phase_a(),))
        result = sc_full - sc_remove
        assert len(result) == 1
        assert FakeCtxA not in result

    def test_sub_by_phase(self) -> None:
        sc = SchemaCompiler(phases=(_make_phase_a(), _make_phase_b()))
        result = sc - _make_phase_a()
        assert len(result) == 1

    def test_sub_by_type(self) -> None:
        sc = SchemaCompiler(phases=(_make_phase_a(), _make_phase_b()))
        result = sc - FakeCtxA
        assert len(result) == 1

    def test_and_intersection(self) -> None:
        sc_a = SchemaCompiler(phases=(_make_phase_a(), _make_phase_b()))
        sc_b = SchemaCompiler(phases=(_make_phase_b(),))
        result = sc_a & sc_b
        assert len(result) == 1
        assert FakeCtxB in result

    def test_contains_by_phase(self) -> None:
        pa = _make_phase_a()
        sc = SchemaCompiler(phases=(pa,))
        assert pa in sc
        assert _make_phase_b() not in sc

    def test_contains_by_type(self) -> None:
        sc = SchemaCompiler(phases=(_make_phase_a(),))
        assert FakeCtxA in sc
        assert FakeCtxB not in sc

    def test_len(self) -> None:
        sc = SchemaCompiler(phases=(_make_phase_a(), _make_phase_b()))
        assert len(sc) == 2

    def test_iter(self) -> None:
        pa = _make_phase_a()
        pb = _make_phase_b()
        sc = SchemaCompiler(phases=(pa, pb))
        assert list(sc) == [pa, pb]

    def test_bool_empty_falsy(self) -> None:
        sc = SchemaCompiler(phases=())
        assert not sc

    def test_bool_nonempty_truthy(self) -> None:
        sc = SchemaCompiler(phases=(_make_phase_a(),))
        assert sc

    def test_getitem_found(self) -> None:
        pa = _make_phase_a()
        sc = SchemaCompiler(phases=(pa,))
        assert sc[FakeCtxA] is pa

    def test_getitem_missing_raises(self) -> None:
        sc = SchemaCompiler(phases=(_make_phase_a(),))
        with pytest.raises(KeyError):
            sc[FakeCtxB]


# ═══════════════════════════════════════════════════════════════════════════════
# _phase.py — FieldCompilation
# ═══════════════════════════════════════════════════════════════════════════════


class TestFieldCompilationGetitem:
    """FieldCompilation.__getitem__ type mismatch raises TypeError."""

    def test_type_mismatch_raises(self) -> None:
        # Store an object of the wrong type under a context_type key
        fc = FieldCompilation(
            name="test_field",
            info=FieldInfo(
                name="test_field",
                base_type=str,
                is_optional=False,
                capabilities=(),
            ),
            _contexts={FakeCtxA: "not_a_FakeCtxA"},
        )
        phase = _make_phase_a()
        with pytest.raises(TypeError, match="Expected"):
            fc[phase]

    def test_correct_type_succeeds(self) -> None:
        ctx_val = FakeCtxA(name="f", typ=str)
        fc = FieldCompilation(
            name="test_field",
            info=FieldInfo(
                name="test_field",
                base_type=str,
                is_optional=False,
                capabilities=(),
            ),
            _contexts={FakeCtxA: ctx_val},
        )
        phase = _make_phase_a()
        assert fc[phase] is ctx_val


# ═══════════════════════════════════════════════════════════════════════════════
# _phase.py — EntityCompilation
# ═══════════════════════════════════════════════════════════════════════════════


class TestEntityCompilation:
    """EntityCompilation.get, has_entity, __getitem__, __iter__, __len__."""

    def test_get_returns_none_for_missing(self) -> None:
        ec = EntityCompilation(fields=(), _entity_contexts={})
        ef = _make_entity_fold_a()
        assert ec.get(ef) is None

    def test_get_returns_context(self) -> None:
        ctx = FakeEntityCtxA(class_name="Test")
        ec = EntityCompilation(
            fields=(),
            _entity_contexts={FakeEntityCtxA: ctx},
        )
        ef = _make_entity_fold_a()
        assert ec.get(ef) is ctx

    def test_has_entity_true(self) -> None:
        ec = EntityCompilation(
            fields=(),
            _entity_contexts={FakeEntityCtxA: FakeEntityCtxA("X")},
        )
        fold_any: Any = _make_entity_fold_a()
        assert ec.has_entity(fold_any) is True

    def test_has_entity_false(self) -> None:
        ec = EntityCompilation(fields=(), _entity_contexts={})
        fold_any: Any = _make_entity_fold_a()
        assert ec.has_entity(fold_any) is False

    def test_getitem_raises_on_missing(self) -> None:
        ec = EntityCompilation(fields=(), _entity_contexts={})
        with pytest.raises(KeyError, match="No entity context"):
            ec[_make_entity_fold_a()]

    def test_getitem_returns_context(self) -> None:
        ctx = FakeEntityCtxA(class_name="Test")
        ec = EntityCompilation(
            fields=(),
            _entity_contexts={FakeEntityCtxA: ctx},
        )
        assert ec[_make_entity_fold_a()] is ctx

    def test_iter_yields_fields(self) -> None:
        fc = FieldCompilation(
            name="x",
            info=FieldInfo(name="x", base_type=int, is_optional=False, capabilities=()),
            _contexts={},
        )
        ec = EntityCompilation(fields=(fc,), _entity_contexts={})
        assert list(ec) == [fc]
        assert len(ec) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# _phase.py — Compilation.identity_field
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompilationIdentityField:
    """Compilation.identity_field finds Identity field or None."""

    def test_no_identity(self) -> None:
        fc = FieldCompilation(
            name="name",
            info=FieldInfo(name="name", base_type=str, is_optional=False, capabilities=()),
            _contexts={
                StorageFieldContext: StorageFieldContext(
                    field_name="name", field_type=str, is_identity=False,
                ),
            },
        )
        comp: Compilation[str, Any] = Compilation(model=dict, entity=str, fields=(fc,))
        assert comp.identity_field is None

    def test_finds_identity(self) -> None:
        fc_id = FieldCompilation(
            name="id",
            info=FieldInfo(name="id", base_type=int, is_optional=False, capabilities=()),
            _contexts={
                StorageFieldContext: StorageFieldContext(
                    field_name="id", field_type=int, is_identity=True,
                ),
            },
        )
        fc_other = FieldCompilation(
            name="name",
            info=FieldInfo(name="name", base_type=str, is_optional=False, capabilities=()),
            _contexts={
                StorageFieldContext: StorageFieldContext(
                    field_name="name", field_type=str, is_identity=False,
                ),
            },
        )
        comp: Compilation[str, Any] = Compilation(model=dict, entity=str, fields=(fc_id, fc_other))
        assert comp.identity_field == "id"


# ═══════════════════════════════════════════════════════════════════════════════
# ops/_graph.py — _is_op_type
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsOpType:
    """_is_op_type: True for Op subclasses, False for non-Op types, handles TypeError."""

    def test_true_for_op_subclass(self) -> None:
        assert _is_op_type(_TestOpA) is True

    def test_false_for_non_op_type(self) -> None:
        assert _is_op_type(int) is False
        assert _is_op_type(str) is False

    def test_false_for_non_type(self) -> None:
        assert _is_op_type("hello") is False
        assert _is_op_type(42) is False
        assert _is_op_type(None) is False

    def test_true_for_op_base(self) -> None:
        # Op itself is abstract but is still a subclass of Op
        assert _is_op_type(Op) is True


# ═══════════════════════════════════════════════════════════════════════════════
# ops/_graph.py — _CachedOp
# ═══════════════════════════════════════════════════════════════════════════════


class TestCachedOp:
    """_CachedOp wraps a Result and returns it via get() and __await__."""

    @pytest.mark.anyio
    async def test_get_returns_ok(self) -> None:
        cached: _CachedOp[int, str] = _CachedOp(Ok(42))
        result = await cached.get()
        assert result == Ok(42)

    @pytest.mark.anyio
    async def test_get_returns_error(self) -> None:
        cached: _CachedOp[int, str] = _CachedOp(Error("fail"))
        result = await cached.get()
        assert result == Error("fail")

    @pytest.mark.anyio
    async def test_await(self) -> None:
        cached: _CachedOp[str, str] = _CachedOp(Ok("hello"))
        result = await cached
        assert result == Ok("hello")


# ═══════════════════════════════════════════════════════════════════════════════
# ops/_graph.py — OpsBuilder
# ═══════════════════════════════════════════════════════════════════════════════


class TestOpsBuilder:
    """OpsBuilder.on returns new builder, accumulates, last wins."""

    def test_on_returns_new_builder(self) -> None:
        async def handler(req: _TestOpA) -> Result[int, str]:
            return Ok(req.x)

        builder = ops()
        new_builder = builder.on(_TestOpA, handler)
        assert new_builder is not builder
        assert len(new_builder._items) == 1
        assert len(builder._items) == 0

    def test_on_accumulates(self) -> None:
        async def handler_a(req: _TestOpA) -> Result[int, str]:
            return Ok(req.x)

        async def handler_b(req: _TestOpB) -> Result[str, str]:
            return Ok(req.y)

        builder = ops().on(_TestOpA, handler_a).on(_TestOpB, handler_b)
        assert len(builder._items) == 2

    def test_on_last_wins(self) -> None:
        async def handler1(req: _TestOpA) -> Result[int, str]:
            return Ok(1)

        async def handler2(req: _TestOpA) -> Result[int, str]:
            return Ok(2)

        builder = ops().on(_TestOpA, handler1).on(_TestOpA, handler2)
        assert len(builder._items) == 1
        # Last handler should win
        assert builder._items[0][1] is handler2

    def test_compile_produces_runner(self) -> None:
        async def handler(req: _TestOpA) -> Result[int, str]:
            return Ok(req.x)

        runner = ops().on(_TestOpA, handler).compile()
        assert isinstance(runner, Runner)


# ═══════════════════════════════════════════════════════════════════════════════
# ops/_graph.py — Op base
# ═══════════════════════════════════════════════════════════════════════════════


class TestOpBase:
    """Op.get() raises RuntimeError when not bound."""

    def test_get_raises_unbound(self) -> None:
        op = _UnboundOp(x=1)
        with pytest.raises(RuntimeError, match="not bound"):
            op.get()


# ═══════════════════════════════════════════════════════════════════════════════
# Mutation-killing tests for ops/_graph.py survivors
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunnerInjectChaining:
    """Runner.inject() returns self for chaining — mutation to None must fail."""

    def test_inject_returns_self(self) -> None:
        async def handler(req: _TestOpA) -> Result[int, str]:
            return Ok(req.x)

        builder = ops()
        runner = builder.on(_TestOpA, handler).compile()
        result = runner.inject(str, "hello")
        assert result is runner

    def test_inject_chain(self) -> None:
        async def handler(req: _TestOpA) -> Result[int, str]:
            return Ok(req.x)

        builder = ops()
        runner = builder.on(_TestOpA, handler).compile()
        # Chained inject — would crash if inject returns None
        result = runner.inject(str, "hello").inject(int, 42)
        assert result is runner


class TestOpDependencyResolution:
    """_create_node_for_handler correctly distinguishes Op deps from regular deps.

    Kills mutant: L162 `and` -> `or` — if changed, an Op type NOT in registry
    would be treated as an Op dependency (KeyError) instead of a regular dep.
    """

    def test_two_ops_where_second_depends_on_first(self) -> None:
        """Handler for OpB takes OpA as param — OpA must be registered first."""
        async def handle_a(req: _TestOpA) -> Result[int, str]:
            return Ok(req.x * 2)

        async def handle_b(req: _TestOpB, a_result: _TestOpA) -> Result[str, str]:
            return Ok(f"{req.y}-{a_result}")

        builder = ops().on(_TestOpA, handle_a).on(_TestOpB, handle_b)
        runner = builder.compile()
        assert runner is not None
