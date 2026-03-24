"""Extended tests for schema delta dialect — coverage gaps.

Covers:
- NumericDelta.apply: multiply producing non-whole float from int
- DeltaField.compile_openapi
- DeltaField.compile_delta
- compose_deltas: numeric multiply-only compose edge cases
- _compose_field_deltas: different-type deltas fallback
- _delta_kind: unknown type
- delta_type: collection field generation branch
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field, make_dataclass
from typing import Annotated

import emergent.wire.axis.schema.dialects.delta as _delta_mod
from emergent.wire.axis.schema.dialects.delta import (
    CollectionDelta,
    DeltaField,
    NumericDelta,
    StringDelta,
    apply_delta,
    compose_deltas,
    delta_type,
    validate_delta,
)

# Access private functions via getattr for testing internal behavior;
# pyright disallows direct use of private names from other modules.
_compose_field_deltas_fn = getattr(_delta_mod, "_compose_field_deltas")
_delta_kind_fn = getattr(_delta_mod, "_delta_kind")


# ─── NumericDelta.apply: non-whole float from int ────────────────────────────


def test_numeric_delta_multiply_non_whole_from_int():
    """Multiplying an int by a non-whole factor returns float, not int."""
    d = NumericDelta(multiply=2.5)
    result = d.apply(10)
    # 10 * 2.5 = 25.0 which IS whole, so it should be int
    assert result == 25
    assert isinstance(result, int)

    # Now a true non-whole result
    d2 = NumericDelta(multiply=0.3)
    _result2 = d2.apply(10)
    # 10 * 0.3 = 3.0 which IS whole... let's use something that isn't
    d3 = NumericDelta(multiply=0.7)
    result3 = d3.apply(3)
    # 3 * 0.7 = 2.0999... which is NOT whole
    assert isinstance(result3, float)
    assert abs(result3 - 2.1) < 1e-9


def test_numeric_delta_add_float_preserves_float():
    """Adding to a float does not coerce to int."""
    d = NumericDelta(add=0.5)
    result = d.apply(1.0)
    assert result == 1.5
    assert isinstance(result, float)


# ─── DeltaField.compile_openapi ──────────────────────────────────────────────


def test_delta_field_compile_openapi():
    """DeltaField.compile_openapi populates x-delta-type in schema."""
    from emergent.wire.axis._capability import OpenAPIContext

    df = DeltaField("numeric")
    ctx = OpenAPIContext(field_name="balance", field_type=int)
    new_ctx = df.compile_openapi(ctx)
    assert new_ctx.schema.get("x-delta-type") == "numeric"


def test_delta_field_compile_openapi_string():
    """DeltaField compile_openapi for string type."""
    from emergent.wire.axis._capability import OpenAPIContext

    df = DeltaField("string")
    ctx = OpenAPIContext(field_name="notes", field_type=str)
    new_ctx = df.compile_openapi(ctx)
    assert new_ctx.schema.get("x-delta-type") == "string"


def test_delta_field_compile_openapi_collection():
    """DeltaField compile_openapi for collection type."""
    from emergent.wire.axis._capability import OpenAPIContext

    df = DeltaField("collection")
    ctx = OpenAPIContext(field_name="tags", field_type=list)
    new_ctx = df.compile_openapi(ctx)
    assert new_ctx.schema.get("x-delta-type") == "collection"


# ─── DeltaField.compile_delta ────────────────────────────────────────────────


def test_delta_field_compile_delta():
    """DeltaField.compile_delta sets delta_kind on context."""
    from emergent.wire.axis._capability import DeltaContext

    df = DeltaField("numeric")
    ctx = DeltaContext(field_name="balance", field_type=int)
    new_ctx = df.compile_delta(ctx)
    assert new_ctx.delta_kind == "numeric"


def test_delta_field_compile_delta_string():
    """DeltaField.compile_delta for string."""
    from emergent.wire.axis._capability import DeltaContext

    df = DeltaField("string")
    ctx = DeltaContext(field_name="notes", field_type=str)
    new_ctx = df.compile_delta(ctx)
    assert new_ctx.delta_kind == "string"


# ─── compose_deltas: multiply-only numeric composition ───────────────────────


def test_compose_deltas_numeric_multiply_both():
    """Composing two multiply-only numeric deltas multiplies the multipliers."""

    @dataclass
    class Acc:
        val: Annotated[int, DeltaField("numeric")]

    AccDelta = delta_type(Acc)
    d1 = AccDelta(val=NumericDelta(multiply=2.0))
    d2 = AccDelta(val=NumericDelta(multiply=3.0))
    combined = compose_deltas(d1, d2)
    assert combined.val.multiply is not None and abs(combined.val.multiply - 6.0) < 1e-9


def test_compose_deltas_numeric_multiply_first_only():
    """Composing deltas where only first has multiply."""

    @dataclass
    class Acc:
        val: Annotated[int, DeltaField("numeric")]

    AccDelta = delta_type(Acc)
    d1 = AccDelta(val=NumericDelta(multiply=2.0))
    d2 = AccDelta(val=NumericDelta(add=5))
    combined = compose_deltas(d1, d2)
    assert combined.val.multiply == 2.0
    assert combined.val.add == 5


def test_compose_deltas_numeric_multiply_second_only():
    """Composing deltas where only second has multiply."""

    @dataclass
    class Acc:
        val: Annotated[int, DeltaField("numeric")]

    AccDelta = delta_type(Acc)
    d1 = AccDelta(val=NumericDelta(add=5))
    d2 = AccDelta(val=NumericDelta(multiply=3.0))
    combined = compose_deltas(d1, d2)
    assert combined.val.multiply == 3.0
    assert combined.val.add == 5


def test_compose_deltas_numeric_set_from_first():
    """Composing deltas where first has set and second doesn't."""

    @dataclass
    class Acc:
        val: Annotated[int, DeltaField("numeric")]

    AccDelta = delta_type(Acc)
    d1 = AccDelta(val=NumericDelta(set=42))
    d2 = AccDelta(val=NumericDelta(add=5))
    combined = compose_deltas(d1, d2)
    assert combined.val.set == 42


