"""Tests for compiler algebra — algebraic laws on SchemaCompiler and TargetCompiler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import pytest

from emergent.wire.axis._capability import (
    PydanticContext,
    OpenAPIContext,
    ArgparseContext,
    ConstraintsContext,
    StorageFieldContext,
)
from emergent.wire.compile._core import Axes
from emergent.wire.compile._phase import (
    CompilationPhase,
    SchemaCompiler,
    PYDANTIC_PHASE,
    OPENAPI_PHASE,
    ARGPARSE_PHASE,
    CONSTRAINTS_PHASE,
    STORAGE_FIELD_PHASE,
    FASTAPI_SCHEMA,
    CLI_SCHEMA,
    TG_SCHEMA,
    CONSTRAINTS_SCHEMA,
    STORAGE_SCHEMA,
)
from emergent.wire.compile._target import CodecAdapter, TargetCompiler
from emergent.wire.axis.schema._inspect import inspect_dataclass
from emergent.wire.axis.schema._universal import Identity, Min, Max, MaxLen, Unique


# ─── Test Entities ────────────────────────────────────────────────────────────


@dataclass
class User:
    id: Annotated[int, Identity]
    name: Annotated[str, MaxLen(100)]
    email: Annotated[str, Unique, MaxLen(255)]
    score: Annotated[int, Min(0), Max(1000)]


_AXES = Axes(schema=inspect_dataclass)
_EMPTY = SchemaCompiler(phases=())


# ═══════════════════════════════════════════════════════════════════════════════
# SchemaCompiler — Algebraic Laws
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchemaAdd:
    """+ is left-biased union, idempotent, associative."""

    def test_identity_right(self) -> None:
        assert (FASTAPI_SCHEMA + _EMPTY).phases == FASTAPI_SCHEMA.phases

    def test_identity_left(self) -> None:
        assert (_EMPTY + FASTAPI_SCHEMA).phases == FASTAPI_SCHEMA.phases

    def test_idempotent(self) -> None:
        """A + A == A (no crash, no duplicates)."""
        result = FASTAPI_SCHEMA + FASTAPI_SCHEMA
        assert len(result.phases) == 2
        assert result.phases == FASTAPI_SCHEMA.phases

    def test_associative_disjoint(self) -> None:
        a, b, c = FASTAPI_SCHEMA, CLI_SCHEMA, CONSTRAINTS_SCHEMA
        left = (a + b) + c
        right = a + (b + c)
        assert len(left.phases) == len(right.phases)
        for lp, rp in zip(left.phases, right.phases):
            assert lp is rp

    def test_associative_overlapping(self) -> None:
        """When keys overlap, A's version wins regardless of grouping."""
        from emergent.wire.compile.targets.sqlalchemy import SA_SCHEMA

        a = FASTAPI_SCHEMA + STORAGE_SCHEMA  # has STORAGE_FIELD
        b = SA_SCHEMA  # also has STORAGE_FIELD
        c = CONSTRAINTS_SCHEMA

        left = (a + b) + c
        right = a + (b + c)
        assert len(left.phases) == len(right.phases)
        for lp, rp in zip(left.phases, right.phases):
            assert lp is rp

    def test_left_biased(self) -> None:
        """Self's version kept on conflict."""
        custom_pydantic = PYDANTIC_PHASE.with_handlers({})
        custom = SchemaCompiler(phases=(custom_pydantic, OPENAPI_PHASE))
        result = FASTAPI_SCHEMA + custom
        # FASTAPI_SCHEMA's PYDANTIC_PHASE kept, custom's dropped
        assert result.phases[0] is PYDANTIC_PHASE

    def test_add_phase_directly(self) -> None:
        """SchemaCompiler + CompilationPhase works."""
        result = FASTAPI_SCHEMA + CONSTRAINTS_PHASE
        assert len(result.phases) == 3
        assert CONSTRAINTS_PHASE in result

    def test_add_phase_left(self) -> None:
        """CompilationPhase + SchemaCompiler works via __radd__."""
        result = CONSTRAINTS_PHASE + FASTAPI_SCHEMA
        assert len(result.phases) == 3
        assert CONSTRAINTS_PHASE in result

    def test_compiles_after_add(self) -> None:
        """Idempotent add produces valid compiler."""
        compiler = FASTAPI_SCHEMA + FASTAPI_SCHEMA + CONSTRAINTS_SCHEMA
        fields = compiler.compile(User, _AXES)
        assert len(fields) == 4


