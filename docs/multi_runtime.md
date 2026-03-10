# Multi-Runtime — Open-World Graph Execution

## Overview

The graph runtime is a **compilation target**. Each scheduling policy is a compiler: it defines its own context, its own protocol, folds `schema_meta` from nodes, and builds an agent. Third-party policies work without any emergent changes — open-world by construction.

```python
from emergent.graph.runtime import RuntimeAgent, RuntimePolicy, WorkStealing

agent_cls = RuntimeAgent.with_policy(RuntimePolicy(
    scheduling=WorkStealing(workers=4),
))
pipeline = graph(ProcessOrder, agent_cls=agent_cls)
```

---

## 1. Built-in Scheduling Policies

### Cooperative

Single-thread `asyncio.gather` via `CallbackAgent`. Default.

```python
from emergent.graph.runtime import RuntimePolicy, Cooperative

policy = RuntimePolicy(scheduling=Cooperative())
```

Uses `CallbackAgent` internally — same DAG semantics as nodnod's `EventLoopAgent`, but lives in emergent (modifiable) and supports `Spawnable` (live node management). No per-node capabilities — ignores all `schema_meta`. Trivial compiler.

### WorkStealing

N OS threads with work-stealing deques. Requires free-threaded Python (3.13t+).

```python
from emergent.graph.runtime import RuntimePolicy, WorkStealing

# Auto workers: min(cpu_count, node_count)
policy = RuntimePolicy(scheduling=WorkStealing())

# Explicit
policy = RuntimePolicy(scheduling=WorkStealing(workers=8))
```

Defines `WorkStealingContext` + `WorkStealingCompilable` protocol. Capabilities can implement `compile_work_stealing()` to affect per-node scheduling behavior. Folded traits are stored on the agent and available via `agent.traits`.

```python
from emergent.graph.runtime import WorkStealingContext, WorkStealingCompilable
```

### ThreadedAgent (convenience alias)

```python
from emergent.graph.runtime import ThreadedAgent

# Equivalent to:
# RuntimeAgent.with_policy(RuntimePolicy(
#     scheduling=WorkStealing(),
#     errors=FailFast(),
#     gil=RequireFreeThreaded(),
# ))
pipeline = graph(ProcessOrder, agent_cls=ThreadedAgent)
```

---

## 2. GIL Resolution

GIL policies implement `GILResolvable` — decides what to do when scheduling requires free-threaded Python but GIL is enabled.

```python
from emergent.graph.runtime import RequireFreeThreaded, AutoDowngrade

# Hard error (default)
RuntimePolicy(scheduling=WorkStealing(), gil=RequireFreeThreaded())

# Silent fallback to Cooperative
RuntimePolicy(scheduling=WorkStealing(), gil=AutoDowngrade())
```

---

## 3. Error Policy

Controls how the runtime handles node failures.

```python
from emergent.graph.runtime import FailFast, CollectErrors

# First error kills the entire graph (default, current behavior)
RuntimePolicy(errors=FailFast())

# CollectErrors is reserved for future use — raises NotImplementedError
RuntimePolicy(errors=CollectErrors())  # NotImplementedError
```

`ErrorPolicy = FailFast | CollectErrors` — union type for the `errors` axis.

---

## 4. Per-Node Capabilities via schema_meta

Capabilities are `SchemaCapability` subclasses — self-contained compiler plugins. Each scheduling policy defines its own context and protocol. Capabilities implement `compile_*` methods against whichever compilers they care about. Unknown capabilities are silently skipped (open-world).

Traits are folded for **all nodes** in the graph (targets + transitive dependencies), not just the target nodes.

```python
from dataclasses import dataclass, replace
from emergent.wire.axis.schema._universal import SchemaCapability, schema_meta
from emergent.graph.runtime import WorkStealingContext

@dataclass(frozen=True, slots=True)
class Priority(SchemaCapability):
    value: int

    def compile_work_stealing(self, ctx: WorkStealingContext) -> WorkStealingContext:
        return replace(ctx, priority=self.value)

@schema_meta(Priority(10))
@scalar_node
class HeavyComputation:
    @classmethod
    async def __compose__(cls, data: InputData) -> Result: ...
```

