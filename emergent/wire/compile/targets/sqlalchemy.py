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
from typing import Any, TypedDict, TypeGuard

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql.roles import DDLConstraintColumnRole

from emergent.wire.axis.schema._inspect import inspect_dataclass
from emergent.wire.axis._capability import (
    SQLAlchemyContext, SQLAlchemyCompilable,
    SQLAlchemyTableContext, SQLAlchemyTableCompilable,
    TableCheckSpec, TableConstraintSpec, TableIndexSpec,
    IndexElement,
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

type SATypeMap = Mapping[type, type]
type TableSchemaDict = dict[str, str]
type TableArgItem = Index | UniqueConstraint | CheckConstraint | TableSchemaDict
type TableArgs = tuple[TableArgItem, ...] | TableSchemaDict | None
type ModelAttrs = dict[str, Column[Any] | str | TableSchemaDict | Table | tuple[TableArgItem, ...]]
type ColumnKwargs = dict[str, str | int | bool | None]
type SAExprHandlers = dict[type, ExprHandler[Any]]
type SAExprHandlersRO = Mapping[type, ExprHandler[Any]]


class _SAColumnKwargs(TypedDict, total=False):
    """The Column(...) keyword vocabulary this compiler emits.

    Capabilities accumulate untyped column kwargs (``ColumnKwargs`` — a flat
    ``str → str|int|bool|None`` map); every key they set is a real
    ``Column.__init__`` parameter. This TypedDict re-types that flat map into
    the precise per-parameter types so the spread into ``Column(...)`` is
    checkable — SQLAlchemy's own ``**dialect_kwargs: Any`` tail can't be
    targeted by a heterogeneous ``**dict`` unpack.
    """
    name: str
    nullable: bool
    primary_key: bool
    unique: bool
    index: bool
    autoincrement: bool
    comment: str
    server_default: str
    onupdate: str


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


def _index_element(field: IndexElement) -> str | DDLConstraintColumnRole:
    """Narrow an `IndexElement` to what `Index(...)` accepts as a column arg.

    `IndexElement` is `str | ClauseElement`; SQLAlchemy's index-element argument
    is `str | Column | DDLConstraintColumnRole`. A SQL expression used as an
    index element (a column reference, `text(...)`, `col.desc()`, …) is always a
    `DDLConstraintColumnRole` at runtime — that is precisely the contract SA
    enforces — so the assert encodes a real invariant rather than widening.
    """
    if isinstance(field, str):
        return field
    assert isinstance(field, DDLConstraintColumnRole)
    return field


def _build_index(spec: TableIndexSpec) -> Index:
    """Build an `Index` from a `TableIndexSpec`.

    Opaque `dialect_kwargs` (e.g. `postgresql_using`/`postgresql_where`) are
    applied via `Index.kwargs` after construction — equivalent to passing them
    to the constructor's `**dialect_kw` tail, which a heterogeneous `**Mapping`
    unpack cannot statically target.
    """
    index = Index(
        spec.name,
        *(_index_element(f) for f in spec.fields),
        unique=spec.unique,
    )
    for key, value in spec.dialect_kwargs.items():
        index.kwargs[key] = value
    return index


def _build_table_args(
    table_indexes: tuple[TableIndexSpec, ...],
    table_constraints: tuple[TableConstraintSpec, ...],
    table_checks: tuple[TableCheckSpec, ...],
    schema: str | None,
) -> TableArgs:
    """Assemble `__table_args__` from table-level index/constraint/check specs.

    Columns are referenced by name (resolved against the table by SQLAlchemy).
    Returns a plain dict when only a schema is set, a tuple (optionally ending
    with the schema dict) when there are indexes/constraints/checks, or None.
    """
    items: list[TableArgItem] = [
        UniqueConstraint(*spec.fields, name=spec.name) for spec in table_constraints
    ]
    items.extend(
        CheckConstraint(spec.expression, name=spec.name) for spec in table_checks
    )
    items.extend(_build_index(spec) for spec in table_indexes)
    if not items:
        return {"schema": schema} if schema else None
    if schema:
        return (*items, {"schema": schema})
    return tuple(items)


def _str_kwarg(col_kwargs: ColumnKwargs, key: str) -> str | None:
    """Read a column kwarg as `str`, or None if absent / not a string."""
    value = col_kwargs.get(key)
    return value if isinstance(value, str) else None


def _bool_kwarg(col_kwargs: ColumnKwargs, key: str) -> bool | None:
    """Read a column kwarg as `bool`, or None if absent / not a bool."""
    value = col_kwargs.get(key)
    return value if isinstance(value, bool) else None


def _typed_column_kwargs(col_kwargs: ColumnKwargs) -> _SAColumnKwargs:
    """Re-type the flat column-kwarg map into `Column(...)`'s parameter types.

    Capabilities set each key to a real `Column.__init__` parameter; the values
    are `str`/`bool`. Pulling each known parameter out by name (with a value-type
    guard) lets the result spread into `Column(...)` without the
    heterogeneous-`**dict` mismatch a flat `str|int|bool|None` map would trigger.
    FK keys are removed by the caller before this runs.
    """
    typed: _SAColumnKwargs = {}
    if (name := _str_kwarg(col_kwargs, "name")) is not None:
        typed["name"] = name
    if (comment := _str_kwarg(col_kwargs, "comment")) is not None:
        typed["comment"] = comment
    if (server_default := _str_kwarg(col_kwargs, "server_default")) is not None:
        typed["server_default"] = server_default
    if (onupdate := _str_kwarg(col_kwargs, "onupdate")) is not None:
        typed["onupdate"] = onupdate
    if (nullable := _bool_kwarg(col_kwargs, "nullable")) is not None:
        typed["nullable"] = nullable
    if (primary_key := _bool_kwarg(col_kwargs, "primary_key")) is not None:
        typed["primary_key"] = primary_key
    if (unique := _bool_kwarg(col_kwargs, "unique")) is not None:
        typed["unique"] = unique
    if (index := _bool_kwarg(col_kwargs, "index")) is not None:
        typed["index"] = index
    if (autoincrement := _bool_kwarg(col_kwargs, "autoincrement")) is not None:
        typed["autoincrement"] = autoincrement
    return typed


def _new_model_type(
    model_name: str,
    model_base: type[DeclarativeBase],
    attrs: ModelAttrs,
) -> type[DeclarativeBase]:
    """Build a declarative model subclass via `type(...)`.

    `type(name, bases, ns)` is statically `type[Any]`; the `issubclass` assert
    re-narrows it to `type[DeclarativeBase]` — a real invariant, since
    `model_base` is itself a `DeclarativeBase` subclass.
    """
    cls = type(model_name, (model_base,), attrs)
    assert issubclass(cls, DeclarativeBase)
    return cls


def _assemble_model[T](
    compiled: list[FieldCompilation],
    entity: type[T],
    tablename: str,
    base: type[DeclarativeBase] | None,
    schema: str | None,
    table_indexes: tuple[TableIndexSpec, ...] = (),
    table_constraints: tuple[TableConstraintSpec, ...] = (),
    table_checks: tuple[TableCheckSpec, ...] = (),
) -> type[DeclarativeBase]:
    """Pure assembler: compiled fields → SA model class.

    Creates the ORM model class. No private attrs — metadata lives in Compilation.
    """
    model_base = base or _GeneratedBase
    model_name = f"{entity.__name__}Model"

    # Reuse existing model if table already compiled (idempotent compilation).
    # Match on the mapper's local table name — robust for classes declared via
    # `__tablename__` AND via `__table__` (a `__table__`-mapped class carries no
    # `__tablename__` attribute, so an attribute check would miss it).
    if tablename in model_base.metadata.tables:
        for mapper in model_base.registry.mappers:
            local = mapper.local_table
            # A mapped declarative class's local table is a `Table` (which has
            # `.name`); `isinstance` both supplies the attribute and stands in
            # for the runtime None-check (a non-`Table` FromClause never matches).
            if isinstance(local, Table) and local.name == tablename:
                return mapper.class_
        # The Table object is registered on this MetaData but no mapped class
        # carries it (SQLAlchemy's process-global mapper state can be polluted
        # across compilations — e.g. a same-named model replaced on a shared
        # base). Map the new class onto the *existing* Table instead of letting
        # `type(...)` redefine it, which would raise "Table already defined".
        reuse_attrs: ModelAttrs = {"__table__": model_base.metadata.tables[tablename]}
        return _new_model_type(model_name, model_base, reuse_attrs)

    attrs: ModelAttrs = {
        "__tablename__": tablename,
    }

    for fc in compiled:
        sa = fc[SA_PHASE]

        col_type = sa.column_type
        col_kwargs: ColumnKwargs = dict(sa.column_kwargs)
        col_kwargs.setdefault("nullable", fc.info.is_optional)

        # Extract FK config. None ondelete/onupdate → no referential-action clause
        # (bare FK == SQL default NO ACTION); we pass None through, never invent CASCADE.
        fk_target = col_kwargs.pop("fk_target", None)
        fk_ondelete = col_kwargs.pop("fk_ondelete", None)
        fk_onupdate = col_kwargs.pop("fk_onupdate", None)

        fk_instance: ForeignKey | None = None
        if fk_target is not None:
            fk_instance = ForeignKey(
                str(fk_target),
                ondelete=fk_ondelete if isinstance(fk_ondelete, str) else None,
                onupdate=fk_onupdate if isinstance(fk_onupdate, str) else None,
            )

        typed_kwargs = _typed_column_kwargs(col_kwargs)
        if fk_instance is not None:
            attrs[fc.name] = Column(col_type, fk_instance, **typed_kwargs)
        else:
            attrs[fc.name] = Column(col_type, **typed_kwargs)

    table_args = _build_table_args(table_indexes, table_constraints, table_checks, schema)
    if table_args is not None:
        attrs["__table_args__"] = table_args

    return _new_model_type(model_name, model_base, attrs)


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
    table_indexes: tuple[TableIndexSpec, ...] = ()
    table_constraints: tuple[TableConstraintSpec, ...] = ()
    table_checks: tuple[TableCheckSpec, ...] = ()
    if isinstance(fields, EntityCompilation):
        ec = fields
        fields_tuple = ec.fields
        # Read entity context for table name + table-level indexes/constraints/checks
        table_ctx = ec.get(SA_TABLE_FOLD)
        resolved_tablename = (
            tablename
            or (table_ctx.table_name if table_ctx is not None else None)
            or entity.__name__.lower()
        )
        if table_ctx is not None:
            table_indexes = table_ctx.indexes
            table_constraints = table_ctx.constraints
            table_checks = table_ctx.checks
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
        table_indexes, table_constraints, table_checks,
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


# Handler bodies access subclass-specific attributes (`.left`, `.field`, …),
# but `ExprHandler` types the node as base `Expr` (fold_expr dispatches on the
# concrete type via the map key). Each handler re-establishes the concrete type
# with `assert isinstance(...)` — a real invariant: fold_expr only calls a
# handler for the node type it is keyed under. SA column-op return types are
# genuinely untyped (`ColumnElement` from overloaded `==`/`<`/`in_`/…), so the
# result stays `Any` — the documented type of the whole compiler.


def _is_const(expr: Expr) -> TypeGuard[Const[Any]]:
    """Narrow Expr to `Const[Any]` — avoids `Const[Unknown]` from plain isinstance.

    Mirrors `query._coerce._is_const`: a query const holds an arbitrary Python
    value, so `Any` is its real element type, not a silencing widening.
    """
    return isinstance(expr, Const)


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

    def _field(n: Expr, _r: Callable[[Expr], Any]) -> Any:
        assert isinstance(n, Field)
        return resolve_field(n.name)

    def _const(n: Expr, _r: Callable[[Expr], Any]) -> Any:
        assert _is_const(n)
        return n.value

    def _cmp(op: Callable[[Any, Any], Any]) -> ExprHandler[Any]:
        def handler(n: Expr, r: Callable[[Expr], Any]) -> Any:
            assert isinstance(n, (Eq, Ne, Lt, Le, Gt, Ge))
            return op(r(n.left), r(n.right))
        return handler

    def _and(n: Expr, r: Callable[[Expr], Any]) -> Any:
        assert isinstance(n, And)
        return and_(r(n.left), r(n.right))

    def _or(n: Expr, r: Callable[[Expr], Any]) -> Any:
        assert isinstance(n, Or)
        return or_(r(n.left), r(n.right))

    def _not(n: Expr, r: Callable[[Expr], Any]) -> Any:
        assert isinstance(n, Not)
        return not_(r(n.operand))

    def _in(n: Expr, r: Callable[[Expr], Any]) -> Any:
        assert isinstance(n, In)
        return r(n.field).in_(n.values)

    def _contains(n: Expr, r: Callable[[Expr], Any]) -> Any:
        assert isinstance(n, Contains)
        return r(n.field).contains(n.substring)

    def _startswith(n: Expr, r: Callable[[Expr], Any]) -> Any:
        assert isinstance(n, StartsWith)
        return r(n.field).startswith(n.prefix)

    def _endswith(n: Expr, r: Callable[[Expr], Any]) -> Any:
        assert isinstance(n, EndsWith)
        return r(n.field).endswith(n.suffix)

    def _is_null(n: Expr, r: Callable[[Expr], Any]) -> Any:
        assert isinstance(n, IsNull)
        return r(n.field).is_(None)

    def _is_not_null(n: Expr, r: Callable[[Expr], Any]) -> Any:
        assert isinstance(n, IsNotNull)
        return r(n.field).isnot(None)

    def _between(n: Expr, r: Callable[[Expr], Any]) -> Any:
        assert isinstance(n, Between)
        return r(n.field).between(r(n.low), r(n.high))

    def _like(n: Expr, r: Callable[[Expr], Any]) -> Any:
        assert isinstance(n, Like)
        return r(n.field).like(n.pattern)

    def _ilike(n: Expr, r: Callable[[Expr], Any]) -> Any:
        assert isinstance(n, ILike)
        return r(n.field).ilike(n.pattern)

    def _regex(n: Expr, r: Callable[[Expr], Any]) -> Any:
        assert isinstance(n, Regex)
        return r(n.field).regexp_match(n.pattern)

    def _json_extract_h(n: Expr, r: Callable[[Expr], Any]) -> Any:
        assert isinstance(n, JsonExtract)
        return _json_extract(r(n.field), n.path)

    def _json_contains(n: Expr, r: Callable[[Expr], Any]) -> Any:
        assert isinstance(n, JsonContains)
        return r(n.field).contains(n.value)

    def _json_has_key(n: Expr, r: Callable[[Expr], Any]) -> Any:
        assert isinstance(n, JsonHasKey)
        return r(n.field).has_key(n.key)

    def _array_contains(n: Expr, r: Callable[[Expr], Any]) -> Any:
        assert isinstance(n, ArrayContains)
        return r(n.field).contains([n.value])

    def _array_any(n: Expr, r: Callable[[Expr], Any]) -> Any:
        assert isinstance(n, ArrayAny)
        return r(n.field).overlap(list(n.values))

    def _array_all(n: Expr, r: Callable[[Expr], Any]) -> Any:
        assert isinstance(n, ArrayAll)
        return r(n.field).contains(list(n.values))

    def _array_overlap(n: Expr, r: Callable[[Expr], Any]) -> Any:
        assert isinstance(n, ArrayOverlap)
        return r(n.field).overlap(list(n.values))

    return {
        # Leaf
        Field: _field,
        Const: _const,

        # Comparison
        Eq: _cmp(lambda l, r: l == r),
        Ne: _cmp(lambda l, r: l != r),
        Lt: _cmp(lambda l, r: l < r),
        Le: _cmp(lambda l, r: l <= r),
        Gt: _cmp(lambda l, r: l > r),
        Ge: _cmp(lambda l, r: l >= r),

        # Logical
        And: _and,
        Or: _or,
        Not: _not,

        # Collection
        In: _in,
        Contains: _contains,
        StartsWith: _startswith,
        EndsWith: _endswith,

        # Null
        IsNull: _is_null,
        IsNotNull: _is_not_null,

        # Range
        Between: _between,

        # Pattern
        Like: _like,
        ILike: _ilike,
        Regex: _regex,

        # JSON
        JsonExtract: _json_extract_h,
        JsonContains: _json_contains,
        JsonHasKey: _json_has_key,

        # Array
        ArrayContains: _array_contains,
        ArrayAny: _array_any,
        ArrayAll: _array_all,
        ArrayOverlap: _array_overlap,
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
