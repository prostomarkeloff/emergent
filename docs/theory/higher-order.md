# Higher-order compilation

emergent compiles entities to endpoints. This document goes further — what happens when compilation output becomes compilation input, and when the compiler itself is the thing being compiled.

No heuristics. No if-chains. Every level is `fold(items, ctx, protocol, method)`. Every decision is a capability. Every transformation is compositional.

## Level 0: Entity → App

```python
Users = memory_node()

@derive(http_crud("/users", Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: Annotated[str, MinLen(1), MaxLen(100)]
    email: Annotated[str, Unique, MaxLen(255)]

app = build_application_from_decorated(User)
fastapi_app = targets.fastapi.compile(app)
cli_app = targets.cli.compile(app)
```

Same entity, two targets. `MinLen(1)` on `name` compiles to:
- Pydantic: `Annotated[str, MinLen(min_length=1)]` → rejects `""`
- OpenAPI: `{"minLength": 1}` → documented
- Argparse: length validator → CLI rejects short input
- Verify: `min_length=1` stored → `MinLen(10), MaxLen(5)` caught at import

One annotation. Four compilations. Zero code written for any of them.

## Level 1: Capability spawns entity + wraps handlers via effects

A `DeriveAugmentable` capability receives the fully-generated `DeriveCtx` — it sees all specs with their effects. It uses the effect system to:

1. **Generate a new entity** from the source entity's fields
2. **Wrap mutation handlers** by dispatching on `Mutation` effect — no if-chains, just `has_effect`
3. The new entity goes through its own `compile_derive` → its own fold → its own endpoints

```python
@dataclass(frozen=True, slots=True)
class Journaled(UniversalCapability):
    """Every mutation is journaled. The journal is a separate compiled entity."""

    def compile_derive_augment[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        source = ctx.entity
        source_name = source.__name__.lower()

        # 1. Build journal entity from source schema — PROJECTION of source fields
        journal_annotations: dict[str, Any] = {
            "id": Annotated[int, Identity],
            "entity_id": int,
            "action": Annotated[str, OneOf("create", "update", "delete")],
            "timestamp": float,
        }
        for name, info in ctx.fields.items():
            if name != "id":
                journal_annotations[f"val_{name}"] = info.base_type | None

        JournalEntry = dataclass(type(
            f"{source.__name__}Journal", (), {"__annotations__": journal_annotations}
        ))

        # 2. Attach CRUD to journal — it compiles through its own fold
        journal_store = memory_node()
        schema_meta(
            http_crud(f"/{source_name}s/journal", journal_store),
            Readonly(),  # Read-only — journal is append-only
        )(JournalEntry)

        # 3. Wrap every mutation handler via effect dispatch
        #    has_effect uses isinstance — Creates/Updates/Deletes all match Mutation
        new_specs: list[OpSpec] = []
        for spec in ctx.specs:
            if has_effect(spec.effects, Mutation):
                new_specs.append(replace(spec,
                    handler_template=WrappedTemplate(
                        inner=spec.handler_template,
                        wrapper=_JournalWrapper(JournalEntry, journal_store),
                    ),
                ))
            else:
                new_specs.append(spec)

        return replace(ctx, specs=tuple(new_specs))
```

The wrapper intercepts mutation results and writes journal entries:

```python
@dataclass(frozen=True, slots=True)
class _JournalWrapper:
    journal_entity: type
    journal_store: type

    def __call__[T](
        self, inner: OperationHandler[T, DomainError], spec: HandlerSpec[T]
    ) -> OperationHandler[T, DomainError]:
        async def wrapped(op: Any) -> Result[T, DomainError]:
            result = await inner(op)
            match result:
                case Ok(value):
                    # Write journal entry — journal store is a nodnod node,
                    # resolved at compose time via DI
                    pass  # emit journal event
            return result
        return wrapped
```

Usage — one line adds full journaling:

```python
@derive(http_crud("/orders", Orders), Journaled())
@dataclass
class Order:
    id: Annotated[int, Identity]
    customer: str
    total: Annotated[float, Min(0)]
    status: Annotated[str, OneOf("pending", "paid", "shipped")]
```

`compile_derive(Order)` produces:
- Order's 6 CRUD endpoints (mutations wrapped with journal emitter)
- `OrderJournal`'s 2 read-only endpoints (list + get by id)

