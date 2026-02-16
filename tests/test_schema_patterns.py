"""Tests for emergent.wire.axis.schema._patterns — capability pattern tuples."""

from dataclasses import dataclass
from typing import Annotated

from emergent.wire.axis.schema._universal import Identity, Unique, MinLen, MaxLen, Min, Max, Pattern
from emergent.wire.axis.schema._patterns import (
    Id,
    Email,
    Slug,
    Username,
    Short,
    Medium,
    RequiredShort,
    NonNegative,
    Percentage,
    Probability,
    UniqueValue,
)
from emergent.wire.axis.schema._inspect import inspect_type


class TestPatternContents:
    """Verify each pattern contains the expected capabilities."""

    def test_id(self):
        assert len(Id) == 1
        assert isinstance(Id[0], Identity)

    def test_email(self):
        assert len(Email) == 2
        assert any(isinstance(c, Unique) for c in Email)
        assert any(isinstance(c, MaxLen) and c.value == 255 for c in Email)

    def test_slug(self):
        assert len(Slug) == 3
        assert any(isinstance(c, Unique) for c in Slug)
        assert any(isinstance(c, MaxLen) and c.value == 100 for c in Slug)
        assert any(isinstance(c, Pattern) for c in Slug)

    def test_username(self):
        assert len(Username) == 3
        assert any(isinstance(c, Unique) for c in Username)
        assert any(isinstance(c, MinLen) and c.value == 3 for c in Username)
        assert any(isinstance(c, MaxLen) and c.value == 50 for c in Username)

    def test_short(self):
        assert len(Short) == 1
        assert isinstance(Short[0], MaxLen)
        assert Short[0].value == 100

    def test_medium(self):
        assert len(Medium) == 1
        assert isinstance(Medium[0], MaxLen)
        assert Medium[0].value == 500

    def test_required_short(self):
        assert len(RequiredShort) == 2
        assert any(isinstance(c, MinLen) and c.value == 1 for c in RequiredShort)
        assert any(isinstance(c, MaxLen) and c.value == 100 for c in RequiredShort)

    def test_positive(self):
        assert len(NonNegative) == 1
        assert isinstance(NonNegative[0], Min)
        assert NonNegative[0].value == 0

    def test_percentage(self):
        assert len(Percentage) == 2
        assert any(isinstance(c, Min) and c.value == 0 for c in Percentage)
        assert any(isinstance(c, Max) and c.value == 100 for c in Percentage)

    def test_probability(self):
        assert len(Probability) == 2
        assert any(isinstance(c, Min) and c.value == 0 for c in Probability)
        assert any(isinstance(c, Max) and c.value == 1 for c in Probability)

    def test_unique_value(self):
        assert len(UniqueValue) == 1
        assert isinstance(UniqueValue[0], Unique)


