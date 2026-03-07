"""Temporal dialect — version tracking and bi-temporal capabilities.

Provides capabilities for:
- Versioning: track entity versions with optimistic locking
- Bi-temporal: valid_from/valid_to for point-in-time queries
- Audit timestamps: created_at, updated_at

Usage:
    from emergent.wire.axis.schema.dialects.temporal import (
        Versioned, ValidFrom, ValidTo, CreatedAt, UpdatedAt
    )

    @schema_meta(Versioned())
    @dataclass
    class User:
        id: Annotated[int, Identity]
        email: str
        # version, valid_from, valid_to auto-added by capabilities

    # Query at specific version
    user_v2 = await repo.get_at_version(user_id, version=2)

    # Query as of timestamp
    user_then = await repo.get_as_of(user_id, timestamp)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from emergent.wire.axis.schema._universal import SchemaCapability

if TYPE_CHECKING:
    from emergent.wire.derive._ctx import DeriveCtx
from emergent.wire.axis._capability import (
    SQLAlchemyTableContext,
    PydanticModelContext,
    ExtraColumnSpec,
    ExtraFieldSpec,
    sqlalchemy_table,
    pydantic_model,
)


class TemporalCapability(SchemaCapability):
    """Base for temporal capabilities — version tracking, bi-temporal, audit."""

    pass


# ============================================================================
# Version Tracking
# ============================================================================


@dataclass(frozen=True, slots=True)
class Versioned(TemporalCapability):
    """Entity has version tracking for optimistic locking.

    Adds a version field that increments on each update.
    Used for:
    - Optimistic concurrency control
    - Version history queries
    - Conflict detection

    Compiles to:
    - SQLAlchemy: Integer column with onupdate increment
    - Pydantic: int field with default=1
    """

    version_field: str = "version"
    start_version: int = 1

    def compile_sqlalchemy_table(self, ctx: SQLAlchemyTableContext) -> SQLAlchemyTableContext:
        """Add version column at table level."""
        from sqlalchemy import Integer

        return sqlalchemy_table(ctx, add_column=ExtraColumnSpec(
            self.version_field, Integer, nullable=False, default=self.start_version,
        ))

    def compile_pydantic_model(self, ctx: PydanticModelContext) -> PydanticModelContext:
        """Add version field to Pydantic model."""
        return pydantic_model(ctx, add_field=ExtraFieldSpec(
            self.version_field, int, self.start_version,
        ))


# ============================================================================
# Bi-Temporal Tracking
# ============================================================================


@dataclass(frozen=True, slots=True)
class ValidFrom(TemporalCapability):
    """Bi-temporal: when this version became valid.

    For point-in-time queries. Combined with ValidTo for
    full temporal range.

    Compiles to:
    - SQLAlchemy: DateTime column with server_default=now()
    """

    field_name: str = "valid_from"
    use_server_default: bool = True

    def compile_sqlalchemy_table(self, ctx: SQLAlchemyTableContext) -> SQLAlchemyTableContext:
        """Add valid_from column."""
        from sqlalchemy import DateTime, func

        return sqlalchemy_table(ctx, add_column=ExtraColumnSpec(
            self.field_name, DateTime, nullable=False,
            server_default=func.now() if self.use_server_default else None,
        ))


@dataclass(frozen=True, slots=True)
class ValidTo(TemporalCapability):
    """Bi-temporal: when this version stopped being valid.

    None/NULL means currently valid.

    Compiles to:
    - SQLAlchemy: DateTime column, nullable
    """

    field_name: str = "valid_to"

    def compile_sqlalchemy_table(self, ctx: SQLAlchemyTableContext) -> SQLAlchemyTableContext:
        """Add valid_to column."""
        from sqlalchemy import DateTime

        return sqlalchemy_table(ctx, add_column=ExtraColumnSpec(
            self.field_name, DateTime,
        ))


@dataclass(frozen=True, slots=True)
class Temporal(TemporalCapability):
    """Convenience: adds both ValidFrom and ValidTo.

    Use when you need full bi-temporal support.

    Example:
        @schema_meta(Temporal())
        @dataclass
        class User:
            id: int
            email: str
            # valid_from and valid_to auto-added
    """

    valid_from_field: str = "valid_from"
    valid_to_field: str = "valid_to"

    def compile_sqlalchemy_table(self, ctx: SQLAlchemyTableContext) -> SQLAlchemyTableContext:
        """Add both temporal columns."""
        from sqlalchemy import DateTime, func

        ctx = sqlalchemy_table(ctx, add_column=ExtraColumnSpec(
            self.valid_from_field, DateTime, nullable=False,
            server_default=func.now(),
        ))
        return sqlalchemy_table(ctx, add_column=ExtraColumnSpec(
            self.valid_to_field, DateTime,
        ))


# ============================================================================
# Audit Timestamps
# ============================================================================


@dataclass(frozen=True, slots=True)
class CreatedAt(TemporalCapability):
    """Audit: when entity was created.

    Auto-set on insert, never updated.

    Compiles to:
    - SQLAlchemy: DateTime column with server_default=now()
    """

    field_name: str = "created_at"

    def compile_sqlalchemy_table(self, ctx: SQLAlchemyTableContext) -> SQLAlchemyTableContext:
        """Add created_at column."""
        from sqlalchemy import DateTime, func

        return sqlalchemy_table(ctx, add_column=ExtraColumnSpec(
            self.field_name, DateTime, nullable=False,
            server_default=func.now(),
        ))


@dataclass(frozen=True, slots=True)
class UpdatedAt(TemporalCapability):
    """Audit: when entity was last updated.

    Auto-updated on every modification.

    Compiles to:
    - SQLAlchemy: DateTime column with onupdate=now()
    """

    field_name: str = "updated_at"

    def compile_sqlalchemy_table(self, ctx: SQLAlchemyTableContext) -> SQLAlchemyTableContext:
        """Add updated_at column."""
        from sqlalchemy import DateTime, func

        return sqlalchemy_table(ctx, add_column=ExtraColumnSpec(
            self.field_name, DateTime, nullable=False,
            server_default=func.now(), onupdate=func.now(),
        ))


@dataclass(frozen=True, slots=True)
class Timestamps(TemporalCapability):
    """Convenience: adds both CreatedAt and UpdatedAt.

    Example:
        @schema_meta(Timestamps())
        @dataclass
        class User:
            id: int
            email: str
            # created_at and updated_at auto-added
    """

    created_field: str = "created_at"
    updated_field: str = "updated_at"

    def compile_sqlalchemy_table(self, ctx: SQLAlchemyTableContext) -> SQLAlchemyTableContext:
        """Add both timestamp columns."""
        from sqlalchemy import DateTime, func

        ctx = sqlalchemy_table(ctx, add_column=ExtraColumnSpec(
            self.created_field, DateTime, nullable=False,
            server_default=func.now(),
        ))
        return sqlalchemy_table(ctx, add_column=ExtraColumnSpec(
            self.updated_field, DateTime, nullable=False,
            server_default=func.now(), onupdate=func.now(),
        ))

    def compile_derive_modify(self, ctx: "DeriveCtx") -> "DeriveCtx":  # type: ignore[type-arg]
        """Replace Create/Update handlers with timestamp-aware versions."""
        from emergent.wire.derive._effects import Creates, Updates
        from emergent.wire.derive._handler import TimestampInsert, TimestampUpdate

        exclude = frozenset({self.created_field, self.updated_field})
        ctx = ctx.replace_handler(Creates, TimestampInsert(self.created_field, self.updated_field))
        ctx = ctx.replace_handler(Updates, TimestampUpdate(self.updated_field))
        ctx = ctx.exclude_fields(Creates, exclude)
        ctx = ctx.exclude_fields(Updates, exclude)
        return ctx


# ============================================================================
# Soft Delete
# ============================================================================


@dataclass(frozen=True, slots=True)
class SoftDelete(TemporalCapability):
    """Entity uses soft delete instead of hard delete.

    Adds a deleted_at field. When set, entity is considered deleted.
    Queries should filter out soft-deleted records by default.

    Compiles to:
    - SQLAlchemy: DateTime column, nullable
    - Query modifier: WHERE deleted_at IS NULL
    - Derive: replaces Delete handler with SoftDeleteMark, filters base_query
    """

    field_name: str = "deleted_at"

    def compile_sqlalchemy_table(self, ctx: SQLAlchemyTableContext) -> SQLAlchemyTableContext:
        """Add deleted_at column."""
        from sqlalchemy import DateTime

        return sqlalchemy_table(ctx, add_column=ExtraColumnSpec(
            self.field_name, DateTime,
        ))

    def compile_derive_modify(self, ctx: "DeriveCtx") -> "DeriveCtx":  # type: ignore[type-arg]
        """Replace Delete handler with SoftDeleteMark, filter base_query."""
        from emergent.wire.derive._effects import Deletes
        from emergent.wire.derive._handler import SoftDeleteMark

        field = self.field_name
        ctx = ctx.replace_handler(Deletes, SoftDeleteMark(field))
        ctx = ctx.filter_query(lambda e, _f=field: getattr(e, _f).is_null())
        return ctx


# ============================================================================
# Temporal Query Helpers
# ============================================================================


def temporal_filter_current(field_name: str = "valid_to"):
    """Create filter for current records (valid_to IS NULL)."""
    from emergent.wire.axis.query._expr import IsNull, Field

    return IsNull(Field(field_name))


def temporal_filter_as_of(timestamp: datetime, valid_from: str = "valid_from", valid_to: str = "valid_to"):
    """Create filter for records valid at specific timestamp.

    Returns expression: valid_from <= timestamp AND (valid_to IS NULL OR valid_to > timestamp)
    """
    from emergent.wire.axis.query._expr import And, Or, Le, Gt, IsNull, Field, Const

    return And(
        Le(Field(valid_from), Const(timestamp)),
        Or(
            IsNull(Field(valid_to)),
            Gt(Field(valid_to), Const(timestamp)),
        ),
    )


def temporal_filter_version(version: int, version_field: str = "version"):
    """Create filter for specific version."""
    from emergent.wire.axis.query._expr import Eq, Field, Const

    return Eq(Field(version_field), Const(version))


# ============================================================================
# Exports
# ============================================================================

__all__ = (
    # Base
    "TemporalCapability",
    # Version tracking
    "Versioned",
    # Bi-temporal
    "ValidFrom",
    "ValidTo",
    "Temporal",
    # Audit timestamps
    "CreatedAt",
    "UpdatedAt",
    "Timestamps",
    # Soft delete
    "SoftDelete",
    # Query helpers
    "temporal_filter_current",
    "temporal_filter_as_of",
    "temporal_filter_version",
)
