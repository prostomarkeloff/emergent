# Architecture: The Theory Behind emergent

This document explains **why** emergent's architecture works, not what it contains. For the "what", see `wire-reference.md`, `universal-derivation.md`, and `intro.md`. This document is about the structural invariants, the algebraic properties, and the design decisions that make the entire stack -- from `kungfu`'s `Result[T, E]` through `combinators.py`'s `Interp[T, E]` through `nodnod`'s auto-parallelizing graphs to `emergent.wire`'s multi-target compilation -- work as a coherent whole.

---

## 1. The Tower as Successive Constraint

The stack is not six independent libraries that happen to work together. It's a tower where each layer **constrains** the layer above, and each constraint enables the layer above to do less manually and get more for free.

```
Level 6: YOUR CODE           — business logic, domain invariants
Level 5: emergent            — domain patterns (saga, cache, graph, wire)
Level 4: nodnod              — programs as dependency graphs
Level 3: combinators.py      — resilience (retry, timeout, fallback, race)
Level 2: kungfu              — explicit errors (Result[T, E], Option[T])
Level 1: Python 3.13         — type foundations (unions, protocols)
```

The deep structure: each layer is a **free construction** over the constraints established by the layer below.

**Level 2 (kungfu)** constrains errors to be values. No exceptions for domain logic. `Result[T, E]` forces every function to declare its failure modes in the type signature. This constraint eliminates an entire class of bugs (uncaught exceptions) and enables everything above: you can't retry an exception you didn't know existed, you can't race computations whose failures are invisible.

**Level 3 (combinators.py)** constrains effects to be lazy and composable. `Interp[T, E]` (alias for `LazyCoroResult[T, E]`) is a **suspended** computation -- it doesn't run until you `await L.down.to_result(...)`. This laziness is the constraint that makes composition possible: `flow(L.call(f)).retry(times=3).timeout(seconds=5).compile()` builds an AST first, interprets it second. If `L.call(f)` ran eagerly, retry couldn't re-execute it. The laziness constraint enables the free algebra of resilience combinators.

**Level 4 (nodnod)** constrains dependencies to be type-declared. A node's `__compose__` signature **is** its dependency declaration. `async def __compose__(cls, db: Database, user: CurrentUser) -> Profile` means "I need a Database and a CurrentUser." The type system is the constraint; the framework extracts the dependency graph from signatures and schedules execution with automatic parallelization. No manual orchestration, no container configuration, no provider registration.

**Level 5 (emergent.wire)** constrains application topology to axes + capabilities. Instead of scattering behavior across decorators, middleware, config files, and string-keyed registries, all behavior flows through typed capabilities folded through typed contexts. The constraint is structural: if it's not a capability, it can't influence compilation. This makes the system closed under composition and open for extension simultaneously.

Each constraint **removes a degree of freedom** from the layer above. The removed freedom is exactly the one that causes bugs: uncaught exceptions, eager side effects, implicit dependencies, string-keyed configuration. What remains is the freedom to compose safely.

---

## 2. Defunctionalization as Foundation

The intro says "defunctionalization" and moves on. The implication runs deeper than it looks.

Every consumer of emergent does the same move: take something that would normally be a **callback** or **behavior** and turn it into **inert data**.

- A capability like `MaxLen(50)` is not a function that validates. It's a **description** of a constraint that each compiler interprets differently. The Pydantic compiler reads it as `max_length=50`. The OpenAPI compiler reads it as `maxLength: 50`. The argparse compiler could add a length check. The capability doesn't know and doesn't care which compilers exist.

- An `Op` in algosik isn't an instruction that executes. It's a **reified intention** that the Python interpreter evaluates recursively and the LLVM backend compiles to native machine code.

- An `OpSpec` in wire.derive isn't a code generator. It's a **specification** of what to generate, inspectable before any types are materialized.

- A `Workload` in deployme isn't a running process. It's a **description** of a deployment unit that the compose compiler renders to a docker-compose dict and the uvicorn target runs directly.

This is why `explain()` exists everywhere for free. When your program is data, introspection is just reading fields. When your program is functions, introspection requires tracing, reflection, or source analysis. The architecture chose data over functions at every junction, and that single choice cascades into everything else: composability, serializability, tracing, testing, multi-target compilation.

The converse also holds: **if you can't explain it, you defunctionalized wrong.** Every IR node in emergent can be printed, compared, serialized to a dict, and fed to an explain function. This isn't a nice-to-have; it's a structural test that the defunctionalization is complete.

The defunctionalization runs through the entire tower:

- **combinators.py**: `flow(L.call(f)).retry(times=3).timeout(seconds=5)` doesn't retry or time out anything. It builds a `Flow` AST -- a data structure describing the pipeline. `.compile()` interprets the AST into a concrete `Interp`. The retry policy, the timeout duration, the fallback chain -- all are data, not behavior, until the moment of execution.

