"""SQL dialect — SQLAlchemy-specific capabilities.

These are IGNORED by other compilers (JSON Schema, Pydantic, etc.).

    from emergent.wire.axis.schema.dialects import sql

    @dataclass
    class User:
        email: Annotated[str, Unique, sql.Index("idx_email")]
        bio: Annotated[str, sql.Type("TEXT")]
        created_at: Annotated[datetime, sql.ServerDefault("CURRENT_TIMESTAMP")]
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from emergent.wire.axis.schema._universal import SchemaAxisCapability

if TYPE_CHECKING:
    from emergent.wire.axis._capability import SQLAlchemyContext, SQLAlchemyTableContext


class SQLCapability(SchemaAxisCapability):
    """Base for SQL-specific capabilities."""

    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Indexing
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Index(SQLCapability):
    """Create index on column.

    Args:
        name: Index name (auto-generated if None)
        unique: Create unique index
    """
    name: str | None = None
    unique: bool = False

    def compile_sqlalchemy(self, ctx: "SQLAlchemyContext") -> "SQLAlchemyContext":
        kwargs: dict[str, str | int | bool | None] = {**ctx.column_kwargs, "index": True}
        if self.unique:
            kwargs["unique"] = True
        return replace(ctx, column_kwargs=kwargs)


@dataclass(frozen=True, slots=True)
class FullText(SQLCapability):
    """Full-text search index (Postgres/MySQL specific).

    Table-level DDL — no compile_sqlalchemy (read directly by table compiler).
    """
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Type Override
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Type(SQLCapability):
    """Override inferred SQL type.

    Examples:
        bio: Annotated[str, sql.Type("TEXT")]
        data: Annotated[dict, sql.Type("JSONB")]
        amount: Annotated[float, sql.Type("DECIMAL(19,4)")]
    """
    sql_type: str

    def compile_sqlalchemy(self, ctx: "SQLAlchemyContext") -> "SQLAlchemyContext":
        return replace(ctx, column_kwargs={**ctx.column_kwargs, "type_": self.sql_type})


# ═══════════════════════════════════════════════════════════════════════════════
# Defaults
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ServerDefault(SQLCapability):
    """Server-side default value (SQL expression).

    Examples:
        sql.ServerDefault("CURRENT_TIMESTAMP")
        sql.ServerDefault("gen_random_uuid()")
        sql.ServerDefault("0")
    """
    expression: str

    def compile_sqlalchemy(self, ctx: "SQLAlchemyContext") -> "SQLAlchemyContext":
        return replace(ctx, column_kwargs={**ctx.column_kwargs, "server_default": self.expression})


@dataclass(frozen=True, slots=True)
class OnUpdate(SQLCapability):
    """Value to set on UPDATE (SQL expression).

    Example:
        updated_at: Annotated[datetime, sql.OnUpdate("CURRENT_TIMESTAMP")]
    """
    expression: str

    def compile_sqlalchemy(self, ctx: "SQLAlchemyContext") -> "SQLAlchemyContext":
        return replace(ctx, column_kwargs={**ctx.column_kwargs, "onupdate": self.expression})


# ═══════════════════════════════════════════════════════════════════════════════
# Constraints
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Check(SQLCapability):
    """Custom CHECK constraint.

    Example:
        age: Annotated[int, sql.Check("age >= 0 AND age <= 150")]

    Table-level DDL — no compile_sqlalchemy (read directly by table compiler).
    """
    expression: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class PrimaryKey(SQLCapability):
    """Explicit primary key (usually inferred from Identity)."""
    autoincrement: bool = True

    def compile_sqlalchemy(self, ctx: "SQLAlchemyContext") -> "SQLAlchemyContext":
        return replace(ctx, column_kwargs={
            **ctx.column_kwargs,
            "primary_key": True,
            "autoincrement": self.autoincrement,
        })


# ═══════════════════════════════════════════════════════════════════════════════
# Foreign Key Details
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ForeignKey(SQLCapability):
    """Explicit foreign key reference.

    Example:
        team_id: Annotated[int, sql.ForeignKey("teams.id", ondelete="SET NULL")]
    """
    target: str  # "table.column"
    ondelete: str = "CASCADE"
    onupdate: str = "CASCADE"

    def compile_sqlalchemy(self, ctx: "SQLAlchemyContext") -> "SQLAlchemyContext":
        # Store FK config in kwargs - compiler builds sqlalchemy.ForeignKey from these
        return replace(ctx, column_kwargs={
            **ctx.column_kwargs,
            "fk_target": self.target,
            "fk_ondelete": self.ondelete,
            "fk_onupdate": self.onupdate,
        })


# ═══════════════════════════════════════════════════════════════════════════════
# Table-Level
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TableName(SQLCapability):
    """Override SQL table name.

    SQL-specific — only affects SQLAlchemy table name.
    Use SchemaName for multi-target (Pydantic title + OpenAPI + SQL).

    Example:
        @schema_meta(sql.TableName("user_accounts"))
        @dataclass
        class User: ...
    """
    name: str

    def compile_sqlalchemy_table(
        self, ctx: "SQLAlchemyTableContext"
    ) -> "SQLAlchemyTableContext":
        from emergent.wire.axis._capability import sqlalchemy_table

        return sqlalchemy_table(ctx, table_name=self.name)


@dataclass(frozen=True, slots=True)
class CompositeUnique(SQLCapability):
    """Unique constraint across multiple fields.

    Example:
        @schema_meta(CompositeUnique("email", "tenant_id"))
        @dataclass
        class User: ...

    SQL: UNIQUE(email, tenant_id)
    """

    fields: tuple[str, ...]
    name: str | None = None

    def __init__(self, *fields: str, name: str | None = None) -> None:
        object.__setattr__(self, "fields", fields)
        object.__setattr__(self, "name", name)

    def compile_sqlalchemy_table(
        self, ctx: "SQLAlchemyTableContext"
    ) -> "SQLAlchemyTableContext":
        return replace(ctx, constraints=(*ctx.constraints, self.fields))


@dataclass(frozen=True, slots=True)
class CompositeIndex(SQLCapability):
    """Index across multiple fields.

    Example:
        @schema_meta(CompositeIndex("status", "created_at", name="idx_status_date"))
        @dataclass
        class Order: ...

    SQL: CREATE INDEX
    """

    fields: tuple[str, ...]
    name: str | None = None
    unique: bool = False

    def __init__(
        self, *fields: str, name: str | None = None, unique: bool = False
    ) -> None:
        object.__setattr__(self, "fields", fields)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "unique", unique)

    def compile_sqlalchemy_table(
        self, ctx: "SQLAlchemyTableContext"
    ) -> "SQLAlchemyTableContext":
        return replace(ctx, indexes=(*ctx.indexes, self.fields))


__all__ = (
    "SQLCapability",
    # Indexing
    "Index",
    "FullText",
    # Type
    "Type",
    # Defaults
    "ServerDefault",
    "OnUpdate",
    # Constraints
    "Check",
    "PrimaryKey",
    # Foreign Key
    "ForeignKey",
    # Table-Level
    "TableName",
    "CompositeIndex",
    "CompositeUnique",
)
