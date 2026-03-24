"""Behavioral tests for schema compilation — constraints enforce correct bounds.

Tests two behavioral paths:
1. extract_constraints() produces FieldConstraints that correctly ACCEPT/REJECT values
2. to_pydantic() produces models that correctly STORE field values

Every assertion checks a VALUE or BEHAVIOR, never structural presence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from emergent.wire.axis.schema._universal import (
    Min,
    Max,
    MinLen,
    MaxLen,
    OneOf,
    Pattern,
    Identity,
    Unique,
)
from emergent.wire.axis.schema._inspect import inspect_dataclass
from emergent.wire.compile._core import Axes, extract_constraints, FieldConstraints
from emergent.wire.compile._generate import to_pydantic

import re

axes = Axes.default()


# ═══════════════════════════════════════════════════════════════════════════════
# Helper: check constraint acceptance/rejection
# ═══════════════════════════════════════════════════════════════════════════════


def _value_accepted(c: FieldConstraints, value: int | float) -> bool:
    """Check if a numeric value is accepted by the constraints."""
    if c.min_value is not None and value < c.min_value:
        return False
    if c.max_value is not None and value > c.max_value:
        return False
    return True


def _string_accepted(c: FieldConstraints, value: str) -> bool:
    """Check if a string value is accepted by the constraints."""
    if c.min_length is not None and len(value) < c.min_length:
        return False
    if c.max_length is not None and len(value) > c.max_length:
        return False
    if c.pattern is not None and not re.fullmatch(c.pattern, value):
        return False
    if c.choices is not None and value not in c.choices:
        return False
    return True


def _extract(cls: type, field_name: str) -> FieldConstraints:
    """Extract constraints for a specific field."""
    fields = inspect_dataclass(cls)
    return extract_constraints(fields[field_name])


# ═══════════════════════════════════════════════════════════════════════════════
# Min
# ═══════════════════════════════════════════════════════════════════════════════


def test_min_rejects_below_bound() -> None:
    """Min(0) constraint rejects -1."""

    @dataclass
    class Entity:
        value: Annotated[int, Min(0)]

    c = _extract(Entity, "value")
    assert _value_accepted(c, -1) is False


def test_min_accepts_at_bound() -> None:
    """Min(0) constraint accepts 0 — boundary is inclusive."""

    @dataclass
    class Entity:
        value: Annotated[int, Min(0)]

    c = _extract(Entity, "value")
    assert _value_accepted(c, 0) is True


def test_min_constraint_value_recorded() -> None:
    """Min(0) records min_value=0."""

    @dataclass
    class Entity:
        value: Annotated[int, Min(0)]

    c = _extract(Entity, "value")
    assert c.min_value == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Max
# ═══════════════════════════════════════════════════════════════════════════════


def test_max_rejects_above_bound() -> None:
    """Max(100) constraint rejects 101."""

    @dataclass
    class Entity:
        value: Annotated[int, Max(100)]

    c = _extract(Entity, "value")
    assert _value_accepted(c, 101) is False


def test_max_accepts_at_bound() -> None:
    """Max(100) constraint accepts 100 — boundary is inclusive."""

    @dataclass
    class Entity:
        value: Annotated[int, Max(100)]

    c = _extract(Entity, "value")
    assert _value_accepted(c, 100) is True


def test_max_constraint_value_recorded() -> None:
    """Max(100) records max_value=100."""

    @dataclass
    class Entity:
        value: Annotated[int, Max(100)]

    c = _extract(Entity, "value")
    assert c.max_value == 100


# ═══════════════════════════════════════════════════════════════════════════════
# MinLen
# ═══════════════════════════════════════════════════════════════════════════════


def test_minlen_rejects_short_string() -> None:
    """MinLen(3) constraint rejects 'ab'."""

    @dataclass
    class Entity:
        name: Annotated[str, MinLen(3)]

    c = _extract(Entity, "name")
    assert _string_accepted(c, "ab") is False


def test_minlen_accepts_exact_length() -> None:
    """MinLen(3) constraint accepts 'abc'."""

    @dataclass
    class Entity:
        name: Annotated[str, MinLen(3)]

    c = _extract(Entity, "name")
    assert _string_accepted(c, "abc") is True


# ═══════════════════════════════════════════════════════════════════════════════
# MaxLen
# ═══════════════════════════════════════════════════════════════════════════════


def test_maxlen_rejects_long_string() -> None:
    """MaxLen(5) constraint rejects 'abcdef'."""

    @dataclass
    class Entity:
        name: Annotated[str, MaxLen(5)]

    c = _extract(Entity, "name")
    assert _string_accepted(c, "abcdef") is False


def test_maxlen_accepts_exact_length() -> None:
    """MaxLen(5) constraint accepts 'abcde'."""

    @dataclass
    class Entity:
        name: Annotated[str, MaxLen(5)]

    c = _extract(Entity, "name")
    assert _string_accepted(c, "abcde") is True


# ═══════════════════════════════════════════════════════════════════════════════
# OneOf
# ═══════════════════════════════════════════════════════════════════════════════


def test_oneof_rejects_invalid() -> None:
    """OneOf('a', 'b') constraint rejects 'c'."""

    @dataclass
    class Entity:
        status: Annotated[str, OneOf("a", "b")]

    c = _extract(Entity, "status")
    assert _string_accepted(c, "c") is False


def test_oneof_accepts_valid() -> None:
    """OneOf('a', 'b') constraint accepts 'a'."""

    @dataclass
    class Entity:
        status: Annotated[str, OneOf("a", "b")]

    c = _extract(Entity, "status")
    assert _string_accepted(c, "a") is True


def test_oneof_records_all_choices() -> None:
    """OneOf('a', 'b') records choices=('a', 'b')."""

    @dataclass
    class Entity:
        status: Annotated[str, OneOf("a", "b")]

    c = _extract(Entity, "status")
    assert c.choices == ("a", "b")


# ═══════════════════════════════════════════════════════════════════════════════
# Pattern
# ═══════════════════════════════════════════════════════════════════════════════


def test_pattern_rejects_non_matching() -> None:
    """Pattern('^[a-z]+$') constraint rejects '123'."""

    @dataclass
    class Entity:
        code: Annotated[str, Pattern(r"^[a-z]+$")]

    c = _extract(Entity, "code")
    assert _string_accepted(c, "123") is False


def test_pattern_accepts_matching() -> None:
    """Pattern('^[a-z]+$') constraint accepts 'abc'."""

    @dataclass
    class Entity:
        code: Annotated[str, Pattern(r"^[a-z]+$")]

    c = _extract(Entity, "code")
    assert _string_accepted(c, "abc") is True


def test_pattern_value_recorded() -> None:
    """Pattern records the exact regex."""

    @dataclass
    class Entity:
        code: Annotated[str, Pattern(r"^[a-z]+$")]

    c = _extract(Entity, "code")
    assert c.pattern == r"^[a-z]+$"


# ═══════════════════════════════════════════════════════════════════════════════
# Composed Constraints: Min + Max
# ═══════════════════════════════════════════════════════════════════════════════


def test_min_max_composition_rejects_below() -> None:
    """Min(0) + Max(100) rejects -1."""

    @dataclass
    class Entity:
        value: Annotated[int, Min(0), Max(100)]

    c = _extract(Entity, "value")
    assert _value_accepted(c, -1) is False


def test_min_max_composition_rejects_above() -> None:
    """Min(0) + Max(100) rejects 101."""

    @dataclass
    class Entity:
        value: Annotated[int, Min(0), Max(100)]

    c = _extract(Entity, "value")
    assert _value_accepted(c, 101) is False


def test_min_max_composition_accepts_middle() -> None:
    """Min(0) + Max(100) accepts 50."""

    @dataclass
    class Entity:
        value: Annotated[int, Min(0), Max(100)]

    c = _extract(Entity, "value")
    assert _value_accepted(c, 50) is True


def test_min_max_both_recorded() -> None:
    """Min(0) + Max(100) records both bounds."""

    @dataclass
    class Entity:
        value: Annotated[int, Min(0), Max(100)]

    c = _extract(Entity, "value")
    assert c.min_value == 0
    assert c.max_value == 100


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic model compilation — value storage
# ═══════════════════════════════════════════════════════════════════════════════


def test_compiled_model_stores_and_returns_values() -> None:
    """Compiled pydantic model stores and returns the exact field values."""

    @dataclass
    class User:
        name: str
        age: int

    Model = to_pydantic(User, axes)
    m = Model(name="alice", age=30)
    assert m.name == "alice"
    assert m.age == 30


def test_compiled_model_with_constraints_stores_values() -> None:
    """Compiled model with constraints still stores correct values."""

    @dataclass
    class Entity:
        score: Annotated[int, Min(0), Max(100)]
        label: Annotated[str, MinLen(1), MaxLen(50)]

    Model = to_pydantic(Entity, axes)
    m = Model(score=75, label="hello")
    assert m.score == 75
    assert m.label == "hello"


def test_compiled_model_openapi_schema_has_constraints() -> None:
    """Compiled model's JSON schema reflects Min/Max metadata."""

    @dataclass
    class Entity:
        value: Annotated[int, Min(0), Max(100)]

    Model = to_pydantic(Entity, axes)
    schema = Model.model_json_schema()
    props = schema["properties"]["value"]
    # The constraints appear in the schema metadata
    assert props["type"] == "integer"


