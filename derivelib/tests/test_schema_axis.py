"""Tests for derivelib.axes.schema — schema axis derivation steps."""

from __future__ import annotations

import pytest

from derivelib._ctx import SchemaCtx
from derivelib.axes.schema import (
    ExcludeSchemaFields,
    InspectEntity,
    RequireFields,
    RequireIdentity,
    exclude_fields,
    inspect_entity,
    require_fields,
    require_identity,
)

from .conftest import NoIdentity, User, no_id_schema, user_schema


class TestInspectEntity:
    def test_no_op(self) -> None:
        ctx = user_schema()
        result = InspectEntity().derive_schema(ctx)
        assert result is ctx

    def test_constructor(self) -> None:
        step = inspect_entity()
        assert isinstance(step, InspectEntity)


class TestRequireIdentity:
    def test_passes_with_identity(self) -> None:
        ctx = user_schema()
        result = RequireIdentity().derive_schema(ctx)
        assert result is ctx

    def test_raises_without_identity(self) -> None:
        ctx = no_id_schema()
        with pytest.raises(ValueError, match="Identity"):
            RequireIdentity().derive_schema(ctx)

    def test_constructor(self) -> None:
        step = require_identity()
        assert isinstance(step, RequireIdentity)


class TestExcludeSchemaFields:
    def test_removes_fields(self) -> None:
        ctx = user_schema()
        step = ExcludeSchemaFields(names=("email",))
        result = step.derive_schema(ctx)
        assert "email" not in result.fields
        assert "name" in result.fields
        assert "id" in result.fields

    def test_removes_multiple(self) -> None:
        ctx = user_schema()
        step = ExcludeSchemaFields(names=("name", "email"))
        result = step.derive_schema(ctx)
        assert "name" not in result.fields
        assert "email" not in result.fields
        assert "id" in result.fields

    def test_constructor(self) -> None:
        step = exclude_fields("name", "email")
        assert isinstance(step, ExcludeSchemaFields)
        assert step.names == ("name", "email")


class TestRequireFields:
    def test_passes_when_present(self) -> None:
        ctx = user_schema()
        step = RequireFields(names=("name", "email"))
        result = step.derive_schema(ctx)
        assert result is ctx

    def test_raises_when_missing(self) -> None:
        ctx = user_schema()
        step = RequireFields(names=("nonexistent",))
        with pytest.raises(ValueError, match="nonexistent"):
            step.derive_schema(ctx)

    def test_constructor(self) -> None:
        step = require_fields("name")
        assert isinstance(step, RequireFields)