One capability can implement compile methods for **multiple** compilers — just like `MaxLen` implements both `compile_pydantic` and `compile_openapi`:

```python
@dataclass(frozen=True, slots=True)
class Heavy(SchemaCapability):
    def compile_work_stealing(self, ctx: WorkStealingContext) -> WorkStealingContext:
        return replace(ctx, priority=max(ctx.priority, 100))

    def compile_ray(self, ctx: RayContext) -> RayContext:
        return replace(ctx, offload=True)
```

WorkStealing sees `Heavy` -> `compile_work_stealing` -> priority=100.
RayDistributed sees `Heavy` -> `compile_ray` -> offload=True.
Pydantic sees `Heavy` -> skipped (no `compile_pydantic`).

---

## 5. Writing a Custom Scheduling Policy

A scheduling policy implements `SchedulingCompilable`:

```python
from emergent.graph.runtime import SchedulingCompilable

class SchedulingCompilable(Protocol):
    requires_free_threaded: bool
    def build_agent(self, nodes: set[type[Node]]) -> Agent: ...
```

### Example: Remote Cluster Execution

`CallbackAgent` handles all nodnod orchestration (dependency tracking, Either, ResultNode, error propagation). You only provide the `NodeExecutor` — how to run a single node.

```python
from dataclasses import dataclass, replace
from typing import Protocol, runtime_checkable
from nodnod.agent.base import Agent
from nodnod.node import Node
from nodnod.compose import compose_node
from emergent.wire.compile._core import fold_schema
from emergent.graph.runtime import CallbackAgent


# 1. Context — WHAT the compiler wants to know about each node
@dataclass(frozen=True, slots=True)
class RemoteContext:
    host: str | None = None
    gpu: bool = False


# 2. Protocol — HOW capabilities write into the context
@runtime_checkable
class RemoteCompilable(Protocol):
    def compile_remote(self, ctx: RemoteContext) -> RemoteContext: ...


# 3. Scheduling policy — the compiler itself
@dataclass(frozen=True, slots=True)
class RemoteCluster:
    requires_free_threaded: bool = False
    default_host: str = "worker-pool.internal"

    def build_agent(self, nodes: set[type[Node]]) -> Agent:
        # Fold schema_meta from each node using our protocol
        placement: dict[type[Node], RemoteContext] = {}
        for node in nodes:
            ctx = fold_schema(
                node, RemoteContext(), RemoteCompilable, "compile_remote"
            )
            if ctx != RemoteContext():
                placement[node] = ctx

        remote_nodes = {n for n, ctx in placement.items() if ctx.host}

        # Custom executor: remote nodes go to cluster, rest run locally
        async def execute(node, node_scope, local_scope):
            if node in remote_nodes:
                host = placement[node].host
                return await send_to_cluster(host, node, node_scope, local_scope)
            return await compose_node(node, node_scope, local_scope)

        # CallbackAgent handles ALL orchestration — we just provide execute
        return CallbackAgent.build_with_executor(nodes, execute)
```

### Capabilities for the custom policy

```python
@dataclass(frozen=True, slots=True)
class RunOn(SchemaCapability):
    host: str

    def compile_remote(self, ctx: RemoteContext) -> RemoteContext:
        return replace(ctx, host=self.host)


@dataclass(frozen=True, slots=True)
class GPU(SchemaCapability):
    def compile_remote(self, ctx: RemoteContext) -> RemoteContext:
        return replace(ctx, gpu=True)

    # Same capability also affects local work-stealing
    def compile_work_stealing(self, ctx: WorkStealingContext) -> WorkStealingContext:
        return replace(ctx, priority=max(ctx.priority, 100))
```

### Usage

