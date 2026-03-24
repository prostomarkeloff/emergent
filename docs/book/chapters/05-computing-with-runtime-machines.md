# 5. Computing with Runtime Machines

> My aim is to show that the heavenly machine is not a kind of divine, live being, but a kind of clockwork (and he who believes that a clock has soul attributes the maker's glory to the work), insofar as nearly all the manifold motions are caused by a most simple and material force, just as all motions of the clock are caused by a single weight.
>
> — Johannes Kepler (letter to Herwart von Hohenburg, 1605)

We began this book by studying compilation processes and by describing compilation processes in terms of capabilities consumed by fold. To explain the meanings of these capabilities, we used a succession of models: the fold model of Chapter 1, the data abstraction model of Chapter 2, the Log model of Chapter 3, and the metalinguistic model of Chapter 4. Our examination of the metacircular fold, in particular, dispelled much of the mystery of how capability languages are evaluated. But even the metacircular fold leaves important questions unanswered, because it fails to elucidate the mechanisms of execution in an emergent system. For instance, the fold does not explain how multiple compilation phases run in parallel (banana split), how nodnod nodes resolve dependencies and schedule execution, or how theworld's WorkStealing scheduler maps computations to OS threads. These questions remain unanswered because fold inherits the control structure of the underlying Python runtime. In order to provide a more complete description of how emergent systems execute, we must work at a more primitive level than fold itself.

In this chapter we will describe execution in terms of the step-by-step operation of runtime machines. Such a machine — a nodnod agent — sequentially or concurrently executes *nodes* that manipulate the contents of typed *scopes*. Our descriptions of execution by runtime machines will look very much like the dependency graphs that nodnod constructs from node signatures. However, instead of focusing on any particular scheduling algorithm, we will examine several emergent programs and design a specific runtime to execute each. Thus, we will approach our task from the perspective of a runtime architect rather than that of a capability programmer.

---

## 5.1 Designing Runtime Machines

To design a runtime machine, we must design its *data paths* (scopes and values) and the *scheduler* that sequences node execution. To illustrate the design of a simple runtime machine, let us examine the composition of a single nodnod node.

### 5.1.1 Nodes and Scopes

A nodnod node is a Python type with a `__compose__` classmethod. The parameters of `__compose__` declare dependencies by type:

```python
@G.node
class FetchUser:
    @classmethod
    async def __compose__(cls, order: Order, db: Database) -> FetchUser:
        return cls(await db.get_user(order.user_id))
```

The parameter `order: Order` means: "before I can execute, I need a value of type Order in the scope." The parameter `db: Database` means the same for Database. The return type `FetchUser` means: "after I execute, I will place a value of type FetchUser in the scope."

A *scope* is an OrderedDict keyed by type: `Scope[type] = Value`. nodnod's Scope is both a dict and a linked list — each scope has an optional `prev` pointer to a parent scope. `retrieve(type)` walks the chain: check self, then parent, then grandparent. `create_child(detail)` produces a new scope with `prev=self`.

```python
class Scope(OrderedDict):
    def __init__(self, prev=None, detail=None):
        self.prev = prev
        super().__init__([(Scope, Value(Scope, self))])   # scope injects itself

    def retrieve(self, key):
        if key not in self:
            return self.prev.retrieve(key) if self.prev else NOTHING
        return Some(self[key])

    def inject(self, t, value):
        self[t] = Value(t, value)
```

This is lexical scoping for computation graphs. A World scope holds the Log and Config. A per-computation scope inherits from the World scope and adds computation-specific values. A per-operation scope inherits from the computation scope. Values "close over" their scope chain — just as closures close over their lexical environment.

### 5.1.2 Nodes Are Types, Not Instances

A critical design decision in nodnod: a Node is a Python TYPE, not an instance. `@G.node` calls `type()` to create a new class:

```python
class scalar_node:
    def __new__(cls, node_class):
        if isinstance(node_class, type):
            return type(node_class.__name__, (Node, node_class), dict(is_scalar=True))
        if callable(node_class):
            return type(f"ScalarNode:{node_class.__name__}", (Node,), dict(__compose__=node_class, is_scalar=True))
```

Each `@G.node` = one new Python type. The type IS the identity. `Scope[FetchUser]` stores the result of composing FetchUser. If FetchUser appears twice in the dependency graph, it is composed ONCE — the second lookup hits the scope cache.

This means: O(K) node types for K unique computations. NOT O(N) instances for N data items. A World with 3 computations × 5 internal nodes each = 15 types, not 15,000 instances. Memory: ~600 bytes per type. Speed: ~39µs per type creation. For typical systems (hundreds of types, not millions), this is negligible.

The consequence for theworld: each Computation compiles to a small number of node types (perception, action, lifecycle, plan). The World folds computations into node types. RuntimeAgent builds a DAG of types and executes them. The execution graph is small (tens to hundreds of types) even when the data being processed is large (millions of events in the Log).

### 5.1.3 Dependency Resolution

When nodnod builds a graph from a set of target nodes, it inspects each node's `__compose__` signature in `__init_subclass__` — at class creation time, not at execution time:

1. Parameter types that are themselves Node subclasses → `__dependencies__` (must be composed first).
2. Types that are Composable (have `__compose__`) but aren't Nodes → auto-wrapped into a Node via `create_node_from_composable`.
3. `Union[A, B]` → `create_union_node` → Either node (try alternatives).
4. `Option[T]` → `create_option_node` → SequentialEither(SomeNode, NothingNode).
5. `Result[T, E]` → `create_result_node` → ResultNode (wrap success/failure).
6. Everything else → `__injections__` (must be present in Scope before execution).
7. ForwardRef → deferred until the referenced type is defined (FORWARD_REF_REQUESTS registry).

The result: `__dependencies__: set[type[Node]]`, `__injections__: set[type]`, `__compose_names_by_type__: dict[type, str]` (reverse mapping for unboxing values into `__compose__` arguments).

### 5.1.4 Either and ResultNode

nodnod has first-class support for fallback and error handling — without try/except:

**SequentialEither**: try the first alternative. If it fails, try the second. If that fails, try the third. Stop at first success.

```python
class GetUser(SequentialEither):
    __either__ = (CacheNode, DatabaseNode, ExternalAPINode)
```

nodnod only resolves the first node initially. If it succeeds, GetUser composes from its value. If it fails, nodnod resolves the second, and so on. Dependencies for later alternatives are NOT resolved until needed — lazy evaluation of the fallback chain.

**ConcurrentEither**: race all alternatives simultaneously. First success wins.

```python
class FetchPrice(ConcurrentEither):
    __either__ = (APIv1Node, APIv2Node, ScraperNode)
```

All three nodes start concurrently. The first to produce a value wins. Others are effectively discarded (their results are ignored, though they may still complete in the background).

**ResultNode**: wrap a node's success/failure into a kungfu.Result:

```python
class SafeComputation(ResultNode[Result, TimeoutError]):
    __from_node__ = DangerousNode
    __error__ = TimeoutError
```

If DangerousNode succeeds, SafeComputation produces Ok(value). If DangerousNode raises TimeoutError, SafeComputation produces Ok() (swallowed). If DangerousNode raises anything else, SafeComputation produces Error(exception). This is typed error handling at the graph level — no try/except in user code.
3. Union types → *Either nodes* (try alternatives).
4. Option types → *SequentialEither* (try SomeNode, fall back to NothingNode).
5. Result types → *ResultNode* (wrap success/failure).

The result is a directed acyclic graph (DAG) where edges represent "must execute before." Nodes with no incoming edges are *ready roots* — they can execute immediately (their dependencies are injections, already in scope).

### 5.1.3 The Graph Info

`build_graph_info(nodes)` traverses the dependency graph and computes:

```python
@dataclass(frozen=True, slots=True)
class GraphInfo:
    all_nodes: tuple[type[Node], ...]           # topological order
    dependents: Mapping[type[Node], frozenset]   # who depends on me
    initial_pending: Mapping[type[Node], int]     # how many deps unsatisfied
    ready_roots: frozenset[type[Node]]            # zero pending → start immediately
    final_nodes: frozenset[type[Node]]            # originally requested targets
```

This is the static structure of the computation graph — frozen, computed once, reused across runs. The graph is data. It can be visualized (`to_mermaid`, `to_tree`, `to_ascii`), analyzed (`get_layers`, `get_dependencies`), and inspected before any execution begins.

---

## 5.2 A Runtime Machine Simulator

### 5.2.1 The Cooperative Runtime

The default runtime is `Cooperative` — a single asyncio event loop. All nodes execute as coroutines on one thread.

CallbackAgent implements this:

```python
class CallbackAgent(Agent):
    def __init__(self, graph_info, execute):
        self._graph_info = graph_info
        self._execute = execute
```

The execute callback defaults to `compose_node` — nodnod's standard node composition. The agent creates an asyncio Future for each node. Ready roots start immediately. When a node completes, the agent decrements pending counters of its dependents. When a dependent's counter reaches zero, its Future starts.

The execution is a wavefront: ready roots form the first wave. When they complete, their dependents form the next wave. Independent nodes within a wave run concurrently (asyncio concurrency — interleaved, not parallel).

For I/O-bound workloads — HTTP calls, database queries, LLM invocations — this is efficient. The event loop multiplexes many concurrent operations on one thread. No locks, no data races, no synchronization overhead.

### 5.2.2 The Work-Stealing Runtime

For CPU-bound workloads — matrix computation, data transformation, model inference — Cooperative is insufficient. All coroutines share one OS thread; Python's GIL (on standard builds) prevents true parallelism.

`WorkStealing` provides true parallelism on free-threaded Python (3.13t+):

```python
WorkStealing(workers=4)
```

N OS worker threads, each with its own asyncio event loop and a local task deque. Tasks are pushed onto the local deque (LIFO — cache-friendly) and stolen from other workers' deques (FIFO — reduces contention) when idle.

The design follows the Tokio model (Rust async runtime) adapted for Python's free-threading model. Each worker is an OS thread running its own event loop. Work distribution is hash-based: `hash(node_type) % len(workers)` assigns each node type to a home worker. But any idle worker can steal tasks from others — FIFO steal from the front of another's deque, so the stolen task is the one that has been waiting longest.

**Why LIFO push, FIFO steal?** Locality. A worker pushes its ready-to-run dependents to the BACK of its own deque. When it finishes its current task, it pops from the back — getting the most recently pushed task, which is likely to share cache lines with the just-completed task (they're adjacent in the dependency graph). A stealing worker takes from the FRONT — the oldest task, which is farthest from the stealer's cache but also the one that would wait longest without intervention. This is the Chase-Lev deque protocol, proven optimal for work-stealing schedulers.

**A worked example.** Consider a computation graph for a simple analytics pipeline:

```python
@G.node
class FetchSales:
    @classmethod
    async def __compose__(cls, db: Database) -> FetchSales:
        return cls(await db.query("SELECT * FROM sales"))

@G.node
class FetchInventory:
    @classmethod
    async def __compose__(cls, db: Database) -> FetchInventory:
        return cls(await db.query("SELECT * FROM inventory"))

@G.node
class ComputeRevenue:
    @classmethod
    async def __compose__(cls, sales: FetchSales) -> ComputeRevenue:
        return cls(sum(s.amount for s in sales.data))

@G.node
class ComputeStockValue:
    @classmethod
    async def __compose__(cls, inv: FetchInventory) -> ComputeStockValue:
        return cls(sum(i.price * i.quantity for i in inv.data))

@G.node
class BuildReport:
    @classmethod
    async def __compose__(cls, rev: ComputeRevenue, stock: ComputeStockValue) -> BuildReport:
        return cls(f"Revenue: {rev.total}, Stock Value: {stock.total}")
```

The dependency graph:

```
FetchSales ──→ ComputeRevenue ──┐
                                 ├──→ BuildReport
FetchInventory → ComputeStockValue ┘
```

With `WorkStealing(workers=2)`:

**Step 1: Build graph info.** `build_graph_info({BuildReport})` traverses dependencies:
- BuildReport depends on ComputeRevenue, ComputeStockValue
- ComputeRevenue depends on FetchSales
- ComputeStockValue depends on FetchInventory
- FetchSales and FetchInventory depend on Database (injection, not node)

Graph layers:
- Layer 0: FetchSales, FetchInventory (ready roots — Database injected)
- Layer 1: ComputeRevenue, ComputeStockValue (depend on layer 0)
- Layer 2: BuildReport (depends on layer 1)

**Step 2: Fold scheduling traits.** `fold_schema(node, WorkStealingContext(), WorkStealingCompilable, "compile_work_stealing")` for each node. If any node has `@schema_meta(Priority(10))`, its WorkStealingContext gets priority=10. In this example, no node has special traits — all default.

**Step 3: Create pool.** 2 worker threads. Worker 0 and Worker 1, each with an asyncio loop and a deque.

**Step 4: Submit ready roots.** `hash(FetchSales) % 2 = 0` → Worker 0. `hash(FetchInventory) % 2 = 1` → Worker 1. Both workers start simultaneously.

**Step 5: Execution.**

```
Time 0ms:   Worker 0 starts FetchSales (DB query)
            Worker 1 starts FetchInventory (DB query)
            — TRUE PARALLELISM on free-threaded Python —

Time 50ms:  Worker 1 completes FetchInventory
            → decrements ComputeStockValue.pending from 1 to 0
            → submits ComputeStockValue to Worker 1 (hash-based)
            Worker 1 starts ComputeStockValue (CPU computation)

Time 55ms:  Worker 0 completes FetchSales
            → decrements ComputeRevenue.pending from 1 to 0
            → submits ComputeRevenue to Worker 0 (hash-based)
            Worker 0 starts ComputeRevenue (CPU computation)

Time 56ms:  Worker 1 completes ComputeStockValue
            → decrements BuildReport.pending from 2 to 1
            Worker 1 is IDLE. Tries to steal from Worker 0.
            Worker 0's deque is empty (ComputeRevenue running, not in deque).
            Worker 1 sleeps 0.1ms, retries.

Time 58ms:  Worker 0 completes ComputeRevenue
            → decrements BuildReport.pending from 1 to 0
            → submits BuildReport to Worker 0 (hash-based)
            Worker 0 starts BuildReport.

Time 59ms:  Worker 0 completes BuildReport.
            → remaining_finals reaches 0
            → done_event set
            → Both workers stop
```

Total time: 59ms. Sequential would take: 50 + 50 + 3 + 3 + 1 = 107ms. The parallelism saves ~45% — both DB queries ran simultaneously, and the two CPU computations overlapped slightly.

The key observation: the programmer wrote ZERO concurrency code. No threads, no locks, no async/await coordination. The dependency graph was discovered from type signatures. The parallelism was determined by the graph structure. The work-stealing scheduler handled load balancing. The programmer wrote pure nodes — `async def __compose__` — and the runtime did the rest.

The implementation:

1. **Build graph info** — same static structure as Cooperative.
2. **Fold per-node traits** — `fold_schema(node, WorkStealingContext(), WorkStealingCompilable, "compile_work_stealing")` collects priority, affinity, etc. from each node's schema_meta. Same fold.
3. **Create worker pool** — N threads, each with an event loop and a deque.
4. **Submit ready roots** — hash-distributed across workers.
5. **Execution loop** — each worker: pop from local deque → execute → on completion, decrement dependents' pending counters → submit newly ready nodes. Idle workers steal from others.

The concurrency is safe because:
- Scope writes are to unique keys (one per node type) — no conflicting writes.
- Pending counters are protected by a lock (one atomic decrement per completion).
- The Log is append-only — concurrent appends serialized internally.
- Capabilities are frozen — no shared mutable state.

The GIL policy handles the real world: `RequireFreeThreaded` raises RuntimeError if WorkStealing is requested and GIL is enabled. `AutoDowngrade` silently falls back to Cooperative. The policy is a frozen dataclass — a capability consumed by fold, same encoding as everything else.

---

## 5.3 Storage Allocation and the Log

SICP Chapter 5.3 addresses memory management — how cons cells are allocated and garbage collected. The emergent analog is the Log — how events are stored, indexed, and queried.

### 5.3.1 The InMemoryLog

The simplest Log backend stores events in a list and maintains a type index:

```python
class InMemoryLog:
    _events: list[Event]           # append-only
    _type_index: dict[type, list]   # type → events of that type
    _notifiers: dict[type, list]    # push-based wake on new events
```

Append: O(1) — list.append + index update. Query by type: O(1) lookup + O(bucket) filter. Subscribe: register notifier, await wake on matching type.

The type index is the key optimization. BEAM's mailbox requires O(N) scan for selective receive. The InMemoryLog's type index provides O(1) type dispatch. For a Log with 10K events across 50 types, a type query touches ~200 events, not 10K.

### 5.3.2 The TieredLog

Real systems need multiple storage tiers:

```python
log = TieredLog(
    TierBinding(Ephemeral, InMemoryLog()),     # fast, volatile
    TierBinding(Durable, sqlite_log),           # persistent
)
```

Events carry a tier marker. `put(log, event, tier=Durable)` writes to the SQLite-backed log. `put(log, event, tier=Ephemeral)` writes to memory only. Queries can filter by tier: `Lens().tier(Durable)`.

The SQLite backend uses emergent's wire compilation: `compile_sa(EventType, "table_name")` produces a SQLAlchemy model from the event's frozen dataclass definition. The same compilation that generates Pydantic models and OpenAPI schemas also generates the storage layer for events. One encoding. Every level.

### 5.3.3 ViewSnapshot and Incremental Computation

The Log grows without bound. Querying the entire Log to reconstruct state becomes expensive as events accumulate. ViewSnapshot provides incremental computation:

```python
await put(log, ViewSnapshot(view_id="progress", state=progress_state, cursor=current_position))
```

A ViewSnapshot is an event — frozen dataclass in the Log, queryable through Lens. On restart, a Computation queries the last ViewSnapshot, recovers its cursor, and continues folding from that point. O(Δ) recovery instead of O(all events).

This is the emergent analog of SICP's garbage collection: rather than discarding old data (which the append-only Log cannot do), we create summary checkpoints that make it unnecessary to process old data.

---

## 5.4 The Explicit-Control Fold

SICP Chapter 5.4 implements the metacircular evaluator on a register machine — making the control flow explicit. In emergent, the analog is tracing: making fold's control flow visible.

### 5.4.1 traced_fold

When `trace=TraceCollector()` is passed to fold, the execution switches to `traced_fold`:

```python
def traced_fold(items, initial, protocol, method, handlers, collector):
    ctx = initial
    steps = []
    for item in items:
        ctx_before = ctx
        if handlers and item.__class__ in handlers:
            ctx = handlers[item.__class__](item, ctx)
            dispatch = "handler"
        elif isinstance(item, protocol):
            ctx = getattr(item, method)(ctx)
            dispatch = "protocol"
        else:
            dispatch = "skipped"
        step = FoldStep(item_type=..., dispatch=dispatch,
                        context_before=ctx_before, context_after=ctx, changed=...)
        collector.fold_step(step)
        steps.append(step)
    fold_trace = FoldTrace(protocol=..., method=..., initial=initial, final=ctx, steps=tuple(steps))
    collector.fold_complete(fold_trace)
    return ctx, fold_trace
```

Every step is recorded: which item, how it dispatched, what the context was before and after, whether it changed. The trace is a tree of frozen dataclasses: FoldStep → FoldTrace → FieldPhaseTrace → FieldTrace → TypeTrace.

This makes fold's control flow explicit — every dispatch decision, every context transformation, every skip. The production fold (six lines) has zero tracing overhead — the `if trace is not None` check is a single branch prediction. traced_fold runs only when explicitly requested.

### 5.4.2 explain

The explain system reads the trace:

```python
axes = Axes.traced()
FASTAPI_SCHEMA.compile(User, axes)
print(explain(axes))
```

explain() produces human-readable output: which capabilities applied, which were skipped, what changed. explain_field() narrows to one field. explain_type() shows the entire entity.

The dict layer (`trace_dict`, `field_dict`, `type_dict`) produces machine-readable dicts — for agents, for programmatic analysis, for test assertions.

Five explain systems read the same frozen trace data: schema explain, surface explain, query explain, compilation trace explain, derive explain. Each is a catamorphism over the trace tree. explain is fold applied to fold's own output.

---

## 5.5 Compilation

SICP Chapter 5.5 implements a compiler — translating Scheme to register-machine instructions. In emergent, the corresponding concept is *target compilation* — translating the wire Application to framework-native artifacts.

### 5.5.1 The Target Compiler

Each framework target has a TargetCompiler:

```python
FASTAPI_COMPILER = TargetCompiler(
    trigger_type=HTTPRouteTrigger,
    adapters=(
        CodecBinding(RequestResponseCodec, rrc_from_codec),
        CodecBinding(StatefulCodec, stateful_from_codec),
        ...
    ),
    pipeline_protocol=FastAPIPipelineCompilable,
    pipeline_method="compile_fastapi_pipeline",
    assemble=assemble_fastapi_route,
)
```

scan_and_wrap iterates the wire Application's endpoints and exposures. For each matching (trigger, codec) pair:

1. `from_codec(codec, trigger)` → WrapCtx (seed the context from codec and trigger data)
2. `fold(capabilities, wrap_ctx, pipeline_protocol, pipeline_method)` → fold surface capabilities through the context (tags, auth, OpenAPI metadata)
3. `assemble(wrap_ctx, handler, axes)` → produce framework-native route

For FastAPI: the route goes to `fastapi_app.add_api_route(path, endpoint, methods=[method], ...)`.
For CLI: the route goes to `parser.add_subparser(name, ...)`.
For Telegrinder: the route goes to `dp.message.register(handler, rule)`.

### 5.5.2 The Execution Pipeline

When a request arrives at a compiled endpoint, the execution pipeline is:

1. **Framework adapter** creates a nodnod Scope, injects framework context (Request for FastAPI, Namespace for CLI, Context for Telegrinder).
2. **Enricher chain** executes: auth → timeout → rate limit → core. Enrichers are ScopeEnricher capabilities, chained at compile time, executed at request time.
3. **Core handler**: `request.to_domain()` → domain Op → `runner.run(op)` → Result → `response.from_domain(result)`.
4. **Response transforms** post-process: RFC 7807 errors, status codes, headers.

The enricher chain is built by `fold_handler_runtime(capabilities)` — fold over surface capabilities to extract ScopeEnrichers. `chain_enrichers(enrichers, core_handler)` builds the middleware stack: `e1(e2(e3(core)))`. First enricher runs first.

The target-specific `enrich_fastapi`, `enrich_cli`, `enrich_telegrinder` methods allow framework-aware enrichers. BearerExtract's `enrich_fastapi` reads the Authorization header. Its `enrich_cli` reads a --token argument. Same capability, different extraction per target — dispatched by the `target` parameter of `chain_enrichers`.

### 5.5.3 From fold to Metal

Let us trace, in complete detail, the execution path from a capability annotation to an HTTP response arriving at a client's browser. This is the emergent analog of SICP Chapter 5.5 tracing the execution of a Scheme expression through the register machine.

**The source:**

```python
@derive(http_crud("/users", Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
```

**Step 1: Import time — compile_derive.** When Python imports the module containing the User class, the `@derive` decorator attaches `http_crud("/users", Users)` to User via `@schema_meta`. Nothing else happens yet.

When `build_application_from_decorated(User)` is called:

```python
for entity in entities:
    for ctx in compile_derive(entity):
        endpoints.append(materialize(ctx))
```

`compile_derive(User)` retrieves `(CRUD("/users", Users),)` from @schema_meta. Three folds:

- **Fold 1 (Generate):** `fold_schema(User, DeriveCtx.from_entity(User), DeriveGeneratable, "compile_derive_generate")`. CRUD.compile_derive_generate inspects User's fields (id: Identity, name: str), generates 7 OpSpecs: List, Get, Create, Update, Patch, Delete, Upsert. Each OpSpec carries: name, input fields, output spec, handler template, HTTPRouteTrigger, effects.
- **Fold 2 (Modify):** `fold_schema(User, ctx, DeriveModifiable, "compile_derive_modify")`. No modifiers in this example. ctx unchanged.
- **Fold 3 (Augment):** `fold_schema(User, ctx, DeriveAugmentable, "compile_derive_augment")`. No augmenters. ctx unchanged.

**Step 2: Import time — materialize.** `materialize(ctx)` takes the DeriveCtx with 7 OpSpecs and produces an Endpoint:

For each OpSpec:
- `build_from_spec(spec, ctx)` creates: (a) a frozen dataclass type `UserListOp(provider: MutatingRelationalProvider)` for List, `UserGetOp(id: int, provider: ...)` for Get, etc.; (b) an async handler function built from the handler template (FetchMany.build(spec), InsertNew.build(spec), etc.); (c) an Exposure (HTTPRouteTrigger("GET", "/users") + rrc(UserListOp, UserListResponse) + error capabilities).
- All (OpType, handler) pairs are registered: `ops().on(UserListOp, list_handler).on(UserGetOp, get_handler)...`
- `.compile()` produces a Runner — backed by nodnod, wrapping all handlers in a node graph.

Result: `Endpoint(runner=Runner, exposures=(Exposure(GET /users, rrc), Exposure(GET /users/{id}, rrc), Exposure(POST /users, rrc), ...))`.

**Step 3: Import time — fastapi.compile.** `targets.fastapi.compile(app)` creates a FastAPI instance and iterates the Application's endpoints via `FASTAPI_COMPILER.scan_and_wrap(app, axes)`:

For each Exposure with HTTPRouteTrigger:
- `rrc_from_codec(codec, trigger)` → FastAPIWrapContext seeded with request/response types and HTTP method/path.
- **Fold 4 (Surface):** `fold(exposure.capabilities, wrap_ctx, FastAPIPipelineCompilable, "compile_fastapi_pipeline")` — error capabilities set up RFC 7807 error handlers.
- `assemble_fastapi_route(wrap_ctx, handler, axes)` → produces an async route function that: creates Scope, injects Request, extracts JSON body, builds request type via Pydantic fold (**Fold 5: Schema fold** — field capabilities → Pydantic FieldInfo → model class), validates, calls execute_rrc.
- `fastapi_app.add_api_route("/users", route_fn, methods=["GET"], ...)`.

7 routes registered. At this point, everything is compiled. The FastAPI app is a standard ASGI application.

**Step 4: Runtime — uvicorn.** `uvicorn.run(fastapi_app)` starts an asyncio event loop, binds a TCP socket (default port 8000), and waits for HTTP connections.

**Step 5: Runtime — request arrives.** A client sends `POST /users` with body `{"name": "Alice"}`.

- uvicorn reads bytes from the TCP socket, parses HTTP headers, identifies the route as POST /users.
- FastAPI's router matches the route to the compiled route function.
- The route function executes:
  1. Creates nodnod Scope. Injects `fastapi.Request`.
  2. Extracts JSON body: `{"name": "Alice"}`.
  3. **Fold 5 (Schema):** Pydantic model class (compiled at step 3) validates the body. MaxLen? No MaxLen on name. Identity? id is auto-generated. The model accepts `{"name": "Alice"}`.
  4. Builds the domain Op: `UserCreateOp(name="Alice", provider=memory_provider)`.
  5. `execute_rrc(handler, request_obj, scope)`:
     - Extracts enrichers via `fold_handler_runtime(capabilities)` — **Fold 6 (Enricher)**.
     - No enrichers in this example. Core handler runs directly.
     - `request_obj.to_domain()` → `UserCreateOp(name="Alice", provider=...)`.
     - `runner.run(op)` → nodnod composes the op node. InsertNew handler: generates id via `provider.next_id()` → `1`. Constructs `User(id=1, name="Alice")`. Calls `provider.insert(user)`. Returns `Ok(User(id=1, name="Alice"))`.
     - `response_type.from_domain(Ok(User(id=1, name="Alice")))` → `{"id": 1, "name": "Alice"}`.
  6. FastAPI serializes to JSON. Sets Content-Type. Returns 200.
- uvicorn writes HTTP response bytes to TCP socket.
- Client receives: `{"id": 1, "name": "Alice"}`.

**Six folds in this path.** Schema fold (field capabilities → Pydantic model). Generate fold (CRUD → OpSpecs). Modify fold (transforms → modified OpSpecs, trivial here). Surface fold (error capabilities → route config). Request fold (JSON → validated domain Op). Enricher fold (capabilities → enricher chain).

Each fold is the same six lines. Each operates on different data. Each uses different protocols. But the mechanism is always: iterate frozen data, check isinstance, call compile_* method, accumulate context. From `@derive` annotation to TCP bytes — fold at every level.

The abstraction we built in Chapters 1-4 — capabilities, data abstraction, the Log, metalinguistic fold — bottoms out here, at the metal: Python's asyncio event loop, uvicorn's HTTP parser, the OS kernel's TCP stack. But the structure is clear at every level because the structure is always the same: frozen data, compiled by fold.

---

Kepler wanted to show that the heavenly machine is clockwork — all manifold motions caused by a single weight. We have tried to show something similar: that the manifold compilations of emergent — schema, query, verification, derivation, scheduling, distributed computation — are caused by a single fold. The capabilities change. The contexts change. The protocols change. fold does not.

One fold. Three language primitives. The rest is consequences.

---

## Exercises

**Exercise 5.1.** Design a register-machine simulator for fold. The "registers" are: `items` (list), `idx` (current index), `ctx` (current context), `protocol` (the protocol type), `method` (the method name). The "instructions" are: LOAD_ITEM, CHECK_HANDLER, CHECK_ISINSTANCE, CALL_METHOD, SKIP, INCREMENT, TEST_DONE, HALT. Write the instruction sequence for folding `[MaxLen(255), Unique, sql.Index()]` through PydanticCompilable. Trace the register state at each step.

**Exercise 5.2.** The Cooperative runtime uses asyncio — single-thread, coroutine-based concurrency. The WorkStealing runtime uses N OS threads. Design a THIRD runtime: DistributedAgent, where nodes execute on remote machines via a shared Log. Each machine runs a subset of nodes. Dependencies cross machine boundaries through Log events. What are the challenges? (Hint: consider scope access across machines.)

**Exercise 5.3.** The GraphInfo data structure contains `initial_pending` — the number of unsatisfied dependencies for each node. This is computed once and reused. Design a scenario where the dependency count changes dynamically — a node that, depending on its input, spawns additional dependencies. Can the current GraphInfo structure support this? What changes would be needed?

**Exercise 5.4.** traced_fold records a FoldStep per capability. For a compilation with 100 fields × 5 phases × 10 capabilities per field = 5000 FoldSteps. Design a "sampling trace" that records only every Nth step, or only steps where the context changed, or only steps for capabilities of a specified type. What information is lost? For debugging, which sampling strategy would you recommend?

**Exercise 5.5.** The full execution path from `@derive` annotation to HTTP response involves six fold operations (enumerated in 5.5.3). Instrument each fold with tracing and compute the total number of FoldSteps for a system with 10 entities, 7 fields each, 3 capabilities per field, 5 compilation phases. How does this scale with entity count? With field count? With phase count? Is the scaling linear, quadratic, or worse?

**Exercise 5.6.** SICP 5.3 discusses garbage collection — reclaiming memory from unreachable data. The append-only Log never reclaims. Design a "Log compaction" mechanism that: (a) preserves all ViewSnapshots, (b) removes raw events that are older than the oldest ViewSnapshot's cursor, (c) maintains correctness for all computations that use ViewSnapshot-based recovery. What invariants must hold? Under what conditions is compaction safe?

**Exercise 5.7.** The enricher chain `chain_enrichers(enrichers, core_handler, target="fastapi")` wraps the core handler with middleware. The execution order is: first enricher runs first (outermost wrapper). Design an enricher `TimeExecution` that measures the time taken by all inner enrichers plus the core handler. Where must it be placed in the chain? Can it be placed anywhere? What if you want to measure EACH enricher separately?

**Exercise 5.8.** WorkStealing uses hash-based task distribution: `hash(node) % len(workers)`. This is simple but may produce unbalanced loads. Design an alternative distribution strategy based on the GraphInfo structure — assign layers (from get_layers) to workers in round-robin fashion. Show that this produces better load balance for wide, shallow graphs and worse balance for narrow, deep graphs.

**Exercise 5.9.** The target compilation (5.5) produces framework-native routes. But the compilation itself happens at import time (or at app startup). Design a JIT compilation model where routes are compiled on first request. What data structures would you lazy-initialize? What happens to verify() — can it still run at import time if routes haven't been compiled yet?

**Exercise 5.10.** Kepler's epigraph: "all manifold motions caused by a single weight." The "single weight" in emergent is fold. But fold has five parameters (items, initial, protocol, method, handlers). Is there a simpler formulation? Can fold be expressed as a method on the items tuple itself — `items.fold(initial, protocol)`? What would this gain? What would it cost? (Hint: consider the handler map.)
