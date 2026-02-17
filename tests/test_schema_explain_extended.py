"""Extended tests for emergent/wire/axis/schema/_explain.py — coverage gaps.

Covers missed lines:
- _cap_repr: with dataclass cap having fields, with type-valued field, with no fields
- _cap_repr: non-dataclass capability
- _cap_dict: with type-valued field
- _format_cap_short: with fields, without fields
- _format_field: with has_default, with optional, with dialect caps
- _format_schema: with meta, with fields
- explain_field: with existing field, with missing field, with custom dialects
- schema_dict: custom dialects parameter
- field_info_dict: non-type base_type (e.g. generic alias)
"""

from dataclasses import dataclass
from typing import Annotated

from emergent.wire.axis.schema import (
    Identity,
    MaxLen,
    SchemaName,
    SchemaDoc,
    Deprecated,
    schema_meta,
    schema_dict,
    field_info_dict,
    explain_schema,
    explain_field,
    FieldInfo,
    SchemaAxisCapability,
    Ref,
)
import emergent.wire.axis.schema._explain as _explain_mod  # pyright: ignore[reportPrivateUsage] - testing private helpers
from emergent.wire.axis.schema.dialects.cli import CLICapability, Help

# Access private helpers through the module for testing.
_cap_repr = _explain_mod._cap_repr  # pyright: ignore[reportPrivateUsage] - testing private helper
_cap_dict = _explain_mod._cap_dict  # pyright: ignore[reportPrivateUsage] - testing private helper
_format_cap_short = _explain_mod._format_cap_short  # pyright: ignore[reportPrivateUsage] - testing private helper
_format_field = _explain_mod._format_field  # pyright: ignore[reportPrivateUsage] - testing private helper
_format_schema = _explain_mod._format_schema  # pyright: ignore[reportPrivateUsage] - testing private helper


# ============================================================================
# _cap_repr
# ============================================================================


class TestCapRepr:
    def test_dataclass_cap_with_fields(self) -> None:
        cap = MaxLen(value=255)
        result = _cap_repr(cap)
        assert result == "MaxLen(255)"

    def test_dataclass_cap_no_fields(self) -> None:
        cap = Identity()
        result = _cap_repr(cap)
        assert result == "Identity"

    def test_dataclass_cap_type_valued_field(self) -> None:
        """Cap with a type-valued field shows __name__."""
        cap = Ref(target=str)
        result = _cap_repr(cap)
        # Ref has fields: target, on_delete, on_update
        assert "Ref(" in result
        assert "'str'" in result

    def test_non_dataclass_cap(self) -> None:
        """Non-dataclass capability shows just the type name."""
        class CustomCap(SchemaAxisCapability):
            pass

        cap = CustomCap()
        result = _cap_repr(cap)
        assert result == "CustomCap"


# ============================================================================
# _cap_dict
# ============================================================================


class TestCapDict:
    def test_dataclass_cap_dict(self) -> None:
        cap = MaxLen(value=255)
        d = _cap_dict(cap)
        assert d["type"] == "MaxLen"
        assert d["value"] == 255

    def test_type_valued_field(self) -> None:
        """Type-valued field in cap shows __name__."""
        cap = Ref(target=int)
        d = _cap_dict(cap)
        assert d["type"] == "Ref"
        assert d["target"] == "int"

    def test_no_fields(self) -> None:
        cap = Identity()
        d = _cap_dict(cap)
        assert d["type"] == "Identity"
        # No extra keys (Identity has no fields)
        assert len(d) == 1

    def test_non_dataclass(self) -> None:
        class SimpleCap(SchemaAxisCapability):
            pass

        cap = SimpleCap()
        d = _cap_dict(cap)
        assert d["type"] == "SimpleCap"
        assert len(d) == 1


# ============================================================================
# _format_cap_short
# ============================================================================


class TestFormatCapShort:
    def test_with_fields(self) -> None:
        d = {"type": "MaxLen", "value": 255}
        result = _format_cap_short(d)
        assert result == "MaxLen(255)"

    def test_no_fields(self) -> None:
        d = {"type": "Identity"}
        result = _format_cap_short(d)
        assert result == "Identity"

    def test_multiple_fields(self) -> None:
        d = {"type": "Ref", "target": "users.id", "on_delete": "CASCADE"}
        result = _format_cap_short(d)
        assert "Ref(" in result
        assert "'users.id'" in result
        assert "'CASCADE'" in result


# ============================================================================
# _format_field
# ============================================================================