- **nodnod**: A node's `__compose__` signature is not an imperative "fetch this, then fetch that." It's a **declaration** of what types are needed. The EventLoopAgent reads these declarations, builds a dependency graph, topologically sorts it, and schedules execution. The function body runs; the scheduling is derived from the defunctionalized signature.

- **wire**: A `MaxLen(50)` capability is not a validator. It's a datum that compilers interpret. The `Application` IR is not a running server. It's a topology that compilers project into framework artifacts.

---

## 3. Free Algebras and Catamorphisms

The surface pattern across all consumers is "fold frozen dataclasses through a context." The reason this works universally is algebraic.

### The free algebra

A **free algebra** over a set of generators is the most general structure you can build from those generators with no laws except the minimum structural ones (associativity of concatenation, existence of empty). In emergent:

- **Capabilities** are generators. `MaxLen(50)`, `sql.Index()`, `cli.Help("name")`, `tg.Bold()` are atoms.
- **A capability tuple** `(MaxLen(50), sql.Index(), cli.Help("name"))` is an element of the free monoid over those generators. Concatenation is the operation, empty tuple is the identity.
- **No laws** hold between generators. `MaxLen` knows nothing about `sql.Index`. They don't interact, don't conflict, don't have ordering constraints within an axis.

This is the key property. Because the algebra is **free**, capabilities compose without interference. You never get "MaxLen conflicts with Index" or "Help must come before Bold." The generators are independent by construction.

### The catamorphism

A **catamorphism** (fold) is the unique way to consume a free algebra by mapping each generator to an operation on some target structure. In emergent, the target structure is a compilation context:

```
fold(capabilities, initial_context, dispatch) -> final_context
```

Every interpretation of every IR in emergent is a catamorphism:

| Module | Free algebra | Catamorphism | Target |
|--------|-------------|--------------|--------|
| combinators.py | Flow AST nodes | `.compile()` / `.lower()` | `Interp[T, E]` (executable) |
| nodnod | node set + signatures | `EventLoopAgent.run(scope)` | resolved scope with values |
| wire.compile | capability tuple | `fold(caps, PydanticContext, "compile_pydantic")` | Pydantic field config |
| wire.query | query op list | `MEMORY_DIALECT.fold(ops, data)` | filtered/sorted list |
| wire.derive | capability tuple | `compile_derive(Entity)` | DeriveCtx |
| deployme | capability tuple | `fold(caps, ComposeCtx, handlers)` | compose service dict |
| algosik | op list | `interpret(ops, data)` or `compile_compute(ops)` | Python list or LLVM IR |

This is not a metaphor. It's the literal algebraic structure. The reason `fold` appears in every module is that it's the **only** thing you can do with a free algebra: interpret its generators one by one through a homomorphism. Any other operation on the algebra factors through a fold.

### Why this matters

The practical consequence: **to add a new capability, you don't touch any existing code.** You define a new generator (frozen dataclass), implement its `compile_*` methods (the homomorphism image), and every fold that checks the right protocol picks it up. To add a new compiler, you define a new fold with a new context type. The algebra doesn't change; you just add a new interpretation.

This is the expression problem solved structurally, not by clever dispatch tricks.

---

## 4. The Expression Problem: Two Dispatch Styles

emergent uses two dispatch mechanisms, and the choice per module is not arbitrary.

### Protocol dispatch (wire.compile, wire.derive)

Capabilities carry their own `compile_pydantic()`, `compile_openapi()`, `compile_argparse()` methods. The fold checks `isinstance(cap, PydanticCompilable)` and calls the method.

This is **open on the data side**: anyone adds a new capability with its own compile methods, and existing compilers pick it up via isinstance. But adding a new compiler target requires every capability that wants to participate to implement a new method.

### Handler-dict dispatch (deployme, wire.query)

The compiler owns a `Mapping[type, handler]` and looks up each capability by its type. The fold does `handlers.get(type(cap))` and calls the handler.

This is **open on the interpreter side**: anyone writes a new compiler with its own handler table. But adding a new capability type requires updating every compiler's table.

### extract/wrap dispatch (combinators.py)

The `*M` generic combinators take `extract: Raw -> Result[T, E]` and `wrap: (-> Raw) -> M`. This is a **natural transformation** between monads. Every combinator is written once against `extract`/`wrap`, then instantiated per monad:

- `retry(interp, policy)` = `retryM(interp, extract=identity, wrap=LazyCoroResult, policy=policy)`
- `retry_writer(interp, policy)` = `retryM(interp, extract=extract_writer_result, wrap=wrap_lazy_coro_result_writer, policy=policy)`

This is **open on the monad side**: add a new monad (a new `extract`/`wrap` pair), and every combinator works with it. But adding a new combinator requires implementing the generic `*M` version.

### Why each module chose what it chose