```python
@schema_meta(RunOn("gpu-cluster-1"), GPU())
@scalar_node
class TrainModel:
    @classmethod
    async def __compose__(cls, data: PreparedData) -> TrainedModel: ...

@scalar_node  # No capabilities — runs on default host
class PrepareData:
    @classmethod
    async def __compose__(cls, raw: RawInput) -> PreparedData: ...

# Plug in
agent_cls = RuntimeAgent.with_policy(RuntimePolicy(scheduling=RemoteCluster()))
pipeline = graph(TrainModel, agent_cls=agent_cls)
result = await pipeline.run(raw_input)
```

Inside `build_agent()`, fold sees:
- `TrainModel` -> `RemoteContext(host="gpu-cluster-1", gpu=True)`
- `PrepareData` -> `RemoteContext()` (default, nothing matched)

### Custom GIL policy

```python
@dataclass(frozen=True, slots=True)
class NeverDowngrade:
    def resolve_scheduling(
        self,
        scheduling: SchedulingCompilable,
        is_gil_enabled: bool,
    ) -> SchedulingCompilable:
        return scheduling  # Always pass through

RuntimePolicy(scheduling=RemoteCluster(), gil=NeverDowngrade())
```

---

## 6. Spawnable — Live Node Management

`Spawnable` is an opt-in protocol for agents that support adding/removing nodes while `run()` is active. Both `CallbackAgent` and `_WorkStealingAgent` implement it.

```python
from emergent.graph.runtime import Spawnable

agent = RuntimeAgent.with_policy(RuntimePolicy()).build(nodes)

# Check if delegate supports it
if isinstance(agent, Spawnable):
    agent.spawn({NewNode})           # Add nodes to running agent
    agent.despawn({OldNode})         # Remove nodes, cancel in-flight
    print(agent.living_nodes)        # Currently tracked nodes
```

### Protocol

```python
@runtime_checkable
class Spawnable(Protocol):
    def spawn(
        self,
        nodes: set[type[Node]],
        mapped_scopes: Mapping[type[Node], Scope] | None = None,
    ) -> None: ...

    def despawn(self, nodes: set[type[Node]]) -> None: ...

    @property
    def living_nodes(self) -> frozenset[type[Node]]: ...
```

`RuntimeAgent` delegates `spawn`/`despawn`/`living_nodes` to the inner agent, raising `TypeError` if the delegate isn't `Spawnable`.

---

## 7. CallbackAgent — Building Blocks for Custom Agents

Writing a full nodnod `Agent` from scratch means reimplementing dependency tracking, Either/ResultNode handling, error propagation (~500 lines). `CallbackAgent` provides all of that — you only supply a `NodeExecutor`.

```python
from emergent.graph.runtime import CallbackAgent, GraphInfo, build_graph_info
```

### NodeExecutor

```python
type NodeExecutor = Callable[
    [type[Node], Scope, Scope],
    Awaitable[kungfu.Result[Value, NodeError]],
]
```

Same signature as `compose_node`. Replace it to control WHERE and HOW each node runs.

### Default — identical to EventLoopAgent

```python
agent = CallbackAgent.build(nodes)
```

### Custom — logging, metrics, remote

```python
async def logging_executor(node, node_scope, local_scope):
    start = time.monotonic()
    result = await compose_node(node, node_scope, local_scope)
    log.info(f"{node.__name__} took {time.monotonic() - start:.3f}s")
    return result

agent = CallbackAgent.build_with_executor(nodes, logging_executor)
```

### GraphInfo

Dependency graph structure, built once, immutable:

```python
info = build_graph_info({Diamond})
info.all_nodes       # (LeafA, LeafB, Diamond)
info.ready_roots     # frozenset({LeafA, LeafB})
info.initial_pending # {LeafA: 0, LeafB: 0, Diamond: 2}
info.dependents      # {LeafA: {Diamond}, LeafB: {Diamond}}
info.final_nodes     # frozenset({Diamond})
```

---

## 8. WorkStealing Internals