class TestSchemaMerge:
    """| is right-biased merge, idempotent, associative."""

    def test_identity_right(self) -> None:
        assert (FASTAPI_SCHEMA | _EMPTY).phases == FASTAPI_SCHEMA.phases

    def test_identity_left(self) -> None:
        assert (_EMPTY | FASTAPI_SCHEMA).phases == FASTAPI_SCHEMA.phases

    def test_idempotent(self) -> None:
        result = FASTAPI_SCHEMA | FASTAPI_SCHEMA
        assert len(result.phases) == 2
        assert result.phases == FASTAPI_SCHEMA.phases

    def test_right_biased_override(self) -> None:
        """Other's version wins on conflict."""
        custom_pydantic = PYDANTIC_PHASE.with_handlers({})
        custom = SchemaCompiler(phases=(custom_pydantic,))
        result = FASTAPI_SCHEMA | custom
        # custom's pydantic replaces FASTAPI's
        assert result.phases[0] is custom_pydantic
        assert result.phases[1] is OPENAPI_PHASE
        assert len(result.phases) == 2

    def test_associative(self) -> None:
        custom_p = PYDANTIC_PHASE.with_handlers({})
        a = FASTAPI_SCHEMA
        b = SchemaCompiler(phases=(custom_p,))
        c = CONSTRAINTS_SCHEMA

        left = (a | b) | c
        right = a | (b | c)
        assert len(left.phases) == len(right.phases)
        for lp, rp in zip(left.phases, right.phases):
            assert lp is rp

    def test_merge_adds_new(self) -> None:
        """Merge also adds phases not in self."""
        result = FASTAPI_SCHEMA | CONSTRAINTS_SCHEMA
        assert len(result.phases) == 3
        assert CONSTRAINTS_PHASE in result

    def test_merge_phase_directly(self) -> None:
        """SchemaCompiler | CompilationPhase works."""
        custom_pydantic = PYDANTIC_PHASE.with_handlers({})
        result = FASTAPI_SCHEMA | custom_pydantic
        assert result.phases[0] is custom_pydantic

    def test_subsumes_replace_phase(self) -> None:
        """A | SchemaCompiler(phases=(new,)) == A.replace_phase(old, new)."""
        custom_pydantic = PYDANTIC_PHASE.with_handlers({})
        via_merge = FASTAPI_SCHEMA | custom_pydantic
        via_replace = FASTAPI_SCHEMA.replace_phase(PYDANTIC_PHASE, custom_pydantic)
        assert via_merge.phases == via_replace.phases


class TestSchemaSub:
    """- is restriction by context_type."""

    def test_identity(self) -> None:
        assert (FASTAPI_SCHEMA - _EMPTY).phases == FASTAPI_SCHEMA.phases

    def test_zero(self) -> None:
        assert len((_EMPTY - FASTAPI_SCHEMA).phases) == 0

    def test_self_annihilation(self) -> None:
        assert len((FASTAPI_SCHEMA - FASTAPI_SCHEMA).phases) == 0

    def test_by_context_type(self) -> None:
        """Removes by context_type even with different phase instances."""
        custom_pydantic = PYDANTIC_PHASE.with_handlers({})
        custom = SchemaCompiler(phases=(custom_pydantic,))
        result = FASTAPI_SCHEMA - custom
        assert len(result.phases) == 1
        assert result.phases[0] is OPENAPI_PHASE

    def test_sub_bare_type(self) -> None:
        """compiler - PydanticContext removes pydantic phase."""
        result = FASTAPI_SCHEMA - PydanticContext
        assert len(result.phases) == 1
        assert result.phases[0] is OPENAPI_PHASE

    def test_sub_phase_directly(self) -> None:
        """compiler - PHASE works."""
        result = FASTAPI_SCHEMA - PYDANTIC_PHASE
        assert len(result.phases) == 1

    def test_sub_non_present_noop(self) -> None:
        """Removing non-present key is a no-op."""
        result = FASTAPI_SCHEMA - CLI_SCHEMA
        assert result.phases == FASTAPI_SCHEMA.phases

    def test_roundtrip_with_add(self) -> None:
        """(A + B) - B == A when disjoint."""
        combined = FASTAPI_SCHEMA + CLI_SCHEMA
        restricted = combined - CLI_SCHEMA
        assert restricted.phases == FASTAPI_SCHEMA.phases


