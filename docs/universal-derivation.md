# Universal Derivation

Derive anything from anything. One primitive (`fold_schema`), three-phase compilation, full composition.

All examples below are from a single trading platform. Runnable:

```bash
uv run python docs/_test_universal_derive_examples.py
```

---

## Architecture Overview

Three layers, each built on the one below:

| Layer | Primitive | Context | Output |
|-------|-----------|---------|--------|
| **wire.derive** | `compile_derive` | `DeriveCtx` | Endpoints (OpSpec + Operation) |
| **Custom algebra** | `fold_schema` | Your context | Your output (state machine, rules, events, ...) |
| **Bridge** | Capability implementing both | Runs its own algebra, emits into DeriveCtx | Endpoints generated from custom algebra data |

All three layers share the same mechanism: `fold_schema(cls, initial_ctx, Protocol, "method_name")`.

---

## 1. Three-Phase Compilation

`compile_derive(cls)` runs three protocol folds in sequence:

```
Phase 1: DeriveGeneratable  — GENERATE endpoints (CRUD, Methods, bridges)
Phase 2: DeriveModifiable   — MODIFY generated specs (Paginated, Readonly, SoftDelete, ...)
Phase 3: DeriveAugmentable  — AUGMENT after modification (NestedCRUD backlinks, ...)
```

```python
from emergent.wire.derive import compile_derive, materialize

ctxs = compile_derive(User)          # list[DeriveCtx] — one per generator group
endpoints = [materialize(ctx) for ctx in ctxs]
```

### Multi-Generator Handling

When a class has multiple `DeriveGeneratable` capabilities, each gets its own `DeriveCtx`. Shared modifiers and augmenters are applied to each:

```python
@schema_meta(
    http_crud("/api/products", Store),   # generator 1
    cli_crud("product", Store),          # generator 2
    Paginated(20),                       # modifier — applied to both
)
@dataclass
class Product: ...

ctxs = compile_derive(Product)  # [http_ctx, cli_ctx]
```

Single generator or zero generators → single-element list.

---

## 2. DeriveCtx — Unified Context

Frozen dataclass accumulating all derivation state. Merges old SchemaCtx + QueryCtx + SurfaceCtx.

```python
from emergent.wire.derive import DeriveCtx

@dataclass(frozen=True, slots=True)
class DeriveCtx[EntityT]:
    entity: type[EntityT]
    fields: dict[str, FieldInfo]              # schema axis
    identity_fields: dict[str, FieldInfo]     # Identity-annotated fields
    query_strategy: QueryStrategy[EntityT]    # query axis (relational, none, ...)
    specs: tuple[OpSpec, ...]                 # generated OpSpecs (Phase 1)
    operations: tuple[Operation, ...]         # direct operations (Phase 1)
    capabilities: tuple[SurfaceCapability, ...] # global capabilities (surface axis)
```

### Two Factory Methods

**`from_entity(cls)`** — for dataclasses with field inspection:

```python
ctx = DeriveCtx.from_entity(User)
# ctx.fields = {"id": FieldInfo(...), "name": FieldInfo(...)}
# ctx.identity_fields = {"id": FieldInfo(...)}
```

**`from_subject(cls)`** — for any type (services, configs, plain classes):

```python
ctx = DeriveCtx.from_subject(RiskEngine)
# ctx.fields = {}  — no field inspection
# ctx.identity_fields = {}  — no identity requirement
```

`compile_derive` auto-detects: tries `from_entity`, falls back to `from_subject` on `TypeError`.

### Two Paths Through Materialization

`materialize(ctx)` merges two paths into a single Endpoint:

1. **OpSpec path** — `ctx.specs` → `build_from_spec()` → types + handler + exposure. Used by CRUD.
2. **Direct operations path** — `ctx.operations` → already built `(OpType, handler, Exposure)` tuples. Used by Methods, bridges.

```python
endpoint = materialize(ctx)
# endpoint.runner — ops-based dispatch
# endpoint.exposures — triggers + codecs + capabilities
```

### Context Accumulation Methods

All return new `DeriveCtx` via `dataclasses.replace()` (immutable):