```
caller's event loop
        |  await agent.run(scope, mapped_scopes)
        v
WorkStealing.build_agent(nodes)
  |-- build_graph_info(nodes) -> expand all transitive deps
  |-- fold_schema per node (WorkStealingCompilable) -> per-node traits
  |-- _WorkStealingAgent(graph_info, n_workers, traits)

_WorkStealingAgent.run()
  |-- Builds _RunState (dependency counters, ready roots, dependents map)
  |-- Creates _WorkStealingPool (N workers, each with own asyncio event loop)
  |-- Submits ready tasks (zero-dependency nodes)
  |-- Awaits done_event via loop.run_in_executor (non-blocking bridge)

_WorkStealingPool
  |-- Worker-0: event_loop_0, local_deque_0
  |-- Worker-1: event_loop_1, local_deque_1
  |-- Worker-N: event_loop_N, local_deque_N

Each Worker:
  |-- Pop from local deque (LIFO — cache-hot)
  |-- If empty: steal from another worker (FIFO — from front)
  |-- Run: compose_node(node, scope, local_scope)
  |-- On completion: decrement dependents -> submit newly-ready tasks
```

Owner pushes to **back** of own deque (LIFO), thief steals from **front** (FIFO). Minimizes contention: opposite ends.

### Scope Thread Safety

No extra locks needed:

1. Each node writes to a **unique key** in scope — no write-write conflicts
2. Dependencies are guaranteed complete (counter = 0) before a node starts — no read-write races
3. In free-threaded CPython, dict operations have per-object locks providing memory ordering
4. `Scope.retrieve()` is read-only traversal of parent chain (set up before `run()`, never modified)

---

## 9. Benchmarks

Free-threaded Python 3.14t, 12 cores, 8 parallel nodes per benchmark.

### CPU Bound (matrix mul + json serde + SHA-256)

```
Scale         EventLoop     Threaded     Speedup
----------  ------------ ------------ ----------
easy             510ms        110ms       4.6x
medium          3316ms        633ms       5.2x
hard           16873ms       3948ms       4.3x
```

### IO Bound (HTTP to local server, sequential keep-alive)

```
Scale         EventLoop     Threaded     Speedup
----------  ------------ ------------ ----------
easy            2732ms       1221ms       2.2x
medium         11117ms       4877ms       2.3x
hard           92356ms      79119ms       1.2x
```

### IO+CPU (HTTP fetch then heavy CPU processing)

```
Scale         EventLoop     Threaded     Speedup
----------  ------------ ------------ ----------
easy            1597ms        676ms       2.4x
medium          8764ms       3124ms       2.8x
hard           62227ms      42666ms       1.5x
```

---

## 10. Comparison with Alternatives

| Approach | Parallelism | GIL-free needed | Overhead |
|---|---|---|---|
| `asyncio.gather` (EventLoopAgent) | Cooperative, 1 thread | No | ~0 |
| `ThreadPoolExecutor` | OS threads, GIL-bound | No (but GIL blocks CPU) | Thread creation |
| `ProcessPoolExecutor` | OS processes | No | Process spawn + IPC pickle |
| Ray / Dask | Distributed processes | No | Cluster overhead, serialization |
| **WorkStealing** | OS threads, GIL-free | Yes (3.13t+) | Thread pool + work-stealing |
| **Custom (e.g. RemoteCluster)** | User-defined | User-defined | User-defined |

---

## 11. When to Use What

| Policy | When |
|---|---|
| `Cooperative` | GIL Python, trivial nodes, pure IO, sequential graphs |
| `WorkStealing` | Free-threaded Python, CPU-heavy nodes, IO at volume |
| Custom | Remote execution, GPU cluster, distributed scheduling |

---

## 12. Files

- `emergent/graph/runtime/_policy.py` — protocols, built-in policies, contexts, error policy
- `emergent/graph/runtime/_agent.py` — RuntimeAgent, GIL detection, protocol dispatch
- `emergent/graph/runtime/_helpers.py` — GraphInfo, build_graph_info, CallbackAgent, NodeExecutor
- `emergent/graph/runtime/_threaded.py` — WorkStealing agent implementation
- `emergent/graph/runtime/_spawnable.py` — Spawnable protocol (live node management)
- `emergent/graph/runtime/__init__.py` — re-exports
- `tests/test_threaded_agent.py` — 116 tests
