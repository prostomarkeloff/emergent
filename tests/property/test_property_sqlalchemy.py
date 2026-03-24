# pyright: reportPrivateUsage=false
"""Property tests for SQLAlchemy compilation target and expression compiler.

Tests the compile_sa pipeline: dataclass -> SA model, verifying column types,
constraints, primary keys, and expression compilation to SA clauses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, cast

import pytest

sa = pytest.importorskip("sqlalchemy")

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase

from emergent.wire.axis.schema._universal import (
    Identity,
    MaxLen,
    Min,
    Nullable,
    Unique,
)
from emergent.wire.axis.schema.dialects.sql import (
    Index,
    ServerDefault,
    Type as SQLType,
)
from emergent.wire.axis.query._expr import (
    And,
    Between,
    Const,
    Contains,
    EndsWith,
    Eq,
    Field,
    Ge,
    Gt,
    In,
    IsNotNull,
    IsNull,
    Le,
    Lt,
    Ne,
    Not,
    Or,
    StartsWith,
)
from emergent.wire.compile._phase import (
    Compilation,
    FieldCompilation,
    STORAGE_FIELD_PHASE,
)
from emergent.wire.compile.targets.sqlalchemy import (
    SA_PHASE,
    compile_expr,
    compile_sa,
    entity_to_model,
    model_to_entity,
)


# ---------------------------------------------------------------------------
# Test entities
# ---------------------------------------------------------------------------


class _TestBase(DeclarativeBase):  # noqa: F841
    """Isolated base so compiled models do not leak between test modules."""
    pass


_TEST_BASE_REF: type[DeclarativeBase] = _TestBase  # prevent reportUnusedClass


@dataclass
class User:
    id: Annotated[int, Identity]
    name: Annotated[str, MaxLen(100)]
    email: Annotated[str, Unique, MaxLen(255)]


@dataclass
class Article:
    id: Annotated[int, Identity]
    title: Annotated[str, MaxLen(200)]
    body: str
    published: bool = False
    views: int = 0


@dataclass
class Event:
    id: Annotated[int, Identity]
    name: str
    happened_at: datetime = datetime(2000, 1, 1)


@dataclass
class Profile:
    id: Annotated[int, Identity]
    bio: Annotated[str | None, Nullable] = None
    score: Annotated[float, Min(0)] = 0.0


@dataclass
class IndexedEntity:
    id: Annotated[int, Identity]
    email: Annotated[str, Index(), MaxLen(255)]


@dataclass
class TypeOverrideEntity:
    id: Annotated[int, Identity]
    data: Annotated[str, SQLType(Text)]


@dataclass
class ServerDefaultEntity:
    id: Annotated[int, Identity]
    created_at: Annotated[datetime, ServerDefault("CURRENT_TIMESTAMP")]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_bases: dict[str, type[DeclarativeBase]] = {}


def _fresh_base(name: str) -> type[DeclarativeBase]:
    """Create or return a fresh DeclarativeBase per logical test group."""
    if name not in _bases:

        class _B(DeclarativeBase):
            pass

        _bases[name] = _B
    return _bases[name]


def _compile(
    entity: type,
    tablename: str,
    base_name: str = "default",
) -> Compilation[object, DeclarativeBase]:
    base = _fresh_base(base_name)
    return compile_sa(entity, tablename, base=base)


def _get_columns(
    compiled: Compilation[object, DeclarativeBase],
) -> dict[str, Column[Any]]:
    """Return {name: Column} from the compiled model's __table__."""
    table = compiled.model.__table__  # type: ignore[attr-defined]
    return cast(dict[str, Column[Any]], {str(c.name): c for c in table.columns})


# ===========================================================================
# 1. Column presence and field name mapping
# ===========================================================================