class TestFormatField:
    def test_field_with_default(self) -> None:
        fd = {"name": "active", "type": "bool", "has_default": True}
        result = _format_field(fd)
        assert "active (bool = default):" in result

    def test_field_optional(self) -> None:
        fd = {"name": "middle", "type": "str", "optional": True, "has_default": False}
        result = _format_field(fd)
        assert "middle (str | None):" in result

    def test_field_required(self) -> None:
        fd = {"name": "name", "type": "str", "optional": False, "has_default": False}
        result = _format_field(fd)
        assert "name (str):" in result

    def test_field_with_universal(self) -> None:
        fd = {
            "name": "email",
            "type": "str",
            "optional": False,
            "has_default": False,
            "universal": [{"type": "Unique"}, {"type": "MaxLen", "value": 255}],
        }
        result = _format_field(fd)
        assert "[Unique, MaxLen(255)]" in result

    def test_field_with_dialect(self) -> None:
        fd = {
            "name": "email",
            "type": "str",
            "optional": False,
            "has_default": False,
            "cli": [{"type": "Help", "text": "Email"}],
        }
        result = _format_field(fd)
        assert "cli:" in result
        assert "Help" in result


# ============================================================================
# _format_schema
# ============================================================================


class TestFormatSchema:
    def test_with_meta(self) -> None:
        data = {
            "name": "User",
            "meta": [{"type": "SchemaName", "value": "users"}],
            "fields": [],
        }
        result = _format_schema(data)
        assert "=== User ===" in result
        assert "SchemaName('users')" in result

    def test_without_meta(self) -> None:
        data = {
            "name": "Simple",
            "fields": [{"name": "x", "type": "int", "optional": False, "has_default": False}],
        }
        result = _format_schema(data)
        assert "=== Simple ===" in result
        assert "x (int):" in result


# ============================================================================
# schema_dict with custom dialects
# ============================================================================


class TestSchemaDictCustomDialects:
    def test_custom_dialect_subset(self) -> None:
        @dataclass
        class Entity:
            name: Annotated[str, MaxLen(50), Help("The name")]

        d = schema_dict(Entity, dialects={"cli": CLICapability})
        field_d = d["fields"][0]
        assert "cli" in field_d
        # Other dialects not present
        assert "openapi" not in field_d
        assert "sql" not in field_d

    def test_empty_dialects(self) -> None:
        @dataclass
        class Entity:
            name: Annotated[str, MaxLen(50)]

        d = schema_dict(Entity, dialects={})
        field_d = d["fields"][0]
        # Only universal, no dialect keys
        assert "universal" in field_d
        assert "cli" not in field_d


# ============================================================================
# field_info_dict edge cases
# ============================================================================


class TestFieldInfoDictEdgeCases:
    def test_non_type_base_type(self) -> None:
        """When base_type is not a plain type (e.g. generic alias)."""
        info = FieldInfo(
            name="items",
            base_type=list[int],  # type: ignore[arg-type] - intentionally passing GenericAlias to test the str() fallback branch in field_info_dict
            is_optional=False,
            capabilities=(),
        )
        d = field_info_dict(info, dialects={})
        # Should use str() for non-type
        assert d["name"] == "items"
        assert "type" in d


# ============================================================================
# explain_field
# ============================================================================


class TestExplainFieldExtended:
    def test_field_not_found(self) -> None:
        @dataclass
        class Entity:
            x: int

        text = explain_field(Entity, "nonexistent")
        assert "not found" in text
        assert "Entity" in text

    def test_field_found(self) -> None:
        @dataclass
        class Entity:
            x: Annotated[int, Identity]

        text = explain_field(Entity, "x")
        assert "x (int):" in text
        assert "Identity" in text

    def test_field_with_custom_dialects(self) -> None:
        @dataclass
        class Entity:
            name: Annotated[str, MaxLen(50), Help("Name")]

        text = explain_field(Entity, "name", dialects={"cli": CLICapability})
        assert "cli:" in text
        assert "Help" in text
        # openapi/sql not shown
        assert "openapi:" not in text


# ============================================================================
# explain_schema
# ============================================================================


class TestExplainSchemaExtended:
    def test_schema_with_meta_and_fields(self) -> None:
        @schema_meta(SchemaName("products"), SchemaDoc("Product catalog"))
        @dataclass
        class Product:
            id: Annotated[int, Identity]
            name: Annotated[str, MaxLen(100)]
            price: float
            active: bool = True

        text = explain_schema(Product)
        assert "=== Product ===" in text
        assert "SchemaName" in text
        assert "SchemaDoc" in text
        assert "id (int):" in text
        assert "Identity" in text
        assert "name (str):" in text
        assert "MaxLen" in text
        assert "active (bool = default):" in text

    def test_schema_no_caps(self) -> None:
        @dataclass
        class Plain:
            x: int
            y: str

        text = explain_schema(Plain)
        assert "=== Plain ===" in text
        assert "x (int):" in text
        assert "y (str):" in text

    def test_schema_with_deprecated_field(self) -> None:
        @dataclass
        class Legacy:
            old_field: Annotated[str, Deprecated(reason="Use new_field")]

        text = explain_schema(Legacy)
        assert "Deprecated" in text
