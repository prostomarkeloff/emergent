"""Tests for all code examples in docs/tutorial/25-verify-and-explain.md.

Each test corresponds to a code block in the tutorial, verifying it actually works.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Annotated, Protocol, runtime_checkable

import pytest

from emergent.wire.axis.schema import Min, Max, Identity, ReadOnly, Nullable, Sensitive, Unique
from emergent.wire.axis.schema._universal import SchemaAxisCapability
from emergent.wire.axis.schema._inspect import inspect_type, FieldInfo
from emergent.wire.axis.schema._explain import explain_schema, schema_dict
from emergent.wire.axis.surface._explain import explain_application, application_dict, SURFACE_EXPLAIN
from emergent.wire.axis.query._explain import RELATIONAL_EXPLAIN_DIALECT
from emergent.wire.axis.query._contexts import QueryPhase
from emergent.wire.axis.query import (
    Filter, OrderBy, Limit, Offset, GroupBy, Having, Aggregate, Distinct,
    relational,
)
from emergent.wire.compile import Axes
from emergent.wire.compile._phase import CompilationPhase, SchemaCompiler, FASTAPI_SCHEMA
from emergent.wire.compile._explain import explain as explain_trace, explain_field as explain_trace_field
from emergent.wire.verify import (
    verify, verify_raising, Severity, Issue, VerificationError,
    VERIFY_PHASES, VERIFY_SCHEMA, NUMERIC_VERIFY_PHASE,
    NumericVerifyCtx, SemanticsVerifyCtx,
)


# ─── Section: "Using verify in practice" ─────────────────────────────────────


@dataclass
class Account:
    id: Annotated[int, Identity]
    balance: Annotated[float, Min(0), Max(-1)]  # impossible range
    name: Annotated[str, ReadOnly]


def test_verify_raising_catches_impossible_range():
    with pytest.raises(VerificationError) as exc_info:
        verify_raising(Account)
    assert any(i.field == "balance" and i.severity is Severity.ERROR for i in exc_info.value.issues)


def test_verify_returns_issues():
    issues = verify(Account)
    errors = [i for i in issues if i.severity is Severity.ERROR]
    warnings = [i for i in issues if i.severity is Severity.WARNING]
    assert len(errors) >= 1
    assert errors[0].field == "balance"


def test_verify_specific_phase():
    issues = verify(Account, phases=(NUMERIC_VERIFY_PHASE,))
    assert len(issues) >= 1
    assert issues[0].field == "balance"


def test_verify_schema_composition():
    full_schema = FASTAPI_SCHEMA + VERIFY_SCHEMA
    assert len(full_schema.phases) > len(FASTAPI_SCHEMA.phases)


# ─── Section: "Building your own verification phase" ──────────────────────────


@dataclass(frozen=True, slots=True)
class SecurityVerifyCtx:
    field_name: str
    field_type: type
    is_sensitive: bool = False
    is_encrypted: bool = False
    is_nullable: bool = False

    def check(self) -> tuple[Issue, ...]:
        issues: list[Issue] = []
        f = self.field_name

        if self.is_sensitive and not self.is_encrypted:
            issues.append(Issue(
                f, Severity.ERROR,
                "Sensitive field must have encryption marker",
            ))

        if self.is_sensitive and self.is_nullable:
            issues.append(Issue(
                f, Severity.WARNING,
                "Sensitive + Nullable — consider if NULL leaks information",
            ))

        return tuple(issues)


@runtime_checkable
class SecurityVerifyCompilable(Protocol):
    def compile_verify_security(self, ctx: SecurityVerifyCtx) -> SecurityVerifyCtx: ...


SECURITY_VERIFY_PHASE = CompilationPhase(
    SecurityVerifyCtx, SecurityVerifyCompilable,
    lambda n, t: SecurityVerifyCtx(field_name=n, field_type=t),
)


@dataclass(frozen=True, slots=True)
class Encrypted(SchemaAxisCapability):
    """Marks a field as encrypted."""

    def compile_verify_security(self, ctx: SecurityVerifyCtx) -> SecurityVerifyCtx:
        return replace(ctx, is_encrypted=True)


# Sensitive already exists — test that it participates if we add the method
# For the tutorial, we show that the existing Sensitive COULD participate.
# Here, test the custom phase with a custom SensitiveMarker.
@dataclass(frozen=True, slots=True)
class SensitiveMarker(SchemaAxisCapability):
    def compile_verify_security(self, ctx: SecurityVerifyCtx) -> SecurityVerifyCtx:
        return replace(ctx, is_sensitive=True)


def test_custom_security_phase_catches_unencrypted_sensitive():
    @dataclass
    class Patient:
        id: Annotated[int, Identity]
        ssn: Annotated[str, SensitiveMarker()]  # sensitive but NOT encrypted

    ALL_PHASES = (*VERIFY_PHASES, SECURITY_VERIFY_PHASE)
    issues = verify(Patient, phases=ALL_PHASES)
    security_errors = [i for i in issues if i.field == "ssn" and i.severity is Severity.ERROR]
    assert len(security_errors) == 1
    assert "encryption" in security_errors[0].message.lower()


def test_custom_security_phase_passes_with_encryption():
    @dataclass
    class Patient:
        id: Annotated[int, Identity]
        ssn: Annotated[str, SensitiveMarker(), Encrypted()]

    ALL_PHASES = (*VERIFY_PHASES, SECURITY_VERIFY_PHASE)
    issues = verify(Patient, phases=ALL_PHASES)
    security_errors = [i for i in issues if i.field == "ssn" and i.severity is Severity.ERROR]
    assert len(security_errors) == 0


# ─── Section: "Making existing capabilities participate" ──────────────────────


@dataclass(frozen=True, slots=True)
class PositiveOnly(SchemaAxisCapability):
    """Marks a field as strictly positive (> 0)."""

    def compile_verify_numeric(self, ctx: NumericVerifyCtx) -> NumericVerifyCtx:
        return replace(ctx, exclusive_lower=max(ctx.exclusive_lower or 0, 0))


def test_positive_only_catches_negative_max():
    @dataclass
    class Item:
        price: Annotated[float, PositiveOnly(), Max(-5)]

    issues = verify(Item, phases=(NUMERIC_VERIFY_PHASE,))
    errors = [i for i in issues if i.severity is Severity.ERROR]
    assert len(errors) >= 1
    assert errors[0].field == "price"


# ─── Section: "Verification on the query axis" ───────────────────────────────


@dataclass(frozen=True, slots=True)
class QueryVerifyCtx:
    has_limit: bool = False
    has_order: bool = False
    has_group: bool = False
    has_having: bool = False
    has_aggregate: bool = False
    has_offset: bool = False

    def check(self) -> tuple[Issue, ...]:
        issues: list[Issue] = []

        if self.has_limit and not self.has_order:
            issues.append(Issue(
                "query", Severity.WARNING,
                "Limit without OrderBy — results are non-deterministic",
            ))

        if self.has_having and not self.has_group:
            issues.append(Issue(
                "query", Severity.ERROR,
                "Having without GroupBy — invalid query",
            ))

        if self.has_group and not self.has_aggregate:
            issues.append(Issue(
                "query", Severity.WARNING,
                "GroupBy without Aggregate — did you forget the aggregation?",
            ))

        if self.has_offset and not self.has_limit:
            issues.append(Issue(
                "query", Severity.WARNING,
                "Offset without Limit — fetching everything after a skip",
            ))

        return tuple(issues)


@runtime_checkable
class QueryVerifyCompilable(Protocol):
    def compile_verify_query(self, ctx: QueryVerifyCtx) -> QueryVerifyCtx: ...


QUERY_VERIFY: QueryPhase[QueryVerifyCtx] = QueryPhase(
    protocol=QueryVerifyCompilable,
    method="compile_verify_query",
    handlers={
        Limit: lambda op, ctx: replace(ctx, has_limit=True),
        OrderBy: lambda op, ctx: replace(ctx, has_order=True),
        GroupBy: lambda op, ctx: replace(ctx, has_group=True),
        Having: lambda op, ctx: replace(ctx, has_having=True),
        Aggregate: lambda op, ctx: replace(ctx, has_aggregate=True),
        Offset: lambda op, ctx: replace(ctx, has_offset=True),
    },
)


@dataclass
class User:
    id: int
    name: str
    balance: float


def test_query_verify_limit_without_order():
    q = (
        relational(User)
        .filter(lambda u: u.balance > 0)
        .limit(10)
    )
    ctx = QUERY_VERIFY.fold(q.ops, QueryVerifyCtx())
    issues = ctx.check()
    assert len(issues) == 1
    assert issues[0].severity is Severity.WARNING
    assert "Limit without OrderBy" in issues[0].message


def test_query_verify_limit_with_order_is_clean():
    q = (
        relational(User)
        .filter(lambda u: u.balance > 0)
        .limit(10)
        .order_by(lambda u: u.balance.desc())
    )
    ctx = QUERY_VERIFY.fold(q.ops, QueryVerifyCtx())
    issues = ctx.check()
    assert not issues


def test_query_verify_with_handler_extension():
    STRICT_VERIFY = QUERY_VERIFY.with_handler(
        Distinct, lambda op, ctx: ctx,
    )
    q = relational(User).limit(10).order_by(lambda u: u.name)
    ctx = STRICT_VERIFY.fold(q.ops, QueryVerifyCtx())
    assert not ctx.check()


# ─── Section: "Schema explain" ───────────────────────────────────────────────


def test_schema_explain_produces_output():
    @dataclass
    class Product:
        id: Annotated[int, Identity]
        name: Annotated[str, Unique]

    text = explain_schema(Product)
    assert "Product" in text
    assert "id" in text
    assert "name" in text


def test_schema_dict_structure():
    @dataclass
    class Product:
        id: Annotated[int, Identity]
        name: Annotated[str, Unique]

    data = schema_dict(Product)
    assert data["name"] == "Product"
    assert len(data["fields"]) == 2
    assert data["fields"][0]["name"] == "id"


# ─── Section: "Query explain" ────────────────────────────────────────────────


def test_query_explain_dialect():
    q = (
        relational(User)
        .filter(lambda u: u.balance > 100)
        .order_by(lambda u: u.name)
        .limit(10)
    )
    text = RELATIONAL_EXPLAIN_DIALECT.format(q.ops)
    assert "Filter" in text
    assert "OrderBy" in text
    assert "Limit" in text


# ─── Section: "Compilation trace explain" ────────────────────────────────────


def test_compilation_trace():
    @dataclass
    class Item:
        id: Annotated[int, Identity]
        label: Annotated[str, Unique]

    axes = Axes.traced()
    ec = FASTAPI_SCHEMA.compile(Item, axes)
    text = explain_trace(axes)
    assert "Item" in text or "id" in text or "label" in text


# ─── Section: "Extending explain — query dialect" ────────────────────────────


def test_query_explain_with_handler():
    @dataclass(frozen=True, slots=True)
    class MyCustomOp:
        value: int

    def my_handler(op: MyCustomOp) -> dict[str, object]:
        return {"op": "MyCustom", "value": op.value}

    my_dialect = RELATIONAL_EXPLAIN_DIALECT.with_handler(MyCustomOp, my_handler)
    text = my_dialect.format([MyCustomOp(42)])
    assert "MyCustom" in text
    assert "42" in text


# ─── Section: type-safe tests (replacing string-based ones) ─────────────────


def test_no_contradictions():
    @dataclass
    class Clean:
        id: Annotated[int, Identity]
        name: Annotated[str, Unique]

    issues = verify(Clean)
    errors = [i for i in issues if i.severity is Severity.ERROR]
    assert not errors


def test_sensitive_fields_detected_via_inspect():
    """Type-safe capability check — no strings."""
    @dataclass
    class Secrets:
        id: Annotated[int, Identity]
        password: Annotated[str, Sensitive]
        token: Annotated[str, Sensitive]
        name: str

    fields = inspect_type(Secrets)
    sensitive_fields = [
        name for name, info in fields.items()
        if info.has(Sensitive)
    ]
    assert sensitive_fields == ["password", "token"]


def test_field_has_specific_capability():
    """Type-safe get() on FieldInfo."""
    @dataclass
    class Bounded:
        score: Annotated[int, Min(0), Max(100)]

    fields = inspect_type(Bounded)
    score = fields["score"]

    min_cap = score.get(Min)
    max_cap = score.get(Max)
    assert min_cap is not None
    assert max_cap is not None
    assert min_cap.value == 0
    assert max_cap.value == 100


def test_verify_catches_real_semantic_contradiction():
    """ReadOnly + Sensitive (which implies WriteOnly) on same field."""
    @dataclass
    class Bad:
        secret: Annotated[str, ReadOnly, Sensitive]

    issues = verify(Bad)
    errors = [i for i in issues if i.severity is Severity.ERROR]
    # Sensitive sets is_write_only on semantics, ReadOnly sets is_read_only
    # ReadOnly + WriteOnly = ERROR
    assert any(i.field == "secret" for i in errors)