class TestSchemaAnd:
    """& is intersection by context_type."""

    def test_idempotent(self) -> None:
        result = FASTAPI_SCHEMA & FASTAPI_SCHEMA
        assert result.phases == FASTAPI_SCHEMA.phases

    def test_empty(self) -> None:
        result = FASTAPI_SCHEMA & _EMPTY
        assert len(result.phases) == 0

    def test_disjoint(self) -> None:
        result = FASTAPI_SCHEMA & CLI_SCHEMA
        assert len(result.phases) == 0

    def test_partial_overlap(self) -> None:
        from emergent.wire.compile.targets.sqlalchemy import SA_SCHEMA

        # FASTAPI has pydantic + openapi; SA has sa + storage_field
        # Combined has all 4; intersect with STORAGE_SCHEMA keeps storage_field
        combined = FASTAPI_SCHEMA + SA_SCHEMA
        result = combined & STORAGE_SCHEMA
        assert len(result.phases) == 1
        assert result.phases[0].context_type is StorageFieldContext

    def test_associative(self) -> None:
        from emergent.wire.compile.targets.sqlalchemy import SA_SCHEMA

        full = FASTAPI_SCHEMA + SA_SCHEMA + CONSTRAINTS_SCHEMA
        a = full & (FASTAPI_SCHEMA + CONSTRAINTS_SCHEMA)
        b_inner = FASTAPI_SCHEMA + CONSTRAINTS_SCHEMA
        left = (full & FASTAPI_SCHEMA) & b_inner  # hmm this doesn't test associativity well

        # Better: (A & B) & C == A & (B & C) where A = full, B = FASTAPI+CONSTRAINTS, C = FASTAPI
        b = FASTAPI_SCHEMA + CONSTRAINTS_SCHEMA
        c = FASTAPI_SCHEMA
        left2 = (full & b) & c
        right2 = full & (b & c)
        assert len(left2.phases) == len(right2.phases)
        for lp, rp in zip(left2.phases, right2.phases):
            assert lp is rp


class TestSchemaContains:
    """in checks by context_type."""

    def test_phase_present(self) -> None:
        assert PYDANTIC_PHASE in FASTAPI_SCHEMA
        assert OPENAPI_PHASE in FASTAPI_SCHEMA

    def test_phase_absent(self) -> None:
        assert ARGPARSE_PHASE not in FASTAPI_SCHEMA

    def test_customized_variant(self) -> None:
        """Custom phase with same context_type is found."""
        custom_pydantic = PYDANTIC_PHASE.with_handlers({})
        assert custom_pydantic in FASTAPI_SCHEMA

    def test_bare_type(self) -> None:
        assert PydanticContext in FASTAPI_SCHEMA
        assert OpenAPIContext in FASTAPI_SCHEMA
        assert ArgparseContext not in FASTAPI_SCHEMA


class TestSchemaDataModel:
    """len, iter, bool, getitem."""

    def test_len(self) -> None:
        assert len(FASTAPI_SCHEMA) == 2
        assert len(_EMPTY) == 0

    def test_iter(self) -> None:
        phases = list(FASTAPI_SCHEMA)
        assert phases == [PYDANTIC_PHASE, OPENAPI_PHASE]

    def test_bool(self) -> None:
        assert bool(FASTAPI_SCHEMA)
        assert not bool(_EMPTY)

    def test_getitem(self) -> None:
        phase = FASTAPI_SCHEMA[PydanticContext]
        assert phase is PYDANTIC_PHASE

    def test_getitem_not_found(self) -> None:
        with pytest.raises(KeyError):
            FASTAPI_SCHEMA[ArgparseContext]