class TestColumnPresence:
    """Compiled model has correct columns matching dataclass fields."""

    def test_user_has_all_columns(self) -> None:
        compiled = _compile(User, "t_user_cols", "col_presence_1")
        cols = _get_columns(compiled)
        assert set(cols.keys()) == {"id", "name", "email"}

    def test_article_has_all_columns(self) -> None:
        compiled = _compile(Article, "t_article_cols", "col_presence_2")
        cols = _get_columns(compiled)
        assert set(cols.keys()) == {"id", "title", "body", "published", "views"}

    def test_event_has_all_columns(self) -> None:
        compiled = _compile(Event, "t_event_cols", "col_presence_3")
        cols = _get_columns(compiled)
        assert set(cols.keys()) == {"id", "name", "happened_at"}

    def test_profile_has_all_columns(self) -> None:
        compiled = _compile(Profile, "t_profile_cols", "col_presence_4")
        cols = _get_columns(compiled)
        assert set(cols.keys()) == {"id", "bio", "score"}


# ===========================================================================
# 2. Identity -> primary key
# ===========================================================================


class TestIdentityPrimaryKey:
    """Identity annotation produces a primary_key column."""

    def test_user_id_is_primary_key(self) -> None:
        compiled = _compile(User, "t_user_pk", "pk_1")
        cols = _get_columns(compiled)
        assert cols["id"].primary_key is True

    def test_article_id_is_primary_key(self) -> None:
        compiled = _compile(Article, "t_article_pk", "pk_2")
        cols = _get_columns(compiled)
        assert cols["id"].primary_key is True

    def test_non_identity_field_is_not_pk(self) -> None:
        compiled = _compile(User, "t_user_no_pk", "pk_3")
        cols = _get_columns(compiled)
        assert cols["name"].primary_key is False

    def test_identity_field_name_in_compilation(self) -> None:
        compiled = _compile(User, "t_user_id_field", "pk_4")
        assert compiled.identity_field == "id"


# ===========================================================================
# 3. Unique constraint
# ===========================================================================


class TestUniqueConstraint:
    """Unique annotation produces unique=True on the column."""

    def test_email_is_unique(self) -> None:
        compiled = _compile(User, "t_user_uniq", "uniq_1")
        cols = _get_columns(compiled)
        assert cols["email"].unique is True

    def test_non_unique_field(self) -> None:
        compiled = _compile(User, "t_user_nouniq", "uniq_2")
        cols = _get_columns(compiled)
        assert cols["name"].unique is not True


# ===========================================================================
# 4. MaxLen(n) on str -> String(n)
# ===========================================================================


class TestMaxLenStringType:
    """MaxLen(n) on str fields compiles to String(n) column type."""

    def test_name_string_100(self) -> None:
        compiled = _compile(User, "t_user_maxlen", "maxlen_1")
        cols = _get_columns(compiled)
        col_type = cols["name"].type
        assert isinstance(col_type, String)
        assert col_type.length == 100

    def test_email_string_255(self) -> None:
        compiled = _compile(User, "t_user_maxlen2", "maxlen_2")
        cols = _get_columns(compiled)
        col_type = cols["email"].type
        assert isinstance(col_type, String)
        assert col_type.length == 255

    def test_title_string_200(self) -> None:
        compiled = _compile(Article, "t_article_maxlen", "maxlen_3")
        cols = _get_columns(compiled)
        col_type = cols["title"].type
        assert isinstance(col_type, String)
        assert col_type.length == 200


# ===========================================================================
# 5. Default type mapping (int -> Integer, bool -> Boolean, etc.)
# ===========================================================================


