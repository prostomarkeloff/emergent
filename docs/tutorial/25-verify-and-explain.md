# Verify and Explain

You've built an entity. Annotated the fields. Chained transforms. Compiled to FastAPI. Everything works. But how do you know it's *correct*? Not "runs without crashing" correct — *logically consistent* correct. Can a field be both `ReadOnly` and `WriteOnly`? Can `Min(100)` coexist with `Max(50)`? Can an identity field be nullable?

These are contradictions. They compile fine — fold doesn't check logic, it accumulates context. The contradiction only surfaces when a user hits an impossible state at runtime. Or worse, it doesn't surface at all. The field silently accepts nothing.

Verification catches contradictions at import time. Explain lets you inspect everything at every level. Both are compilation targets — same fold, same architecture, same extension points as FastAPI or CLI. Both are designed to be extended by you.

---

## Verification as compilation

Open `emergent/wire/verify/__init__.py`. The entire public API:

```python
from emergent.wire.verify import verify, verify_raising

issues = verify(User, Product)           # -> tuple[Issue, ...]
verify_raising(User, Product)            # raises VerificationError on errors
```

`verify` compiles your entities through verification phases and collects issues. Each issue has a field name, a severity (`ERROR` or `WARNING`), and a message. `verify_raising` is the fail-fast version — it raises if any errors exist.

Three built-in phases ship out of the box:

**Numeric.** Catches impossible numeric ranges. `Min(100)` + `Max(50)` is an error. `ExclusiveMin(10)` + `ExclusiveMax(10)` is an error (empty range). `Min(10)` + `ExclusiveMax(10)` is an error (no value satisfies both).

**Length.** Catches impossible string constraints. `MinLen(20)` + `MaxLen(5)` is an error. `MaxLen(0)` is a warning — the field can't contain any characters.

**Semantics.** Catches logical contradictions between field roles. `ReadOnly` + `WriteOnly` is an error — the field is inaccessible. `Computed` + `WriteOnly` is an error — computed fields are read-only by definition. `Identity` + `Nullable` is a warning — primary keys shouldn't be null.

Each phase is a `CompilationPhase` — the exact same type that powers the Pydantic phase, the OpenAPI phase, every compilation target. Verification isn't a special subsystem bolted on. It's fold, applied to constraint checking.

```python
from emergent.wire.verify import VERIFY_PHASES, VERIFY_SCHEMA

# VERIFY_PHASES = (NUMERIC_VERIFY_PHASE, LENGTH_VERIFY_PHASE, SEMANTICS_VERIFY_PHASE)
# VERIFY_SCHEMA = SchemaCompiler(phases=VERIFY_PHASES)
```

## Using verify in practice

The simplest use: fail at import time if your entities are contradictory.

```python
from dataclasses import dataclass
from typing import Annotated
from emergent.wire.axis.schema import Min, Max, Identity, ReadOnly, Nullable
from emergent.wire.verify import verify_raising

@dataclass
class Account:
    id: Annotated[int, Identity]
    balance: Annotated[float, Min(0), Max(-1)]    # impossible range
    name: Annotated[str, ReadOnly]

verify_raising(Account)
# VerificationError: Verification failed:
#   balance: Min(0.0) > Max(-1.0)
```

For softer handling, use `verify` and inspect the issues:

```python
from emergent.wire.verify import verify, Severity

issues = verify(Account)
errors = [i for i in issues if i.severity is Severity.ERROR]
warnings = [i for i in issues if i.severity is Severity.WARNING]

for issue in issues:
    print(f"[{issue.severity.value}] {issue.field}: {issue.message}")
```

You can verify specific phases:

```python
from emergent.wire.verify import verify, NUMERIC_VERIFY_PHASE

# Only check numeric constraints
issues = verify(Account, phases=(NUMERIC_VERIFY_PHASE,))
```

And combine verification with other compilation by composing schemas:

```python
from emergent.wire.compile.targets import fastapi
from emergent.wire.verify import VERIFY_SCHEMA

# Verify AND compile in one schema
full_schema = fastapi.FASTAPI_SCHEMA + VERIFY_SCHEMA
```