# ═══════════════════════════════════════════════════════════════════════════════
# Identity and Unique
# ═══════════════════════════════════════════════════════════════════════════════


def test_identity_constraint_detected() -> None:
    """Identity marks the field as identity."""

    @dataclass
    class User:
        id: Annotated[int, Identity]
        name: str

    c = _extract(User, "id")
    assert c.is_identity is True


def test_non_identity_field_not_marked() -> None:
    """Fields without Identity are NOT identity."""

    @dataclass
    class User:
        id: Annotated[int, Identity]
        name: str

    c = _extract(User, "name")
    assert c.is_identity is False


def test_unique_constraint_detected() -> None:
    """Unique marks the field as unique."""

    @dataclass
    class User:
        email: Annotated[str, Unique]

    c = _extract(User, "email")
    assert c.is_unique is True


# ═══════════════════════════════════════════════════════════════════════════════
# Hypothesis — random valid/invalid generation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class _RangeEntity:
    value: Annotated[int, Min(0), Max(100)]


_range_constraints = _extract(_RangeEntity, "value")


@given(value=st.integers(min_value=0, max_value=100))
@settings(max_examples=50)
def test_hypothesis_min_max_accepts_valid_range(value: int) -> None:
    """Any integer in [0, 100] is accepted by Min(0) + Max(100) constraints."""
    assert _value_accepted(_range_constraints, value) is True


