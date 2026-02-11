"""Tests for schema explain — dict layer, format layer, dialect grouping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import pytest

from emergent.wire.axis.schema import (
    Identity,
    Unique,
    MaxLen,
    MinLen,
    Doc,
    SchemaName,
    Deprecated,
    Nullable,
    Ref,
    inspect_type,
    schema_meta,
    get_schema_meta,
)
from emergent.wire.axis.schema._explain import (
    schema_dict,
    field_info_dict,
    explain_schema,
    explain_field,
)
from emergent.wire.axis.schema._inspect import FieldInfo
from emergent.wire.axis.schema.dialects.cli import CLICapability, Help
from emergent.wire.axis.schema.dialects.openapi import OpenAPICapability, Description, Format
from emergent.wire.axis.schema.dialects.sql import SQLCapability, Index


# ─── Test Fixtures ──────────────────────────────────────────────────────────


@schema_meta(SchemaName("users"))
@dataclass
class User:
    id: Annotated[int, Identity]
    email: Annotated[str, Unique, MaxLen(255), Help("Email address"), Description("User email"), Format("email"), Index("idx_email")]
    name: Annotated[str, MaxLen(50), Help("Full name")]
    active: Annotated[bool, Doc("Whether user is active")] = True


@dataclass
class Simple:
    value: int
    label: str = "default"


# ─── Dict Layer ─────────────────────────────────────────────────────────────


class TestSchemaDict:
    def test_basic_schema(self):
        data = schema_dict(User)
        assert data["name"] == "User"
        assert "fields" in data
        assert len(data["fields"]) == 4

    def test_schema_meta(self):
        data = schema_dict(User)
        assert "meta" in data
        meta = data["meta"]
        assert len(meta) == 1
        assert meta[0]["type"] == "SchemaName"

    def test_field_names(self):
        data = schema_dict(User)
        field_names = [f["name"] for f in data["fields"]]
        assert field_names == ["id", "email", "name", "active"]

    def test_field_types(self):
        data = schema_dict(User)
        types = {f["name"]: f["type"] for f in data["fields"]}
        assert types["id"] == "int"
        assert types["email"] == "str"
        assert types["active"] == "bool"

    def test_universal_caps(self):
        data = schema_dict(User)
        id_field = data["fields"][0]
        assert "universal" in id_field
        cap_types = [c["type"] for c in id_field["universal"]]
        assert "Identity" in cap_types

    def test_dialect_caps(self):
        data = schema_dict(User)
        email_field = data["fields"][1]
        # CLI dialect
        assert "cli" in email_field
        cli_caps = [c["type"] for c in email_field["cli"]]
        assert "Help" in cli_caps
        # OpenAPI dialect
        assert "openapi" in email_field
        openapi_caps = [c["type"] for c in email_field["openapi"]]
        assert "Description" in openapi_caps
        assert "Format" in openapi_caps
        # SQL dialect
        assert "sql" in email_field
        sql_caps = [c["type"] for c in email_field["sql"]]
        assert "Index" in sql_caps

    def test_default_field(self):
        data = schema_dict(User)
        active_field = data["fields"][3]
        assert active_field["has_default"] is True

    def test_no_meta_when_absent(self):
        data = schema_dict(Simple)
        assert "meta" not in data

    def test_no_dialect_when_absent(self):
        data = schema_dict(Simple)
        value_field = data["fields"][0]
        # No dialect keys should be present
        assert "cli" not in value_field
        assert "openapi" not in value_field
        assert "sql" not in value_field


class TestFieldInfoDict:
    def test_single_field(self):
        fields = inspect_type(User)
        d = field_info_dict(fields["email"])
        assert d["name"] == "email"
        assert d["type"] == "str"
        assert d["optional"] is False
        assert "universal" in d

    def test_custom_dialects(self):
        fields = inspect_type(User)
        # Only check CLI dialect
        d = field_info_dict(fields["email"], dialects={"cli": CLICapability})
        assert "cli" in d
        # Other dialects not checked
        assert "openapi" not in d
        assert "sql" not in d


# ─── Human-Readable Layer ───────────────────────────────────────────────────


class TestExplainSchema:
    def test_header(self):
        text = explain_schema(User)
        assert "=== User ===" in text

    def test_meta_shown(self):
        text = explain_schema(User)
        assert "SchemaName" in text

    def test_fields_shown(self):
        text = explain_schema(User)
        assert "id (int" in text
        assert "email (str" in text
        assert "name (str" in text
        assert "active (bool" in text

    def test_universal_caps_shown(self):
        text = explain_schema(User)
        assert "Identity" in text
        assert "Unique" in text
        assert "MaxLen" in text

    def test_dialect_caps_shown(self):
        text = explain_schema(User)
        assert "cli:" in text
        assert "Help" in text
        assert "openapi:" in text
        assert "Description" in text

    def test_default_shown(self):
        text = explain_schema(User)
        assert "= default" in text

    def test_simple_schema(self):
        text = explain_schema(Simple)
        assert "=== Simple ===" in text
        assert "value (int" in text


class TestExplainField:
    def test_existing_field(self):
        text = explain_field(User, "email")
        assert "email" in text
        assert "Unique" in text

    def test_missing_field(self):
        text = explain_field(User, "nonexistent")
        assert "not found" in text

    def test_field_with_dialect(self):
        text = explain_field(User, "email")
        assert "cli:" in text
        assert "Help" in text


# ─── Open World ─────────────────────────────────────────────────────────────


class TestOpenWorld:
    def test_no_crash_on_plain_dataclass(self):
        @dataclass
        class Bare:
            x: int
            y: str

        data = schema_dict(Bare)
        assert data["name"] == "Bare"
        assert len(data["fields"]) == 2

    def test_no_crash_on_empty_caps(self):
        @dataclass
        class NoCaps:
            value: int

        text = explain_schema(NoCaps)
        assert "=== NoCaps ===" in text
