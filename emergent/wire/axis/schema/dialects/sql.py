"""SQL dialect — SQLAlchemy-specific capabilities.

These are IGNORED by other compilers (JSON Schema, Pydantic, etc.).

    from emergent.wire.axis.schema.dialects import sql

    @dataclass
    class User:
        email: Annotated[str, Unique, sql.Index("idx_email")]
        bio: Annotated[str, sql.Type("TEXT")]
        created_at: Annotated[datetime, sql.ServerDefault("CURRENT_TIMESTAMP")]
"""

from dataclasses import dataclass

from emergent.wire.axis.schema._universal import Capability


class SQLCapability(Capability):
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


@dataclass(frozen=True, slots=True)
class FullText(SQLCapability):
    """Full-text search index (Postgres/MySQL specific)."""
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


@dataclass(frozen=True, slots=True)
class OnUpdate(SQLCapability):
    """Value to set on UPDATE (SQL expression).

    Example:
        updated_at: Annotated[datetime, sql.OnUpdate("CURRENT_TIMESTAMP")]
    """
    expression: str


# ═══════════════════════════════════════════════════════════════════════════════
# Constraints
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Check(SQLCapability):
    """Custom CHECK constraint.

    Example:
        age: Annotated[int, sql.Check("age >= 0 AND age <= 150")]
    """
    expression: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class PrimaryKey(SQLCapability):
    """Explicit primary key (usually inferred from Identity)."""
    autoincrement: bool = True


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


# ═══════════════════════════════════════════════════════════════════════════════
# Table-Level
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TableName(SQLCapability):
    """Override table name."""
    name: str


@dataclass(frozen=True, slots=True)
class CompositeIndex(SQLCapability):
    """Index across multiple columns."""
    columns: tuple[str, ...]
    name: str | None = None
    unique: bool = False


@dataclass(frozen=True, slots=True)
class CompositeUnique(SQLCapability):
    """Unique constraint across multiple columns."""
    columns: tuple[str, ...]
    name: str | None = None


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
