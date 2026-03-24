"""Tests for emergent.wire.verify — verification as compilation target."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import pytest

from emergent.wire.axis.schema import Identity, Unique
from emergent.wire.axis.schema._universal import (
    Computed,
    ExclusiveMax,
    ExclusiveMin,
    Immutable,
    Max,
    MaxLen,
    Min,
    MinLen,
    Nullable,
    Pattern,
    ReadOnly,
    UniversalCapability,
    WriteOnly,
)
from emergent.wire.compile._core import Axes
from emergent.wire.compile._phase import FASTAPI_SCHEMA, SchemaCompiler
from emergent.wire.verify import (
    LENGTH_VERIFY_PHASE,
    NUMERIC_VERIFY_PHASE,
    SEMANTICS_VERIFY_PHASE,
    VERIFY_SCHEMA,
    Issue,
    Severity,
    VerificationError,
    verify,
    verify_raising,
)

_AXES = Axes.default()


# Module-level entities for open-world test (local classes break get_type_hints)
@dataclass(frozen=True, slots=True)
class _CustomCap(UniversalCapability):
    """Capability without any compile_verify_* — should be ignored."""
    pass


@dataclass
class _EntityWithCustomCap:
    x: Annotated[int, _CustomCap()]


# ═══════════════════════════════════════════════════════════════════════════════
# Numeric
# ═══════════════════════════════════════════════════════════════════════════════


class TestNumericVerify:
    def test_min_greater_than_max(self) -> None:
        @dataclass
        class Bad:
            temp: Annotated[int, Min(200), Max(125)]

        issues = verify(Bad)
        errors = [i for i in issues if i.severity is Severity.ERROR]
        assert len(errors) == 1
        assert "Min(200.0) > Max(125.0)" in errors[0].message
        assert errors[0].field == "temp"

    def test_exclusive_min_eq_exclusive_max(self) -> None:
        @dataclass
        class Bad:
            x: Annotated[float, ExclusiveMin(10), ExclusiveMax(10)]

        issues = verify(Bad)
        errors = [i for i in issues if i.severity is Severity.ERROR]
        assert len(errors) == 1
        assert "ExclusiveMin" in errors[0].message

    def test_min_eq_exclusive_max_empty_range(self) -> None:
        @dataclass
        class Bad:
            x: Annotated[int, Min(5), ExclusiveMax(5)]

        issues = verify(Bad)
        errors = [i for i in issues if i.severity is Severity.ERROR]
        assert len(errors) == 1
        assert "empty range" in errors[0].message

    def test_exclusive_min_eq_max_empty_range(self) -> None:
        @dataclass
        class Bad:
            x: Annotated[int, ExclusiveMin(10), Max(10)]

        issues = verify(Bad)
        errors = [i for i in issues if i.severity is Severity.ERROR]
        assert len(errors) == 1
        assert "empty range" in errors[0].message

    def test_valid_numeric_no_issues(self) -> None:
        @dataclass
        class Good:
            score: Annotated[int, Min(0), Max(100)]

        issues = verify(Good)
        assert len(issues) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Length
# ═══════════════════════════════════════════════════════════════════════════════


class TestLengthVerify:
    def test_minlen_greater_than_maxlen(self) -> None:
        @dataclass
        class Bad:
            name: Annotated[str, MinLen(50), MaxLen(10)]

        issues = verify(Bad)
        errors = [i for i in issues if i.severity is Severity.ERROR]
        assert len(errors) == 1
        assert "MinLen(50) > MaxLen(10)" in errors[0].message

    def test_maxlen_zero_warning(self) -> None:
        @dataclass
        class Suspicious:
            tag: Annotated[str, MaxLen(0)]

        issues = verify(Suspicious)
        warnings = [i for i in issues if i.severity is Severity.WARNING]
        assert len(warnings) == 1
        assert "MaxLen(0)" in warnings[0].message

    def test_valid_length_no_issues(self) -> None:
        @dataclass
        class Good:
            name: Annotated[str, MinLen(1), MaxLen(100)]

        issues = verify(Good)
        assert len(issues) == 0

    def test_pattern_only_no_issues(self) -> None:
        @dataclass
        class Good:
            email: Annotated[str, Pattern(r"^.+@.+$")]

        issues = verify(Good)
        assert len(issues) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Semantics
# ═══════════════════════════════════════════════════════════════════════════════


class TestSemanticsVerify:
    def test_read_only_plus_write_only(self) -> None:
        @dataclass
        class Bad:
            x: Annotated[str, ReadOnly(), WriteOnly()]

        issues = verify(Bad)
        errors = [i for i in issues if i.severity is Severity.ERROR]
        assert len(errors) == 1
        assert "inaccessible" in errors[0].message

    def test_computed_plus_write_only(self) -> None:
        @dataclass
        class Bad:
            x: Annotated[str, Computed(), WriteOnly()]

        issues = verify(Bad)
        errors = [i for i in issues if i.severity is Severity.ERROR]
        assert len(errors) == 1
        assert "Computed + WriteOnly" in errors[0].message

    def test_identity_plus_nullable_warning(self) -> None:
        @dataclass
        class Suspicious:
            id: Annotated[int, Identity, Nullable()]

        issues = verify(Suspicious)
        warnings = [i for i in issues if i.severity is Severity.WARNING]
        assert any("Identity + Nullable" in w.message for w in warnings)

    def test_unique_plus_nullable_warning(self) -> None:
        @dataclass
        class Suspicious:
            email: Annotated[str, Unique, Nullable()]

        issues = verify(Suspicious)
        warnings = [i for i in issues if i.severity is Severity.WARNING]
        assert any("Unique + Nullable" in w.message for w in warnings)

    def test_identity_plus_computed_warning(self) -> None:
        @dataclass
        class Suspicious:
            id: Annotated[int, Identity, Computed()]

        issues = verify(Suspicious)
        warnings = [i for i in issues if i.severity is Severity.WARNING]
        assert any("Identity + Computed" in w.message for w in warnings)

    def test_valid_semantics_no_issues(self) -> None:
        @dataclass
        class Good:
            id: Annotated[int, Identity]
            name: str
            password: Annotated[str, WriteOnly()]

        issues = verify(Good)
        assert len(issues) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Open-world & Algebra
# ═══════════════════════════════════════════════════════════════════════════════


class TestOpenWorld:
    def test_unknown_capability_silently_skipped(self) -> None:
        issues = verify(_EntityWithCustomCap)
        assert len(issues) == 0

    def test_no_annotated_fields_no_issues(self) -> None:
        @dataclass
        class Plain:
            name: str
            age: int

        issues = verify(Plain)
        assert len(issues) == 0


class TestAlgebra:
    def test_verify_schema_plus_fastapi(self) -> None:
        combined = FASTAPI_SCHEMA + VERIFY_SCHEMA
        assert len(combined.phases) == len(FASTAPI_SCHEMA.phases) + len(VERIFY_SCHEMA.phases)

    def test_individual_phase_opt_in(self) -> None:
        @dataclass
        class Bad:
            x: Annotated[int, Min(200), Max(125)]
            name: Annotated[str, MinLen(50), MaxLen(10)]

        # Only numeric — should catch Min>Max but NOT MinLen>MaxLen
        issues = verify(Bad, phases=(NUMERIC_VERIFY_PHASE,))
        assert len(issues) == 1
        assert "Min" in issues[0].message

    def test_compile_with_verify_phases(self) -> None:
        @dataclass
        class User:
            id: Annotated[int, Identity]
            score: Annotated[int, Min(0), Max(100)]

        combined = FASTAPI_SCHEMA + VERIFY_SCHEMA
        ec = combined.compile(User, _AXES)
        # Can access both fastapi and verify results
        for fc in ec:
            numeric_ctx = fc[NUMERIC_VERIFY_PHASE]
            assert numeric_ctx.check() == ()


# ═══════════════════════════════════════════════════════════════════════════════
# verify_raising
# ═══════════════════════════════════════════════════════════════════════════════


class TestVerifyRaising:
    def test_raises_on_error(self) -> None:
        @dataclass
        class Bad:
            x: Annotated[int, Min(200), Max(125)]

        with pytest.raises(VerificationError) as exc_info:
            verify_raising(Bad)
        assert len(exc_info.value.issues) == 1

    def test_no_raise_on_warning_only(self) -> None:
        @dataclass
        class WarnOnly:
            tag: Annotated[str, MaxLen(0)]

        # MaxLen(0) is WARNING, not ERROR — should not raise
        verify_raising(WarnOnly)

    def test_no_raise_on_clean(self) -> None:
        @dataclass
        class Clean:
            name: Annotated[str, MinLen(1), MaxLen(100)]

        verify_raising(Clean)

    def test_multiple_entities(self) -> None:
        @dataclass
        class A:
            x: Annotated[int, Min(100), Max(50)]

        @dataclass
        class B:
            y: Annotated[str, MinLen(20), MaxLen(5)]

        issues = verify(A, B)
        errors = [i for i in issues if i.severity is Severity.ERROR]
        assert len(errors) == 2