```python
ctx = ctx.add_spec(spec)              # append OpSpec
ctx = ctx.add_operation(op_triple)    # append (type, handler, Exposure)
ctx = ctx.add_capability(cap)         # global capability

# Spec transforms (for DeriveModifiable):
ctx = ctx.reject_by_effect(Mutation)  # remove specs with effect
ctx = ctx.select_by_effect(Read)      # keep only specs with effect
ctx = ctx.replace_handler(Deletes, SoftDeleteMark("deleted_at"))
ctx = ctx.wrap_handler(Read, my_wrapper)
ctx = ctx.exclude_fields(Creates, frozenset({"created_at"}))
ctx = ctx.filter_query(lambda e: e.deleted_at.is_null())
ctx = ctx.add_spec_capability(AuthCap(), Mutation)
ctx = ctx.map_specs_by_effect(Read, transform_fn)
```

---

## 3. Built-in Generators (Phase 1)

### CRUD

Transport-agnostic. Generates OpSpecs from entity fields.

```python
from emergent.wire.derive import http_crud, cli_crud
from emergent.wire.derive._crud import LIST, GET, CREATE, UPDATE, PATCH, DELETE, UPSERT

@schema_meta(http_crud("/api/users", UserProvider))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str

# Selective ops:
@schema_meta(http_crud("/api/users", UserProvider, ops=(LIST, GET, CREATE)))
```

7 built-in Op constants: `LIST`, `GET`, `CREATE`, `UPDATE`, `PATCH`, `DELETE`, `UPSERT`.

CRUD requires `Identity` field — raises `ValueError` on plain classes.

### Methods

Scan class for `@method`-decorated methods, generate one operation per trigger.

```python
from emergent.wire.derive.patterns.methods import Methods, post, get, command

@schema_meta(Methods())
class MyService:
    @staticmethod
    @post("/api/health")
    async def health() -> Result[dict, DomainError]:
        return Ok({"status": "ok"})

    @classmethod
    @get("/api/version")
    async def version(cls) -> Result[str, DomainError]:
        return Ok("2.0")
```

Three calling conventions: `@staticmethod`, `@classmethod`, instance method.

Multi-target — stack decorators for multiple exposures per method:

```python
@classmethod
@post("/api/orders")
@command("order-create")
async def create(cls, customer: str) -> Result[int, DomainError]: ...
```

### MethodDialect

Transport-agnostic Methods — methods describe WHAT (`@op`), trigger gen decides WHERE:

```python
from emergent.wire.derive.patterns.methods import MethodDialect, op

@schema_meta(MethodDialect(triggers=HTTPTriggers("/api/orders")))
class OrderService:
    @classmethod
    @op("Create", effects=(Creates(),))
    async def create(cls, customer: str) -> Result[Order, DomainError]: ...
```

---

## 4. Built-in Modifiers (Phase 2)

All implement `DeriveModifiable` via `compile_derive_modify`.

### Query Enrichment

```python
Paginated(50)           # paginated list with page/page_size params
Sorted("name", "desc")  # sorted list with sort/order params
```

### Effect-Based Filters

```python
Readonly()       # remove mutations, keep reads
MutationsOnly()  # keep mutations, remove reads
WithoutDelete()  # remove delete operations
WithoutCreate()  # remove create operations
CreateOnly()     # keep only create
UpdateOnly()     # keep only update
OnlyOps(("List", "Get"))  # keep only named ops
```

### Response Projection

```python
ProjectResponse(exclude=("secret", "internal_id"))  # hide fields from response
```

### In-Memory Filtering & Search

```python
Filtered("name", "status")   # add filter_{field} params to Read ops
Searchable("name", "bio")    # add q param for full-text search on Read ops
```

**Warning:** Both do in-memory filtering after fetch.

### Composed Transforms

```python
SoftDelete()                              # replace hard delete with set deleted_at + filter query
SoftDelete(deleted_field="removed_at")    # custom field name
Timestamped()                             # auto-set created_at/updated_at
Timestamped(created_field="made_at", updated_field="changed_at")
```

### Enricher Transforms

```python
WithTimeout(30.0)      # add Timeout enricher to all ops
WithRetry(3)           # add Retry enricher to mutation ops
WithRateLimit(rpm=60)  # add RateLimit enricher to all ops
EffectRateLimited()    # rate limit only ops declaring RateLimited effect
EffectDeprecated()     # deprecation warning on ops declaring Deprecated effect
```

---

## 5. Trigger System

`TriggerGen` — callable that maps `(entity, Op) -> Trigger | tuple[Trigger, ...] | None`:

```python
from emergent.wire.derive._trigger import HTTPTriggers, CLITriggers

HTTPTriggers("/api/users")  # List→GET /api/users, Get→GET /api/users/{id}, etc.
CLITriggers("user")         # List→user-list, Get→user-get, etc.
```

Composable trigger generators:

```python
from emergent.wire.derive import PrefixedTriggerGen, FilteredTriggerGen, MultiTriggerGen

PrefixedTriggerGen("/v2", inner)      # prefix all paths
FilteredTriggerGen(inner, allow={"List", "Get"})  # filter by op name
MultiTriggerGen(http_triggers, cli_triggers)      # multiple triggers per op
```

---

## 6. OpSpec — Intermediate Representation

OpSpec is the inspectable, transformable, serializable description of a derived operation. Types are built only at materialization time.

```python
@dataclass(frozen=True, slots=True)
class OpSpec:
    name: str
    entity_name: str
    input_fields: Mapping[str, AnnotationValue]
    request_fields: Mapping[str, AnnotationValue]
    response_spec: ResponseSpec
    handler_template: HandlerTemplate
    trigger: Trigger
    capabilities: tuple[SurfaceCapability, ...]
    effects: tuple[DerivationEffect, ...]
    source: str  # "CRUD", "NestedCRUD", etc.
```

This is what Phase 2 modifiers transform. Paginated replaces `handler_template` and `response_spec`. Readonly rejects specs by effect. SoftDelete replaces handler + adds query filter.

### Handler Templates

Protocol-based handler construction:

```python
class HandlerTemplate(Protocol):
    def build(self, spec: HandlerSpec) -> OperationHandler: ...
```

Built-in: `FetchMany`, `FetchOneById`, `InsertNew`, `UpdateExisting`, `PatchExisting`, `DeleteOne`, `UpsertExisting`, `PaginatedFetchMany`, `SortedFetchMany`, `SoftDeleteMark`, `TimestampInsert`, `TimestampUpdate`.

Composition via `WrappedTemplate`:

```python
from emergent.wire.derive._handler import WrappedTemplate

template = WrappedTemplate(inner=FetchMany(), wrapper=my_logging_wrapper)
```

And `Pipeline` for multi-step handlers:

```python
from emergent.wire.derive import Pipeline, PipelineStep

pipeline = Pipeline(steps=(ValidateStep(), TransformStep(), PersistStep()))
```

---

## 7. Query Strategy

Controls how handlers access data. Set during Phase 1 generation.

```python
from emergent.wire.derive import RelationalStrategy, NoQueryStrategy, ProviderInjection

# CRUD sets this automatically:
RelationalStrategy(
    provider_node=UserProvider,
    base_query=relational(User),
    injection=ProviderInjection(op_field=..., request_field=...),
)

# Non-entity subjects get:
NoQueryStrategy()  # default — no provider, no query
```

---

## 8. Custom Algebras (Level 3)

Own context, own protocol, own compile. Not tied to wire.derive. Not endpoints.

### State Machine Example

```python
@dataclass(frozen=True, slots=True)
class StateMachineCtx:
    subject: type
    initial_state: str = ""
    transitions: tuple[TransitionDef, ...] = ()
    terminal_states: frozenset[str] = frozenset()

@runtime_checkable
class StateMachineDerivable(Protocol):
    def derive_state_machine(self, ctx: StateMachineCtx) -> StateMachineCtx: ...

def compile_state_machine(cls: type) -> StateMachineCtx:
    return fold_schema(
        cls, StateMachineCtx(subject=cls),
        StateMachineDerivable, "derive_state_machine",
    )
```

Capability:

```python
@dataclass(frozen=True, slots=True)
class Lifecycle(SchemaCapability):
    initial: str
    transitions: tuple[tuple[str, str, str], ...]
    terminal: frozenset[str] = frozenset()
    guards: dict[str, str] = dataclass_field(default_factory=dict)

    def derive_state_machine(self, ctx: StateMachineCtx) -> StateMachineCtx:
        defs = tuple(
            TransitionDef(action=a, source=s, target=t, guard=self.guards.get(a, ""))
            for a, s, t in self.transitions
        )
        return replace(ctx, initial_state=self.initial,
                       transitions=(*ctx.transitions, *defs),
                       terminal_states=ctx.terminal_states | self.terminal)
```

This algebra has NO knowledge of HTTP, endpoints, or wire.derive. Pure domain logic.

---