`OrderJournal` has `val_customer: str | None`, `val_total: float | None`, `val_status: str | None` — **derived from Order's fields**. Add a field to Order → journal tracks it. Remove → journal stops.

The key: `has_effect(spec.effects, Mutation)` dispatches on the effect hierarchy. `Creates`, `Updates`, `Deletes` all match `Mutation` via isinstance. No if-chain. No string matching. The effect IS the selector.

This is how emergent's built-in transforms work:

```python
# Readonly removes all mutations — one line
Readonly().compile_derive_modify(ctx)  →  ctx.reject_by_effect(Mutation)

# SoftDelete replaces DeleteOne with SoftDeleteMark — effect-targeted
SoftDelete().compile_derive_modify(ctx)  →  ctx.replace_handler(Deletes, SoftDeleteMark(...))

# Paginated replaces Read+Pageable handlers — effect intersection
Paginated(20).compile_derive_modify(ctx)  →  ctx.map_specs_by_effect(Pageable, ...)

# WithTimeout adds enricher to ALL ops
WithTimeout(5.0)  →  ctx.add_spec_capability(Timeout(5.0))

# WithRetry adds enricher only to mutations
WithRetry(3)  →  ctx.add_spec_capability(Retry(...), effect=Mutation)
```

Effects are the type system of the derive pipeline. They classify ops semantically. Transforms dispatch on classifications. No heuristics.

## Level 2: Entity assembles its own compiler

`SchemaCompiler` is `tuple[CompilationPhase, ...]` — frozen data with algebra. So it can be the output of a fold.

```python
@dataclass(frozen=True, slots=True)
class CompilerCtx:
    phases: tuple[CompilationPhase[Any], ...] = ()

@runtime_checkable
class CompilerCompilable(Protocol):
    def compile_compiler(self, ctx: CompilerCtx) -> CompilerCtx: ...

@dataclass(frozen=True, slots=True)
class WithGraphQL(UniversalCapability):
    def compile_compiler(self, ctx: CompilerCtx) -> CompilerCtx:
        return replace(ctx, phases=(*ctx.phases, GRAPHQL_PHASE))

@dataclass(frozen=True, slots=True)
class WithPrometheus(UniversalCapability):
    buckets: tuple[float, ...] = (0.01, 0.1, 1.0, 10.0)

    def compile_compiler(self, ctx: CompilerCtx) -> CompilerCtx:
        return replace(ctx, phases=(*ctx.phases, PROMETHEUS_PHASE))

    def compile_prometheus(self, ctx: PrometheusCtx) -> PrometheusCtx:
        return replace(ctx, histogram_buckets=self.buckets)
```

Entity declares requirements:

```python
@derive(http_crud("/payments", Payments))
@dataclass
class Payment:
    id: Annotated[int, Identity]
    amount: Annotated[float, Min(0), WithPrometheus(buckets=(1, 10, 100, 1000, 10000))]
    currency: Annotated[str, OneOf("USD", "EUR", "GBP")]
    status: Annotated[str, OneOf("pending", "completed", "failed"), WithGraphQL()]
```

The meta-compiler:

```python
def compile_adaptive(entities: list[type]) -> dict[type, EntityCompilation]:
    """Each entity declares its compiler. We build it. Then use it."""
    results: dict[type, EntityCompilation] = {}

    for entity in entities:
        # Fold 1: entity tells us what phases it needs
        compiler_ctx = fold_schema(entity, CompilerCtx(), CompilerCompilable, "compile_compiler")

        # Fold 2: assemble SchemaCompiler from requirements (algebra: + unions phases)
        compiler = FASTAPI_SCHEMA
        for phase in compiler_ctx.phases:
            compiler = compiler + phase

        # Fold 3: compile entity with its self-assembled compiler
        results[entity] = compiler.compile(entity, axes)

    return results
```

`Payment.amount` has `WithPrometheus` → compiler includes `PROMETHEUS_PHASE` → `amount` compiles to histogram config. `Payment.status` has `WithGraphQL` → compiler includes `GRAPHQL_PHASE` → `status` compiles to GraphQL type. Fields that DON'T have these capabilities → phases skip them (open-world).

No global config. No "enable_graphql = True". Each field says what it needs.

## Level 3: Entity graph as compilation unit