**wire** chose protocol dispatch because capabilities proliferate (dozens of schema annotations: `MaxLen`, `Min`, `Pattern`, `OneOf`, `Unique`, `Identity`, `ReadOnly`, `Sensitive`, `Ref`, `Nested`, `Embedded`, plus every dialect...) while compilers are few and stable (Pydantic, OpenAPI, argparse, SQLAlchemy, telegrinder). The cost of "add a method per compiler to a new capability" is small. The cost of "update every capability when adding a compiler" would be large, but new compilers are rare.

**deployme** chose handler-dict dispatch because infrastructure targets proliferate (compose, k8s, nomad, local, testing...) while capabilities are stable (`Port`, `Volume`, `Image`, `HealthCheck`, `Replicas` -- these don't change often). The cost of "add a handler to a new compiler's table" is small. The cost of "add compile methods for every target to a new capability" would be wasteful.

**wire.query** chose handler-dict dispatch (`QueryDialect.handlers`) because query interpreters proliferate (memory, SQL, HTTP API, explain, custom) while query ops are stable (Filter, OrderBy, Limit, Offset, Select, Join...).

**combinators.py** chose extract/wrap because monads proliferate (Interp, Writer, future custom monads) while combinators are stable (retry, fallback, timeout, race, batch, traverse...).

The architecture picks the right solution to the expression problem **per module** based on which axis grows faster. This is a deliberate design choice, not an accident.

---

## 5. combinators.py: The Free Monad of Resilience

`combinators.py` looks like a utility library (retry, timeout, fallback). It's actually the place where the stack's defunctionalization principle first manifests as a user-facing API.

### Interp as suspended computation

`Interp[T, E]` (alias `LazyCoroResult[T, E]`) wraps `Callable[[], Coroutine[Any, Any, Result[T, E]]]`. It's a **thunk** -- a computation that hasn't happened yet. Nothing runs until you `await L.down.to_result(interp)`.

This laziness is not incidental. It's the **enabling constraint** for everything else. Retry can only re-execute a computation if execution is deferred. Race can only run two computations concurrently if neither has started. Fallback can only try a secondary if the primary hasn't consumed shared resources. Laziness turns "do this thing" into "here's a plan for doing this thing," and plans can be composed before execution.

### Flow as free structure

`flow(L.call(f)).retry(times=3).timeout(seconds=5).compile()` is not three nested function calls. It's an **AST construction** followed by **interpretation**:

1. `flow(L.call(f))` creates a `Flow` node wrapping the initial Interp.
2. `.retry(times=3)` appends a Retry node to the AST.
3. `.timeout(seconds=5)` appends a Timeout node.
4. `.compile()` folds the AST into a concrete `Interp[T, E]`.

The Flow AST is a free structure. Its nodes (retry, timeout, tap, ensure, recover, race_ok, delay, rate_limit, repeat_until) are generators. `.compile()` is the catamorphism that interprets them into nested `Interp` wrappers. Before `.compile()`, the pipeline is inspectable data. After, it's an executable thunk.

This is the same build-then-interpret pattern seen everywhere else in the stack. The only difference is what's being described: here it's resilience policy, not compilation targets or database queries.

### Error types as constraint propagation

Combinators transform error types:
- `timeout` adds: `E -> E | TimeoutError`
- `recover` eliminates: `E -> Never`
- `repeat_until` adds: `E -> E | ConditionNotMetError`
- `validate` collects: `E -> list[E]`

These are not arbitrary. They're **type-level proofs** of what the combinator does. `timeout` can fail with a new error (TimeoutError), so the type expands. `recover` handles all errors, so the type collapses to `Never`. Pyright enforces this at compile time. You can't forget to handle a timeout error because the type system won't let you.

This is the deepest payoff of Level 2's constraint (errors are values): because errors are in the type signature, combinators that modify error behavior are forced to declare it in their return type. The type system becomes a **constraint propagation engine** for error handling.

---

## 6. nodnod: Types as Graph Edges

nodnod looks like a dependency injection framework. It's actually a **compiler from type signatures to parallel execution plans**.

### The graph is implicit

Traditional DI frameworks require explicit registration: "bind `Database` to `PostgresDatabase`", "bind `Cache` to `RedisCache`". nodnod requires nothing. The graph is implicit in the type signatures:

```python
class ProfileNode(Node):
    @classmethod
    async def __compose__(cls, db: Database, user: CurrentUser) -> ProfileNode: ...

class LoyaltyNode(Node):
    @classmethod
    async def __compose__(cls, db: Database, user: CurrentUser) -> LoyaltyNode: ...

class CheckoutNode(Node):
    @classmethod
    async def __compose__(cls, profile: ProfileNode, loyalty: LoyaltyNode) -> CheckoutNode: ...
```

This IS the graph:
```
Database ──┬──> ProfileNode ──┐
           │                  ├──> CheckoutNode
CurrentUser┼──> LoyaltyNode ──┘
           │
           └──> (shared)
```

No graph builder. No adjacency list. No registration. The `__compose__` parameter types **are** the edges. `EventLoopAgent.build({CheckoutNode})` reads the signatures, extracts the types, constructs the DAG, checks for cycles, and topologically sorts -- all from type annotations.

This is defunctionalization applied to dependency graphs: instead of manually building a DAG object, you declare dependencies in function signatures (data), and the framework extracts the graph (interpretation).

### Automatic parallelization as topological interpretation

`EventLoopAgent.run()` doesn't execute nodes sequentially. It creates an `asyncio.Task` for each node and `asyncio.gather()`s the results. Nodes whose dependencies are satisfied run concurrently. In the example above, `ProfileNode` and `LoyaltyNode` both depend only on `Database` and `CurrentUser` (which are available from the parent scope), so they run **in parallel**. `CheckoutNode` waits for both to complete.

This is another fold. The free structure is the set of nodes with their type-declared dependency edges. The catamorphism (EventLoopAgent) interprets it into a concurrent execution plan:

1. Topological sort: determine execution layers.
2. For each layer: create Tasks for all nodes in that layer.
3. `asyncio.gather()`: run the layer concurrently.
4. Store results in scope.
5. Next layer sees results from previous layers.

The parallelization is not heuristic or best-effort. It's **optimal**: every node runs at the earliest possible moment given its dependencies. No manual `asyncio.gather()` calls, no manual dependency ordering, no "await this before that" logic.

### Scope as runtime value store

nodnod's `Scope` forms parent-child chains: `global_scope -> request_scope -> nested_scope`. A `scope.retrieve(Type)` call walks up the chain until it finds a value. Once a node is composed, its value lives in the scope keyed by type. If `ProfileNode` and `LoyaltyNode` both depend on `CurrentUser`, nodnod resolves `CurrentUser` **once** and shares the instance. This is structural sharing in a DAG, enforced by the scope's type-keyed store.

### Either nodes as lattice operations

nodnod's `SequentialEither` and `ConcurrentEither` are lattice operations on the node space:

- `SequentialEither` is a **fallback chain**: try variant 1, if it fails try variant 2, etc. This is `combinators.py`'s `fallback_chain` lifted to the graph level.

- `ConcurrentEither` is a **race**: run all variants concurrently, first success wins. This is `combinators.py`'s `race_ok` lifted to the graph level.

The fact that these correspond exactly to Level 3 combinators is not coincidence. nodnod (Level 4) builds on combinators.py (Level 3). The graph-level operations are the point-free versions of the combinator-level operations: instead of explicitly writing `race_ok(fetch_from_cache, fetch_from_db)`, you declare `class Data(ConcurrentEither): __either__ = (CacheData, DBData)` and the graph handles it.

---

## 7. emergent.graph: Bridging Compile-Time Topology and Runtime Execution

nodnod is powerful but raw. Its `Scope` is a flat runtime container -- it knows nothing about application tiers, lifetime hierarchies, or which types belong at which level. emergent's `graph` module and wire's `ScopeLayer`/`ScopeFamily`/`Tier` system build a **compile-time description of scope topology** that nodnod materializes at runtime.

### The problem nodnod doesn't solve

nodnod gives you `Scope` and `Agent`. You can create child scopes, inject values, compose nodes. But it doesn't answer:

- Which types should live in the application-scoped singleton vs. the per-request scope?
- When a request arrives, which nodes need composing and which are already available from the parent?
- How does a wire compiler know which nodnod types to resolve during request handling?

These are **compile-time topology** questions. nodnod is a runtime engine; it doesn't have a compile phase. emergent fills this gap.

### Tier and ScopeFamily: the compile-time description

Wire defines `Tier` as a frozen dataclass representing a lifetime level:

```python
App = Tier()                 # application-scoped
Request = Tier(parent=App)   # request-scoped
```

`ScopeFamily[Tier]` is the **algebra of type-to-tier bindings**:

```python
family = (
    ScopeFamily[Tier]()
    .bind(App, DBPool, Config)           # these live at app level
    .bind(Request, CurrentUser, AuthToken)  # these live at request level
)
```

This is a compile-time data structure. It doesn't create scopes or compose nodes. It describes **which types belong where**. The `|` operator merges families (right-biased on conflicts), `.unbind()` removes bindings, `.types_for(tier)` projects one tier's types, `.tier_of(type)` looks up a type's tier. Pure algebra on immutable bindings.

### ScopeLayer: the compile/runtime bridge

`ScopeLayer` is the frozen dataclass that wire compilers receive. It bundles the compile-time family with runtime scope references:

```python
layer = ScopeLayer(
    scopes={App: app_scope},        # pre-existing runtime scopes
    family=family,                  # compile-time bindings
    leaf=Request,                   # the tier created per-execution
)
```

At compile time, the compiler reads `layer.compose` (= `family.types_for(Request)`) to know which node types need composing per-request. At runtime, `layer.parent` walks the tier chain upward to find the nearest available scope (Request -> App -> found). The `Composer` wraps this into a single object that a handler can use:

```python
composer = Composer.create(request_scope, agent_cls=EventLoopAgent)
ok, user = await composer.compose(CurrentUser)
```

### Why this matters architecturally

The pattern is the same compile/execute staging seen everywhere else in the stack:

| Compile-time (wire) | Runtime (nodnod) |
|---|---|
| `Tier(parent=App)` | `app_scope.create_child("request")` |
| `ScopeFamily.bind(App, DBPool)` | `app_scope.inject(DBPool, pool)` |
| `ScopeLayer(family=..., leaf=Request)` | `Composer.create(req_scope)` |
| `layer.compose -> frozenset of types` | `agent.run(local_scope=req_scope)` |

The compile-time structures (Tier, ScopeFamily, ScopeLayer) are frozen dataclasses -- inspectable, composable, explainable. The runtime structures (Scope, Agent, Composer) are the execution. emergent.graph is the bridge between the two: it takes wire's declarative topology and nodnod's runtime engine and wires them together so that compilers can emit correct request-handling code without knowing the specifics of either.

### ScopeFamily as composable algebra

`ScopeFamily` supports `|` (merge), `.bind()`, `.unbind()`, `.types_for()`, `.tier_of()`, `.to_groups()`, `.materialize()`. This is a **composable algebra on type-to-tier mappings**, following the same pattern as capability tuples (free monoid) and query ops (free structure). Different parts of the application declare their own families:

```python
auth_family = ScopeFamily[Tier]().bind(Request, AuthUser, AuthToken)
db_family = ScopeFamily[Tier]().bind(App, DBPool).bind(Request, DBSession)
app_family = auth_family | db_family
```

Families compose via `|`. The merged family is what the compiler sees. This is the same "many small descriptions merged into one, then interpreted" pattern that appears in every other part of emergent.

---

## 8. Axes as Orthogonal Dimensions

The four axes (schema, surface, storage, query) are not layers stacked on each other. They are **orthogonal dimensions of a product space**.

A field like:
```python
Annotated[str, MaxLen(50), sql.Index(), cli.Help("name"), tg.Bold(), api.Filterable()]
```

is a single point in the space `Schema x Surface x Storage x Query`. Each compiler is a **projection** that extracts one coordinate and ignores the rest.

### Why orthogonality matters

Capabilities from different axes never interact. The fold for `PydanticContext` skips `cli.Help` because it doesn't implement `PydanticCompilable`. The fold for `ArgparseContext` skips `sql.Index` because it doesn't implement `ArgparseCompilable`. This is guaranteed structurally by the protocol check, not by convention or documentation.

This means:
- **No ordering constraints between axes.** You can put `sql.Index()` before or after `cli.Help()` in the annotation tuple; the result is identical.
- **No cross-axis interference.** Adding a SQL capability never breaks CLI compilation. Adding a Telegram rendering hint never affects OpenAPI schema generation.
- **Independent evolution.** The SQL dialect can add new capabilities without touching CLI, OpenAPI, Pydantic, or Telegram code.

### The schema axis as diagonal

wire.derive's three-phase compilation reveals something subtle. Phase 1 (Generate) reads the entity schema to produce OpSpecs. Phase 2 (Modify) rewrites OpSpecs via transforms. Phase 3 (Augment) post-processes. All phases read from the schema axis.

Schema is the **diagonal** of the product space. It's read by every other axis but written by none of them during compilation. This is why schema must resolve first: it establishes the shared coordinate system that surface, query, and storage project from.

---

## 9. Capability Commutativity and Its Limits

Capabilities within an axis are **commutative**. The order in which they appear in the annotation tuple doesn't affect the compilation result.

This sounds like a minor convenience, but it's a structural guarantee that distinguishes capabilities from middleware chains or mixin inheritance:

- **Middleware chains** are order-dependent. `auth -> rate_limit -> handler` differs from `rate_limit -> auth -> handler`. Reordering changes behavior. Composition is fragile.

- **Mixin inheritance** is order-dependent. Method resolution order (MRO) depends on class order. `class Foo(AuthMixin, CacheMixin)` differs from `class Foo(CacheMixin, AuthMixin)`.

- **Capabilities** are order-independent within an axis. `Annotated[str, MaxLen(50), Unique()]` and `Annotated[str, Unique(), MaxLen(50)]` produce identical compilation results. Each capability writes to an **independent part** of the context. `MaxLen` sets `max_length` on the Pydantic context. `Unique` sets constraints on the SQL context. They don't touch the same fields, so order is irrelevant.

This commutativity is enforced by the fold structure: each capability receives the context and returns a new context with its specific fields updated via `dataclasses.replace()`. As long as capabilities target different context fields (which they do by design -- each capability "owns" specific context fields), the fold is commutative.

The practical consequence: you never debug "capability ordering bugs." There's no emergent interaction between capabilities that depends on who runs first. The system is compositional in the strong sense: the meaning of a combination is determined entirely by the meanings of the parts.

### ScopeEnricher: where commutativity breaks

Not all capabilities are pure compile-time context transforms. `ScopeEnricher` is a `SurfaceCapability` that operates at **runtime**, not compile-time. Its protocol is:

```python
async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R
```

This is a middleware signature: receive the next handler in the chain, the current scope, decide whether to continue or short-circuit. `Provide`, the most important enricher, runs an op, and on success injects the result into the scope and calls next; on error, returns an error response without calling the handler at all.

Enrichers break the commutativity property. They are **chained**, not folded:

```python
chain_enrichers(enrichers, core_handler)
# → enricher_1(enricher_2(enricher_3(core_handler)))
```

Order matters. An auth enricher must run before a permissions enricher that reads the authenticated user from scope. A rate-limit enricher wrapping an auth enricher differs from an auth enricher wrapping a rate-limit enricher.

This is a deliberate architectural choice, not a flaw. The system distinguishes between two kinds of surface capabilities:

1. **Compile-time capabilities** (`Tag`, `BearerAuth`, `Summary`, `CORS`, `Deprecated`...) -- pure `Context -> Context` transforms. Commutative. Folded at compile time. Affect the framework artifact (OpenAPI tags, route metadata, middleware registration). No runtime behavior.

2. **Runtime capabilities** (`ScopeEnricher` implementations like `Provide`, auth enrichers, validators) -- async middleware. Non-commutative. Chained at runtime around the core handler. Affect the execution flow (short-circuit, inject, transform).

The bridge between the two worlds is `HandlerRuntimeContext`: a frozen dataclass populated by a **compile-time fold** over surface capabilities. Each enricher implements `compile_handler_runtime()` which appends itself to the context's `enrichers` tuple. This fold is pure and commutative (it just accumulates a tuple). But the tuple is then interpreted at runtime as an ordered middleware chain. The compile-time fold collects; the runtime chain executes.

This is the same staging pattern: compile-time produces data (the enricher tuple), runtime interprets it (middleware chaining). But unlike pure capabilities where the fold IS the final interpretation, enrichers have two stages: fold-to-collect, then chain-to-execute. The first stage is commutative; the second is not.

---

## 10. Staging: Why Two Phases

Every consumer separates a sync/pure phase from an async/effectful phase:

| Module | Phase 1 (compile) | Phase 2 (execute) |
|--------|-------------------|-------------------|
| combinators.py | `flow(...).retry().timeout().compile()` -> `Interp[T, E]` | `await L.down.to_result(interp)` |
| nodnod | `EventLoopAgent.build(nodes)` -> topological plan | `await agent.run(scope)` |
| wire | `fastapi.compile(app, axes)` -> FastAPI | `uvicorn.run(fastapi_app)` |
| wire.derive | `compile_derive(Entity)` -> DeriveCtx | `materialize(ctx)` -> Endpoint |
| deployme | `target.compile()` -> CompiledCompose | `await target.apply(compiled)` |
| algosik | `compile_compute(ops)` -> LLVM IR | `jit(ir)` -> native_fn(data) |

This is not defensive programming or "good separation of concerns." It's **partial evaluation** (staging).

### What staging buys you

Phase 1 specializes a generic interpreter against a specific configuration, producing a **residual program**. Phase 2 runs that residual.

algosik makes this most explicit. `interpret()` is the naive interpreter: for each element, pattern-match on the op, dispatch, evaluate. The dispatch cost is paid per-element. `run()` is the staged version: phase 1 (LLVM emission) eliminates all dispatch overhead at compile time, producing a tight native loop with no runtime dispatch. The semantics are identical; the performance differs by orders of magnitude.

The same principle appears everywhere:
- `to_pydantic(cls, axes)` doesn't validate data. It produces a Pydantic model class (the residual) that will validate data later at request time. The compilation phase is partial evaluation; the runtime phase is the residual executing.
- deployme's `target.compile()` produces a compose dict. That dict is the residual. `apply()` runs `docker compose up` on it.
- wire.derive's `compile_derive` produces `OpSpec` descriptions. `materialize()` generates concrete types from those descriptions. The OpSpecs are the partially-evaluated program; the generated types are the residual.
- combinators.py's `flow(...).compile()` produces an `Interp` thunk. The thunk is the residual. `await L.down.to_result(...)` runs it.
- nodnod's `EventLoopAgent.build(nodes)` produces a topologically sorted plan. The plan is the residual. `.run(scope)` executes it with asyncio.gather parallelism.

### Why this matters practically

1. **Inspectability.** The residual can be examined before execution. `explain(axes)` reads the compilation trace. `deployme describe` prints the compose dict. OpSpecs can be listed before materialization. You debug the compilation, not the runtime.

2. **Idempotence.** Phase 1 is a pure function. Same input, same output. No side effects, no state mutation. This makes compilation testable, cacheable, and reproducible.

3. **Target independence.** The IR is compiled once and can be handed to multiple phase-2 executors. The same `Application` compiles to FastAPI, CLI, and Telegram. The same algosik ops run through Python interpreter or LLVM JIT.

---

## 11. Compile/Bridge as Adjunction

Compile and bridge are not just "opposites." They form an **adjunction** in the categorical sense.

**Compile** is the free construction: take an abstract IR (`Application`) and produce the most general framework artifact that respects it. It's a left adjoint -- it freely generates structure.

**Bridge** is the forgetful functor: take a framework artifact (a FastAPI app with all its routes, middleware, dependencies) and extract what IR it implies. It forgets framework-specific details that have no IR representation.

### The asymmetry

The key property of an adjunction is asymmetric round-tripping:

- `bridge(compile(app)) ~ app` -- round-trip approximately recovers the original. You lose nothing essential because compile preserves all IR information, and bridge can read it back.

- `compile(bridge(fastapi_app))` produces something **different** from the original FastAPI app. Framework-specific details (custom middleware implementations, Depends injection logic, decorator chains) that have no IR representation are lost by bridge. The compiled result is a "clean" version that preserves behavior but not implementation details.

This is exactly the unit/counit asymmetry of an adjunction. It's not a bug that bridge is lossy; it's a mathematical inevitability. A forgetful functor cannot reconstruct what it forgot.

### Why bridge needs hints

Bridge capabilities (`WrapAsDelegate`, `IsolateGlobal`, `AddTrigger`, `MapDepends`) exist because the forgetful functor needs guidance about **what to reconstruct**. The default bridge extracts the obvious structure (routes become triggers, handlers become codecs). But framework-specific patterns (dependency injection, global state, decorator behavior) require explicit instructions for how to map them into the IR.

This is analogous to type annotations in a dynamically typed language: the structure is there implicitly, but you need explicit hints to recover it in a typed representation.

---

## 12. wire.derive as Term Rewriting

wire.derive is often described as "a CRUD generator." It's actually a **term rewriting system** over the wire IR.

### Terms

The terms are `OpSpec`s -- pure data descriptions of operations. An OpSpec knows its name, input field projection, response shape, handler template, trigger, capabilities, and effects. It's a term in the algebra of operations.

### Rewrite rules

DeriveModifiable capabilities are rewrite rules applied to the derivation tuple before evaluation (materialization):

```python
@schema_meta(
    http_crud("/api/users", Users),
    Readonly(),                                # delete OpSpecs tagged Mutation
    Paginated(20),                             # rewrite FetchMany -> PaginatedFetchMany
    WithoutDelete(),                           # remove Delete OpSpec
)
```

- `readonly()` is a **filter rule**: reject all DeriveOp steps whose effects include `Mutation` (or any subclass: `Creates`, `Updates`, `Deletes`).
- `paginated(20)` is a **rewrite rule**: find DeriveOp steps with `Pageable` effect, replace their handler template with `PaginatedFetchMany(page_size=20)`.
- `add_capability(cap, effect)` is a **conditional injection**: add a capability to DeriveOp steps matching an effect.
- `swap_handler(name, template)` is a **substitution**: replace the handler template for a named operation.

### Effects as semantic tags

Effects (`Read`, `Mutation`, `Creates`, `Updates`, `Deletes`, `Pageable`, `Sortable`) are **semantic classifiers** that enable pattern-matching in the rewriting system. They use inheritance for subsumption: `Creates` extends `Mutation`, so a rule targeting `Mutation` matches `Creates`, `Updates`, and `Deletes`.

This is nominal typing used as a dispatch mechanism for rewrite rules. No `if-else` chains, no string matching. `isinstance(effect, Mutation)` is the entire dispatch.

### Late materialization

The crucial property: **rewriting happens before types are generated.** OpSpecs are descriptions, not code. `build_from_spec()` materializes concrete request/response types from OpSpecs only after all rewrite rules have been applied.

This means:
- **Introspection works on descriptions.** `explain_entity()` shows OpSpecs before materialization. You see what will be generated without generating it.
- **Transforms compose.** stacking `Readonly()` and `Paginated(20)` in `@schema_meta` applies both rewrites to the same description. The order doesn't matter (they target different effects).
- **No dead code.** If `readonly()` removes `Delete`, no delete handler type, no delete request type, no delete route are ever generated. They were never materialized in the first place.

### Macro hygiene

wire.derive's three-phase compilation is macro hygiene. Phase 1 (Generate) establishes the **binding environment**: which fields exist, which are identity, which have defaults. Pass 2 (surface) expands terms against those bindings: `IdOnly` projection resolves to actual identity field names, `NonId` resolves to non-identity field names.

You can't generate a Create request type until you know which fields aren't identity fields, so schema must resolve first. This is the same constraint that macro systems face: bindings must be established before expansion.

---

## 13. Domain Independence

algosik is the strongest evidence that emergent's architecture is **domain-independent**.

algosik has nothing to do with web APIs, HTTP routing, CRUD operations, or deployment. It's a numeric compute pipeline with an LLVM JIT backend. Yet it uses:

- The same `Expr` base class from wire's query axis (extending it with arithmetic and math operations).
- The same frozen-dataclass-as-AST-node pattern.
- The same "build description then interpret" flow.
- The same dual-backend execution (Python interpreter = naive fold; LLVM = staged fold with dispatch elimination).

deployme is the same story from the infrastructure side. It has nothing to do with HTTP handlers or query building. Yet it uses:

- The same capability-tuple pattern for describing workloads.
- The same fold-through-handlers compilation.
- The same two-phase compile/execute separation.
- The same open-world extensibility (unknown capabilities silently skipped).

This means the architecture isn't "a good web framework pattern." It's a **general pattern for multi-target compilation from typed descriptions**. The domain (HTTP, math, infrastructure, CRUD generation) is incidental. The invariant is:

> If you can express your problem as typed data that multiple backends need to interpret, this architecture applies.

The specific instantiation varies:
- wire: typed annotations -> multiple framework targets
- wire.derive: entity shape -> multiple API operations
- deployme: workload descriptions -> multiple infrastructure targets
- algosik: numeric expressions -> multiple execution backends

But the structure is identical: free algebra of frozen dataclass nodes, interpreted by catamorphism (fold), with staging (compile/execute separation) for performance and inspectability.

---

## 14. The Full Hierarchy

The complete picture, from Level 2 foundations through Level 5 consumers:

```
Level 2: kungfu
   Result[T, E], Option[T]
   └── constraint: errors are values
         │
Level 3: combinators.py
   Interp[T, E] = LazyCoroResult[T, E]
   Flow AST: .retry().timeout().compile()
   extract/wrap natural transformation
   └── constraint: effects are lazy and composable
         │
Level 4: nodnod
   Node, Scope, EventLoopAgent
   __compose__ signatures = dependency graph
   automatic parallelization via topological sort
   SequentialEither = fallback_chain in the graph
   ConcurrentEither = race_ok in the graph
   └── constraint: dependencies are type-declared
         │
Level 5: emergent
   ├── wire (axes + capabilities -> Application IR)
   │   ├── ScopeFamily/ScopeLayer/Tier = compile-time scope topology
   │   ├── Composer = runtime bridge to nodnod
   │   ├── compile: Application -> FastAPI / CLI / TG
   │   └── bridge: FastAPI -> Application
   │
   ├── wire.derive (entity shape -> Application via term rewriting)
   │
   ├── deployme (Application -> infrastructure via capability fold)
   │
   └── algosik (Expr AST -> Python interpreter / LLVM JIT)
```

Each level consumes the IR of the level below and produces its own. The same fold/freeze/stage pattern operates at every level. This is self-similarity: the architecture is fractal. Zoom into any level and you see the same structure: frozen data nodes, fold interpretation, two-phase execution. The tower is not a stack of unrelated libraries; it's a single architectural idea (free algebra + catamorphism + staging) instantiated at increasing levels of abstraction.

---

## 15. Summary of Invariants

These are the structural properties that hold across all of emergent and all its consumers:

1. **All IR is frozen dataclasses.** No mutation, no metaclasses, no monkey-patching. IR nodes are values: equality-comparable, hashable, serializable.

2. **All interpretation is catamorphism (fold).** There is exactly one way to consume a free algebra: interpret its generators one by one. Every compiler, every interpreter, every explain function is a fold.

3. **All compilation is staged.** Phase 1 is sync, pure, inspectable. Phase 2 is async, effectful, executable. The residual (output of phase 1) can be examined, serialized, and handed to multiple phase-2 executors.

4. **Capabilities are commutative within an axis.** Order doesn't matter for pure compile-time capabilities. No emergent interactions. ScopeEnrichers are the deliberate exception: they chain as runtime middleware where order carries meaning.

5. **Axes are orthogonal.** Capabilities from different axes never interfere. Each compiler projects one dimension and ignores the rest.

6. **Extension is structural, not registrative.** New capabilities implement protocols. New compilers define folds. No central registry, no decorator registration, no plugin discovery. `isinstance` is the dispatch.

7. **Explanation is free.** Because IR is data, introspection is field access. Every level has an explain module that reads the IR without executing it.

8. **The architecture is domain-independent.** The pattern (free algebra + catamorphism + staging) applies to any problem expressible as "typed descriptions interpreted by multiple backends."

9. **Each layer constrains the layer above.** Errors are values (kungfu). Effects are lazy (combinators). Dependencies are types (nodnod). Topology is capabilities (wire). Each constraint removes a class of bugs and enables a class of optimizations.

10. **The type system is the specification language.** Result types declare failure modes. Interp laziness enables recomposition. Node signatures declare dependencies. Annotated types declare multi-target capabilities. Pyright is the verifier. The gap between specification and implementation is zero.