## 9. Bridge Pattern — Custom Algebra + Endpoints

Dual-protocol capability — implements its own algebra AND bridges to wire.derive.

```python
@dataclass(frozen=True, slots=True)
class RiskChecks(SchemaCapability):
    rules: tuple[tuple[str, str, str, str], ...]

    # Protocol 1: own algebra → RulesCtx
    def derive_risk(self, ctx: RulesCtx) -> RulesCtx:
        defs = tuple(RiskRule(name=n, severity=s, condition=c, message=m)
                     for n, s, c, m in self.rules)
        return replace(ctx, rules=(*ctx.rules, *defs), ...)

    # Protocol 2: bridge → wire.derive, generates GET /risk-rules endpoint
    def compile_derive_generate(self, ctx: DeriveCtx) -> DeriveCtx:
        rules_ctx = self.derive_risk(RulesCtx(subject=ctx.entity))
        # ... build handler returning rules as JSON ...
        return ctx.add_operation((op_type, annotated, exposure))
```

Same `@schema_meta`, same capability — two completely different outputs depending on which fold runs.

### Lifecycle Bridge — State Machine to Endpoints

```python
@dataclass(frozen=True, slots=True)
class LifecycleBridge(SchemaCapability):
    base_path: str

    def compile_derive_generate(self, ctx: DeriveCtx) -> DeriveCtx:
        sm_ctx = compile_state_machine(ctx.entity)  # run Level 3 algebra
        for tr in sm_ctx.transitions:
            # generate POST /api/orders/{action} per transition
            ctx = ctx.add_operation((op_type, handler, exposure))
        return ctx
```

Composition: Level 3 algebra produces data, bridge converts to endpoints.

---

## 10. Trading Platform Example

Three types, three algebras, every kind of composition:

| Type | Kind | Algebras |
|------|------|----------|
| `Instrument` | Entity (dataclass) | CRUD + risk rules |
| `Order` | Entity (dataclass) | CRUD (readonly) + state machine + lifecycle endpoints + risk rules |
| `RiskEngine` | Plain class (NOT entity) | Methods + risk rules |

### Instrument: CRUD + risk rules

```python
@schema_meta(
    http_crud("/api/instruments", InstrumentStore, ops=(LIST, GET, CREATE, DELETE)),
    RiskChecks(rules=(...)),
    Paginated(50),
)
@dataclass
class Instrument:
    id: Annotated[int, Identity]
    symbol: str
    exchange: str
    currency: str
```

Result — 5 exposures: 4 CRUD specs + 1 risk-rules operation.

### Order: CRUD + state machine + lifecycle + risk rules

Three algebras on one type:

```python
@schema_meta(
    http_crud("/api/orders", OrderStore),
    Lifecycle(initial="new", transitions=(...), terminal=frozenset({...}), guards={...}),
    LifecycleBridge(base_path="/api/orders"),
    RiskChecks(rules=(...)),
    Readonly(),
)
@dataclass
class Order:
    id: Annotated[int, Identity]
    instrument_id: int
    side: str
    quantity: int
    price: float
    status: str
```

Result — 11 exposures: 2 CRUD specs (readonly) + 8 lifecycle + 1 risk-rules.

Three folds, three outputs, same capabilities, same `@schema_meta`:

```python
ctxs = compile_derive(Order)        # 3 DeriveCtx (CRUD, Lifecycle, RiskChecks)
sm = compile_state_machine(Order)   # StateMachineCtx: 8 transitions
rules = compile_risk_rules(Order)   # RulesCtx: 3 rules
```

### RiskEngine: NOT an entity

```python
@schema_meta(
    Methods(),
    RiskChecks(rules=(...)),
)
class RiskEngine:
    @staticmethod
    @post("/api/risk/evaluate")
    async def evaluate(instrument_id: int, quantity: int, price: float) -> Result[dict, DomainError]: ...

    @staticmethod
    @get("/api/risk/status")
    async def status() -> Result[dict, DomainError]: ...
```

Result — 3 exposures: 2 method operations + 1 risk-rules. No fields, no identity.

---

## 11. Explain / Introspection

DeriveCtx is self-describing — all state is inspectable frozen data.

```python
from emergent.wire.derive import explain_derive, derive_dict, explain_entity

text = explain_derive(ctx)    # human-readable multi-line
data = derive_dict(ctx)       # structured dict
text = explain_entity(Order)  # compile + explain in one call
```