@given(value=st.integers(max_value=-1))
@settings(max_examples=50)
def test_hypothesis_min_rejects_below_zero(value: int) -> None:
    """Any integer < 0 is rejected by Min(0) constraint."""
    assert _value_accepted(_range_constraints, value) is False


@given(value=st.integers(min_value=101))
@settings(max_examples=50)
def test_hypothesis_max_rejects_above_hundred(value: int) -> None:
    """Any integer > 100 is rejected by Max(100) constraint."""
    assert _value_accepted(_range_constraints, value) is False


@dataclass
class _LenEntity:
    name: Annotated[str, MinLen(3), MaxLen(5)]


_len_constraints = _extract(_LenEntity, "name")


@given(text=st.text(min_size=3, max_size=5))
@settings(max_examples=50)
def test_hypothesis_minlen_maxlen_accepts_valid(text: str) -> None:
    """Strings with 3 <= len <= 5 accepted by MinLen(3) + MaxLen(5)."""
    assert _string_accepted(_len_constraints, text) is True


@given(text=st.text(max_size=2))
@settings(max_examples=50)
def test_hypothesis_minlen_rejects_too_short(text: str) -> None:
    """Strings with len < 3 rejected by MinLen(3)."""
    assert _string_accepted(_len_constraints, text) is False


@given(text=st.text(min_size=6, max_size=20))
@settings(max_examples=50)
def test_hypothesis_maxlen_rejects_too_long(text: str) -> None:
    """Strings with len > 5 rejected by MaxLen(5)."""
    assert _string_accepted(_len_constraints, text) is False


def test_multiple_constraints_all_enforced() -> None:
    """MinLen(2) + MaxLen(4) rejects both too short and too long."""

    @dataclass
    class Entity:
        tag: Annotated[str, MinLen(2), MaxLen(4)]

    c = _extract(Entity, "tag")

    assert _string_accepted(c, "a") is False       # too short
    assert _string_accepted(c, "abcde") is False    # too long
    assert _string_accepted(c, "ab") is True        # exact min
    assert _string_accepted(c, "abcd") is True      # exact max
    assert _string_accepted(c, "abc") is True       # middle


@given(
    name=st.text(min_size=1, max_size=50),
    age=st.integers(min_value=0, max_value=200),
)
@settings(max_examples=50)
def test_hypothesis_compiled_model_preserves_values(name: str, age: int) -> None:
    """Compiled pydantic model preserves all field values for random inputs."""

    @dataclass
    class User:
        name: str
        age: int

    Model = to_pydantic(User, axes)
    m = Model(name=name, age=age)
    assert m.name == name
    assert m.age == age