class TestDefaultTypeMapping:
    """Fields without explicit type override use the default SA type map."""

    def test_int_maps_to_integer(self) -> None:
        compiled = _compile(User, "t_user_types", "types_1")
        cols = _get_columns(compiled)
        assert isinstance(cols["id"].type, Integer)

    def test_str_without_maxlen_maps_to_text(self) -> None:
        compiled = _compile(Article, "t_article_types", "types_2")
        cols = _get_columns(compiled)
        assert isinstance(cols["body"].type, Text)

    def test_bool_maps_to_boolean(self) -> None:
        compiled = _compile(Article, "t_article_bool", "types_3")
        cols = _get_columns(compiled)
        assert isinstance(cols["published"].type, Boolean)

    def test_float_maps_to_float(self) -> None:
        compiled = _compile(Profile, "t_profile_float", "types_4")
        cols = _get_columns(compiled)
        assert isinstance(cols["score"].type, Float)

    def test_datetime_maps_to_datetime(self) -> None:
        compiled = _compile(Event, "t_event_dt", "types_5")
        cols = _get_columns(compiled)
        assert isinstance(cols["happened_at"].type, DateTime)


# ===========================================================================
# 6. Compilation is deterministic
# ===========================================================================


class TestDeterministic:
    """Same input always produces structurally identical output."""

    def test_same_field_count(self) -> None:
        c1 = _compile(User, "t_det_a", "det_1")
        c2 = _compile(User, "t_det_b", "det_2")
        assert len(c1.fields) == len(c2.fields)

    def test_same_field_names(self) -> None:
        c1 = _compile(User, "t_det_c", "det_3")
        c2 = _compile(User, "t_det_d", "det_4")
        names1 = [fc.name for fc in c1.fields]
        names2 = [fc.name for fc in c2.fields]
        assert names1 == names2

    def test_same_identity_field(self) -> None:
        c1 = _compile(User, "t_det_e", "det_5")
        c2 = _compile(User, "t_det_f", "det_6")
        assert c1.identity_field == c2.identity_field

    def test_same_column_types(self) -> None:
        c1 = _compile(User, "t_det_g", "det_7")
        c2 = _compile(User, "t_det_h", "det_8")
        cols1 = _get_columns(c1)
        cols2 = _get_columns(c2)
        for name in cols1:
            assert type(cols1[name].type) is type(cols2[name].type)

    def test_same_pk_flags(self) -> None:
        c1 = _compile(User, "t_det_i", "det_9")
        c2 = _compile(User, "t_det_j", "det_10")
        cols1 = _get_columns(c1)
        cols2 = _get_columns(c2)
        for name in cols1:
            assert cols1[name].primary_key == cols2[name].primary_key

    def test_same_unique_flags(self) -> None:
        c1 = _compile(User, "t_det_k", "det_11")
        c2 = _compile(User, "t_det_l", "det_12")
        cols1 = _get_columns(c1)
        cols2 = _get_columns(c2)
        for name in cols1:
            assert cols1[name].unique == cols2[name].unique


# ===========================================================================
# 7. Error cases
# ===========================================================================


class TestErrorCases:
    """Compilation rejects invalid inputs."""

    def test_non_dataclass_raises(self) -> None:
        class NotADataclass:
            pass

        with pytest.raises(TypeError, match="must be a dataclass"):
            compile_sa(NotADataclass, "t_fail")

    def test_no_identity_raises(self) -> None:
        @dataclass
        class NoId:
            name: str
            value: int

        with pytest.raises(TypeError, match="no field annotated with Identity"):
            compile_sa(NoId, "t_noid", base=_fresh_base("err_1"))


# ===========================================================================
# 8. Tablename and model class name
# ===========================================================================


class TestTableAndModelName:
    """Compiled model uses given tablename and generates a model class name."""

    def test_tablename_matches(self) -> None:
        compiled = _compile(User, "custom_users_table", "tblname_1")
        assert compiled.model.__tablename__ == "custom_users_table"  # type: ignore[attr-defined]

    def test_model_class_name(self) -> None:
        compiled = _compile(User, "t_model_name", "tblname_2")
        assert compiled.model.__name__ == "UserModel"


# ===========================================================================
# 9. Entity <-> Model mapping
# ===========================================================================