```
Entity: Order
  Fields: id, instrument_id, side, quantity, price, status
  Identity: id
  Provider: OrderStore
  Query: relational
Operations (2 specs):
  List: GET /api/orders [Read, Pageable, Sortable] ()
  Get: GET /api/orders/{id} [Read, Idempotent, Cacheable] (id)
```

---

## 12. Recipe — Extending

### New DeriveModifiable

1. Subclass `SchemaCapability`
2. Implement `compile_derive_modify(self, ctx: DeriveCtx) -> DeriveCtx`
3. Use `ctx.reject_by_effect`, `ctx.replace_handler`, `ctx.wrap_handler`, etc.

### New DeriveGeneratable

1. Subclass `SchemaCapability`
2. Implement `compile_derive_generate(self, ctx: DeriveCtx) -> DeriveCtx`
3. Use `ctx.add_spec(OpSpec(...))` for template-based ops, or `ctx.add_operation(triple)` for direct ops

### New custom algebra (Level 3)

1. **Context** — frozen dataclass accumulator
2. **Protocol** — `@runtime_checkable`, one method: `def derive_X(self, ctx: MyCtx) -> MyCtx`
3. **Capabilities** — `SchemaCapability` + protocol method
4. **Compile** — `fold_schema(cls, MyCtx(subject=cls), MyDerivable, "derive_X")`
5. **Bridge** (optional) — same capability also implements `compile_derive_generate`

---

## 13. Files

### Core

- `emergent/wire/derive/_compile.py` — `compile_derive`, three-phase orchestration
- `emergent/wire/derive/_ctx.py` — `DeriveCtx`, unified context, `from_entity`/`from_subject`
- `emergent/wire/derive/_protocols.py` — `DeriveGeneratable` / `DeriveModifiable` / `DeriveAugmentable`
- `emergent/wire/derive/_materialize.py` — `materialize`, DeriveCtx → Endpoint
- `emergent/wire/derive/_opspec.py` — `Op`, `OpSpec`, `build_from_spec`, `generate_specs`

### Handlers & Codegen

- `emergent/wire/derive/_handler.py` — `HandlerTemplate`, `HandlerSpec`, all built-in templates, `WrappedTemplate`
- `emergent/wire/derive/_codegen.py` — runtime dataclass/request/response type creation
- `emergent/wire/derive/_project.py` — response projections (entity, list, paginated, composed)
- `emergent/wire/derive/_pipeline.py` — `Pipeline`, `PipelineStep`, `PipelineContext`

### Generators & Transforms

- `emergent/wire/derive/_crud.py` — `CRUD`, `http_crud`, `cli_crud`, Op constants
- `emergent/wire/derive/_transforms.py` — all DeriveModifiable transforms
- `emergent/wire/derive/patterns/methods.py` — `Methods`, `MethodDialect`, decorators (`@post`, `@get`, `@op`, ...)
- `emergent/wire/derive/patterns/nested.py` — `NestedCRUD` (DeriveAugmentable)

### Supporting

- `emergent/wire/derive/_trigger.py` — `TriggerGen`, `HTTPTriggers`, `CLITriggers`, composable generators
- `emergent/wire/derive/_query_strategy.py` — `QueryStrategy`, `RelationalStrategy`, `NoQueryStrategy`
- `emergent/wire/derive/_query_helpers.py` — identity queries, scoped queries, provider field helpers
- `emergent/wire/derive/_effects.py` — `DerivationEffect` types (Read, Creates, Deletes, Pageable, ...)
- `emergent/wire/derive/_errors.py` — `DomainError`, `NotFound`
- `emergent/wire/derive/_error_caps.py` — default error surface capabilities
- `emergent/wire/derive/_metadata.py` — `DerivedMetadata` for target compiler introspection
- `emergent/wire/derive/_explain.py` — `explain_derive`, `derive_dict`, `explain_entity`
- `emergent/wire/derive/_builders.py` — `ExposureBuilder`, `endpoint_builder`

### Fold Primitive

- `emergent/wire/compile/_core.py` — `fold`, `fold_schema`, `fold_field`
- `emergent/wire/axis/schema/_universal.py` — `SchemaCapability`, `schema_meta`, `get_schema_meta`, `Identity`

### Tests & Examples

- `tests/test_universal_derive.py` — Level 1-3 tests
- `docs/_test_universal_derive_examples.py` — runnable trading platform example