# ─── _compose_field_deltas: different types ──────────────────────────────────


def test_compose_field_deltas_different_types():
    """When composing different delta types, last one wins."""
    d1 = NumericDelta(add=10)
    d2 = StringDelta(set="override")
    result = _compose_field_deltas_fn(d1, d2)
    assert isinstance(result, StringDelta)
    assert result.set == "override"


# ─── _delta_kind: unknown type ───────────────────────────────────────────────


def test_delta_kind_unknown():
    """_delta_kind returns 'unknown' for unrecognized delta type."""

    class WeirdDelta:
        pass

    result = _delta_kind_fn(WeirdDelta())
    assert result == "unknown"


# ─── delta_type with string field generation ─────────────────────────────────


def test_delta_type_string_field():
    """delta_type generates StringDelta field for DeltaField('string')."""

    @dataclass
    class Doc:
        id: int
        title: Annotated[str, DeltaField("string")]

    DocDelta = delta_type(Doc)
    d = DocDelta(title=StringDelta(append=" v2"))
    assert d.title.append == " v2"


def test_delta_type_collection_field():
    """delta_type generates CollectionDelta field for DeltaField('collection')."""

    @dataclass
    class Bag:
        id: int
        items: Annotated[list[str], DeltaField("collection")]

    BagDelta = delta_type(Bag)
    d = BagDelta(items=CollectionDelta(push=("new_item",)))
    assert d.items.push == ("new_item",)


def test_delta_type_all_three_types():
    """delta_type handles numeric, string, and collection fields together."""

    @dataclass
    class Full:
        id: int
        count: Annotated[int, DeltaField("numeric")]
        label: Annotated[str, DeltaField("string")]
        tags: Annotated[list[str], DeltaField("collection")]

    FullDelta = delta_type(Full)
    d = FullDelta(
        count=NumericDelta(add=1),
        label=StringDelta(prepend="[x] "),
        tags=CollectionDelta(push=("a",)),
    )
    assert d.count.add == 1
    assert d.label.prepend == "[x] "
    assert d.tags.push == ("a",)


# ─── apply_delta with string delta ──────────────────────────────────────────


def test_apply_delta_string():
    """apply_delta works with StringDelta fields."""

    @dataclass
    class Doc:
        id: int
        title: Annotated[str, DeltaField("string")]

    DocDelta = delta_type(Doc)
    doc = Doc(id=1, title="Hello")
    d = DocDelta(title=StringDelta(append=" World"))
    result = apply_delta(doc, d)
    assert result.title == "Hello World"


# ─── validate_delta with unknown delta kind ──────────────────────────────────


def test_validate_delta_unknown_delta_kind():
    """validate_delta reports error for unrecognized delta type on a DeltaField."""

    @dataclass
    class Acc:
        balance: Annotated[int, DeltaField("numeric")]

    class WeirdDelta:
        pass

    FakeDelta = make_dataclass(
        "FakeDelta",
        [("balance", WeirdDelta | None, dc_field(default=None))],
        frozen=True,
        slots=True,
    )

    d = FakeDelta(balance=WeirdDelta())
    errors = validate_delta(d, Acc)
    assert len(errors) == 1
    assert "expects numeric delta, got unknown" in errors[0]