class TestPatternsInAnnotated:
    """Test that patterns work correctly inside Annotated type hints."""

    def test_pattern_extracted_from_annotated(self):
        @dataclass
        class User:
            id: Annotated[int, Id]
            email: Annotated[str, Email]
            name: Annotated[str, Short]
            score: Annotated[int, Percentage]

        fields = inspect_type(User)

        # Id pattern → Identity capability
        assert fields["id"].has(Identity)

        # Email pattern → Unique + MaxLen(255)
        assert fields["email"].has(Unique)
        ml = fields["email"].get(MaxLen)
        assert ml is not None
        assert ml.value == 255

        # Short pattern → MaxLen(100)
        ml2 = fields["name"].get(MaxLen)
        assert ml2 is not None
        assert ml2.value == 100

        # Percentage pattern → Min(0) + Max(100)
        assert fields["score"].has(Min)
        assert fields["score"].has(Max)


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: Patterns compose across multi-field entities
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegrationPatternComposition:
    """Patterns compose correctly when multiple patterns annotate a single entity,
    and interact with inspect_type, helpers, and explain."""

    def test_multi_pattern_entity_full_pipeline(self):
        """Entity uses 5+ distinct patterns — inspect all, verify capabilities correct."""
        from emergent.wire.axis.schema._helpers import (
            get_identity_field,
            fields_with_capability,
            get_required_fields,
        )

        @dataclass
        class Product:
            id: Annotated[int, Id]
            name: Annotated[str, RequiredShort]
            slug: Annotated[str, Slug]
            email: Annotated[str, Email]
            price: Annotated[float, NonNegative]
            discount: Annotated[float, Percentage]
            chance: Annotated[float, Probability]
            sku: Annotated[str, UniqueValue]

        fields = inspect_type(Product)
        assert len(fields) == 8

        # Id field recognized
        id_field = get_identity_field(Product)
        assert id_field is not None
        assert id_field.name == "id"

        # RequiredShort → MinLen(1) + MaxLen(100)
        assert fields["name"].has(MinLen)
        assert fields["name"].has(MaxLen)
        assert fields["name"].get(MinLen).value == 1
        assert fields["name"].get(MaxLen).value == 100

        # Slug → Unique + MaxLen(100) + Pattern
        assert fields["slug"].has(Unique)
        assert fields["slug"].has(MaxLen)
        assert fields["slug"].has(Pattern)

        # NonNegative → Min(0)
        assert fields["price"].get(Min).value == 0

        # Percentage → Min(0) + Max(100)
        assert fields["discount"].get(Min).value == 0
        assert fields["discount"].get(Max).value == 100

        # Probability → Min(0) + Max(1)
        assert fields["chance"].get(Min).value == 0
        assert fields["chance"].get(Max).value == 1

        # UniqueValue → Unique
        assert fields["sku"].has(Unique)

        # All required
        required = get_required_fields(Product)
        assert len(required) == 8

        # fields_with_capability
        unique_fields = fields_with_capability(Product, Unique)
        unique_names = {name for name, _, _ in unique_fields}
        assert unique_names == {"slug", "email", "sku"}

    def test_pattern_stacking_with_extra_caps(self):
        """Patterns can be combined with extra inline capabilities."""
        from emergent.wire.axis.schema._universal import Doc, Deprecated

        @dataclass
        class Account:
            email: Annotated[str, Email, Doc("Primary email")]
            slug: Annotated[str, Slug, Deprecated(reason="Use name instead")]

        fields = inspect_type(Account)

        # Email pattern caps + Doc
        assert fields["email"].has(Unique)
        assert fields["email"].has(MaxLen)
        assert fields["email"].has(Doc)
        doc = fields["email"].get(Doc)
        assert doc.text == "Primary email"

        # Slug pattern caps + Deprecated
        assert fields["slug"].has(Unique)
        assert fields["slug"].has(Pattern)
        assert fields["slug"].has(Deprecated)

    def test_pattern_to_openapi_roundtrip(self):
        """Pattern capabilities compile to OpenAPI schema via fold_field."""
        from emergent.wire.axis._capability import (
            OpenAPIContext, OpenAPICompilable,
        )
        from emergent.wire.compile._core import fold_field

        @dataclass
        class Config:
            retries: Annotated[int, Percentage]
            email: Annotated[str, Email]

        fields = inspect_type(Config)

        # fold_field for retries → Min(0) + Max(100) in OpenAPI
        retries_ctx = fold_field(
            fields["retries"],
            OpenAPIContext(field_name="retries", field_type=int),
            OpenAPICompilable,
            "compile_openapi",
        )
        assert retries_ctx.schema.get("minimum") == 0
        assert retries_ctx.schema.get("maximum") == 100

        # fold_field for email → maxLength(255) in OpenAPI
        email_ctx = fold_field(
            fields["email"],
            OpenAPIContext(field_name="email", field_type=str),
            OpenAPICompilable,
            "compile_openapi",
        )
        assert email_ctx.schema.get("maxLength") == 255