## Building your own verification phase

Every domain has constraints the built-in phases don't cover. A financial system might require that sensitive fields are never nullable. A healthcare system might require that PII fields carry encryption markers. You don't patch the framework — you build a new phase.

A verification phase needs three things: a context dataclass with a `check()` method, a protocol, and an initial factory. The same triple as any compilation phase.

```python
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from emergent.wire.compile._phase import CompilationPhase
from emergent.wire.verify import Issue, Severity


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
```

That's a complete verification phase. Any capability that implements `compile_verify_security` now participates. Your existing `Sensitive` capability? Add the protocol method:

```python
@dataclass(frozen=True, slots=True)
class Sensitive(SchemaAxisCapability):
    def compile_verify_security(self, ctx: SecurityVerifyCtx) -> SecurityVerifyCtx:
        return replace(ctx, is_sensitive=True)

    def compile_verify_semantics(self, ctx: SemanticsVerifyCtx) -> SemanticsVerifyCtx:
        return replace(ctx, is_sensitive=True)
```

Use it:

```python
from emergent.wire.verify import verify, VERIFY_PHASES

ALL_PHASES = (*VERIFY_PHASES, SECURITY_VERIFY_PHASE)
issues = verify(Patient, phases=ALL_PHASES)
```

Open-world. The built-in phases don't know your `SecurityVerifyCtx` exists. Your phase doesn't know `NumericVerifyCtx` exists. They fold independently over the same fields, each checking its own concerns.

## Making existing capabilities participate

You don't always need a new phase. Sometimes you want existing capabilities to contribute to existing verification.

The built-in `Min` capability already implements `NumericVerifyCompilable`. It sets `lower_bound` on the numeric context. If you create a custom capability — say, `PositiveOnly` — you can make it participate in the same numeric verification:

```python
from dataclasses import dataclass, replace
from emergent.wire.axis.schema._universal import SchemaAxisCapability
from emergent.wire.verify import NumericVerifyCtx

@dataclass(frozen=True, slots=True)
class PositiveOnly(SchemaAxisCapability):
    """Marks a field as strictly positive (> 0)."""

    def compile_verify_numeric(self, ctx: NumericVerifyCtx) -> NumericVerifyCtx:
        return replace(ctx, exclusive_lower=max(ctx.exclusive_lower or 0, 0))
```

Now `Annotated[int, PositiveOnly(), Max(-5)]` is caught: `ExclusiveMin(0) >= Max(-5)` — empty range. Your capability talks to the existing numeric verification without any registration.

## Verification on the query axis

Schema verification catches contradictions on fields. The query axis uses the same fold — `QueryPhase` is symmetric to `CompilationPhase`. Query ops (Filter, OrderBy, Limit, etc.) are self-compiling frozen dataclasses. Verification is just another compilation target for them.

You don't modify the existing ops. `QueryPhase` accepts handler overrides — functions keyed by op type that take priority over protocol dispatch. Same mechanism that lets you override how `Filter` compiles to SQL. Here, you use it to accumulate verification flags.

```python
from dataclasses import dataclass, replace
from typing import Protocol, runtime_checkable
from emergent.wire.axis.query._contexts import QueryPhase
from emergent.wire.axis.query import (
    Filter, OrderBy, Limit, Offset, GroupBy, Having, Aggregate,
    relational, RelationalQuerySet,
)
from emergent.wire.verify import Issue, Severity


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


# Protocol (for custom ops that want to participate natively)
@runtime_checkable
class QueryVerifyCompilable(Protocol):
    def compile_verify_query(self, ctx: QueryVerifyCtx) -> QueryVerifyCtx: ...


# Handlers for built-in ops — no need to touch the op classes
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
```

Use it on a real queryset:

```python
@dataclass
class User:
    id: int
    name: str
    balance: float

# Build a query with a contradiction
q = (
    relational(User)
    .filter(lambda u: u.balance > 0)
    .limit(10)
    # no .order_by() — non-deterministic!
)

# Verify it
ctx = QUERY_VERIFY.fold(q.ops, QueryVerifyCtx())
issues = ctx.check()
# [Issue(field='query', severity=WARNING, message='Limit without OrderBy — ...')]

# Fix it
q_fixed = q.order_by(lambda u: u.balance.desc())
ctx = QUERY_VERIFY.fold(q_fixed.ops, QueryVerifyCtx())
assert not ctx.check()  # clean
```

Same fold. Same handler dispatch. Same open-world — unknown ops silently skipped. If someone adds a custom op that wants to participate, they implement `QueryVerifyCompilable`. If they don't, it's a no-op. And you can extend the phase with `.with_handler()`:

```python
from emergent.wire.axis.query import Distinct

STRICT_VERIFY = QUERY_VERIFY.with_handler(
    Distinct, lambda op, ctx: ctx,  # Distinct is fine, just acknowledge it
)
```

## The explain systems

Verification catches contradictions. Explain lets you see what's there — the structure, the topology, the data flow. Five explain systems, one per axis plus compilation traces. All follow the same two-layer pattern:

1. **Dict layer** — structured data for tools, APIs, LLM consumption
2. **Human-readable layer** — formatted strings built from the dicts

### Schema explain

```python
from emergent.wire.axis.schema._explain import explain_schema, schema_dict

print(explain_schema(User))
# === User ===
#   [SchemaName("users"), Timestamps]
#
#   id (int):
#     [Identity]
#
#   email (str):
#     [Unique, MaxLen(255)]
#     cli: Help("Email address")
#     openapi: Description("..."), Format("email")
```

The dict layer gives you the same data as a structured object:

```python
data = schema_dict(User)
# data["name"] == "User"
# data["fields"][0]["name"] == "id"
# data["fields"][0]["universal"] == [{"type": "Identity"}]
```

Capabilities are automatically grouped by dialect — cli, openapi, sql, tg, and more. Universal capabilities (not belonging to any dialect) appear in their own section. Unknown capability types get a generic `repr()`, never crash.

### Surface explain

```python
from emergent.wire.axis.surface._explain import explain_application, application_dict

print(explain_application(app))
# === Application (3 endpoints, 1 global cap) ===
#   global: CORS(origins=('*',))
#
#   Endpoint #1 (2 exposures):
#     [POST /api/v1/users] RequestResponseCodec
#       request: CreateUserReq, response: UserResp

data = application_dict(app)
# data["endpoint_count"] == 3
# data["endpoints"][0]["exposures"][0]["trigger"]["path"] == "/api/v1/users"
```

The dict layer is what makes explain useful for agents. An LLM can parse the dict, check that expected routes exist, verify that authentication is on the right endpoints — all without running the server.

### Query explain

```python
from emergent.wire.axis.query._explain import RELATIONAL_EXPLAIN_DIALECT

text = RELATIONAL_EXPLAIN_DIALECT.format(query.ops)
#   1. Filter: expr=balance > 100, fields=balance
#   2. OrderBy: specs=name ASC
#   3. Limit: count=10
```

Three pre-built dialects: `RELATIONAL_EXPLAIN_DIALECT`, `API_EXPLAIN_DIALECT`, `KV_EXPLAIN_DIALECT`. Each covers its family of operations.

### Compilation trace explain

```python
from emergent.wire.compile import Axes
from emergent.wire.compile._explain import explain, explain_field

axes = Axes.traced()
ec = FASTAPI_SCHEMA.compile(User, axes)

print(explain(axes))          # full trace: every field, every phase
print(explain_field(axes, "email"))  # one field's journey through compilation
```

Tracing is off by default — zero overhead. `Axes.traced()` turns it on. Every fold step gets recorded: which capabilities were applied, which were skipped, which actually changed the context.

## Extending explain

Every explain system uses handler dispatch. A mapping from types to functions. You pass custom handlers to see custom things.

### Adding a handler for a custom trigger

Say you've built a `WebSocketTrigger`. The surface explain doesn't know about it — it falls back to a generic dataclass repr. You can fix that:

```python
from emergent.wire.axis.surface._explain import (
    explain_application, SURFACE_EXPLAIN,
)

def _explain_ws_trigger(t: WebSocketTrigger) -> dict[str, Any]:
    return {"type": "WebSocketTrigger", "path": t.path, "protocol": t.protocol}

my_handlers = {**SURFACE_EXPLAIN, WebSocketTrigger: _explain_ws_trigger}
text = explain_application(app, handlers=my_handlers)
```

Same pattern for every axis. Schema explain takes `dialects`. Surface explain takes `handlers`. Query explain uses `ExplainDialect` with immutable `.with_handler()`:

```python
from emergent.wire.axis.query._explain import RELATIONAL_EXPLAIN_DIALECT

my_dialect = RELATIONAL_EXPLAIN_DIALECT.with_handler(MyCustomOp, my_handler)
text = my_dialect.format(query.ops)
```

### Adding a custom schema dialect

Schema explain groups capabilities by dialect. Out of the box it knows cli, openapi, sql, tg, compose, pydantic, api, query. If you create a new dialect — say GraphQL capabilities — you can teach explain about it:

```python
from emergent.wire.axis.schema._explain import explain_schema

my_dialects = {
    **_get_dialect_bases(),
    "graphql": GraphQLCapability,
}
text = explain_schema(User, dialects=my_dialects)
# Now GraphQL capabilities appear under their own "graphql:" heading
```

## Verify + explain with AI agents

This is where both systems converge. An agent's workflow with emergent:

```python
# 1. Agent writes/modifies the entity
@derive(http_crud("/accounts", provider_node=Accounts))
@dataclass
class Account:
    id: Annotated[int, Identity]
    balance: Annotated[float, Min(0)]
    email: Annotated[str, Unique, Sensitive]

# 2. Agent verifies — catches contradictions before anything runs
from emergent.wire.verify import verify
issues = verify(Account)
assert not issues, f"Contradictions found: {issues}"

# 3. Agent inspects the structure — type-safe, no string matching
from emergent.wire.axis.schema._inspect import inspect_type
fields = inspect_type(Account)
sensitive_fields = [
    name for name, info in fields.items()
    if info.has(Sensitive)
]
# Agent checks capability presence via .has(), .get(), .get_all()
# info.get(Min) returns the typed Min instance — access .value directly

# 5. Agent compiles with tracing
from emergent.wire.compile import Axes
from emergent.wire.compile._explain import explain
axes = Axes.traced()
fastapi_app = fastapi.compile(app, axes)
print(explain(axes))  # full compilation audit trail
```

The dict layer is the key. Human-readable output is for terminal display. The dict layer is for programmatic inspection — agents parse it, check invariants, make decisions. It's the same data, two projections.

Write tests that use both — type-safe, no string matching:

```python
from emergent.wire.axis.schema._inspect import inspect_type
from emergent.wire.axis.schema import Sensitive, Identity
from emergent.wire.verify import verify, Severity

def test_no_contradictions():
    issues = verify(Account, Product, Order)
    errors = [i for i in issues if i.severity is Severity.ERROR]
    assert not errors

def test_sensitive_fields_are_encrypted():
    """Type-safe capability check via FieldInfo.has()."""
    fields = inspect_type(Account)
    for name, info in fields.items():
        if info.has(Sensitive):
            assert info.has(Encrypted), f"{name} is Sensitive but not Encrypted"

def test_all_fields_with_identity_are_not_nullable():
    fields = inspect_type(Account)
    for name, info in fields.items():
        if info.has(Identity):
            assert not info.is_optional, f"{name} is Identity but nullable"
```

No strings. `FieldInfo.has(Sensitive)` dispatches on the actual type. `info.get(Min)` returns the typed capability instance — you can inspect `.value` directly. The agent writes these tests, runs them, verifies its own work at the type level. Write, verify, explain, compile, test.

---

**Next:** [The Sweet Spot →](26-llm-sweet-spot.md)