Individual entities compile to endpoints. A *graph* of entities compiles to a system.

```python
@dataclass(frozen=True, slots=True)
class EntityNode:
    entity: type
    refs: Mapping[str, type]  # field_name → target entity

@dataclass(frozen=True, slots=True)
class SystemCtx:
    nodes: tuple[EntityNode, ...] = ()
    edges: tuple[tuple[type, str, type], ...] = ()

@runtime_checkable
class SystemCompilable(Protocol):
    def compile_system(self, ctx: SystemCtx) -> SystemCtx: ...

@dataclass(frozen=True, slots=True)
class RegisterEntity(UniversalCapability):
    """An entity that participates in system compilation."""
    node: EntityNode

    def compile_system(self, ctx: SystemCtx) -> SystemCtx:
        new_edges = tuple((self.node.entity, f, t) for f, t in self.node.refs.items())
        return replace(ctx, nodes=(*ctx.nodes, self.node), edges=(*ctx.edges, *new_edges))
```

Three entities form a graph:

```python
@dataclass
class Author:
    id: Annotated[int, Identity]
    name: str
    bio: str

@dataclass
class Book:
    id: Annotated[int, Identity]
    title: str
    author_id: Annotated[int, Ref(Author)]
    price: Annotated[float, Min(0)]

@dataclass
class Review:
    id: Annotated[int, Identity]
    book_id: Annotated[int, Ref(Book)]
    rating: Annotated[int, Min(1), Max(5)]
    text: str
```

System fold:

```python
system = fold(registrations, SystemCtx(), SystemCompilable, "compile_system")
# system.edges = [(Book, "author_id", Author), (Review, "book_id", Book)]
```

Now this graph is frozen data. It compiles to multiple targets — each a different fold:

```python
# Target 1: SQL migration ordering
@dataclass(frozen=True, slots=True)
class MigrationCtx:
    order: tuple[type, ...] = ()
    sql: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class MigrationStep(Capability):
    node: EntityNode
    deps: tuple[type, ...]

    def compile_migration(self, ctx: MigrationCtx) -> MigrationCtx:
        # Topological: deps first, then self
        return replace(ctx,
            order=(*ctx.order, self.node.entity),
            sql=(*ctx.sql,
                f"CREATE TABLE {self.node.entity.__name__.lower()}s (...);",
                *(f"  FOREIGN KEY ({f}) REFERENCES {t.__name__.lower()}s(id)"
                  for f, t in self.node.refs.items()),
            ),
        )

# Target 2: GraphQL resolvers
@dataclass(frozen=True, slots=True)
class GraphQLResolverCtx:
    resolvers: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class ResolverStep(Capability):
    node: EntityNode

    def compile_graphql_resolver(self, ctx: GraphQLResolverCtx) -> GraphQLResolverCtx:
        new_resolvers = tuple(
            f"{self.node.entity.__name__}.{field} → fetch {target.__name__} by id"
            for field, target in self.node.refs.items()
        )
        return replace(ctx, resolvers=(*ctx.resolvers, *new_resolvers))

# Target 3: Test fixture graph
@dataclass(frozen=True, slots=True)
class FixtureCtx:
    fixtures: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class FixtureStep(Capability):
    node: EntityNode

    def compile_fixture(self, ctx: FixtureCtx) -> FixtureCtx:
        deps = ", ".join(t.__name__ for t in self.node.refs.values())
        line = (f"create {self.node.entity.__name__} (needs: {deps})"
                if deps else f"create {self.node.entity.__name__}")
        return replace(ctx, fixtures=(*ctx.fixtures, line))
```

Same graph, three folds, three outputs:

```python
migration = fold(migration_steps, MigrationCtx(), MigrationCompilable, "compile_migration")
resolvers = fold(resolver_steps, GraphQLResolverCtx(), ..., "compile_graphql_resolver")
fixtures  = fold(fixture_steps, FixtureCtx(), ..., "compile_fixture")
```

No ORM. No GraphQL library. No test framework. Just frozen data → fold → output.

## Level 4: Services as items

Services are entities-of-entities. The same fold that compiled fields into entity contexts now compiles entities into service contexts, and services into fleet contexts.

