"""Extended tests for SQLAlchemy storage — compile_expr, relational ops,
BoundSQLAlchemyStore ops, _python_type_to_sqlalchemy edge cases, no-identity error paths.

Covers lines 317-386 (expression compilation), 578-675 (relational operations),
897-1036 (BoundSQLAlchemyStore operations), type mapping edge cases, and identity error paths.

Uses in-memory SQLite via aiosqlite.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

import pytest
import pytest_asyncio
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from kungfu import Error, Nothing, Ok, Some

from emergent.wire.axis.schema._universal import Identity, MaxLen, Unique
from emergent.wire.axis.query._expr import (
    And,
    ArrayAll,
    ArrayAny,
    ArrayContains,
    ArrayOverlap,
    Between,
    Const,
    Contains,
    EndsWith,
    Eq,
    Expr,
    Field,
    Gt,
    ILike,
    In,
    IsNotNull,
    IsNull,
    JsonContains,
    JsonExtract,
    JsonHasKey,
    Like,
    Lt,
    Not,
    Or,
    Regex,
    StartsWith,
)
import emergent.wire.axis.storage.contrib._impls._sqlalchemy as _sa_mod
from emergent.wire.axis.storage.contrib._impls._sqlalchemy import (
    BoundSQLAlchemyStore,
    SQLAlchemyStorage,
    compile_expr,
    compile_model,
    store,
)

# Access private function via getattr for testing internal behavior;
# pyright disallows direct use of private names from other modules.
_python_type_to_sqlalchemy_fn = getattr(_sa_mod, "_python_type_to_sqlalchemy")


# ═══════════════════════════════════════════════════════════════════════════════
# Test Entities
# ═══════════════════════════════════════════════════════════════════════════════


class ExtTestBase(DeclarativeBase):
    pass


@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, Unique, MaxLen(128)]
    score: int = 0


# A second entity with Identity for extra_models tests in compile_expr
@dataclass
class Product:
    pid: Annotated[int, Identity]
    label: str
    price: int = 0


# Compile models once for expression tests
UserModel = compile_model(User, "ext_users", base=ExtTestBase)
ProductModel = compile_model(Product, "ext_products", base=ExtTestBase)


class _PgOnlyBase(DeclarativeBase):
    """Separate base for PostgreSQL-specific models.

    This base is NEVER used with create_all on SQLite, since JSONB/ARRAY
    types cannot be created there. Only used for compile_expr unit tests
    that verify expression objects without executing SQL.
    """

    pass


class JsonTestModel(_PgOnlyBase):
    """Model with JSONB and ARRAY columns for JSON/Array expression tests.

    Uses PostgreSQL-specific types because has_key, contains, overlap are
    PostgreSQL-only operations. Tests verify that compile_expr produces
    valid SA expression objects; they do not execute against a real DB.
    """

    __tablename__ = "json_test"
    id = Column(Integer, primary_key=True)
    data = Column(JSONB, nullable=True)
    tags = Column(PG_ARRAY(String), nullable=True)


# ═══════════════════════════════════════════════════════════════════════════════
# DB Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


UserStoreFact = store(User, "ext_users", base=ExtTestBase)


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine]:
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(ExtTestBase.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    async with AsyncSession(engine, expire_on_commit=False) as sess:
        yield sess


@pytest_asyncio.fixture
async def user_storage(session: AsyncSession) -> SQLAlchemyStorage[User]:
    return SQLAlchemyStorage(
        session=session,
        entity=User,
        tablename="ext_users",
        base=ExtTestBase,
    )


@pytest_asyncio.fixture
async def user_bound(session: AsyncSession) -> BoundSQLAlchemyStore[User]:
    return UserStoreFact.bind(session)


@pytest_asyncio.fixture
async def no_identity_storage(session: AsyncSession) -> SQLAlchemyStorage[User]:
    """A SQLAlchemyStorage where _identity_field is None, to test error paths."""
    stg = SQLAlchemyStorage(
        session=session,
        entity=User,
        tablename="ext_users",
        base=ExtTestBase,
    )
    # Override identity field to None to exercise no-identity error paths.
    # Using setattr because _identity_field is a protected attribute, accessed
    # here only to test the error path when no identity is defined.
    setattr(stg, "_identity_field", None)
    return stg


@pytest_asyncio.fixture
async def no_identity_bound(session: AsyncSession) -> BoundSQLAlchemyStore[User]:
    """A BoundSQLAlchemyStore where identity_field is None, to test error paths."""
    return BoundSQLAlchemyStore(
        session=session,
        entity=User,
        model=UserModel,
        identity_field=None,
    )


async def _seed_users(
    storage: SQLAlchemyStorage[User] | BoundSQLAlchemyStore[User],
    session: AsyncSession,
) -> list[User]:
    """Insert a handful of users for query tests."""
    users = [
        User(id=1, name="Alice", email="alice@example.com", score=100),
        User(id=2, name="Bob", email="bob@test.org", score=50),
        User(id=3, name="Charlie", email="charlie@example.com", score=0),
        User(id=4, name="Diana", email="diana@test.org", score=200),
        User(id=5, name="Eve", email="eve@example.com", score=75),
    ]
    for u in users:
        await storage.set(u)
    await session.commit()
    return users


# ═══════════════════════════════════════════════════════════════════════════════
# 1. compile_expr — expression compilation
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompileExprLogical:
    """Tests for And, Or, Not compilation."""

    def test_and_produces_clause(self) -> None:
        expr = And(
            Eq(Field("name"), Const("Alice")),
            Gt(Field("score"), Const(50)),
        )
        clause = compile_expr(expr, UserModel)
        sql_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "name" in sql_str
        assert "score" in sql_str

    def test_or_produces_clause(self) -> None:
        expr = Or(
            Eq(Field("name"), Const("Alice")),
            Eq(Field("name"), Const("Bob")),
        )
        clause = compile_expr(expr, UserModel)
        sql_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "OR" in sql_str.upper()

    def test_not_produces_clause(self) -> None:
        # Use an AND inside NOT so SA cannot simplify it away
        inner = And(
            Gt(Field("score"), Const(10)),
            Lt(Field("score"), Const(100)),
        )
        expr = Not(inner)
        clause = compile_expr(expr, UserModel)
        sql_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "NOT" in sql_str.upper()


class TestCompileExprCollection:
    """Tests for In, Contains, StartsWith, EndsWith."""

    def test_in_produces_clause(self) -> None:
        expr = In(Field("name"), ("Alice", "Bob"))
        clause = compile_expr(expr, UserModel)
        sql_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "IN" in sql_str.upper()

    def test_contains_produces_clause(self) -> None:
        expr = Contains(Field("email"), "example")
        clause = compile_expr(expr, UserModel)
        sql_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "example" in sql_str

    def test_startswith_produces_clause(self) -> None:
        expr = StartsWith(Field("name"), "Al")
        clause = compile_expr(expr, UserModel)
        sql_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "Al" in sql_str

    def test_endswith_produces_clause(self) -> None:
        expr = EndsWith(Field("email"), ".com")
        clause = compile_expr(expr, UserModel)
        sql_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert ".com" in sql_str


class TestCompileExprNull:
    """Tests for IsNull, IsNotNull."""

    def test_is_null_produces_clause(self) -> None:
        expr = IsNull(Field("name"))
        clause = compile_expr(expr, UserModel)
        sql_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "NULL" in sql_str.upper()

    def test_is_not_null_produces_clause(self) -> None:
        expr = IsNotNull(Field("name"))
        clause = compile_expr(expr, UserModel)
        sql_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        upper = sql_str.upper()
        assert "NOT" in upper and "NULL" in upper


class TestCompileExprRange:
    """Tests for Between."""

    def test_between_produces_clause(self) -> None:
        expr = Between(Field("score"), Const(10), Const(100))
        clause = compile_expr(expr, UserModel)
        sql_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "BETWEEN" in sql_str.upper()


class TestCompileExprPattern:
    """Tests for Like, ILike, Regex."""

    def test_like_produces_clause(self) -> None:
        expr = Like(Field("email"), "%@example.com")
        clause = compile_expr(expr, UserModel)
        sql_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "LIKE" in sql_str.upper()

    def test_ilike_produces_clause(self) -> None:
        expr = ILike(Field("email"), "%@EXAMPLE.COM")
        clause = compile_expr(expr, UserModel)
        assert clause is not None

    def test_regex_produces_clause(self) -> None:
        expr = Regex(Field("email"), r"^[\w]+@")
        clause = compile_expr(expr, UserModel)
        assert clause is not None


class TestCompileExprJson:
    """Tests for JsonExtract, JsonContains, JsonHasKey.

    These operations require a JSON-typed column, so we use JsonTestModel
    which has a JSON 'data' column.
    """

    def test_json_extract_produces_expression(self) -> None:
        expr = JsonExtract(Field("data"), "foo.bar")
        clause = compile_expr(expr, JsonTestModel)
        assert clause is not None

    def test_json_extract_single_key(self) -> None:
        expr = JsonExtract(Field("data"), "single")
        clause = compile_expr(expr, JsonTestModel)
        assert clause is not None

    def test_json_contains_produces_expression(self) -> None:
        expr = JsonContains(Field("data"), "value")
        clause = compile_expr(expr, JsonTestModel)
        assert clause is not None

    def test_json_has_key_produces_expression(self) -> None:
        expr = JsonHasKey(Field("data"), "key")
        clause = compile_expr(expr, JsonTestModel)
        assert clause is not None


class TestCompileExprArray:
    """Tests for ArrayContains, ArrayAny, ArrayAll, ArrayOverlap.

    These operations require a JSON/ARRAY-typed column, so we use JsonTestModel
    which has a JSON 'tags' column.
    """

    def test_array_contains_produces_expression(self) -> None:
        expr = ArrayContains(Field("tags"), "value")
        clause = compile_expr(expr, JsonTestModel)
        assert clause is not None

    def test_array_any_produces_expression(self) -> None:
        expr = ArrayAny(Field("tags"), ("a", "b"))
        clause = compile_expr(expr, JsonTestModel)
        assert clause is not None

    def test_array_all_produces_expression(self) -> None:
        expr = ArrayAll(Field("tags"), ("a", "b"))
        clause = compile_expr(expr, JsonTestModel)
        assert clause is not None

    def test_array_overlap_produces_expression(self) -> None:
        expr = ArrayOverlap(Field("tags"), ("a", "b"))
        clause = compile_expr(expr, JsonTestModel)
        assert clause is not None


class TestCompileExprEdgeCases:
    """Tests for unsupported expression, Field resolution across extra_models."""

    def test_unsupported_expr_raises_type_error(self) -> None:
        class FakeExpr(Expr):
            def evaluate(self, obj: object) -> object:
                return None

        with pytest.raises(TypeError, match="Unsupported expression type"):
            compile_expr(FakeExpr(), UserModel)

    def test_field_resolved_from_extra_model(self) -> None:
        # Field "label" exists on ProductModel, not UserModel
        expr = Field("label")
        clause = compile_expr(expr, UserModel, ProductModel)
        assert clause is not None

    def test_field_missing_from_all_models_raises(self) -> None:
        expr = Field("nonexistent_field_xyz")
        with pytest.raises(AttributeError):
            compile_expr(expr, UserModel)

    def test_const_returns_raw_value(self) -> None:
        expr = Const(42)
        result = compile_expr(expr, UserModel)
        assert result == 42

    def test_nested_and_or_not(self) -> None:
        """Compound expression: NOT (a AND (b OR c))."""
        expr = Not(
            And(
                Eq(Field("name"), Const("Alice")),
                Or(
                    Gt(Field("score"), Const(10)),
                    Lt(Field("score"), Const(0)),
                ),
            )
        )
        clause = compile_expr(expr, UserModel)
        sql_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "NOT" in sql_str.upper()


# ═══════════════════════════════════════════════════════════════════════════════
# 2. SQLAlchemyStorage relational operations
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_storage_find(
    user_storage: SQLAlchemyStorage[User], session: AsyncSession
) -> None:
    await _seed_users(user_storage, session)
    result = await user_storage.find(lambda u: u.score > 50)
    assert isinstance(result, Ok)
    names = {e.name for e in result.value}
    assert names == {"Alice", "Diana", "Eve"}


@pytest.mark.asyncio
async def test_storage_find_empty_result(
    user_storage: SQLAlchemyStorage[User], session: AsyncSession
) -> None:
    await _seed_users(user_storage, session)
    result = await user_storage.find(lambda u: u.score > 9999)
    assert isinstance(result, Ok)
    assert result.value == []


@pytest.mark.asyncio
async def test_storage_find_one_existing(
    user_storage: SQLAlchemyStorage[User], session: AsyncSession
) -> None:
    await _seed_users(user_storage, session)
    result = await user_storage.find_one(lambda u: u.name == "Bob")
    assert isinstance(result, Ok)
    assert isinstance(result.value, Some)
    assert result.value.value.email == "bob@test.org"


@pytest.mark.asyncio
async def test_storage_find_one_missing(
    user_storage: SQLAlchemyStorage[User], session: AsyncSession
) -> None:
    await _seed_users(user_storage, session)
    result = await user_storage.find_one(lambda u: u.name == "Nobody")
    assert isinstance(result, Ok)
    assert isinstance(result.value, Nothing)


@pytest.mark.asyncio
async def test_storage_count_all(
    user_storage: SQLAlchemyStorage[User], session: AsyncSession
) -> None:
    await _seed_users(user_storage, session)
    result = await user_storage.count()
    assert isinstance(result, Ok)
    assert result.value == 5


@pytest.mark.asyncio
async def test_storage_count_with_predicate(
    user_storage: SQLAlchemyStorage[User], session: AsyncSession
) -> None:
    await _seed_users(user_storage, session)
    result = await user_storage.count(lambda u: u.score >= 100)
    assert isinstance(result, Ok)
    assert result.value == 2  # Alice (100), Diana (200)


@pytest.mark.asyncio
async def test_storage_count_empty_table(
    user_storage: SQLAlchemyStorage[User],
) -> None:
    result = await user_storage.count()
    assert isinstance(result, Ok)
    assert result.value == 0


@pytest.mark.asyncio
async def test_storage_exists_true(
    user_storage: SQLAlchemyStorage[User], session: AsyncSession
) -> None:
    await _seed_users(user_storage, session)
    result = await user_storage.exists(1)
    assert isinstance(result, Ok)
    assert result.value is True


@pytest.mark.asyncio
async def test_storage_exists_false(
    user_storage: SQLAlchemyStorage[User], session: AsyncSession
) -> None:
    await _seed_users(user_storage, session)
    result = await user_storage.exists(999)
    assert isinstance(result, Ok)
    assert result.value is False


@pytest.mark.asyncio
async def test_storage_delete_where(
    user_storage: SQLAlchemyStorage[User], session: AsyncSession
) -> None:
    await _seed_users(user_storage, session)
    result = await user_storage.delete_where(lambda u: u.score < 60)
    assert isinstance(result, Ok)
    assert result.value == 2  # Bob (50), Charlie (0)
    await session.commit()

    remaining = await user_storage.count()
    assert isinstance(remaining, Ok)
    assert remaining.value == 3


@pytest.mark.asyncio
async def test_storage_delete_where_no_matches(
    user_storage: SQLAlchemyStorage[User], session: AsyncSession
) -> None:
    await _seed_users(user_storage, session)
    result = await user_storage.delete_where(lambda u: u.score > 9999)
    assert isinstance(result, Ok)
    assert result.value == 0


@pytest.mark.asyncio
async def test_storage_set_many(
    user_storage: SQLAlchemyStorage[User], session: AsyncSession
) -> None:
    users = [
        User(id=10, name="X", email="x@test.com", score=1),
        User(id=11, name="Y", email="y@test.com", score=2),
        User(id=12, name="Z", email="z@test.com", score=3),
    ]
    result = await user_storage.set_many(users)
    await session.commit()

    assert isinstance(result, Ok)
    assert len(result.value) == 3
    assert {u.name for u in result.value} == {"X", "Y", "Z"}


@pytest.mark.asyncio
async def test_storage_set_many_empty_list(
    user_storage: SQLAlchemyStorage[User], session: AsyncSession
) -> None:
    result = await user_storage.set_many([])
    await session.commit()
    assert isinstance(result, Ok)
    assert result.value == []


@pytest.mark.asyncio
async def test_storage_all(
    user_storage: SQLAlchemyStorage[User], session: AsyncSession
) -> None:
    await _seed_users(user_storage, session)
    result = await user_storage.all()
    assert isinstance(result, Ok)
    assert len(result.value) == 5


@pytest.mark.asyncio
async def test_storage_all_empty(
    user_storage: SQLAlchemyStorage[User],
) -> None:
    result = await user_storage.all()
    assert isinstance(result, Ok)
    assert result.value == []


# ═══════════════════════════════════════════════════════════════════════════════
# 3. BoundSQLAlchemyStore relational operations
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_bound_find(
    user_bound: BoundSQLAlchemyStore[User], session: AsyncSession
) -> None:
    await _seed_users(user_bound, session)
    result = await user_bound.find(lambda u: u.score > 50)
    assert isinstance(result, Ok)
    names = {e.name for e in result.value}
    assert names == {"Alice", "Diana", "Eve"}


@pytest.mark.asyncio
async def test_bound_find_one_existing(
    user_bound: BoundSQLAlchemyStore[User], session: AsyncSession
) -> None:
    await _seed_users(user_bound, session)
    result = await user_bound.find_one(lambda u: u.name == "Charlie")
    assert isinstance(result, Ok)
    assert isinstance(result.value, Some)
    assert result.value.value.score == 0


@pytest.mark.asyncio
async def test_bound_find_one_missing(
    user_bound: BoundSQLAlchemyStore[User], session: AsyncSession
) -> None:
    await _seed_users(user_bound, session)
    result = await user_bound.find_one(lambda u: u.name == "Nobody")
    assert isinstance(result, Ok)
    assert isinstance(result.value, Nothing)


@pytest.mark.asyncio
async def test_bound_count_all(
    user_bound: BoundSQLAlchemyStore[User], session: AsyncSession
) -> None:
    await _seed_users(user_bound, session)
    result = await user_bound.count()
    assert isinstance(result, Ok)
    assert result.value == 5


@pytest.mark.asyncio
async def test_bound_count_with_predicate(
    user_bound: BoundSQLAlchemyStore[User], session: AsyncSession
) -> None:
    await _seed_users(user_bound, session)
    result = await user_bound.count(lambda u: u.score == 0)
    assert isinstance(result, Ok)
    assert result.value == 1  # Charlie


@pytest.mark.asyncio
async def test_bound_exists_true(
    user_bound: BoundSQLAlchemyStore[User], session: AsyncSession
) -> None:
    await _seed_users(user_bound, session)
    result = await user_bound.exists(3)
    assert isinstance(result, Ok)
    assert result.value is True


@pytest.mark.asyncio
async def test_bound_exists_false(
    user_bound: BoundSQLAlchemyStore[User], session: AsyncSession
) -> None:
    await _seed_users(user_bound, session)
    result = await user_bound.exists(777)
    assert isinstance(result, Ok)
    assert result.value is False


@pytest.mark.asyncio
async def test_bound_delete_where(
    user_bound: BoundSQLAlchemyStore[User], session: AsyncSession
) -> None:
    await _seed_users(user_bound, session)
    result = await user_bound.delete_where(lambda u: u.score >= 100)
    assert isinstance(result, Ok)
    assert result.value == 2  # Alice (100), Diana (200)
    await session.commit()

    remaining = await user_bound.count()
    assert isinstance(remaining, Ok)
    assert remaining.value == 3


@pytest.mark.asyncio
async def test_bound_set_many(
    user_bound: BoundSQLAlchemyStore[User], session: AsyncSession
) -> None:
    users = [
        User(id=20, name="P", email="p@test.com", score=10),
        User(id=21, name="Q", email="q@test.com", score=20),
    ]
    result = await user_bound.set_many(users)
    await session.commit()

    assert isinstance(result, Ok)
    assert len(result.value) == 2


@pytest.mark.asyncio
async def test_bound_all(
    user_bound: BoundSQLAlchemyStore[User], session: AsyncSession
) -> None:
    await _seed_users(user_bound, session)
    result = await user_bound.all()
    assert isinstance(result, Ok)
    assert len(result.value) == 5
    ids = {u.id for u in result.value}
    assert ids == {1, 2, 3, 4, 5}


@pytest.mark.asyncio
async def test_bound_all_empty(
    user_bound: BoundSQLAlchemyStore[User],
) -> None:
    result = await user_bound.all()
    assert isinstance(result, Ok)
    assert result.value == []


# ═══════════════════════════════════════════════════════════════════════════════
# 4. _python_type_to_sqlalchemy — edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestPythonTypeToSqlalchemy:
    def test_int_returns_integer(self) -> None:
        assert _python_type_to_sqlalchemy_fn(int) is Integer

    def test_float_returns_float(self) -> None:
        assert _python_type_to_sqlalchemy_fn(float) is Float

    def test_bool_returns_boolean(self) -> None:
        assert _python_type_to_sqlalchemy_fn(bool) is Boolean

    def test_datetime_returns_datetime(self) -> None:
        assert _python_type_to_sqlalchemy_fn(datetime) is DateTime

    def test_str_without_max_length_returns_string_255(self) -> None:
        result = _python_type_to_sqlalchemy_fn(str)
        assert isinstance(result, String)
        assert result.length == 255

    def test_str_with_max_length_returns_string_n(self) -> None:
        result = _python_type_to_sqlalchemy_fn(str, max_length=64)
        assert isinstance(result, String)
        assert result.length == 64

    def test_type_override_returns_text(self) -> None:
        result = _python_type_to_sqlalchemy_fn(int, type_override="anything")
        assert result is Text

    def test_type_override_takes_precedence_over_known_type(self) -> None:
        result = _python_type_to_sqlalchemy_fn(str, max_length=128, type_override="col_override")
        assert result is Text

    def test_unknown_type_returns_text(self) -> None:
        result = _python_type_to_sqlalchemy_fn(bytes)
        assert result is Text

    def test_another_unknown_type_returns_text(self) -> None:
        result = _python_type_to_sqlalchemy_fn(list)
        assert result is Text


# ═══════════════════════════════════════════════════════════════════════════════
# 5. No identity field error paths
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_storage_get_no_identity_returns_error(
    no_identity_storage: SQLAlchemyStorage[User],
) -> None:
    result = await no_identity_storage.get("some_key")
    assert isinstance(result, Error)
    assert "No Identity field defined" in result.error.message


@pytest.mark.asyncio
async def test_storage_delete_no_identity_returns_error(
    no_identity_storage: SQLAlchemyStorage[User],
) -> None:
    result = await no_identity_storage.delete("some_key")
    assert isinstance(result, Error)
    assert "No Identity field defined" in result.error.message


@pytest.mark.asyncio
async def test_storage_exists_no_identity_returns_error(
    no_identity_storage: SQLAlchemyStorage[User],
) -> None:
    result = await no_identity_storage.exists("some_key")
    assert isinstance(result, Error)
    assert "No Identity field defined" in result.error.message


@pytest.mark.asyncio
async def test_bound_get_no_identity_returns_error(
    no_identity_bound: BoundSQLAlchemyStore[User],
) -> None:
    result = await no_identity_bound.get("some_key")
    assert isinstance(result, Error)
    assert "No Identity field defined" in result.error.message


@pytest.mark.asyncio
async def test_bound_delete_no_identity_returns_error(
    no_identity_bound: BoundSQLAlchemyStore[User],
) -> None:
    result = await no_identity_bound.delete("some_key")
    assert isinstance(result, Error)
    assert "No Identity field defined" in result.error.message


@pytest.mark.asyncio
async def test_bound_exists_no_identity_returns_error(
    no_identity_bound: BoundSQLAlchemyStore[User],
) -> None:
    result = await no_identity_bound.exists("some_key")
    assert isinstance(result, Error)
    assert "No Identity field defined" in result.error.message