class TestEntityModelMapping:
    """entity_to_model and model_to_entity round-trip correctly."""

    def test_entity_to_model_creates_instance(self) -> None:
        compiled = _compile(User, "t_e2m", "mapping_1")
        user = User(id=1, name="Alice", email="alice@example.com")
        model = entity_to_model(user, compiled)
        assert model.name == "Alice"  # type: ignore[attr-defined]
        assert model.email == "alice@example.com"  # type: ignore[attr-defined]
        assert model.id == 1  # type: ignore[attr-defined]

    def test_model_to_entity_creates_dataclass(self) -> None:
        compiled = _compile(User, "t_m2e", "mapping_2")
        model = compiled.model(id=2, name="Bob", email="bob@example.com")
        entity = model_to_entity(model, compiled)
        assert isinstance(entity, User)
        assert entity.id == 2
        assert entity.name == "Bob"
        assert entity.email == "bob@example.com"

    def test_round_trip(self) -> None:
        compiled = _compile(User, "t_rt", "mapping_3")
        original = User(id=42, name="Charlie", email="c@example.com")
        model = entity_to_model(original, compiled)
        restored = model_to_entity(model, compiled)
        assert restored == original

    def test_entity_to_model_rejects_non_dataclass(self) -> None:
        compiled = _compile(User, "t_reject", "mapping_4")
        with pytest.raises(TypeError, match="must be a dataclass instance"):
            entity_to_model("not a dataclass", compiled)  # type: ignore[arg-type]


# ===========================================================================
# 10. SQL dialect capabilities (Index, ServerDefault, SQLType)
# ===========================================================================


class TestSQLDialectCapabilities:
    """SQL-specific capabilities are folded into the SA context."""

    def test_index_creates_indexed_column(self) -> None:
        compiled = _compile(IndexedEntity, "t_idx", "dialect_1")
        cols = _get_columns(compiled)
        assert cols["email"].index is True

    def test_type_override(self) -> None:
        compiled = _compile(TypeOverrideEntity, "t_type_ov", "dialect_2")
        cols = _get_columns(compiled)
        assert isinstance(cols["data"].type, Text)

    def test_server_default(self) -> None:
        compiled = _compile(ServerDefaultEntity, "t_srvdef", "dialect_3")
        cols = _get_columns(compiled)
        sd = cols["created_at"].server_default
        assert sd is not None


# ===========================================================================
# 11. STORAGE_FIELD_PHASE metadata
# ===========================================================================


class TestStorageFieldPhase:
    """STORAGE_FIELD_PHASE correctly marks identity and non-identity fields."""

    def test_identity_marked(self) -> None:
        compiled = _compile(User, "t_sf_id", "sf_1")
        for fc in compiled.fields:
            ctx = fc[STORAGE_FIELD_PHASE]
            if fc.name == "id":
                assert ctx.is_identity is True
            else:
                assert ctx.is_identity is False

    def test_all_fields_have_storage_phase(self) -> None:
        compiled = _compile(Article, "t_sf_all", "sf_2")
        for fc in compiled.fields:
            ctx = fc[STORAGE_FIELD_PHASE]
            assert ctx.field_name == fc.name


# ===========================================================================
# 12. SA_PHASE context inspection
# ===========================================================================


class TestSAPhaseContext:
    """SA_PHASE context carries field_name, field_type, and column_type."""

    def test_field_name_preserved(self) -> None:
        compiled = _compile(User, "t_sa_ctx", "sa_ctx_1")
        for fc in compiled.fields:
            ctx = fc[SA_PHASE]
            assert ctx.field_name == fc.name

    def test_field_type_preserved(self) -> None:
        compiled = _compile(Event, "t_sa_ctx2", "sa_ctx_2")
        for fc in compiled.fields:
            ctx = fc[SA_PHASE]
            if fc.name == "happened_at":
                assert ctx.field_type is datetime

    def test_column_type_set(self) -> None:
        compiled = _compile(User, "t_sa_ctx3", "sa_ctx_3")
        for fc in compiled.fields:
            ctx = fc[SA_PHASE]
            assert ctx.column_type is not None


