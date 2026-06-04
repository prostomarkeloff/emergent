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
    from sqlalchemy.sql.elements import ClauseElement

    from emergent.wire.axis._capability import (
        IndexDialectKwargs,
        IndexElement,
        SQLAlchemyContext,
        SQLAlchemyTableContext,
    )


type ColumnKwargs = dict[str, str | int | bool | None]
type _PgIndexKwargs = dict[str, str | list[str] | ClauseElement]


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
        kwargs: ColumnKwargs = {**ctx.column_kwargs, "index": True}
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
    """Override inferred SQL type with a SQLAlchemy type.

    Examples:
        from sqlalchemy import Text, Numeric
        from sqlalchemy.dialects.postgresql import JSONB

        bio: Annotated[str, sql.Type(Text)]
        data: Annotated[dict, sql.Type(JSONB)]
        amount: Annotated[float, sql.Type(Numeric(19, 4))]
    """
    sql_type: type

    def compile_sqlalchemy(self, ctx: "SQLAlchemyContext") -> "SQLAlchemyContext":
        return replace(ctx, column_type=self.sql_type)


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
        from emergent.wire.axis._capability import TableConstraintSpec, sqlalchemy_table

        return sqlalchemy_table(
            ctx, add_constraint=TableConstraintSpec(fields=self.fields, name=self.name)
        )


@dataclass(frozen=True, slots=True)
class CompositeIndex(SQLCapability):
    """Index across columns and/or SQL expressions — plain SQL.

    Example:
        @schema_meta(CompositeIndex("status", "created_at", name="idx_status_date"))
        @schema_meta(CompositeIndex("user_id", text("created_at DESC"), name="ix_user_recent"))

    `fields` may mix column names and `text(...)`/`col.desc()` expressions (functional
    index). Dialect-specific extras (access method, partial WHERE, covering INCLUDE) are
    NOT here — they are their own capability (e.g. `PostgresIndex`), composed by
    inheritance. SQL: CREATE [UNIQUE] INDEX.
    """

    fields: tuple[IndexElement, ...]
    name: str | None = None
    unique: bool = False

    def __init__(self, *fields: IndexElement, name: str | None = None, unique: bool = False) -> None:
        object.__setattr__(self, "fields", fields)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "unique", unique)

    def _dialect_kwargs(self) -> "IndexDialectKwargs":
        """Literal `Index(...)` dialect kwargs — none for plain SQL; subclasses override."""
        return {}

    def compile_sqlalchemy_table(
        self, ctx: "SQLAlchemyTableContext"
    ) -> "SQLAlchemyTableContext":
        from emergent.wire.axis._capability import TableIndexSpec, sqlalchemy_table

        return sqlalchemy_table(
            ctx,
            add_index=TableIndexSpec(
                fields=self.fields,
                name=self.name,
                unique=self.unique,
                dialect_kwargs=self._dialect_kwargs(),
            ),
        )


@dataclass(frozen=True, slots=True)
class PostgresIndex(CompositeIndex):
    """Postgres index: a CompositeIndex that gains its OWN identity — access method,
    partial predicate, covering columns.

    It does not generalise `using`/`where`/`include` into the base (those are not ANSI
    and mean different things per backend); it is a distinct semantic atom that emits
    ONLY `postgresql_*` Index kwargs.

    Example:
        @schema_meta(PostgresIndex("payload", name="ix_payload_gin", using="gin"))
        @schema_meta(PostgresIndex(
            "user_id", text("created_at DESC"),
            name="ix_active_recent", where="deleted_at IS NULL",
        ))
        @schema_meta(PostgresIndex("user_id", "kind", name="ix_cover", include=("created_at",)))
    """

    using: str | None = None
    where: str | None = None
    include: tuple[str, ...] = ()

    def __init__(
        self,
        *fields: IndexElement,
        name: str | None = None,
        unique: bool = False,
        using: str | None = None,
        where: str | None = None,
        include: tuple[str, ...] = (),
    ) -> None:
        super().__init__(*fields, name=name, unique=unique)
        object.__setattr__(self, "using", using)
        object.__setattr__(self, "where", where)
        object.__setattr__(self, "include", include)

    def _dialect_kwargs(self) -> "IndexDialectKwargs":
        from sqlalchemy import text

        kwargs: _PgIndexKwargs = {}
        if self.using is not None:
            kwargs["postgresql_using"] = self.using
        if self.where is not None:
            kwargs["postgresql_where"] = text(self.where)
        if self.include:
            kwargs["postgresql_include"] = list(self.include)
        return kwargs


# ═══════════════════════════════════════════════════════════════════════════════
# JSON Storage
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Json(SQLCapability):
    """Store field as JSON column.

    For collection types (tuple, list, dict) that don't have a native
    SQL column type. The storage compiler serializes to/from JSON.

    Examples:
        tags: Annotated[tuple[str, ...], sql.Json] = ()
        metadata: Annotated[dict[str, str], sql.Json] = field(default_factory=dict)
    """

    def compile_sqlalchemy(self, ctx: "SQLAlchemyContext") -> "SQLAlchemyContext":
        from sqlalchemy import JSON
        return replace(ctx, column_type=JSON)


@dataclass(frozen=True, slots=True)
class JsonB(SQLCapability):
    """Store field as JSONB column (Postgres-specific, indexable).

    Same as Json but uses Postgres JSONB for indexing and query support.

    Examples:
        tags: Annotated[tuple[str, ...], sql.JsonB] = ()
        metadata: Annotated[dict[str, str], sql.JsonB] = field(default_factory=dict)
    """

    def compile_sqlalchemy(self, ctx: "SQLAlchemyContext") -> "SQLAlchemyContext":
        from sqlalchemy.dialects.postgresql import JSONB
        return replace(ctx, column_type=JSONB)


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
    # JSON
    "Json",
    "JsonB",
    # Table-Level
    "TableName",
    "CompositeIndex",
    "PostgresIndex",
    "CompositeUnique",
)