```python
@dataclass(frozen=True, slots=True)
class ServiceDef:
    name: str
    entities: tuple[type, ...]
    base_url: str

@dataclass(frozen=True, slots=True)
class FleetCtx:
    services: tuple[ServiceDef, ...] = ()
    contracts: tuple[tuple[str, str, str, str], ...] = ()  # (from_svc, field, to_svc, entity)
    gateway_routes: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class ServiceRegistration(UniversalCapability):
    svc: ServiceDef

    def compile_fleet(self, ctx: FleetCtx) -> FleetCtx:
        return replace(ctx,
            services=(*ctx.services, self.svc),
            gateway_routes=(*ctx.gateway_routes,
                *(f"/{e.__name__.lower()}s → {self.svc.base_url}" for e in self.svc.entities),
            ),
        )
```

```python
fleet = fold([
    ServiceRegistration(ServiceDef("users", (User, UserProfile), "http://users:8000")),
    ServiceRegistration(ServiceDef("orders", (Order, OrderItem), "http://orders:8001")),
    ServiceRegistration(ServiceDef("catalog", (Product, Category), "http://catalog:8002")),
], FleetCtx(), FleetCompilable, "compile_fleet")

# fleet.gateway_routes = [
#   "/users → http://users:8000",
#   "/userprofiles → http://users:8000",
#   "/orders → http://orders:8001",
#   "/orderitems → http://orders:8001",
#   "/products → http://catalog:8002",
#   "/categorys → http://catalog:8002",
# ]
```

Three services, six routes, zero config files. Add a service → add a `ServiceRegistration`. Add an entity to a service → route appears. Remove → route disappears. Gateway config compiled from entity graph.

## Level 5: Time as compilation axis

Everything so far compiles at one point in time. But entity schemas change. The diff between two schema versions is *also* frozen data. So it folds.

```python
@dataclass(frozen=True, slots=True)
class FieldAdded:
    entity: str
    field: str
    field_type: type
    caps: tuple[Capability, ...]

    def compile_evolution(self, ctx: EvolutionCtx) -> EvolutionCtx:
        stmts = [f"ALTER TABLE {self.entity}s ADD COLUMN {self.field} {_sql_type(self.field_type)};"]
        # Capabilities carry constraints — compile them to SQL CHECK
        for cap in self.caps:
            match cap:
                case Min(value=v): stmts.append(f"  CHECK ({self.field} >= {v})")
                case MaxLen(value=v): stmts.append(f"  -- varchar({v})")
                case _: pass
        rollback = f"ALTER TABLE {self.entity}s DROP COLUMN {self.field};"
        return replace(ctx,
            forward=(*ctx.forward, *stmts),
            backward=(*ctx.backward, rollback),
        )

@dataclass(frozen=True, slots=True)
class FieldRemoved:
    entity: str
    field: str

    def compile_evolution(self, ctx: EvolutionCtx) -> EvolutionCtx:
        return replace(ctx,
            forward=(*ctx.forward, f"ALTER TABLE {self.entity}s DROP COLUMN {self.field};"),
            backward=(*ctx.backward, f"-- CANNOT auto-restore {self.entity}.{self.field}"),
        )

@dataclass(frozen=True, slots=True)
class ConstraintTightened:
    entity: str
    field: str
    old_cap: Capability
    new_cap: Capability

    def compile_evolution(self, ctx: EvolutionCtx) -> EvolutionCtx:
        return replace(ctx,
            forward=(*ctx.forward,
                f"-- Validate: all {self.entity}s.{self.field} must satisfy {self.new_cap}",
                f"DELETE FROM {self.entity}s WHERE NOT ({_sql_check(self.field, self.new_cap)});",
            ),
            backward=(*ctx.backward,
                f"-- Constraint was: {self.old_cap}",
            ),
        )
```

Usage — add a field to User in v2:

```python
# v1
class User:
    id: Annotated[int, Identity]
    name: str

# v2
class User:
    id: Annotated[int, Identity]
    name: str
    role: Annotated[str, OneOf("admin", "user", "mod")]  # NEW

diffs = [FieldAdded("User", "role", str, (OneOf("admin", "user", "mod"),))]
evolution = fold(diffs, EvolutionCtx(), EvolutionCompilable, "compile_evolution")

# evolution.forward = [
#   "ALTER TABLE Users ADD COLUMN role VARCHAR;",
#   "  -- varchar constraint from OneOf"
# ]
# evolution.backward = [
#   "ALTER TABLE Users DROP COLUMN role;"
# ]
```

