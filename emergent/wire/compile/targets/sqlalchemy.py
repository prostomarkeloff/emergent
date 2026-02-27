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

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
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
    CompilationPhase, compile_fields, EntityCompilation, FieldCompilation,
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
)


# ═══════════════════════════════════════════════════════════════════════════════
# Type Mapping + SA Phase
# ═══════════════════════════════════════════════════════════════════════════════


DEFAULT_SA_TYPE_MAP: Mapping[type, type] = {
    int: Integer,
    float: Float,
    bool: Boolean,
    str: Text,
    datetime: DateTime,
}


def make_sa_initial(
    type_map: Mapping[type, type] = DEFAULT_SA_TYPE_MAP,
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
            if hasattr(mapper.class_, '__tablename__') and mapper.class_.__tablename__ == tablename:
                return mapper.class_

    attrs: dict[str, Column[object] | str | dict[str, str]] = {
        "__tablename__": tablename,  # type: ignore[dict-item]
    }

    if schema:
        attrs["__table_args__"] = {"schema": schema}  # type: ignore[assignment]

    for fc in compiled:
        sa = fc[SA_PHASE]

        col_type = sa.column_type
        col_kwargs: dict[str, str | int | bool | None] = dict(sa.column_kwargs)
        col_kwargs.setdefault("nullable", fc.info.is_optional)

        # Extract FK config
        fk_target = col_kwargs.pop("fk_target", None)
        fk_ondelete = col_kwargs.pop("fk_ondelete", None)
        fk_onupdate = col_kwargs.pop("fk_onupdate", None)

        fk_instance: ForeignKey | None = None
        if fk_target is not None:
            fk_instance = ForeignKey(
                fk_target,
                ondelete=str(fk_ondelete or "CASCADE"),
                onupdate=str(fk_onupdate or "CASCADE"),
            )

        if fk_instance is not None:
            attrs[fc.name] = Column(col_type, fk_instance, **col_kwargs)  # type: ignore[arg-type]
        else:
            attrs[fc.name] = Column(col_type, **col_kwargs)  # type: ignore[arg-type]

    model_name = f"{entity.__name__}Model"
    return type(model_name, (model_base,), attrs)  # type: ignore[return-value]


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


def compile_expr(
    expr: Expr,
    compiled: Compilation[object, DeclarativeBase],
    *extra: Compilation[object, DeclarativeBase],
) -> object:
    """Compile query Expr to SQLAlchemy column expression.

    Applies universal coerce_expr (to_storage from STORAGE_FIELD_PHASE) before SA translation.
    """
    expr = coerce_expr(expr, compiled.fields)
    return _compile_expr_raw(expr, compiled.model, *(c.model for c in extra))


def _compile_expr_raw(
    expr: Expr,
    model: type[DeclarativeBase],
    *extra_models: type[DeclarativeBase],
) -> object:
    """Raw Expr → SA expression compiler. No coercion — pure translation."""
    match expr:
        case Field(name=name):
            if hasattr(model, name):
                return getattr(model, name)
            for m in extra_models:
                if hasattr(m, name):
                    return getattr(m, name)
            return getattr(model, name)  # raises AttributeError

        case Const(value=value):
            return value

        case Eq(left=left, right=right):
            return _compile_expr_raw(left, model, *extra_models) == _compile_expr_raw(right, model, *extra_models)

        case Ne(left=left, right=right):
            return _compile_expr_raw(left, model, *extra_models) != _compile_expr_raw(right, model, *extra_models)

        case Lt(left=left, right=right):
            return _compile_expr_raw(left, model, *extra_models) < _compile_expr_raw(right, model, *extra_models)

        case Le(left=left, right=right):
            return _compile_expr_raw(left, model, *extra_models) <= _compile_expr_raw(right, model, *extra_models)

        case Gt(left=left, right=right):
            return _compile_expr_raw(left, model, *extra_models) > _compile_expr_raw(right, model, *extra_models)

        case Ge(left=left, right=right):
            return _compile_expr_raw(left, model, *extra_models) >= _compile_expr_raw(right, model, *extra_models)

        case And(left=left, right=right):
            from sqlalchemy import and_
            return and_(_compile_expr_raw(left, model, *extra_models), _compile_expr_raw(right, model, *extra_models))

        case Or(left=left, right=right):
            from sqlalchemy import or_
            return or_(_compile_expr_raw(left, model, *extra_models), _compile_expr_raw(right, model, *extra_models))

        case Not(operand=operand):
            from sqlalchemy import not_
            return not_(_compile_expr_raw(operand, model, *extra_models))

        case In(field=field, values=values):
            return _compile_expr_raw(field, model, *extra_models).in_(values)  # type: ignore[union-attr]

        case Contains(field=field, substring=substring):
            return _compile_expr_raw(field, model, *extra_models).contains(substring)  # type: ignore[union-attr]

        case StartsWith(field=field, prefix=prefix):
            return _compile_expr_raw(field, model, *extra_models).startswith(prefix)  # type: ignore[union-attr]

        case EndsWith(field=field, suffix=suffix):
            return _compile_expr_raw(field, model, *extra_models).endswith(suffix)  # type: ignore[union-attr]

        case IsNull(field=field):
            return _compile_expr_raw(field, model, *extra_models).is_(None)  # type: ignore[union-attr]

        case IsNotNull(field=field):
            return _compile_expr_raw(field, model, *extra_models).isnot(None)  # type: ignore[union-attr]

        case Between(field=field, low=low, high=high):
            return _compile_expr_raw(field, model, *extra_models).between(  # type: ignore[union-attr]
                _compile_expr_raw(low, model, *extra_models), _compile_expr_raw(high, model, *extra_models)
            )

        case Like(field=field, pattern=pattern):
            return _compile_expr_raw(field, model, *extra_models).like(pattern)  # type: ignore[union-attr]

        case ILike(field=field, pattern=pattern):
            return _compile_expr_raw(field, model, *extra_models).ilike(pattern)  # type: ignore[union-attr]

        case Regex(field=field, pattern=pattern):
            return _compile_expr_raw(field, model, *extra_models).regexp_match(pattern)  # type: ignore[union-attr]

        case JsonExtract(field=field, path=path):
            col = _compile_expr_raw(field, model, *extra_models)
            for key in path.split("."):
                col = col[key]  # type: ignore[index]
            return col

        case JsonContains(field=field, value=value):
            return _compile_expr_raw(field, model, *extra_models).contains(value)  # type: ignore[union-attr]

        case JsonHasKey(field=field, key=key):
            return _compile_expr_raw(field, model, *extra_models).has_key(key)  # type: ignore[union-attr]

        case ArrayContains(field=field, value=value):
            return _compile_expr_raw(field, model, *extra_models).contains([value])  # type: ignore[union-attr]

        case ArrayAny(field=field, values=values):
            return _compile_expr_raw(field, model, *extra_models).overlap(list(values))  # type: ignore[union-attr]

        case ArrayAll(field=field, values=values):
            return _compile_expr_raw(field, model, *extra_models).contains(list(values))  # type: ignore[union-attr]

        case ArrayOverlap(field=field, values=values):
            return _compile_expr_raw(field, model, *extra_models).overlap(list(values))  # type: ignore[union-attr]

        case _:
            raise TypeError(f"Unsupported expression type: {type(expr)}")


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