class TestPhaseLifting:
    """CompilationPhase + CompilationPhase → SchemaCompiler."""

    def test_phase_add_phase(self) -> None:
        result = PYDANTIC_PHASE + OPENAPI_PHASE
        assert isinstance(result, SchemaCompiler)
        assert len(result.phases) == 2
        assert result.phases[0] is PYDANTIC_PHASE
        assert result.phases[1] is OPENAPI_PHASE

    def test_phase_add_compiler(self) -> None:
        result = CONSTRAINTS_PHASE + FASTAPI_SCHEMA
        assert isinstance(result, SchemaCompiler)
        assert len(result.phases) == 3

    def test_compiler_add_phase(self) -> None:
        result = FASTAPI_SCHEMA + CONSTRAINTS_PHASE
        assert isinstance(result, SchemaCompiler)
        assert len(result.phases) == 3

    def test_chain(self) -> None:
        result = PYDANTIC_PHASE + OPENAPI_PHASE + CONSTRAINTS_PHASE
        assert isinstance(result, SchemaCompiler)
        assert len(result.phases) == 3

    def test_same_slot(self) -> None:
        custom = PYDANTIC_PHASE.with_handlers({})
        assert PYDANTIC_PHASE.same_slot(custom)
        assert not PYDANTIC_PHASE.same_slot(OPENAPI_PHASE)


# ═══════════════════════════════════════════════════════════════════════════════
# TargetCompiler — Algebraic Laws
# ═══════════════════════════════════════════════════════════════════════════════


class _TriggerA:
    pass


class _TriggerB:
    pass


class _CodecX:
    pass


class _CodecY:
    pass


class _CodecZ:
    pass


def _noop_wrap(*_args: object) -> None:
    pass


def _alt_wrap(*_args: object) -> str:
    return "alt"


_AX = CodecAdapter(_CodecX, _noop_wrap)
_AY = CodecAdapter(_CodecY, _noop_wrap)
_AZ = CodecAdapter(_CodecZ, _noop_wrap)
_AX_ALT = CodecAdapter(_CodecX, _alt_wrap)

_COMPILER_XY: TargetCompiler[_TriggerA] = TargetCompiler(
    trigger_type=_TriggerA, adapters=(_AX, _AY),
)
_COMPILER_YZ: TargetCompiler[_TriggerA] = TargetCompiler(
    trigger_type=_TriggerA, adapters=(_AY, _AZ),
)
_COMPILER_X: TargetCompiler[_TriggerA] = TargetCompiler(
    trigger_type=_TriggerA, adapters=(_AX,),
)
_COMPILER_Z: TargetCompiler[_TriggerA] = TargetCompiler(
    trigger_type=_TriggerA, adapters=(_AZ,),
)
_EMPTY_TARGET: TargetCompiler[_TriggerA] = TargetCompiler(
    trigger_type=_TriggerA, adapters=(),
)


class TestTargetAdd:
    def test_identity_right(self) -> None:
        result = _COMPILER_XY + _EMPTY_TARGET
        assert result.adapters == _COMPILER_XY.adapters

    def test_identity_left(self) -> None:
        result = _EMPTY_TARGET + _COMPILER_XY
        assert result.adapters == _COMPILER_XY.adapters

    def test_idempotent(self) -> None:
        result = _COMPILER_XY + _COMPILER_XY
        assert len(result.adapters) == 2

    def test_left_biased(self) -> None:
        alt_x = TargetCompiler(trigger_type=_TriggerA, adapters=(_AX_ALT,))
        result = _COMPILER_XY + alt_x
        assert result.adapters[0] is _AX  # original kept

    def test_union_new(self) -> None:
        result = _COMPILER_XY + _COMPILER_Z
        assert len(result.adapters) == 3

    def test_add_codec_adapter(self) -> None:
        result = _COMPILER_XY + _AZ
        assert len(result.adapters) == 3
        assert _CodecZ in result

    def test_trigger_type_mismatch(self) -> None:
        other: TargetCompiler[_TriggerB] = TargetCompiler(
            trigger_type=_TriggerB, adapters=(),
        )
        with pytest.raises(TypeError, match="different trigger types"):
            _COMPILER_XY + other  # type: ignore[operator]

    def test_associative(self) -> None:
        a = _COMPILER_X
        b = _COMPILER_YZ
        c = _COMPILER_Z
        left = (a + b) + c
        right = a + (b + c)
        assert len(left.adapters) == len(right.adapters)
        for la, ra in zip(left.adapters, right.adapters):
            assert la is ra