# ===========================================================================
# 13. Expression compiler: simple comparisons
# ===========================================================================


class TestExprCompilerComparisons:
    """compile_expr translates comparison Expr nodes to SA column expressions."""

    def _compiled(self) -> Compilation[object, DeclarativeBase]:
        return _compile(User, "t_expr_cmp", "expr_cmp_1")

    def test_eq_compiles(self) -> None:
        compiled = self._compiled()
        expr = Eq(Field("name"), Const("Alice"))
        result = compile_expr(expr, compiled)
        sql_str = str(result.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[union-attr]
        assert "name" in sql_str
        assert "Alice" in sql_str

    def test_ne_compiles(self) -> None:
        compiled = self._compiled()
        expr = Ne(Field("name"), Const("Bob"))
        result = compile_expr(expr, compiled)
        sql_str = str(result.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[union-attr]
        assert "!=" in sql_str or "<>" in sql_str

    def test_gt_compiles(self) -> None:
        compiled = self._compiled()
        expr = Gt(Field("id"), Const(10))
        result = compile_expr(expr, compiled)
        sql_str = str(result.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[union-attr]
        assert ">" in sql_str
        assert "10" in sql_str

    def test_lt_compiles(self) -> None:
        compiled = self._compiled()
        expr = Lt(Field("id"), Const(5))
        result = compile_expr(expr, compiled)
        sql_str = str(result.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[union-attr]
        assert "<" in sql_str

    def test_ge_compiles(self) -> None:
        compiled = self._compiled()
        expr = Ge(Field("id"), Const(1))
        result = compile_expr(expr, compiled)
        sql_str = str(result.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[union-attr]
        assert ">=" in sql_str

    def test_le_compiles(self) -> None:
        compiled = self._compiled()
        expr = Le(Field("id"), Const(100))
        result = compile_expr(expr, compiled)
        sql_str = str(result.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[union-attr]
        assert "<=" in sql_str


# ===========================================================================
# 14. Expression compiler: logical operators
# ===========================================================================


class TestExprCompilerLogical:
    """compile_expr translates And, Or, Not to SA and_(), or_(), not_()."""

    def _compiled(self) -> Compilation[object, DeclarativeBase]:
        return _compile(User, "t_expr_logic", "expr_logic_1")

    def test_and_compiles(self) -> None:
        compiled = self._compiled()
        expr = And(
            Eq(Field("name"), Const("Alice")),
            Gt(Field("id"), Const(0)),
        )
        result = compile_expr(expr, compiled)
        sql_str = str(result.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[union-attr]
        assert "AND" in sql_str

    def test_or_compiles(self) -> None:
        compiled = self._compiled()
        expr = Or(
            Eq(Field("name"), Const("Alice")),
            Eq(Field("name"), Const("Bob")),
        )
        result = compile_expr(expr, compiled)
        sql_str = str(result.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[union-attr]
        assert "OR" in sql_str

    def test_not_compiles(self) -> None:
        compiled = self._compiled()
        expr = Not(Eq(Field("name"), Const("Alice")))
        result = compile_expr(expr, compiled)
        sql_str = str(result.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[union-attr]
        # SA renders NOT as either "NOT (...)" or with negation operator
        lower = sql_str.lower()
        assert "not" in lower or "!=" in lower or "<>" in lower

    def test_nested_and_or(self) -> None:
        compiled = self._compiled()
        expr = And(
            Or(
                Eq(Field("name"), Const("Alice")),
                Eq(Field("name"), Const("Bob")),
            ),
            Gt(Field("id"), Const(0)),
        )
        result = compile_expr(expr, compiled)
        sql_str = str(result.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[union-attr]
        assert "AND" in sql_str
        assert "OR" in sql_str


# ===========================================================================
# 15. Expression compiler: collection and pattern operators
# ===========================================================================


class TestExprCompilerCollectionOps:
    """compile_expr handles In, Contains, StartsWith, EndsWith."""

    def _compiled(self) -> Compilation[object, DeclarativeBase]:
        return _compile(User, "t_expr_coll", "expr_coll_1")

    def test_in_compiles(self) -> None:
        compiled = self._compiled()
        expr = In(Field("name"), ("Alice", "Bob"))
        result = compile_expr(expr, compiled)
        sql_str = str(result.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[union-attr]
        assert "IN" in sql_str

    def test_contains_compiles(self) -> None:
        compiled = self._compiled()
        expr = Contains(Field("email"), "@gmail")
        result = compile_expr(expr, compiled)
        sql_str = str(result.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[union-attr]
        lower = sql_str.lower()
        assert "like" in lower or "contains" in lower or "@gmail" in lower

    def test_startswith_compiles(self) -> None:
        compiled = self._compiled()
        expr = StartsWith(Field("name"), "Al")
        result = compile_expr(expr, compiled)
        sql_str = str(result.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[union-attr]
        lower = sql_str.lower()
        assert "like" in lower or "al" in lower.lower()

    def test_endswith_compiles(self) -> None:
        compiled = self._compiled()
        expr = EndsWith(Field("email"), ".com")
        result = compile_expr(expr, compiled)
        sql_str = str(result.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[union-attr]
        lower = sql_str.lower()
        assert "like" in lower or ".com" in lower


# ===========================================================================
# 16. Expression compiler: null checks
# ===========================================================================


class TestExprCompilerNullChecks:
    """compile_expr handles IsNull and IsNotNull."""

    def _compiled(self) -> Compilation[object, DeclarativeBase]:
        return _compile(Profile, "t_expr_null", "expr_null_1")

    def test_is_null_compiles(self) -> None:
        compiled = self._compiled()
        expr = IsNull(Field("bio"))
        result = compile_expr(expr, compiled)
        sql_str = str(result.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[union-attr]
        assert "IS NULL" in sql_str.upper() or "IS_NULL" in sql_str.upper()

    def test_is_not_null_compiles(self) -> None:
        compiled = self._compiled()
        expr = IsNotNull(Field("bio"))
        result = compile_expr(expr, compiled)
        sql_str = str(result.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[union-attr]
        upper = sql_str.upper()
        assert "IS NOT NULL" in upper or "IS_NOT_NULL" in upper or "NOT" in upper


# ===========================================================================
# 17. Expression compiler: Between
# ===========================================================================


class TestExprCompilerBetween:
    """compile_expr handles Between range expressions."""

    def _compiled(self) -> Compilation[object, DeclarativeBase]:
        return _compile(Profile, "t_expr_between", "expr_between_1")

    def test_between_compiles(self) -> None:
        compiled = self._compiled()
        expr = Between(Field("score"), Const(0.0), Const(100.0))
        result = compile_expr(expr, compiled)
        sql_str = str(result.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[union-attr]
        assert "BETWEEN" in sql_str.upper()


# ===========================================================================
# 18. Compilation result shape
# ===========================================================================


class TestCompilationShape:
    """Compilation result has correct structure and types."""

    def test_model_is_subclass_of_base(self) -> None:
        base = _fresh_base("shape_1")
        compiled = compile_sa(User, "t_shape_base", base=base)
        assert issubclass(compiled.model, base)

    def test_entity_type_preserved(self) -> None:
        compiled = _compile(User, "t_shape_ent", "shape_2")
        assert compiled.entity is User

    def test_fields_tuple_length(self) -> None:
        compiled = _compile(User, "t_shape_len", "shape_3")
        assert len(compiled.fields) == 3  # id, name, email

    def test_fields_are_field_compilation(self) -> None:
        compiled = _compile(User, "t_shape_fc", "shape_4")
        for fc in compiled.fields:
            assert isinstance(fc, FieldCompilation)
