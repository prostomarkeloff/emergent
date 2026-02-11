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