class TestTargetMerge:
    def test_identity(self) -> None:
        assert (_COMPILER_XY | _EMPTY_TARGET).adapters == _COMPILER_XY.adapters
        assert (_EMPTY_TARGET | _COMPILER_XY).adapters == _COMPILER_XY.adapters

    def test_right_biased(self) -> None:
        alt_x = TargetCompiler(trigger_type=_TriggerA, adapters=(_AX_ALT,))
        result = _COMPILER_XY | alt_x
        assert result.adapters[0] is _AX_ALT  # overridden
        assert result.adapters[1] is _AY

    def test_idempotent(self) -> None:
        result = _COMPILER_XY | _COMPILER_XY
        assert len(result.adapters) == 2

    def test_merge_adapter(self) -> None:
        result = _COMPILER_XY | _AX_ALT
        assert result.adapters[0] is _AX_ALT


class TestTargetSub:
    def test_identity(self) -> None:
        assert (_COMPILER_XY - _EMPTY_TARGET).adapters == _COMPILER_XY.adapters

    def test_self_annihilation(self) -> None:
        assert len((_COMPILER_XY - _COMPILER_XY).adapters) == 0

    def test_sub_bare_type(self) -> None:
        result = _COMPILER_XY - _CodecX
        assert len(result.adapters) == 1
        assert result.adapters[0] is _AY

    def test_sub_adapter(self) -> None:
        result = _COMPILER_XY - _AX
        assert len(result.adapters) == 1

    def test_roundtrip(self) -> None:
        combined = _COMPILER_X + _COMPILER_Z
        restricted = combined - _COMPILER_Z
        assert restricted.adapters == _COMPILER_X.adapters


class TestTargetAnd:
    def test_idempotent(self) -> None:
        result = _COMPILER_XY & _COMPILER_XY
        assert result.adapters == _COMPILER_XY.adapters

    def test_empty(self) -> None:
        result = _COMPILER_XY & _EMPTY_TARGET
        assert len(result.adapters) == 0

    def test_disjoint(self) -> None:
        result = _COMPILER_X & _COMPILER_Z
        assert len(result.adapters) == 0

    def test_partial_overlap(self) -> None:
        result = _COMPILER_XY & _COMPILER_YZ
        assert len(result.adapters) == 1
        assert result.adapters[0] is _AY


class TestTargetContains:
    def test_type_present(self) -> None:
        assert _CodecX in _COMPILER_XY
        assert _CodecY in _COMPILER_XY

    def test_type_absent(self) -> None:
        assert _CodecZ not in _COMPILER_XY

    def test_adapter_present(self) -> None:
        assert _AX in _COMPILER_XY

    def test_adapter_variant(self) -> None:
        """Adapter with same codec_type but different wrap is found."""
        assert _AX_ALT in _COMPILER_XY


class TestTargetDataModel:
    def test_len(self) -> None:
        assert len(_COMPILER_XY) == 2
        assert len(_EMPTY_TARGET) == 0

    def test_iter(self) -> None:
        adapters = list(_COMPILER_XY)
        assert adapters == [_AX, _AY]

    def test_bool(self) -> None:
        assert bool(_COMPILER_XY)
        assert not bool(_EMPTY_TARGET)

    def test_getitem(self) -> None:
        adapter = _COMPILER_XY[_CodecX]
        assert adapter is _AX

    def test_getitem_not_found(self) -> None:
        with pytest.raises(KeyError):
            _COMPILER_XY[_CodecZ]

    def test_same_slot(self) -> None:
        assert _AX.same_slot(_AX_ALT)
        assert not _AX.same_slot(_AY)


class TestTargetLegoGuards:
    def test_with_codec_conflict(self) -> None:
        with pytest.raises(ValueError, match="already present"):
            _COMPILER_XY.with_codec(_CodecX, _noop_wrap)

    def test_replace_codec_not_found(self) -> None:
        with pytest.raises(KeyError):
            _COMPILER_XY.replace_codec(_CodecZ, _noop_wrap)
