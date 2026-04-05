# 5. Computing with Runtime Machines

> My aim is to show that the heavenly machine is not a kind of divine, live being, but a kind of clockwork (and he who believes that a clock has soul attributes the maker's glory to the work), insofar as nearly all the manifold motions are caused by a most simple and material force, just as all motions of the clock are caused by a single weight.
>
> -- Johannes Kepler (letter to Herwart von Hohenburg, 1605)

But even the metacircular fold leaves important questions unanswered. The fold that gives meaning to capabilities -- the evaluator that evaluates evaluator descriptions -- fails to explain the mechanisms by which compilation actually executes. When `fold` iterates a capability list, what *exactly* happens at each step? When nodnod resolves dependencies and schedules nodes, what data structures change? When WorkStealing distributes tasks across OS threads, what synchronization primitives coordinate them?

These questions matter because the metacircular fold inherits its control structure from Python's runtime. `for item in items` borrows Python's iteration. `isinstance(item, protocol)` borrows Python's MRO traversal. `getattr(item, method)(ctx)` borrows Python's attribute lookup. The fold is eight lines, but each line hides machinery.

In this chapter we will work at a more primitive level than fold itself. We will describe execution in terms of the step-by-step operation of a *runtime machine*: a nodnod agent that sequences or parallelizes *nodes* manipulating the contents of typed *scopes*. We will examine the machine that simulates execution (EventLoopAgent on asyncio), the machine that compiles execution (WorkStealing on OS threads), the explicit-control evaluator that turns abstract computations into running systems (World.run()), and the full trace from a `@derive` annotation to TCP bytes -- the moment when six lines of fold become a thousand concrete dispatch decisions.

---

## 5.1 The Machine

### 5.1.1 Scope: The Register File

A register machine stores intermediate values in named registers. nodnod's equivalent is the `Scope` -- an `OrderedDict` keyed by type, with a parent pointer forming a chain:

```python
# nodnod/scope.py
class Scope(OrderedDict):
    def __init__(self, prev=None, detail=None):
        self.prev = prev
        self.detail = detail or secrets.token_hex(5)
        self.is_closed = False
        super().__init__([(Scope, Value(Scope, self))])  # scope injects itself

    def retrieve(self, key):
        if key not in self:
            if not self.prev:
                return NOTHING
            return self.prev.retrieve(key)
        return Some(self[key])

    def push(self, value):
        self[value.cls] = value

    def create_child(self, detail=None):
        return Scope(prev=self, detail=detail)

    def inject(self, t, value):
        self[t] = Value(t, value)
```

SICP's register machine has a flat register file -- named slots `val`, `env`, `exp`, `continue` that hold values. `(assign val ...)` writes. `(fetch val)` reads.

Scope is a *typed* register file with *lexical scoping*. `scope.push(Value(FetchUser, result))` writes a value keyed by its type -- like `(assign FetchUser result)`. `scope.retrieve(FetchUser)` walks the parent chain: check self, then parent, then grandparent -- like `lookup-variable-value` traversing SICP's environment frames.

**Stop and predict.** A World scope holds the Log and Config. A per-computation scope inherits from the World scope. A per-operation scope inherits from the computation scope. When a node's `__compose__` method asks for `Database`, where does `retrieve(Database)` find it?

It walks up: operation scope (no) -> computation scope (no) -> World scope (yes, injected at startup). This is lexical scoping for computation graphs. Values "close over" their scope chain, just as closures close over their lexical environment. The `create_child` method is `extend-environment` -- it creates a new frame. The parent pointer is the enclosing-environment link.

But Scope keys are *types*, not strings. `Scope[FetchUser]` holds the FetchUser node's computed value. This eliminates an entire class of errors that SICP's evaluator must check at runtime ("Unbound variable"). If the type is not in the scope chain, the dependency was not declared -- caught at graph build time, not at execution time.

### 5.1.2 Node: The Instruction

SICP's instructions are data -- `(assign val (op lookup-variable-value) (reg exp) (reg env))` is a list that the assembler transforms into an executable procedure. At runtime, each instruction is a procedure of no arguments that modifies machine state and advances the program counter.

nodnod's `Node` is a TYPE, not an instance. The type IS the identity:

```python
# nodnod/node.py (simplified — essential structure)
class Node[T]:
    __type__: type = None
    __dependencies__: set[type[Node]] = None
    __injections__: set[type] = None
    __initialize__: Callable[[set[Value]], ComposeResponse[T]] = None
    __compose__: Callable[..., ComposeResponse[T]] = dummy_compose
    __compose_names_by_type__: dict[type, str] = None

    def __init_subclass__(cls, abstract=False):
        if not abstract and not cls.__initialize__:
            # Resolve dependencies from __compose__ signature
            signature = resolve_signature(cls.__compose__, ...)
            all_args = signature.merge()

            dependency_nodes = set[type[Node]]()
            injected_types = set[type]()

            for dep_name, dep_type in all_args.items():
                if is_type(dep_type, Node):
                    dependency_nodes.add(dep_type)
                elif is_type(dep_type, Composable):
                    dependency_nodes.add(create_node_from_composable(dep_type))
                elif is_union(dep_type):
                    dependency_nodes.add(create_union_node(dep_type))
                elif is_option(dep_type):
                    dependency_nodes.add(create_option_node(dep_type))
                elif is_result(dep_type):
                    dependency_nodes.add(create_result_node(dep_type))
                else:
                    injected_types.add(dep_type)

            cls.__dependencies__ = dependency_nodes
            cls.__injections__ = injected_types
            cls.__initialize__ = (
                kungfu.F[set[Value]]()
                .then(lambda values: {
                    cls.__compose_names_by_type__[v.cls]: v.unbox()
                    for v in values if v.cls in cls.__compose_names_by_type__
                })
                .then(lambda ctx: call_with_context(cls.__compose__, ctx).unwrap())
            )

            setattr(cls, "__traverse__", build_queue(cls, []))
```

The critical mechanism is `__init_subclass__`. When you write:

```python
@G.node
class FetchUser:
    @classmethod
    async def __compose__(cls, order: Order, db: Database) -> FetchUser:
        return cls(await db.get_user(order.user_id))
```

At *class definition time* -- not at execution time -- Python calls `__init_subclass__`. This inspects the `__compose__` signature, discovers that `order: Order` is a Node dependency and `db: Database` is an injection, builds a `__traverse__` list (the topological sort), and creates `__initialize__` -- a composed pipeline that maps scope Values to keyword arguments.

The class IS the compiled instruction. `__dependencies__` is the set of registers this instruction reads. `__type__` is the register it writes. `__initialize__` is the execution procedure. All computed once, at import time. The "assembler" has already run by the time any node executes.

**Stop and predict.** `scalar_node` creates a node from a class or function:

```python
# nodnod/interface/scalar.py (simplified)
class scalar_node:
    def __new__(cls, node_class):
        if isinstance(node_class, type):
            return create_node(
                name=node_class.__name__, base_node=Node,
                bases=(node_class,), namespace=dict(is_scalar=True),
            )
        if callable(node_class):
            return type(
                f"ScalarNode:{node_class.__name__}", (Node,),
                dict(__compose__=node_class, is_scalar=True),
            )
```

Each `@G.node` = one new Python type. `Scope[FetchUser]` stores the result by type key. If FetchUser appears twice in the dependency graph, it is composed ONCE -- the second lookup hits the scope cache. O(K) types for K unique nodes. NOT O(N) instances for N data items.

### 5.1.3 Either and ResultNode: Branching

SICP's controller has `branch` (conditional) and `goto` (unconditional). Sequential execution is the default; branching is the exception.

nodnod's branching primitive is `Either`:

```python
# nodnod/interface/either.py
class Either(Node[kungfu.Sum], abstract=True):
    is_concurrent: bool
    __either__: tuple[type[Node], ...]

    def __init_subclass__(cls, abstract=False):
        if not abstract:
            if cls.is_concurrent:
                cls.__dependencies__ = set(cls.__either__)  # all raced
            else:
                cls.__dependencies__ = {cls.__either__[0]}  # only first

class SequentialEither(Either, abstract=True):
    is_concurrent = False

class ConcurrentEither(Either, abstract=True):
    is_concurrent = True
```

**SequentialEither**: try alternatives in order. Only the first member is declared as a dependency -- subsequent members are scheduled lazily, only if earlier ones fail. Like SICP's `(test ...) (branch (label ...))` -- the condition determines which path to take.

**ConcurrentEither**: race all members simultaneously. All members are dependencies -- all resolved in parallel, first success wins. No SICP equivalent. This is pure dataflow parallelism.

**ResultNode** wraps success/failure into a typed Result:

```python
# nodnod/interface/result_node.py
class ResultNode[T, Err: BaseException](Node[kungfu.Result[T, Err]]):
    __from_node__: type[Node]
    __error__: type[Err] | tuple[type[Err], ...]

    def __init_subclass__(cls, abstract=False):
        if not abstract:
            cls.__dependencies__ = {cls.__from_node__}
            cls.__injections__ = set()

    @classmethod
    def __compose__(cls, err):
        try:
            raise err
        except cls.__error__:
            return kungfu.Ok()
        except BaseException as e:
            return kungfu.Error(e)
```

If the parent node succeeds, ResultNode wraps `Ok(value)`. If the parent raises the declared error type, it swallows it with `Ok()`. If the parent raises anything else, it wraps `Error(exception)`. Typed error handling at the graph level -- no try/except in user code.

### 5.1.4 GraphInfo: The Controller Sequence

SICP's controller is a sequence of instructions. The assembler resolves labels to positions and produces a list of executable procedures. The program counter advances through this list.

nodnod's equivalent is `GraphInfo`:

```python
# emergent/graph/runtime/_helpers.py
@dataclass(frozen=True, slots=True)
class GraphInfo:
    all_nodes: tuple[type[Node], ...]            # topological order
    dependents: Mapping[type[Node], frozenset]    # who depends on me
    initial_pending: Mapping[type[Node], int]      # unsatisfied dep count
    ready_roots: frozenset[type[Node]]             # zero pending -> start
    final_nodes: frozenset[type[Node]]             # originally requested

def build_graph_info(nodes):
    all_nodes_list = traverse_all(nodes)  # topological sort
    dependents_mut = {}
    initial_pending = {}

    for node in all_nodes_list:
        deps = node.__dependencies__
        initial_pending[node] = len(deps)
        for dep in deps:
            dependents_mut.setdefault(dep, set()).add(node)

    ready_roots = frozenset(
        n for n in all_nodes_list if initial_pending.get(n, 0) == 0
    )
    return GraphInfo(
        all_nodes=tuple(all_nodes_list),
        dependents=MappingProxyType({k: frozenset(v) for k, v in dependents_mut.items()}),
        initial_pending=MappingProxyType(initial_pending),
        ready_roots=ready_roots,
        final_nodes=frozenset(nodes),
    )
```

`traverse_all` performs a depth-first topological sort -- SICP's assembler resolving labels. `all_nodes` is the instruction sequence. `initial_pending` is the per-node "latch counter" -- how many dependencies must complete before this node can fire. `ready_roots` are nodes with zero dependencies: they can start immediately. `dependents` is the reverse mapping: when node X completes, which nodes become closer to ready.

This structure is frozen. Computed once, reused across runs. The graph is data -- it can be visualized (`to_mermaid`, `to_ascii`), analyzed (`get_layers`), and inspected before any execution begins. The "instruction memory" is immutable.

**Stop and predict.** Consider:

```
FetchSales ------> ComputeRevenue ----\
                                       +---> BuildReport
FetchInventory --> ComputeStockValue --/
```

What are the `initial_pending` values? FetchSales: 0 (root). FetchInventory: 0 (root). ComputeRevenue: 1 (depends on FetchSales). ComputeStockValue: 1 (depends on FetchInventory). BuildReport: 2 (depends on both). What are the ready roots? {FetchSales, FetchInventory}. When FetchSales completes, ComputeRevenue's counter goes from 1 to 0 -- it becomes ready. BuildReport must wait for *both* counters to reach zero.

---

## 5.2 The Simulator

SICP builds a register-machine simulator *in Scheme*. `make-machine` takes register names, operations, and a controller, returning a model you can run. `(start gcd-machine)` executes the controller step by step. The simulator is itself a Scheme program -- the abstract language simulating the concrete machine.

emergent's simulator is `CallbackAgent` running on Python's asyncio event loop.

### 5.2.1 CallbackAgent: The Fetch-Decode-Execute Cycle

```python
# emergent/graph/runtime/_helpers.py
class CallbackAgent(Agent):
    def __init__(self, graph_info, execute):
        self._graph_info = graph_info
        self._execute = execute  # default: compose_node

    @classmethod
    def build(cls, nodes):
        return cls(graph_info=build_graph_info(nodes), execute=default_executor)

    async def run(self, local_scope, mapped_scopes):
        self._futures = {}
        self._push_futures_for(self._graph_info, local_scope, mapped_scopes, self._futures)

        while self._final_nodes:
            pending_futs = set()
            for n in list(self._final_nodes):
                fut = self._futures.get(n)
                if fut is None:
                    self._final_nodes.discard(n)
                    continue
                if fut.done():
                    result = fut.result()
                    if kungfu.is_err(result):
                        raise result.error
                    self._final_nodes.discard(n)
                else:
                    pending_futs.add(fut)
            if not self._final_nodes:
                break
            if not pending_futs:
                break
            await asyncio.wait(pending_futs, return_when=asyncio.FIRST_COMPLETED)
```

The `_push_futures_for` method wires the asyncio task DAG:

```python
    def _push_futures_for(self, graph_info, local_scope, mapped_scopes, futures):
        for node in graph_info.all_nodes:
            if node in futures:
                continue
            node_scope = mapped_scopes.get(node, local_scope)

            if issubclass(node, Either):
                if node.is_concurrent:
                    dep_futures = [futures[dep] for dep in node.__dependencies__]
                    futures[node] = asyncio.ensure_future(
                        _concurrent_either_coroutine(node, dep_futures, node_scope, local_scope, self._execute)
                    )
                else:
                    first_future = futures[node.__either__[0]]
                    futures[node] = asyncio.ensure_future(
                        _sequential_either_coroutine(first_future, node.__either__[1:], ...)
                    )
            elif _is_result_node(node):
                dep_futures = [futures[dep] for dep in node.__dependencies__]
                futures[node] = asyncio.ensure_future(
                    _result_node_coroutine(node, dep_futures, node_scope, local_scope, self._execute)
                )
            else:
                dep_futures = [futures[dep] for dep in node.__dependencies__]
                futures[node] = asyncio.ensure_future(
                    _compose_coroutine(node, dep_futures, node_scope, local_scope, self._execute)
                )
```

This IS the simulator. The `all_nodes` list IS the controller sequence. Each `asyncio.ensure_future` IS an instruction execution procedure. The futures wiring IS the data-path connections. The event loop IS the clock.

A plain node's coroutine:

```python
async def _compose_coroutine(node, dep_futures, node_scope, local_scope, execute):
    for dep_future in dep_futures:
        dep_result = await dep_future
        if kungfu.is_err(dep_result):
            return dep_result  # propagate error
    return await execute(node, node_scope, local_scope)
```

Await all dependency futures (the "fetch" -- wait for register values to be available). Then execute the node (the "execute" -- write result to scope). Error propagation is immediate: a failed dependency cancels all dependents.

The execution is a wavefront. Ready roots form the first wave. When they complete, their dependents (whose counters reach zero) form the next wave. Independent nodes within a wave run concurrently -- asyncio interleaving on one thread, not true parallelism.

For I/O-bound workloads -- HTTP calls, database queries, LLM invocations -- this is efficient. The event loop multiplexes many concurrent operations on one thread. No locks, no data races. But SICP warns us: the simulator runs "much more slowly" than compiled code. The asyncio task scheduling, future resolution, and scope lookups are overhead. The simulator is correct but not fast.

### 5.2.2 The Spawnable Protocol

SICP's simulator is static -- the instruction sequence is fixed before execution. But real systems evolve. nodnod agents support *live node management* through the Spawnable protocol:

```python
# emergent/graph/runtime/_spawnable.py
@runtime_checkable
class Spawnable(Protocol):
    def spawn(self, nodes, mapped_scopes=None): ...
    def despawn(self, nodes): ...
    @property
    def living_nodes(self) -> frozenset[type[Node]]: ...
```

`spawn()` adds new nodes to a running agent -- their dependency graph is built and scheduled immediately. `despawn()` removes nodes -- in-flight futures are cancelled. This is dynamic instruction injection: the controller sequence can grow while the machine is running.

CallbackAgent implements Spawnable by calling `_push_futures_for` with the new nodes' GraphInfo and waking the run loop. The existing futures are untouched. New futures wire into the existing task DAG. The machine's instruction memory is mutable.

---

## 5.3 The Compiler

SICP's compiler (5.5) generates register-machine instructions that execute directly on the machine's data paths -- no interpretation overhead. The compiled code uses the SAME registers and stack as the interpreter, but avoids the interpreter's per-expression classification and conservative save/restore. The key optimization: `preserving` wraps save/restore around a code sequence ONLY if the first sequence modifies a register that the second needs. Result: `(factorial 5)` compiled = 31 pushes, interpreted = 144 pushes.

emergent's compiler is `WorkStealing` -- N OS worker threads with work-stealing deques.

### 5.3.1 The WorkStealing Architecture

```python
# emergent/graph/runtime/_threaded.py
@dataclass(slots=True)
class _Task:
    node: type[Node]
    node_scope: Scope
    local_scope: Scope

@dataclass(slots=True)
class _Worker:
    worker_id: int
    loop: asyncio.AbstractEventLoop      # each worker has its own event loop
    thread: threading.Thread             # OS thread — true parallelism
    local_deque: collections.deque[_Task]  # work-stealing deque
    deque_lock: threading.Lock

@dataclass(slots=True)
class _WorkStealingPool:
    workers: tuple[_Worker, ...]
    shutdown_flag: threading.Event
```

N OS threads. N event loops. Work-stealing deques. Threading locks. This is what "WorkStealing scheduling" means at the register level. The abstract `RuntimePolicy(scheduling=WorkStealing())` becomes: create N threads, give each a deque, hash-distribute initial tasks, run steal-loops.

**Hash-based distribution:** `hash(node_type) % len(workers)` assigns each node type to a home worker:

```python
def _select_worker(pool, node):
    idx = hash(node) % len(pool.workers)
    return pool.workers[idx]
```

**LIFO push, FIFO steal:** A worker pushes ready tasks to the BACK of its own deque. When it finishes, it pops from the back -- getting the most recently pushed task, which likely shares cache lines with the just-completed task (they are adjacent in the dependency graph). A stealing worker takes from the FRONT -- the oldest task, farthest from the stealer's cache but the one that would wait longest. This is the Chase-Lev deque protocol:

```python
def _try_steal(worker, pool):
    for victim in pool.workers:
        if victim.worker_id == worker.worker_id:
            continue
        with victim.deque_lock:
            if victim.local_deque:
                return victim.local_deque.popleft()  # FIFO steal
    return None

def _push_task(worker, task):
    with worker.deque_lock:
        worker.local_deque.append(task)  # LIFO push
```

The per-worker steal loop:

```python
async def _steal_loop(worker, pool, run_state, graph_info):
    while not pool.shutdown_flag.is_set():
        task = None
        with worker.deque_lock:
            if worker.local_deque:
                task = worker.local_deque.pop()  # LIFO: local work first

        if task is None:
            task = _try_steal(worker, pool)  # steal from others

        if task is not None:
            await _execute_task(task, run_state, pool, graph_info)
        else:
            await asyncio.sleep(0.0001)  # brief yield before retrying
```

Each tick: check local deque (LIFO pop), if empty steal from another worker (FIFO popleft), if stolen execute, if nothing sleep briefly. This is the "compiled" execution: no asyncio task scheduling, no future resolution overhead -- direct thread execution with hardware parallelism.

### 5.3.2 The Scheduling Policy IS Fold

Here is the crucial insight: the scheduling policy is not just a runtime configuration. It is *itself* a compiler -- one that uses the same fold mechanism as Pydantic, OpenAPI, and SQL compilation:

```python
# emergent/graph/runtime/_policy.py
@dataclass(frozen=True, slots=True)
class WorkStealingContext:
    priority: int = 0

@runtime_checkable
class WorkStealingCompilable(Protocol):
    def compile_work_stealing(self, ctx: WorkStealingContext) -> WorkStealingContext: ...

@dataclass(frozen=True, slots=True)
class WorkStealing:
    workers: int | None = None
    requires_free_threaded: bool = True

    def build_agent(self, nodes):
        from emergent.wire.compile._core import fold_schema
        from emergent.graph.runtime._helpers import build_graph_info
        from emergent.graph.runtime._threaded import build_work_stealing_agent, resolve_worker_count

        graph_info = build_graph_info(nodes)

        # THE FOLD: same mechanism as Pydantic/OpenAPI/SQL compilation
        traits = {}
        for node in graph_info.all_nodes:
            ctx = fold_schema(
                node, WorkStealingContext(),
                WorkStealingCompilable, "compile_work_stealing"
            )
            if ctx != WorkStealingContext():
                traits[node] = ctx

        n_workers = resolve_worker_count(len(graph_info.all_nodes), self.workers)
        return build_work_stealing_agent(graph_info, n_workers, traits)
```

**Stop and predict.** A capability `Heavy` on a node implements `compile_work_stealing`:

```python
@dataclass(frozen=True, slots=True)
class Heavy(SchemaCapability):
    def compile_work_stealing(self, ctx: WorkStealingContext) -> WorkStealingContext:
        return replace(ctx, priority=max(ctx.priority, 10))
```

`fold_schema(node, WorkStealingContext(), WorkStealingCompilable, "compile_work_stealing")` iterates the node's schema_meta capabilities. `Heavy` implements the protocol -- it sets high priority. `MaxLen(255)` does not implement `WorkStealingCompilable` -- skipped (open-world). The fold produces a `WorkStealingContext(priority=10)` for that node.

The fold that compiles capabilities to Pydantic models is the SAME fold that compiles capabilities to scheduling traits. The compilation infrastructure IS compiled using the compilation infrastructure. This is SICP Exercise 5.50 already in the system: the compiler (fold) compiling the compiler's own configuration (scheduling decisions) using the compiler's own mechanism (fold_schema with protocol dispatch).

### 5.3.3 The Preserving Analog

SICP 5.5's key optimization: `preserving` wraps save/restore only when needed, while the interpreter always saves conservatively. The emergent analog: nodnod's dependency resolution computes `initial_pending` counters ONCE at build time. At runtime, the agent never asks "is this dependency satisfied?" -- it KNOWS, because the counter reached zero:

```python
def _on_node_complete(node, run_state, pool, graph_info):
    deps = graph_info.dependents.get(node, frozenset())
    for dependent in deps:
        with run_state.pending_lock:
            run_state.pending[dependent] -= 1
            ready = run_state.pending[dependent] == 0

        if ready:
            node_scope = run_state.mapped_scopes.get(dependent, run_state.local_scope)
            _submit_task(pool, _Task(dependent, node_scope, run_state.local_scope))
```

The interpreter (CallbackAgent) creates asyncio futures for *every* node and wires them with await chains -- conservative "save everything." The compiler (WorkStealing) tracks only pending counters -- no futures, no await chains, just atomic decrements. When the counter hits zero, the node is submitted directly to a worker. The "compiled" form does less work per node completion.

The concurrency is safe because:
- Scope writes are to unique keys (one per node type) -- no conflicting writes.
- Pending counters are protected by a lock (one atomic decrement per completion).
- Capabilities are frozen -- no shared mutable state.

### 5.3.4 A Worked Example

Consider the analytics pipeline from Section 5.1.4:

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

With `WorkStealing(workers=2)`:

**Step 1: Build graph info.** `build_graph_info({BuildReport})` traverses dependencies. Graph layers: Layer 0 = {FetchSales, FetchInventory} (ready roots). Layer 1 = {ComputeRevenue, ComputeStockValue}. Layer 2 = {BuildReport}.

**Step 2: Fold scheduling traits.** `fold_schema(node, WorkStealingContext(), WorkStealingCompilable, "compile_work_stealing")` for each node. No node has special traits in this example -- all default.

**Step 3: Create pool.** 2 worker threads. Worker 0 and Worker 1, each with an asyncio loop and a deque.

**Step 4: Submit ready roots.** `hash(FetchSales) % 2 = 0` -> Worker 0. `hash(FetchInventory) % 2 = 1` -> Worker 1.

**Step 5: Execution.**

```
Time 0ms:   Worker 0 starts FetchSales (DB query)
            Worker 1 starts FetchInventory (DB query)
            -- TRUE PARALLELISM on free-threaded Python --

Time 50ms:  Worker 1 completes FetchInventory
            -> pending[ComputeStockValue] decrements 1 -> 0
            -> submits ComputeStockValue to Worker 1 (hash-based)
            Worker 1 starts ComputeStockValue (CPU)

Time 55ms:  Worker 0 completes FetchSales
            -> pending[ComputeRevenue] decrements 1 -> 0
            -> submits ComputeRevenue to Worker 0 (hash-based)
            Worker 0 starts ComputeRevenue (CPU)

Time 56ms:  Worker 1 completes ComputeStockValue
            -> pending[BuildReport] decrements 2 -> 1
            Worker 1 is IDLE. Tries to steal from Worker 0.
            Worker 0's deque is empty (ComputeRevenue running).
            Worker 1 sleeps 0.1ms, retries.

Time 58ms:  Worker 0 completes ComputeRevenue
            -> pending[BuildReport] decrements 1 -> 0
            -> submits BuildReport to Worker 0 (hash-based)
            Worker 0 starts BuildReport.

Time 59ms:  Worker 0 completes BuildReport.
            -> remaining_finals reaches 0
            -> done_event set
            -> Both workers stop
```

Total: 59ms. Sequential: 50 + 50 + 3 + 3 + 1 = 107ms. The parallelism saves ~45%.

The programmer wrote ZERO concurrency code. No threads, no locks, no async/await coordination. The dependency graph was discovered from type signatures. The parallelism was determined by graph structure. The work-stealing scheduler handled load balancing. The programmer wrote pure nodes -- `async def __compose__` -- and the runtime did the rest.

### 5.3.5 Compiled and Interpreted Coexistence

SICP 5.5.7 closes the circle: compiled and interpreted code coexist on the same machine. `apply-dispatch` handles primitive, compound, AND compiled procedures -- three kinds of callable, all using the same registers.

emergent's analog: Cooperative and WorkStealing share the same Scope, the same Node types, the same GraphInfo, the same `compose_node` function. The `RuntimePolicy` selects which execution strategy to use:

```python
# emergent/graph/runtime/_policy.py
@dataclass(frozen=True, slots=True)
class RuntimePolicy:
    scheduling: SchedulingCompilable = field(default_factory=Cooperative)
    errors: ErrorPolicy = field(default_factory=FailFast)
    gil: GILResolvable = field(default_factory=RequireFreeThreaded)
```

`AutoDowngrade` is the fallback: if the hardware does not support the compiled form (GIL enabled, no free-threaded Python), silently downgrade to the interpreted form:

```python
@dataclass(frozen=True, slots=True)
class AutoDowngrade:
    def resolve_scheduling(self, scheduling, is_gil_enabled):
        if scheduling.requires_free_threaded and is_gil_enabled:
            return Cooperative()  # fall back to interpreter
        return scheduling
```

The "compiled" and "interpreted" runtimes share the same machine. Same nodes. Same scope. Same dependency graph. Same results. Different execution characteristics. The choice is a DEPLOYMENT decision, not a SEMANTIC one -- just as SICP's choice between interpretation and compilation does not change what the program means, only how fast it runs.

---

## 5.4 The Explicit-Control Evaluator

SICP 5.4 is the intellectual core of Chapter 5. The beautiful recursive `eval/apply` from Chapter 4 is flattened into a sequence of register operations: `eval-dispatch` tests the syntactic type of the expression in the `exp` register, branches to the handler, saves registers before recursive evaluation, restores after. Seven registers: `exp`, `env`, `val`, `continue`, `proc`, `argl`, `unev`. The reader who thought "eval calls apply" now sees the EXACT sequence of register operations. The abstraction dissolves into mechanism.

emergent's explicit-control evaluator is `World.run()`.

### 5.4.1 World.run(): Line by Line

```python
# theworld/src/theworld/_world.py
@dataclass(slots=True)
class World:
    log: Log
    computations: tuple[object, ...]
    policy: RuntimePolicy = field(default_factory=RuntimePolicy)

    async def run(self):
        from emergent import graph as G
        from emergent.graph.runtime import Spawnable

        # Step 1: eval-dispatch — classify and compile each computation
        ctx = fold(
            self.computations,
            WorldContext(log=self.log),
            WorldCompilable,
            "compile_world",
        )

        if not ctx.nodes:
            return

        # Step 2: set up environment register
        scope = G.TypedScope(detail="world")
        scope.inject(type(self.log), self.log)

        # Step 3: assemble — build the execution plan
        agent_cls = RuntimeAgent.with_policy(self.policy)
        agent = agent_cls.build(set(ctx.nodes))

        # Step 4: inject agent for live node management
        if isinstance(agent, Spawnable):
            scope.inject(Spawnable, agent)

        # Step 5: start machine
        await agent.run(local_scope=scope.inner, mapped_scopes={})
```

Line by line, this IS SICP 5.4:

1. **`fold(computations, WorldContext, WorldCompilable, "compile_world")`** = `eval-dispatch`. Each computation is classified by `isinstance(comp, WorldCompilable)`. Those that implement the protocol call their `compile_world` method, producing nodnod node types. This is the flat test-and-branch sequence: check the "expression type" (does it implement WorldCompilable?), dispatch to the handler (call compile_world), accumulate the result (add nodes to ctx.nodes).

2. **`scope.inject(type(self.log), self.log)`** = `(assign env (op get-global-environment))`. Set up the initial environment with the shared state that all computations need.

3. **`agent_cls.build(set(ctx.nodes))`** = `(assemble controller-text machine)`. Build the execution plan: topological sort, dependency analysis, pending counters, ready roots.

4. **`agent.run(scope, {})`** = `(start machine)`. Begin execution: submit ready roots, run the fetch-decode-execute cycle (Cooperative) or the steal loop (WorkStealing).

The computations ARE the expressions. The fold IS eval. The agent IS the controller. The scope IS the register file. The only structural difference: SICP's evaluator processes one expression at a time sequentially; World's agent processes a DAG of nodes potentially in parallel.

### 5.4.2 Computation.compile_world: How Expressions Become Instructions

```python
# theworld/src/theworld/_computation.py
@dataclass(frozen=True, slots=True)
class Computation[I]:
    identity: I
    capabilities: tuple[Capability, ...]
    runner: Runner | None = None

    def compile_world(self, ctx: WorldContext) -> WorldContext:
        from emergent import graph as G

        log = ctx.log
        comp = self

        async def _computation_loop():
            await comp.live(log)

        _computation_loop.__name__ = f"computation:{self.identity}"
        return replace(ctx, nodes=ctx.nodes | {G.node(_computation_loop)})
```

Each Computation that implements `WorldCompilable` creates a nodnod node wrapping its `live` coroutine and adds it to `ctx.nodes`. This is SICP's `ev-lambda`: the expression `(lambda (x) body)` produces a procedure object that closes over the environment. Here, the Computation produces a node that closes over its capabilities and the shared Log.

The `live` method runs the full lifecycle: perceive (Lens query on Log) -> act (direct events from fold) -> plan (Op tree from fold) -> emit (append events to Log) -> loop. Each phase is a fold:

```python
    async def live(self, log):
        lc = self.compile_lifecycle()  # fold -> LifecycleContext
        cycles = 0
        while lc.max_cycles is None or cycles < lc.max_cycles:
            events = await self.run(log)
            if events:
                await log.append(events)
            cycles += 1
            if lc.delay > 0:
                await asyncio.sleep(lc.delay)

    async def run(self, log):
        lens = self.compile_perception()  # fold -> Lens
        perceived = await log.query(lens)
        direct_events = self.compile_action(perceived)  # fold -> events
        op_events = ()
        if self.runner:
            ops = self.compile_plan(perceived)  # fold -> Op tree
            for op in ops:
                result = await self.runner.run(op)
                if is_ok(result):
                    op_events = (*op_events, *result.value)
        return (*direct_events, *op_events)
```

Four folds per computation cycle: perception (LensCompilable), action (ActionCompilable), lifecycle (LifecycleCompilable), plan (PlanCompilable). Each uses different protocols, different contexts, different methods. But the mechanism is always the same six lines of fold.

### 5.4.3 Tracing: The Machine Watches Itself

SICP 5.4.4 adds stack monitoring: `(total-pushes = 144, maximum-depth = 28)` for interpreted factorial. This instrumentation lets the reader MEASURE the machine.

emergent's `traced_fold` is the equivalent. When `trace=TraceCollector()` is passed to fold:

```python
# emergent/wire/compile/_core.py
def fold(items, initial, protocol, method, handlers=None, *, trace=None):
    if trace is not None:
        result, _ = traced_fold(items, initial, protocol, method, handlers, trace)
        return result
    ctx = initial
    for item in items:
        item_cls = item.__class__
        if handlers and item_cls in handlers:
            ctx = handlers[item_cls](item, ctx)
        elif isinstance(item, protocol):
            ctx = getattr(item, method)(ctx)
    return ctx
```

The production fold has zero tracing overhead -- a single branch prediction (`if trace is not None`). `traced_fold` records every step:

```python
def traced_fold(items, initial, protocol, method, handlers, collector):
    ctx = initial
    steps = []
    for item in items:
        item_cls = item.__class__
        ctx_before = ctx
        if handlers and item_cls in handlers:
            ctx = handlers[item_cls](item, ctx)
            dispatch = "handler"
        elif isinstance(item, protocol):
            ctx = getattr(item, method)(ctx)
            dispatch = "protocol"
        else:
            dispatch = "skipped"
        step = FoldStep(
            item_type=item_cls.__qualname__, dispatch=dispatch,
            method=method, context_before=ctx_before, context_after=ctx,
            changed=ctx_before is not ctx,
        )
        collector.fold_step(step)
        steps.append(step)
    fold_trace = FoldTrace(
        protocol=protocol.__qualname__, method=method,
        initial=initial, final=ctx,
        steps=tuple(steps), items_total=len(steps), items_applied=...,
    )
    collector.fold_complete(fold_trace)
    return ctx, fold_trace
```

Every step is recorded as a frozen dataclass: which item, how it dispatched (handler / protocol / skipped), the context before and after, whether it changed. Because all contexts are frozen dataclasses, the "before" and "after" snapshots are the actual immutable values -- no defensive copy needed. The trace IS the execution history.

The `explain` system reads the trace:

```python
axes = Axes.traced()
FASTAPI_SCHEMA.compile(User, axes)
print(explain(axes))
```

Output shows every fold step: which capability fired, which was skipped, how the context evolved. Five explain systems read the same frozen trace data: schema, surface, query, compilation, derive. Each is a catamorphism over the trace tree. `explain` is fold applied to fold's own output.

---

## 5.5 The Six-Fold Trace

Let us trace, in complete detail, the execution path from a capability annotation to an HTTP response arriving at a client's browser. This is the "register trace" -- SICP Chapter 5.5 tracing the execution of a Scheme expression through every register operation.

**The source:**

```python
@derive(http_crud("/users", Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
```

### 5.5.1 compile_derive: Three Folds (Folds 1-3)

When `build_application_from_decorated(User)` is called, `compile_derive(User)` runs three folds. These are the phases we traced in Chapter 1 (Section 1.2.4). From the Chapter 5 perspective, the question is not *what* each fold produces but *what each fold costs at the machine level.*

```python
# emergent/wire/derive/_compile.py
def compile_derive(cls):
    caps = get_schema_meta(cls)  # retrieve (http_crud("/users", Users),)
    ctx = DeriveCtx.from_entity(cls)

    # Fold 1: Generate
    ctx = fold_schema(cls, ctx, DeriveGeneratable, "compile_derive_generate")
    # Fold 2: Modify
    ctx = fold_schema(cls, ctx, DeriveModifiable, "compile_derive_modify")
    # Fold 3: Augment
    ctx = fold_schema(cls, ctx, DeriveAugmentable, "compile_derive_augment")
    return [ctx]
```

Fold 1 (Generate): `fold_schema` retrieves `(http_crud("/users", Users),)` and iterates. `isinstance(http_crud, DeriveGeneratable)` -- True. Call `http_crud.compile_derive_generate(ctx)`. The method inspects User's fields (id: Identity, name: str) and generates OpSpecs: List, Get, Create, Update, Patch, Delete, Upsert. Each OpSpec carries: name, input fields, output spec, handler template, HTTPRouteTrigger, effects. One isinstance check, one getattr, one method call, seven OpSpecs produced.

Fold 2 (Modify): Same capabilities, different protocol. `isinstance(http_crud, DeriveModifiable)` -- False, skipped. No modifiers in this example. Zero method calls.

Fold 3 (Augment): Same capabilities, third protocol. Both skipped. Zero method calls.

Three fold invocations. For this simple entity: 3 isinstance checks total (one capability x three phases), 1 method call. The cost is trivial here. It will not stay trivial.

### 5.5.2 materialize: OpSpecs Become Endpoints (Fold 4 -- Surface)

`materialize(ctx)` takes the DeriveCtx with 7 OpSpecs and produces an Endpoint. For each OpSpec, `build_from_spec` creates:

- A frozen dataclass type: `UserListOp(provider: MutatingRelationalProvider)` for List, `UserGetOp(id: int, provider: ...)` for Get.
- An async handler function from the handler template.
- An Exposure: `HTTPRouteTrigger("GET", "/users")` + `RequestResponseCodec(UserListOp, UserListResponse)` + error capabilities.

All (OpType, handler) pairs are registered via `ops().on(...)`. `.compile()` produces a Runner backed by nodnod.

Result: `Endpoint(runner=Runner, exposures=(Exposure(GET /users, rrc), Exposure(GET /users/{id}, rrc), Exposure(POST /users, rrc), ...))`.

Then `targets.fastapi.compile(app)` creates a FastAPI instance and iterates via `FASTAPI_COMPILER.scan_and_wrap(app, axes)`:

```python
# emergent/wire/compile/_target.py (inside scan_and_wrap)
for binding in self.adapters:
    for trigger, handler in scan(app, self.trigger_type, binding.codec_type):
        ctx = binding.from_codec(handler.codec, trigger)

        # Fold 4: Surface — fold surface capabilities through pipeline
        ctx = fold(
            handler.capabilities, ctx,
            self.pipeline_protocol, self.pipeline_method,
            trace=trace,
        )

        wrapped = self.assemble(ctx, handler, axes)
        yield trigger, handler, wrapped
```

For each Exposure with HTTPRouteTrigger: `from_codec` seeds the context from codec and trigger. `fold(capabilities, ctx, FastAPIPipelineCompilable, "compile_fastapi_pipeline")` folds surface capabilities -- error handlers set up RFC 7807 responses, authentication sets up bearer extraction, rate limiting configures middleware. Then `assemble` produces the framework-native route.

### 5.5.3 Pydantic Compilation and Enrichers (Folds 5-6)

**Fold 5 (Schema):** Inside the assembled route function, when a request arrives, the Pydantic model validates the body. That model was built by fold at compile time: `fold_field(field, PydanticContext(...), PydanticCompilable, "compile_pydantic")` for each field. `MaxLen(255)` implements `PydanticCompilable` -- produces `max_length=255`. `Identity` implements it -- marks the field as auto-generated. `Unique` does not -- skipped (open-world). Per field, per endpoint that needs a request/response model.

**Fold 6 (Enricher):** At request time, `fold_handler_runtime(capabilities)` extracts ScopeEnrichers from surface capabilities. `chain_enrichers(enrichers, core_handler)` builds the middleware stack: `e1(e2(e3(core)))`. First enricher runs first. Each enricher's method is target-specific: `BearerExtract.enrich_fastapi` reads the Authorization header; `BearerExtract.enrich_cli` reads a --token argument. Same capability, different extraction -- dispatched by the `target` parameter.

### 5.5.4 Request to Response

**Step 7: uvicorn.** `uvicorn.run(fastapi_app)` starts an asyncio event loop, binds TCP socket (default 8000), waits for connections.

**Step 8: Request arrives.** `POST /users` with body `{"name": "Alice"}`.

- uvicorn reads bytes from TCP, parses HTTP headers, identifies route.
- FastAPI router matches to compiled route function.
- Route function executes:
  1. Creates nodnod Scope. Injects `fastapi.Request`.
  2. Extracts JSON body: `{"name": "Alice"}`.
  3. Pydantic model (compiled at Fold 5) validates. Identity field is auto-generated. Accepts `{"name": "Alice"}`.
  4. Builds domain Op: `UserCreateOp(name="Alice", provider=memory_provider)`.
  5. `execute_rrc(handler, request_obj, scope)`:
     - Enricher chain (Fold 6) runs. No enrichers in this example -- core handler runs directly.
     - `request_obj.to_domain()` -> `UserCreateOp(name="Alice", ...)`.
     - `runner.run(op)` -> nodnod composes the op node.
     - Handler: generates id via `provider.next_id()` -> 1. Constructs `User(id=1, name="Alice")`. Inserts. Returns `Ok(User(id=1, name="Alice"))`.
     - `response_type.from_domain(Ok(...))` -> `{"id": 1, "name": "Alice"}`.
  6. FastAPI serializes to JSON. Sets Content-Type. Returns 201.
- uvicorn writes HTTP response bytes to TCP socket.
- Client receives: `{"id": 1, "name": "Alice"}`.

**Six folds in this path.** Generate (CRUD -> OpSpecs). Modify (transforms, trivial here). Augment (trivial). Surface (error capabilities -> route config). Schema (field capabilities -> Pydantic model). Enricher (capabilities -> middleware chain). Each fold is the same eight lines. Each operates on different data, uses different protocols. But the mechanism is always: iterate frozen data, check isinstance, call compile_* method, accumulate context.

---

## 5.6 The Crisis

### 5.6.1 The Cost of Abstraction

The reader has been treating fold as a single primitive operation -- "iterate capabilities, accumulate context." Now count what that operation costs.

Consider a system with 10 entities, 7 fields each, 5 compilation phases (Pydantic, OpenAPI, SQLAlchemy, Verification, Constraints), and 3 capabilities per field.

For field-level compilation alone:

```
10 entities x 7 fields x 5 phases x 3 capabilities = 1,050 fold iterations
```

Each iteration: one `isinstance(item, protocol)` check (MRO traversal of the item's class hierarchy), one `getattr(item, method)` call (dict lookup on the class), one method call (function invocation creating a new frozen context via `dataclasses.replace`). The fold's "one line of iteration" is actually: MRO check + dict lookup + function call + dataclass copy. Per capability. Per field. Per phase.

Add schema-level folds: 10 entities x 5 phases x ~2 schema caps = 100 more. Derive folds: 10 entities x 3 phases = 30 more. Surface folds: 10 entities x 7 endpoints x 1 pipeline fold = 70 more. Pydantic model construction: 10 entities x 7 fields = 70 fold_field calls. Total: over 1,300 fold invocations.

**Stop and predict.** The "six-line function" is a loop that runs 1,300 times. Each iteration involves Python's MRO traversal, dict lookup, function call, and frozen dataclass replacement. The machine cost of the abstraction is not zero. It is O(entities x fields x phases x capabilities).

This is SICP's crisis made concrete. The metacircular evaluator of Chapter 4 seemed to "just work." Now we see the register operations: every isinstance is a real computation. Every getattr is a real dict lookup. Every compile_* method call is a real function invocation that allocates a new frozen dataclass.

### 5.6.2 The Optimization: 31 vs 144 Pushes

SICP's revelation: `(factorial 5)` compiled = 31 pushes, interpreted = 144 pushes. The interpreter does unnecessary work -- conservative save/restore that the compiler skips.

nodnod's revelation: the dependency graph that fold produces CAN be parallelized.

Consider a World with 10 computations, each with 4 internal nodes (perception, action, lifecycle, plan). Under Cooperative (the "interpreter"): one event loop, one thread. 40 node compositions executed in dependency order but interleaved on a single thread. If each node takes ~10ms: total time is roughly O(critical-path-length x 10ms), but the event loop adds scheduling overhead per node (asyncio future creation, callback registration, task switching).

Under WorkStealing(workers=4) (the "compiler"): 4 OS threads. Independent computations run truly in parallel. If the 10 computations have no inter-dependencies: 10 computations / 4 workers = ~3 waves. Each wave: 4 x (4 nodes x 10ms) = 40ms. Total: ~120ms. Cooperative with one thread: 10 x (4 nodes x 10ms) = 400ms. 3.3x speedup.

The abstract `RuntimePolicy(scheduling=WorkStealing(workers=4))` -- a frozen dataclass, a capability consumed by fold -- produces a 3x+ speedup. The abstraction that describes the machine is compiled by the same fold that describes the data.

And the cost of the 1,300 fold invocations during compilation? They happen ONCE, at import time. At runtime, the compiled artifacts (Pydantic models, FastAPI routes, nodnod DAGs) execute without re-folding. Compilation is O(entities x fields x phases x capabilities). Execution is O(request). The compiler's work is amortized across all requests -- just as SICP's compiler does classification once at compile time rather than per-evaluation.

---

## 5.7 Storage

SICP Chapter 5.3 addresses memory management -- how cons cells are allocated and garbage collected. The emergent analog is not memory management (delegated to Python's runtime) but the *Log* -- theworld's append-only event store.

The Log grows without bound. Querying the entire Log to reconstruct state becomes expensive as events accumulate. `ViewSnapshot` provides incremental computation:

```python
await put(log, ViewSnapshot(view_id="progress", state=progress_state, cursor=current_position))
```

A ViewSnapshot is an event -- a frozen dataclass in the Log, queryable through Lens. On restart, a Computation queries the last ViewSnapshot, recovers its cursor, and continues folding from that point. O(delta) recovery instead of O(all events).

This is the emergent analog of garbage collection. SICP's GC reclaims memory by identifying unreachable data. The append-only Log cannot discard events -- but ViewSnapshot makes it *unnecessary* to process old data. Where GC says "this cons cell is unreachable, reclaim it," ViewSnapshot says "these events are summarized in this checkpoint, skip them."

The TieredLog extends this with multiple storage backends:

```python
log = TieredLog(
    TierBinding(Ephemeral, InMemoryLog()),    # fast, volatile
    TierBinding(Durable, sqlite_log),          # persistent
)
```

Events carry a tier marker. The SQLite backend uses emergent's wire compilation: `compile_sa(EventType, "table_name")` produces a SQLAlchemy model from the event's frozen dataclass. The same fold that generates Pydantic models also generates the storage layer. One encoding. Every level.

---

## 5.8 The Duality: fold and nodnod

We have been treating nodnod as the machine that executes fold's output. Scope is the register file, Node is the instruction, Agent is the controller. This framing is correct but incomplete. It makes nodnod sound like an implementation detail -- the hardware under the abstraction. It is not. nodnod is the second primitive.

### 5.8.1 Two Primitives, One Platform

emergent is built on two co-equal primitives:

| | fold | nodnod |
|---|---|---|
| **Reads** | Annotated capabilities | `__compose__` signatures |
| **Produces** | Compiled context (PydanticContext, OpSpec...) | Parallel execution plan (DAG) |
| **When** | Import / compile time | Request / run time |
| **Data structure** | Flat list (free monoid) | Dependency graph (DAG) |
| **Accumulator** | Context (frozen, immutable via replace) | Scope (mutable OrderedDict with parent chain) |
| **Dispatch** | `isinstance(item, protocol)` | type-keyed `scope.retrieve(Node)` |

Both share one design principle: **types are the specification language**.

In fold, `Annotated[str, MaxLen(255)]` IS the compilation input. The type annotation carries the metadata. The fold reads it.

In nodnod, `async def __compose__(cls, db: Database, user: CurrentUser)` IS the dependency graph. The function signature carries the edges. The agent reads them.

Neither requires registration. Neither requires a separate declaration file. Neither has a central dispatch table. The structure IS the program.

### 5.8.2 Node.__init_subclass__: nodnod's fold

nodnod's compilation happens at class definition time, inside `Node.__init_subclass__`. When you write:

```python
@G.node
class FetchUser:
    @classmethod
    async def __compose__(cls, order: Order, db: Database) -> FetchUser:
        return cls(await db.get_user(order.user_id))
```

Python calls `__init_subclass__` before any instance exists. Inside:

1. `resolve_signature(cls.__compose__)` extracts the parameter types: `{"order": Order, "db": Database}`.
2. For each param, classify:
   - `is_type(dep_type, Node)` → add to `__dependencies__` (graph edge)
   - `is_type(dep_type, Composable)` → auto-create node wrapper, add to `__dependencies__`
   - `is_union(dep_type)` → create `SequentialEither` node
   - `is_option(dep_type)` → create `SomeNode | NothingNode` either
   - `is_result(dep_type)` → create `ResultNode`
   - else → add to `__injections__` (runtime scope lookup)
3. Build `__initialize__`: a composed pipeline that maps scope Values to keyword arguments:
   ```python
   kungfu.F[set[Value]]()
       .then(lambda values: {name_by_type[v.cls]: v.unbox() for v in values})
       .then(lambda ctx: call_with_context(__compose__, ctx).unwrap())
   ```
4. Compute `__traverse__` via depth-first topological sort.

Compare this with fold:

| fold compilation | nodnod compilation |
|---|---|
| For each item in capability list | For each param in signature |
| `isinstance(item, protocol)` → call compile_* | `is_type(param, Node)` → add to __dependencies__ |
| Unknown items silently skipped (open-world) | Non-node types become injections |
| Result: transformed Context | Result: compiled Node with __initialize__ |
| Happens when fold() is called | Happens at class definition time |

Both are "read typed metadata, produce compiled artifact." Both enable open-world extension. The difference: fold processes a list of capabilities sequentially. nodnod processes a signature of types simultaneously (because the dependency graph resolves in parallel).

### 5.8.3 ScopeFamily: nodnod's SchemaCompiler

`SchemaCompiler` is a composable set of phases keyed by `context_type`:

```python
FULLSTACK = FASTAPI_SCHEMA + CLI_SCHEMA + SA_SCHEMA
ec = FULLSTACK.compile(User, axes)
```

`ScopeFamily` is a composable set of type-to-tier bindings keyed by node type:

```python
family = (
    ScopeFamily[Tier]()
    .bind(App, DBPool, Config)
    .bind(Request, CurrentUser, AuthToken)
)
combined = auth_family | db_family   # merge, right wins
mapped = family.materialize({App: app_scope, Request: req_scope})
```

| SchemaCompiler | ScopeFamily |
|---|---|
| Keyed by context_type | Keyed by node_type |
| `+` (left-biased union) | `\|` (right-biased merge) |
| `.compile(entity) → EntityCompilation` | `.materialize(scopes) → mapped_scopes` |
| Combines compilation phases | Combines DI tiers |

Same idea: **composable typed mapping, interpreted into a concrete artifact**. This is the platform pattern. SchemaCompiler is one algebra on the platform. ScopeFamily is another. Both use frozen dataclasses, immutable operations, and pure interpretation. The platform doesn't privilege either -- they are independent libraries built on the same foundation.

### 5.8.4 ops/ — The Simplest Pipeline

The `emergent.ops` module is 400 lines. It is the simplest possible emergent pipeline: compile-time wiring + runtime execution, with nothing in between. No wire, no derive, no FastAPI. Just the core pattern.

**The description:**

```python
@dataclass(frozen=True, slots=True)
class GetPrice(Op[float, str]):
    product_id: int

@dataclass(frozen=True, slots=True)
class BuildSummary(Op[str, str]):
    product_id: int
    price: GetPrice     # dependency — graph edge
    stock: GetStock     # dependency — graph edge
```

`Op[T, E]` is a frozen dataclass. Like a capability, it is data that describes intent. Unlike a capability, it also describes *dependencies* -- its dataclass fields that are themselves Ops become edges in the execution graph.

**The compilation:**

```python
runner = (
    ops()
    .on(GetPrice, get_price_handler)
    .on(GetStock, get_stock_handler)
    .on(BuildSummary, build_summary_handler)
    .compile()
)
```

`compile()` reads each handler's signature, creates a nodnod Node per handler, and wires Op dependencies as graph edges. `build_summary_handler(req, price: GetPrice, stock: GetStock)` -- the `price` and `stock` params are Op types, so their nodes become dependencies.

**Stop and predict.** When `runner.run(BuildSummary(product_id=42, price=GetPrice(42), stock=GetStock(42)))` executes, which operations run in parallel?

The answer: `GetPrice` and `GetStock` have no dependencies on each other -- both depend only on injected data. nodnod schedules them concurrently. `BuildSummary` depends on both -- it waits. When both complete, their results are wrapped in `_CachedOp` (instant `.get()`) and passed to the summary handler. The programmer wrote *zero concurrency code*. The parallelism was derived from the type structure.

**The microcosm:**

| emergent concept | ops/ analog |
|---|---|
| Capability (frozen data) | Op (frozen dataclass) |
| compile_* method | handler function |
| CompilationPhase | handler registration (ops().on()) |
| SchemaCompiler.compile() | runner = ops().compile() |
| fold(capabilities → context) | agent.run(scope → results) |
| FastAPI route (compiled artifact) | nodnod DAG (execution plan) |

ops/ demonstrates that emergent's two primitives -- fold for compilation, nodnod for execution -- compose into complete systems with minimal ceremony. The 400 lines include: Op base class, handler registration, node creation from signatures, dependency collection, agent execution, and result caching. That's an entire compile-and-execute pipeline. Everything larger (wire, derive, theworld) is this pattern scaled up.

### 5.8.5 Either: combinators Lifted to the Graph

The tower from the architecture document (kungfu → combinators → nodnod → emergent) is not metaphorical. It is concrete in code.

`SequentialEither` is combinators.py's `fallback_chain` lifted to the graph level. In combinators:

```python
result = await fallback_chain(
    fetch_from_cache,
    fetch_from_db,
    fetch_from_remote,
)
```

Try each computation in order. First success wins. In nodnod:

```python
class Data(SequentialEither):
    __either__ = (CacheData, DBData, RemoteData)
```

Same semantics: try alternatives in order, first success wins. But the alternatives are *nodes in a dependency graph*, not functions in a chain. If `CacheData` fails, `DBData`'s dependencies are built and scheduled lazily -- only when needed. The fallback is driven by graph structure, not explicit sequencing.

`ConcurrentEither` is combinators.py's `race_ok` lifted:

```python
class Data(ConcurrentEither):
    __either__ = (SourceA, SourceB, SourceC)
```

All alternatives race concurrently. First success wins. Others are abandoned. In combinators, this is `race_ok(a, b, c)`. In nodnod, it is a node whose dependencies are the alternatives, all scheduled at once.

Each level of the tower lifts the previous level's primitives to a higher abstraction:

| Level | Primitive | Lifted to graph |
|---|---|---|
| kungfu | `Result[T, E]` — typed errors | Node returns `Result` |
| combinators | `fallback_chain` — sequential try | `SequentialEither` |
| combinators | `race_ok` — concurrent race | `ConcurrentEither` |
| combinators | `retry` / `timeout` | (future: scheduling capabilities) |

The abstraction doesn't add complexity. It removes it. `fallback_chain` requires you to compose the chain explicitly. `SequentialEither` discovers the chain from type declarations.

---

Kepler wanted to show that the heavenly machine is clockwork -- all manifold motions caused by a single weight. We have traced the clockwork. The Scope is the register file. The Node is the instruction, compiled at class definition time. The GraphInfo is the controller sequence. CallbackAgent is the simulator -- asyncio tasks wired by futures. WorkStealing is the compiler -- OS threads with work-stealing deques. World.run() is the explicit-control evaluator -- fold becoming register operations.

The fold that compiles capabilities to Pydantic models is the same fold that compiles capabilities to scheduling decisions. The machine that executes compiled capabilities is itself configured by fold. The compiler compiles the compiler's own configuration.

1,300 fold invocations for 10 entities. Each one: isinstance, getattr, method call, frozen dataclass replacement. The "six-line function" is a loop that runs a thousand times. But it runs ONCE -- at import time. At runtime, the compiled artifacts execute without re-folding. The penalty of explicit mechanism is also the opportunity for optimization. The abstraction that seemed to cost nothing has a measurable price. The explicit-control machine reveals that price. The compiler -- WorkStealing, target compilation, the `preserving` analog of build-time dependency resolution -- eliminates the overhead that the interpreter could not avoid.

Two primitives. fold compiles descriptions. nodnod executes dependency graphs. RuntimePolicy bridges them -- a compiler that uses fold to read capabilities and nodnod to run the result. The scheduling policy is itself a compilation target. The execution plan is itself compiled. The clockwork compiles the clockwork.

One fold. One graph executor. The rest is clockwork.

---

## Exercises

**Exercise 5.1.** Design a register-machine simulator for fold. The "registers" are: `items` (list), `idx` (current index), `ctx` (current context), `protocol` (the protocol type), `method` (the method name). The "instructions" are: LOAD_ITEM, CHECK_HANDLER, CHECK_ISINSTANCE, CALL_METHOD, SKIP, INCREMENT, TEST_DONE, HALT. Write the instruction sequence for folding `[MaxLen(255), Unique, sql.Index()]` through PydanticCompilable. Trace the register state at each step. How many total instructions for this three-item fold?

**Exercise 5.2.** The Cooperative runtime uses asyncio -- single-thread, coroutine-based concurrency. The WorkStealing runtime uses N OS threads. Design a THIRD runtime: `DistributedAgent`, where nodes execute on remote machines via a shared Log. Each machine runs a subset of nodes. Dependencies cross machine boundaries through Log events. What are the challenges? (Hint: consider scope access across machines, and how `retrieve` would work when the value was computed on a different host.)

**Exercise 5.3.** The `GraphInfo` data structure contains `initial_pending` -- the number of unsatisfied dependencies for each node, computed once. Design a scenario where the dependency count changes dynamically -- a node that, depending on its input, spawns additional dependencies. Can the current GraphInfo structure support this? How does the `Spawnable` protocol (spawn/despawn) relate to dynamic dependency management?

**Exercise 5.4.** Enable tracing for a User entity with Identity, MaxLen(255), Unique, Timestamps, SchemaName("users"). Count: how many FoldSteps across PydanticCompilable, SQLAlchemyCompilable, and OpenAPICompilable? How many "skipped" vs "protocol" dispatches? What is the ratio? What does the ratio tell you about the open-world design?

**Exercise 5.5.** Instrument the 6-fold trace from Section 5.5 for a system with 10 entities, 7 fields each, 3 capabilities per field, 5 compilation phases. Compute the total number of isinstance checks, getattr calls, and dataclass.replace invocations. How does this scale with entity count (linear? quadratic?)? At what point would compilation time become noticeable (estimate: isinstance ~100ns, getattr ~50ns, replace ~500ns)?

**Exercise 5.6.** SICP 5.3 discusses garbage collection -- reclaiming memory from unreachable data. The append-only Log never reclaims. Design a "Log compaction" mechanism that: (a) preserves all ViewSnapshots, (b) removes raw events older than the oldest ViewSnapshot's cursor, (c) maintains correctness for all computations that use ViewSnapshot-based recovery. What invariants must hold? Under what conditions is compaction safe?

**Exercise 5.7.** The enricher chain `chain_enrichers(enrichers, core_handler, target="fastapi")` wraps the core handler. Execution order: first enricher runs first (outermost). Design an enricher `TimeExecution` that measures time taken by all inner enrichers plus the core handler. Where must it be placed? Can it be placed anywhere? What if you want to measure EACH enricher separately?

**Exercise 5.8.** WorkStealing uses `hash(node) % len(workers)` for task distribution. This may produce unbalanced loads. Design an alternative using GraphInfo's `get_layers`: assign layers to workers in round-robin. Show that this produces better balance for wide, shallow graphs and worse for narrow, deep graphs.

**Exercise 5.9.** `AutoDowngrade` silently falls back from WorkStealing to Cooperative when GIL is enabled. Design a THIRD GIL policy: `HybridMode`, which uses WorkStealing for I/O-bound nodes and Cooperative for CPU-bound nodes within the same graph. How would you classify nodes? (Hint: capabilities could declare `compile_work_stealing` with an `io_bound` flag.) What changes to the agent architecture would this require?

**Exercise 5.10.** SICP Exercise 5.50: "Use the compiler to compile the metacircular evaluator." In emergent: `WorkStealing.build_agent()` folds capabilities using `WorkStealingCompilable` -- the fold compiling the fold's own scheduling. Write a capability `AdaptiveScheduling` that implements both `compile_work_stealing` and `compile_pydantic`. When attached to an entity, it affects both the Pydantic model (adds a computed field showing scheduling priority) and the WorkStealing scheduler (sets priority). One frozen dataclass, two compilation targets, zero coupling between them. Is this the fold compiling the fold?

**Exercise 5.11.** The full path from `@derive` annotation to TCP bytes involves six folds (Section 5.5). But World.run() adds more: `fold(computations, WorldContext, WorldCompilable, "compile_world")` plus four per-cycle folds per computation (perception, action, lifecycle, plan). For a World with 5 computations running 100 cycles each: how many total fold invocations? How does this compare to the static compilation cost?

**Exercise 5.12.** Section 5.8.2 shows that `Node.__init_subclass__` classifies params by type: Node → dependency, Composable → auto-node, union → SequentialEither, Option → SomeNode|NothingNode. This parallels fold's dispatch: isinstance(item, protocol) → call, else → skip. Design a scenario where a node's `__compose__` signature contains `data: Option[CachedResult]`. Trace: what node types does nodnod create? What does the dependency graph look like? What happens if `CachedResult` fails to compose?

**Exercise 5.13.** `ScopeFamily[Tier]().bind(App, DBPool).bind(Request, CurrentUser)` produces a composable typed mapping. `SchemaCompiler(phases=(PYDANTIC_PHASE, OPENAPI_PHASE))` also produces a composable typed mapping. Both use frozen dataclasses and support algebraic operations. Design a THIRD composable typed mapping: `PolicyFamily[Priority]().bind(High, AuthNode, PaymentNode).bind(Low, LogNode, MetricsNode)`. What would `.materialize()` produce? How would a custom scheduling policy use it?

**Exercise 5.14.** The ops/ module (Section 5.8.4) creates nodnod Nodes from handler signatures at compile time. This is the same staging pattern as wire.derive: read types → build IR → execute. Write a minimal ops system in ~50 lines: just Op base class, one `.on()` registration, and `.run()` that creates a Scope, injects the request, builds an EventLoopAgent, and retrieves the result. How many of the 400 lines in `_graph.py` are essential vs. convenience?

**Exercise 5.15.** Section 5.8.5 claims that `SequentialEither` is `fallback_chain` lifted to the graph. Verify this: write a computation that uses `fallback_chain(fetch_cache, fetch_db)` from combinators.py, then rewrite it as a nodnod graph with `class Data(SequentialEither): __either__ = (CacheData, DBData)`. Are the semantics identical? What happens when the fallback's second alternative has its own dependencies? Which version handles that automatically?