The diff items carry their constraints. `OneOf("admin", "user", "mod")` on the new field → evolution compiler generates CHECK constraint. The capability doesn't just describe the field — it describes the *migration*.

Forward + backward = saga. `saga.run(evolution_plan)` executes with automatic rollback.

## Level 6: The loop

System runs. Produces metrics. Metrics are frozen data. Frozen data folds.

```python
@dataclass(frozen=True, slots=True)
class SlowEndpoint:
    entity: str
    path: str
    p99_ms: float

    def compile_insight(self, ctx: InsightCtx) -> InsightCtx:
        return replace(ctx, capabilities=(*ctx.capabilities,
            (self.entity, Cached(ttl=int(self.p99_ms / 100))),
        ))

@dataclass(frozen=True, slots=True)
class HotField:
    entity: str
    field: str
    queries_per_sec: float

    def compile_insight(self, ctx: InsightCtx) -> InsightCtx:
        return replace(ctx, capabilities=(*ctx.capabilities,
            (self.entity, Index(f"idx_{self.entity}_{self.field}")),
        ))

@dataclass(frozen=True, slots=True)
class FrequentPattern:
    entity: str
    filter_fields: tuple[str, ...]

    def compile_insight(self, ctx: InsightCtx) -> InsightCtx:
        idx_name = f"idx_{'_'.join(self.filter_fields)}"
        return replace(ctx, capabilities=(*ctx.capabilities,
            (self.entity, CompositeIndex(idx_name, self.filter_fields)),
        ))
```

Observations → capabilities:

```python
observations = [
    SlowEndpoint("User", "/users", p99_ms=850),
    HotField("Order", "user_id", queries_per_sec=5000),
    FrequentPattern("Order", ("status", "created_at")),
]

insights = fold(observations, InsightCtx(), InsightCompilable, "compile_insight")
# insights.capabilities = [
#   ("User", Cached(ttl=8)),
#   ("Order", Index("idx_Order_user_id")),
#   ("Order", CompositeIndex("idx_status_created_at", ("status", "created_at"))),
# ]
```

Each observation is a capability. Each capability compiles to a recommendation. Recommendations are capabilities for entities. Apply them → recompile → deploy → observe → fold → recommend → apply → recompile.

No `if latency > threshold`. No heuristic scoring. Each observation type has ONE compile method that produces ONE capability. The mapping is declarative and extensible — add a new observation type, implement `compile_insight`, fold picks it up.

## The stacking

Here's what happens when you run all levels together:

```
Level 0: User entity
  → fold field caps → Pydantic + OpenAPI + Storage + Verify contexts

Level 1: User has Journaled()
  → fold augment → UserJournal entity spawned
  → UserJournal goes through Level 0 → its own endpoints

Level 2: User field has WithPrometheus()
  → fold compiler caps → SchemaCompiler assembled with PROMETHEUS_PHASE
  → User compiled with Prometheus phase → histogram config

Level 3: Order.user_id has Ref(User)
  → fold entity graph → SystemCtx with edges
  → SystemCtx → migration order + resolvers + fixtures

Level 4: user-service has (User, UserJournal), order-service has (Order)
  → fold services → FleetCtx with gateway routes + contracts

Level 5: User v2 adds "role" field
  → fold diffs → evolution plan (forward + backward SQL)
  → evolution plan IS a saga → execute atomically

Level 6: /users endpoint slow
  → fold observation → Cached(ttl=8) recommended for User
  → apply → User recompiles with cache → Level 0 runs again
```

Six folds stacked. Each uses the output of the previous. Each is `fold(items, ctx, protocol, method)`. No orchestration code. No glue. Just frozen data flowing through fold.

## Why this isn't abstraction

Every level shown here uses emergent's actual `fold` function from `_core.py`. Every capability is a frozen dataclass with a `compile_*` method. Every protocol is `@runtime_checkable`. Every context is `@dataclass(frozen=True, slots=True)` accumulated via `replace()`.

The code at Level 4 looks exactly like the code at Level 0. Because it IS the same code. Same function, applied to different data at a different scale.

This is why emergent is a platform: the mechanism doesn't change when the problem gets bigger. You define new items, new contexts, new protocols. The fold does the rest.
