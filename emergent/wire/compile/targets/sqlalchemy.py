"""SQLAlchemy compilation target — dataclass → SA model + typed Compilation.

Thin assembler over compile_fields — same pattern as to_pydantic.

    from emergent.wire.compile.targets import sqlalchemy as sa

    compiled = sa.compile_sa(User, "users")
    where = sa.compile_expr(expr, compiled)
    model = sa.entity_to_model(user, compiled)
    entity = sa.model_to_entity(row, compiled)

Requires: sqlalchemy[asyncio]
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    Text,
)
from sqlalchemy.orm import DeclarativeBase

from emergent.wire.axis.schema._inspect import inspect_dataclass
from emergent.wire.axis._capability import (
    SQLAlchemyContext, SQLAlchemyCompilable,
    SQLAlchemyTableContext, SQLAlchemyTableCompilable,
)
from collections.abc import Sequence

from emergent.wire.compile._phase import (
    CompilationPhase, EntityCompilation, FieldCompilation,
    Compilation, SchemaCompiler,
    STORAGE_FIELD_PHASE, to_storage_dict, from_storage, coerce_expr,
)
from emergent.wire.compile._core import Axes
from emergent.wire.axis.query._expr import (
    Expr,
    Field,
    Const,
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
    And,
    Or,
    Not,
    In,
    Contains,
    StartsWith,
    EndsWith,
    IsNull,
    IsNotNull,
    Between,
    Like,
    ILike,
    Regex,
    JsonExtract,
    JsonContains,
    JsonHasKey,
    ArrayContains,
    ArrayAny,
    ArrayAll,
    ArrayOverlap,
    ExprHandler,
    fold_expr,
)

from typing import Protocol, runtime_checkable

type SATypeMap = Mapping[type, type]
type ModelAttrs = dict[str, Column[Any] | str | dict[str, str]]
type ColumnKwargs = dict[str, str | int | bool | None]
type SAExprHandlers = dict[type, ExprHandler[Any]]
type SAExprHandlersRO = Mapping[type, ExprHandler[Any]]


@runtime_checkable
class _HasTablename(Protocol):
    __tablename__: str


# ═══════════════════════════════════════════════════════════════════════════════
# Type Mapping + SA Phase
# ═══════════════════════════════════════════════════════════════════════════════


DEFAULT_SA_TYPE_MAP: SATypeMap = {
    int: Integer,
    float: Float,
    bool: Boolean,
    str: Text,
    bytes: LargeBinary,
    datetime: DateTime,
}


def make_sa_initial(
    type_map: SATypeMap = DEFAULT_SA_TYPE_MAP,
) -> Callable[[str, type], SQLAlchemyContext]:
    """Factory for SA initial function with custom type map.

    Users create custom SA phases with extended type support::

        from sqlalchemy import JSON
        my_map = {**DEFAULT_SA_TYPE_MAP, dict: JSON}
        my_sa_phase = CompilationPhase(SQLAlchemyContext, SQLAlchemyCompilable, make_sa_initial(my_map))
    """
    def _initial(name: str, field_type: type) -> SQLAlchemyContext:
        col_type = type_map.get(field_type, Text)
        return SQLAlchemyContext(
            field_name=name, field_type=field_type,
            column_type=col_type, type_map=type_map,
        )
    return _initial


# Backward compat alias
SA_TYPE_MAP = DEFAULT_SA_TYPE_MAP

_sa_initial = make_sa_initial()


from emergent.wire.compile._phase import EntityFold

SA_TABLE_FOLD: EntityFold[SQLAlchemyTableContext] = EntityFold(
    SQLAlchemyTableContext, SQLAlchemyTableCompilable,
    lambda name: SQLAlchemyTableContext(class_name=name),
)

SA_PHASE: CompilationPhase[SQLAlchemyContext] = CompilationPhase(
    SQLAlchemyContext, SQLAlchemyCompilable, _sa_initial,
    entity=SA_TABLE_FOLD,
)

SA_PHASES = (SA_PHASE, STORAGE_FIELD_PHASE)
SA_SCHEMA = SchemaCompiler(phases=SA_PHASES)


# ═══════════════════════════════════════════════════════════════════════════════
# Model Assembler (internal)
# ═══════════════════════════════════════════════════════════════════════════════


class _GeneratedBase(DeclarativeBase):
    """Base class for generated models."""
    pass


def _assemble_model[T](
    compiled: list[FieldCompilation],
    entity: type[T],
    tablename: str,
    base: type[DeclarativeBase] | None,
    schema: str | None,
) -> type[DeclarativeBase]:
    """Pure assembler: compiled fields → SA model class.

    Creates the ORM model class. No private attrs — metadata lives in Compilation.
    """
    model_base = base or _GeneratedBase

    # Reuse existing model if table already compiled
    if tablename in model_base.metadata.tables:
        for mapper in model_base.registry.mappers:
            mapped = mapper.class_
            if isinstance(mapped, _HasTablename) and mapped.__tablename__ == tablename:
                return mapper.class_

    attrs: ModelAttrs = {
        "__tablename__": tablename,
    }

    if schema:
        attrs["__table_args__"] = {"schema": schema}

    for fc in compiled:
        sa = fc[SA_PHASE]

        col_type = sa.column_type
        col_kwargs: ColumnKwargs = dict(sa.column_kwargs)
        col_kwargs.setdefault("nullable", fc.info.is_optional)

        # Extract FK config
        fk_target = col_kwargs.pop("fk_target", None)
        fk_ondelete = col_kwargs.pop("fk_ondelete", None)
        fk_onupdate = col_kwargs.pop("fk_onupdate", None)

        fk_instance: ForeignKey | None = None
        if fk_target is not None:
            fk_instance = ForeignKey(
                str(fk_target),
                ondelete=str(fk_ondelete or "CASCADE"),
                onupdate=str(fk_onupdate or "CASCADE"),
            )

        if fk_instance is not None:
            attrs[fc.name] = Column(col_type, fk_instance, **col_kwargs)
        else:
            attrs[fc.name] = Column(col_type, **col_kwargs)

    model_name = f"{entity.__name__}Model"
    return type(model_name, (model_base,), attrs)


# ═══════════════════════════════════════════════════════════════════════════════
# compile_sa — typed compilation entry point
# ═══════════════════════════════════════════════════════════════════════════════


def assemble_sa[T](
    entity: type[T],
    fields: EntityCompilation | Sequence[FieldCompilation],
    tablename: str | None = None,
    base: type[DeclarativeBase] | None = None,
    schema: str | None = None,
) -> Compilation[T, DeclarativeBase]:
    """Assemble SA Compilation from compiled fields.

    Accepts EntityCompilation (from SchemaCompiler.compile()) or
    a sequence of FieldCompilation (from compile_fields()).

    When EntityCompilation is provided, reads table_name from
    SQLAlchemyTableContext (set by @schema_meta(SchemaName(...))).
    Explicit tablename parameter overrides entity context.

    Use with SchemaCompiler for composable compilation::

        compiler = SA_SCHEMA + CONSTRAINTS_SCHEMA
        ec = compiler.compile(User, axes)
        sa_compiled = assemble_sa(User, ec)
    """
    if isinstance(fields, EntityCompilation):
        ec = fields
        fields_tuple = ec.fields
        # Read entity context for table name
        table_ctx = ec.get(SA_TABLE_FOLD)
        resolved_tablename = (
            tablename
            or (table_ctx.table_name if table_ctx is not None else None)
            or entity.__name__.lower()
        )
    else:
        fields_tuple = tuple(fields)
        resolved_tablename = tablename or entity.__name__.lower()

    has_identity = any(
        fc[STORAGE_FIELD_PHASE].is_identity for fc in fields_tuple
    )
    if not has_identity:
        raise TypeError(
            f"{entity.__name__} has no field annotated with Identity — "
            f"SQLAlchemy requires a primary key"
        )

    model_class = _assemble_model(
        list(fields_tuple), entity, resolved_tablename, base, schema,
    )
    return Compilation(model=model_class, entity=entity, fields=fields_tuple)


def compile_sa[T](
    entity: type[T],
    tablename: str,
    base: type[DeclarativeBase] | None = None,
    schema: str | None = None,
) -> Compilation[T, DeclarativeBase]:
    """Compile entity to SA — thin assembler over SchemaCompiler + assemble_sa.

    Returns typed Compilation with model and per-field storage metadata.
    All storage info (identity, coercion) lives on STORAGE_FIELD_PHASE — one fold.

        compiled = compile_sa(User, "users")
        compiled.model           # type[DeclarativeBase]
        compiled.identity_field  # "id"
    """
    if not dataclasses.is_dataclass(entity):
        raise TypeError(f"{entity} must be a dataclass")

    axes = Axes(schema=inspect_dataclass)
    ec = SA_SCHEMA.compile(entity, axes)
    return assemble_sa(entity, ec, tablename, base, schema)


def compile_model[T](
    entity: type[T],
    tablename: str,
    base: type[DeclarativeBase] | None = None,
    schema: str | None = None,
) -> type[DeclarativeBase]:
    """Backward compat — prefer compile_sa.

    Returns raw SA model class. Compilation metadata is lost.
    """
    return compile_sa(entity, tablename, base, schema).model


# ═══════════════════════════════════════════════════════════════════════════════
# Expression Compiler
# ═══════════════════════════════════════════════════════════════════════════════


def compile_expr[T](
    expr: Expr,
    compiled: Compilation[T, DeclarativeBase],
    # extra compilations may be for different entity types (e.g. JOIN targets);
    # Any for entity type is unavoidable here — we only use .model and .fields.
    *extra: Compilation[Any, DeclarativeBase],
) -> Any:
    """Compile query Expr to SQLAlchemy column expression.

    Applies universal coerce_expr (to_storage from STORAGE_FIELD_PHASE) before SA translation.
    """
    expr = coerce_expr(expr, compiled.fields)
    return _compile_expr_raw(expr, compiled.model, *(c.model for c in extra))


def _make_sa_expr_handlers(
    model: type[DeclarativeBase],
    *extra_models: type[DeclarativeBase],
) -> SAExprHandlers:
    """Build handler map for Expr → SA expression. Closures capture model.

    Open-world: callers can extend the returned map with custom Expr handlers.
    """
    from sqlalchemy import and_, or_, not_

    def resolve_field(name: str) -> Any:
        if hasattr(model, name):
            return getattr(model, name)
        for m in extra_models:
            if hasattr(m, name):
                return getattr(m, name)
        return getattr(model, name)  # raises AttributeError

    # Any is unavoidable here: SA column objects use __lt__/__le__/__gt__/__ge__
    # overloads returning ColumnElement, not bool. No static type captures this
    # without coupling to SA internals.
    def _cmp(op: Callable[[Any, Any], Any]) -> ExprHandler[Any]:
        def handler(n: Expr, r: Callable[[Expr], Any]) -> Any:
            return op(r(n.left), r(n.right))
        return handler

    return {
        # Leaf
        Field: lambda n, _r: resolve_field(n.name),
        Const: lambda n, _r: n.value,

        # Comparison
        Eq: _cmp(lambda l, r: l == r),
        Ne: _cmp(lambda l, r: l != r),
        Lt: _cmp(lambda l, r: l < r),
        Le: _cmp(lambda l, r: l <= r),
        Gt: _cmp(lambda l, r: l > r),
        Ge: _cmp(lambda l, r: l >= r),

        # Logical
        And: lambda n, r: and_(r(n.left), r(n.right)),
        Or: lambda n, r: or_(r(n.left), r(n.right)),
        Not: lambda n, r: not_(r(n.operand)),

        # Collection
        In: lambda n, r: r(n.field).in_(n.values),
        Contains: lambda n, r: r(n.field).contains(n.substring),
        StartsWith: lambda n, r: r(n.field).startswith(n.prefix),
        EndsWith: lambda n, r: r(n.field).endswith(n.suffix),

        # Null
        IsNull: lambda n, r: r(n.field).is_(None),
        IsNotNull: lambda n, r: r(n.field).isnot(None),

        # Range
        Between: lambda n, r: r(n.field).between(r(n.low), r(n.high)),

        # Pattern
        Like: lambda n, r: r(n.field).like(n.pattern),
        ILike: lambda n, r: r(n.field).ilike(n.pattern),
        Regex: lambda n, r: r(n.field).regexp_match(n.pattern),

        # JSON
        JsonExtract: lambda n, r: _json_extract(r(n.field), n.path),
        JsonContains: lambda n, r: r(n.field).contains(n.value),
        JsonHasKey: lambda n, r: r(n.field).has_key(n.key),

        # Array
        ArrayContains: lambda n, r: r(n.field).contains([n.value]),
        ArrayAny: lambda n, r: r(n.field).overlap(list(n.values)),
        ArrayAll: lambda n, r: r(n.field).contains(list(n.values)),
        ArrayOverlap: lambda n, r: r(n.field).overlap(list(n.values)),
    }


def _json_extract(col: Any, path: str) -> Any:
    """Navigate JSON path on SA column."""
    # Any unavoidable: SA column's __getitem__ returns ColumnElement
    # which has no static type accessible without coupling to SA internals.
    result: Any = col
    for key in path.split("."):
        result = result[key]
    return result


def _compile_expr_raw(
    expr: Expr,
    model: type[DeclarativeBase],
    *extra_models: type[DeclarativeBase],
    handlers: SAExprHandlersRO | None = None,
) -> Any:
    """Raw Expr → SA expression compiler. No coercion — pure translation.

    Open-world via fold_expr: pass handlers to extend with custom Expr types,
    or use _make_sa_expr_handlers() to get the built-in map and extend it.
    """
    h = handlers if handlers is not None else _make_sa_expr_handlers(model, *extra_models)
    return fold_expr(expr, h)


# ═══════════════════════════════════════════════════════════════════════════════
# Entity <-> Model Mapping
# ═══════════════════════════════════════════════════════════════════════════════


def entity_to_model[T](entity: T, compiled: Compilation[T, DeclarativeBase]) -> DeclarativeBase:
    """Convert dataclass entity to SQLAlchemy model instance.

    Thin wrapper: universal to_storage_dict + SA model constructor.
    """
    if not dataclasses.is_dataclass(entity):
        raise TypeError(f"{entity} must be a dataclass instance")
    return compiled.model(**to_storage_dict(entity, compiled.fields))


def model_to_entity[T](model: DeclarativeBase, compiled: Compilation[T, DeclarativeBase]) -> T:
    """Convert SQLAlchemy model instance to dataclass entity.

    Thin wrapper: universal from_storage + getattr as getter.
    """
    if not dataclasses.is_dataclass(compiled.entity):
        raise TypeError(f"{compiled.entity} must be a dataclass")
    return from_storage(lambda n: getattr(model, n), compiled.entity, compiled.fields)


__all__ = (
    # Type mapping
    "SA_TYPE_MAP",
    # Phases
    "SA_PHASE",
    "SA_PHASES",
    # Schema compiler
    "SA_SCHEMA",
    # Assembler (composable — use with SchemaCompiler)
    "assemble_sa",
    # Compilation (thin wrappers — backwards-compat)
    "compile_sa",
    "compile_model",
    # Expression compiler
    "compile_expr",
    # Entity <-> Model mapping
    "entity_to_model",
    "model_to_entity",
)
