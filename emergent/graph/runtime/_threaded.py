"""ThreadedAgent — tokio-style work-stealing runtime for free-threaded Python.

Uses N OS worker threads, each with its own asyncio event loop.
Independent nodes run in true parallel on separate threads.
Work-stealing: idle workers steal tasks from busy workers' deques.

    from emergent.graph.runtime import ThreadedAgent
    from emergent.graph import graph

    pipeline = graph(ProcessOrder, agent_cls=ThreadedAgent)
    result = await pipeline(order, db)

Requires Python 3.13t+ (free-threaded build, no GIL).
"""

from __future__ import annotations

import asyncio
import collections
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

import kungfu
from nodnod.agent.base import Agent
from nodnod.compose import compose_node
from nodnod.error import NodeError
from nodnod.node import Node
from nodnod.scope import Scope, validate_local_scope_is_linked_to_node_scopes
from nodnod.value import Value

from emergent.graph.runtime._helpers import GraphInfo as _GraphInfo
from emergent.graph.runtime._helpers import build_graph_info as _build_graph_info

if TYPE_CHECKING:
    from emergent.graph.runtime._policy import WorkStealingContext

type PendingMap = dict[type[Node], int]
type ScopeMap = dict[type[Node], Scope]
type EventMap = dict[type[Node], threading.Event]
type TraitsMap = Mapping[type[Node], WorkStealingContext]
type MappedScopes = Mapping[type[Node], Scope]


def _is_result_node(node: type[Node]) -> bool:
    """Check if node is a ResultNode without narrowing the type."""
    from nodnod.interface.result_node import ResultNode

    return issubclass(node, ResultNode)


def _is_sequential_either(node: type[Node]) -> bool:
    """Check if node is a sequential Either without narrowing the type."""
    from nodnod.interface.either import Either

    return issubclass(node, Either) and not node.is_concurrent


def _get_either_members(node: type[Node]) -> tuple[type[Node], ...]:
    """Get __either__ members from an Either node.

    Assumes caller has verified node is an Either via _is_sequential_either.
    """
    from nodnod.interface.either import Either

    if not issubclass(node, Either):
        return ()
    return node.__either__


def _get_from_node(node: type[Node]) -> type[Node]:
    """Get __from_node__ from a ResultNode.

    Assumes caller has verified node is a ResultNode via _is_result_node.
    """
    from nodnod.interface.result_node import ResultNode

    if not issubclass(node, ResultNode):
        raise TypeError(f"{node} is not a ResultNode")
    return node.__from_node__


@dataclass(slots=True)
class _Task:
    node: type[Node]
    node_scope: Scope
    local_scope: Scope


@dataclass(slots=True)
class _RunState:
    pending: PendingMap
    pending_lock: threading.Lock
    remaining_finals: int
    remaining_lock: threading.Lock
    active_finals: set[type[Node]]
    done_event: threading.Event
    error: BaseException | None
    error_lock: threading.Lock
    local_scope: Scope
    mapped_scopes: ScopeMap
    node_completed: EventMap
    node_completed_lock: threading.Lock


@dataclass(slots=True)
class _Worker:
    worker_id: int
    loop: asyncio.AbstractEventLoop
    thread: threading.Thread
    local_deque: collections.deque[_Task]
    deque_lock: threading.Lock


@dataclass(slots=True)
class _WorkStealingPool:
    workers: tuple[_Worker, ...]
    shutdown_flag: threading.Event


def _try_steal(worker: _Worker, pool: _WorkStealingPool) -> _Task | None:
    """Try to steal a task from another worker's deque (FIFO — from front)."""
    for victim in pool.workers:
        if victim.worker_id == worker.worker_id:
            continue
        with victim.deque_lock:
            if victim.local_deque:
                return victim.local_deque.popleft()
    return None


def _select_worker(pool: _WorkStealingPool, node: type[Node]) -> _Worker:
    """Select target worker for a task via hash-based distribution."""
    idx = hash(node) % len(pool.workers)
    return pool.workers[idx]


def _push_task(worker: _Worker, task: _Task) -> None:
    """Push task to worker's deque (LIFO — to back)."""
    with worker.deque_lock:
        worker.local_deque.append(task)


def _submit_task(pool: _WorkStealingPool, task: _Task) -> None:
    """Submit a task to an appropriate worker."""
    target = _select_worker(pool, task.node)
    _push_task(target, task)
    target.loop.call_soon_threadsafe(lambda: None)


def _record_error(run_state: _RunState, error: BaseException) -> None:
    """Record the first error and signal completion."""
    with run_state.error_lock:
        if run_state.error is None:
            run_state.error = error
    run_state.done_event.set()


def _signal_node_completed(run_state: _RunState, node: type[Node]) -> None:
    """Signal that a node has completed (for sequential either waiters)."""
    with run_state.node_completed_lock:
        event = run_state.node_completed.get(node)
        if event is None:
            event = threading.Event()
            run_state.node_completed[node] = event
    event.set()


def _wait_node_completed(run_state: _RunState, node: type[Node]) -> None:
    """Wait for a node to complete (blocking, used by sequential either)."""
    with run_state.node_completed_lock:
        event = run_state.node_completed.get(node)
        if event is None:
            event = threading.Event()
            run_state.node_completed[node] = event
    event.wait()


def _on_node_complete(
    node: type[Node],
    run_state: _RunState,
    pool: _WorkStealingPool,
    graph_info: _GraphInfo,
) -> None:
    """Called when a node completes. Decrements dependent counters and submits ready tasks."""
    _signal_node_completed(run_state, node)

    deps = graph_info.dependents.get(node, frozenset())
    for dependent in deps:
        with run_state.pending_lock:
            run_state.pending[dependent] -= 1
            ready = run_state.pending[dependent] == 0

        if not ready:
            continue

        node_scope = run_state.mapped_scopes.get(dependent, run_state.local_scope)
        _submit_task(pool, _Task(dependent, node_scope, run_state.local_scope))

    with run_state.remaining_lock:
        if node in run_state.active_finals:
            run_state.remaining_finals -= 1
            if run_state.remaining_finals == 0:
                run_state.done_event.set()


def _on_node_failed(
    node: type[Node],
    error: NodeError,
    run_state: _RunState,
    pool: _WorkStealingPool,
    graph_info: _GraphInfo,
) -> None:
    """Called when a node fails. Decrements all dependents; queues ResultNode dependents, propagates error for others."""
    _signal_node_completed(run_state, node)

    deps = graph_info.dependents.get(node, frozenset())
    has_result_node_dep = False

    for dependent in deps:
        with run_state.pending_lock:
            run_state.pending[dependent] -= 1
            ready = run_state.pending[dependent] == 0

        if _is_result_node(dependent):
            if ready:
                node_scope = run_state.mapped_scopes.get(dependent, run_state.local_scope)
                _submit_task(pool, _Task(dependent, node_scope, run_state.local_scope))
            has_result_node_dep = True
        elif ready:
            # Non-ResultNode dependent is now unblocked but its parent failed.
            # Propagate the failure and handle finals tracking.
            _signal_node_completed(run_state, dependent)
            with run_state.remaining_lock:
                if dependent in run_state.active_finals:
                    run_state.remaining_finals -= 1
                    if run_state.remaining_finals == 0:
                        run_state.done_event.set()

    if not has_result_node_dep:
        _record_error(run_state, error)


async def _execute_plain_task(
    task: _Task,
    run_state: _RunState,
    pool: _WorkStealingPool,
    graph_info: _GraphInfo,
) -> None:
    """Execute a plain node composition.

    NOTE: compose_node reads/writes Scope (OrderedDict) which is shared across
    worker threads. In free-threaded Python 3.13t+/3.14, dict operations are
    individually atomic (per-object locks). Scope.__setitem__ writes to unique
    keys (one per node) and reads only from already-completed dependencies
    (guaranteed by the pending counter), so the access pattern is safe under
    the free-threading memory model.
    """
    result = await compose_node(task.node, task.node_scope, task.local_scope)
    if kungfu.is_ok(result):
        _on_node_complete(task.node, run_state, pool, graph_info)
    else:
        _on_node_failed(task.node, result.error, run_state, pool, graph_info)


async def _execute_sequential_either(
    task: _Task,
    run_state: _RunState,
    pool: _WorkStealingPool,
    graph_info: _GraphInfo,
) -> None:
    """Execute sequential either: try members one by one until one succeeds."""
    node = task.node
    either_members = _get_either_members(node)
    if not either_members:
        return
    errors: list[NodeError] = []

    first: type[Node] = either_members[0]
    first_result = task.node_scope.retrieve(first)

    if kungfu.is_some(first_result):
        result = await compose_node(node, task.node_scope, task.local_scope)
        if kungfu.is_ok(result):
            _on_node_complete(node, run_state, pool, graph_info)
            return
        else:
            _on_node_failed(node, result.error, run_state, pool, graph_info)
            return

    for member in either_members[1:]:
        existing = task.local_scope.retrieve(member)
        if kungfu.is_some(existing):
            result = await compose_node(node, task.node_scope, task.local_scope)
            if kungfu.is_ok(result):
                _on_node_complete(node, run_state, pool, graph_info)
                return
            else:
                errors.append(result.error)
                continue

        # Need to schedule this member's dependencies and wait
        traverse_list: list[type[Node]] = []
        from nodnod.builder.build_queue import build_queue
        build_queue(member, traverse_list)

        for dep_node in traverse_list:
            if dep_node in run_state.pending:
                continue

            with run_state.pending_lock:
                if dep_node in run_state.pending:
                    continue

                dep_count = len(dep_node.__dependencies__)
                satisfied = 0
                for d in dep_node.__dependencies__:
                    if kungfu.is_some(task.local_scope.retrieve(d)):
                        satisfied += 1

                run_state.pending[dep_node] = dep_count - satisfied
                if run_state.pending[dep_node] == 0:
                    dep_scope = run_state.mapped_scopes.get(dep_node, run_state.local_scope)
                    _submit_task(pool, _Task(dep_node, dep_scope, run_state.local_scope))

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _wait_node_completed, run_state, member)

        member_result = task.local_scope.retrieve(member)
        if kungfu.is_some(member_result):
            result = await compose_node(node, task.node_scope, task.local_scope)
            if kungfu.is_ok(result):
                _on_node_complete(node, run_state, pool, graph_info)
                return
            else:
                errors.append(result.error)
        else:
            errors.append(NodeError(f"sequential either member {member.__name__} failed"))

    _on_node_failed(
        node,
        NodeError("no option found for sequential either", from_many=errors),
        run_state, pool, graph_info,
    )


async def _execute_result_node_task(
    task: _Task,
    run_state: _RunState,
    pool: _WorkStealingPool,
    graph_info: _GraphInfo,
) -> None:
    """Execute a ResultNode — wraps parent node's success/failure into Result."""
    node = task.node
    from_node = _get_from_node(node)
    parent_value = task.local_scope.retrieve(from_node)

    if kungfu.is_some(parent_value):
        value = Value(node.__type__, kungfu.Ok(parent_value.unwrap().value))
        task.node_scope[node] = value
        _on_node_complete(node, run_state, pool, graph_info)
        return

    result = await compose_node(node, task.node_scope, task.local_scope)
    if kungfu.is_ok(result):
        _on_node_complete(node, run_state, pool, graph_info)
    else:
        _on_node_failed(node, result.error, run_state, pool, graph_info)


async def _execute_task(
    task: _Task,
    run_state: _RunState,
    pool: _WorkStealingPool,
    graph_info: _GraphInfo,
) -> None:
    """Dispatch task execution based on node type."""
    if run_state.done_event.is_set() and run_state.error is not None:
        return

    node = task.node

    try:
        if _is_sequential_either(node):
            await _execute_sequential_either(task, run_state, pool, graph_info)
            return

        if _is_result_node(node):
            await _execute_result_node_task(task, run_state, pool, graph_info)
            return

        await _execute_plain_task(task, run_state, pool, graph_info)
    except Exception as e:
        _signal_node_completed(run_state, node)
        _record_error(run_state, e)


async def _steal_loop(
    worker: _Worker,
    pool: _WorkStealingPool,
    run_state: _RunState,
    graph_info: _GraphInfo,
) -> None:
    """Per-worker loop: pull from local deque or steal, then execute."""
    while not pool.shutdown_flag.is_set():
        task = None
        with worker.deque_lock:
            if worker.local_deque:
                task = worker.local_deque.pop()

        if task is None:
            task = _try_steal(worker, pool)

        if task is not None:
            await _execute_task(task, run_state, pool, graph_info)
        else:
            await asyncio.sleep(0.0001)


def _worker_main(
    worker: _Worker,
    pool: _WorkStealingPool,
    run_state: _RunState,
    graph_info: _GraphInfo,
) -> None:
    """Thread entry point: set up event loop and run steal loop."""
    asyncio.set_event_loop(worker.loop)

    async def _run() -> None:
        await _steal_loop(worker, pool, run_state, graph_info)

    try:
        worker.loop.run_until_complete(_run())
    except Exception as exc:
        # Only record if computation is not already done — the pool shutdown
        # closes event loops which raises RuntimeError in workers still running.
        if not run_state.done_event.is_set():
            _record_error(run_state, exc)


def _create_pool(n_workers: int) -> _WorkStealingPool:
    """Create worker pool (threads not started yet)."""
    workers: list[_Worker] = []
    for i in range(n_workers):
        loop = asyncio.new_event_loop()
        worker = _Worker(
            worker_id=i,
            loop=loop,
            thread=threading.Thread(name=f"threaded-agent-worker-{i}", daemon=True),
            local_deque=collections.deque(),
            deque_lock=threading.Lock(),
        )
        workers.append(worker)
    return _WorkStealingPool(workers=tuple(workers), shutdown_flag=threading.Event())


def _start_pool(
    pool: _WorkStealingPool,
    run_state: _RunState,
    graph_info: _GraphInfo,
) -> None:
    """Start all worker threads."""
    for worker in pool.workers:
        worker.thread = threading.Thread(
            target=_worker_main,
            args=(worker, pool, run_state, graph_info),
            name=f"threaded-agent-worker-{worker.worker_id}",
            daemon=True,
        )
        worker.thread.start()


def _shutdown_pool(pool: _WorkStealingPool) -> None:
    """Stop all worker event loops and join threads."""
    pool.shutdown_flag.set()
    for worker in pool.workers:
        worker.loop.call_soon_threadsafe(worker.loop.stop)
    for worker in pool.workers:
        worker.thread.join(timeout=10.0)
    for worker in pool.workers:
        worker.loop.close()


class _WorkStealingAgent(Agent):
    """Tokio-style work-stealing agent for free-threaded Python.

    N OS worker threads, each with its own asyncio event loop.
    Independent nodes run in true parallel on separate threads.
    Idle workers steal tasks from busy workers' deques.

    Implements Spawnable — supports live node management (spawn/despawn)
    while run() is active.

    Internal implementation — use RuntimeAgent.with_policy() or
    the ThreadedAgent alias instead of this class directly.
    """

    def __init__(
        self,
        graph_info: _GraphInfo,
        n_workers: int,
        traits: TraitsMap | None = None,
    ) -> None:
        self._graph_info = graph_info
        self._n_workers = n_workers
        self._traits: TraitsMap = traits if traits is not None else {}
        # Mutable state — initialized in run(), used by spawn/despawn
        self._pool: _WorkStealingPool | None = None
        self._run_state: _RunState | None = None
        self._living: set[type[Node]] = set()

    @staticmethod
    def _resolve_workers(n_nodes: int, workers: int | None) -> int:
        """Compute effective worker count: min(cpu_count, node_count), at least 1."""
        if workers is None:
            cpu_count = os.cpu_count()
            n_workers = min(
                cpu_count if cpu_count is not None else 4,
                n_nodes,
            )
        else:
            n_workers = workers
        return max(n_workers, 1)

    @classmethod
    def build(cls, nodes: set[type[Node]]) -> _WorkStealingAgent:
        return cls.build_with_workers(nodes, workers=None)

    @classmethod
    def build_with_workers(
        cls, nodes: set[type[Node]], workers: int | None = None
    ) -> _WorkStealingAgent:
        graph_info = _build_graph_info(nodes)
        n_workers = cls._resolve_workers(len(graph_info.all_nodes), workers)
        return cls(graph_info=graph_info, n_workers=n_workers)

    @property
    def traits(self) -> TraitsMap:
        """Per-node compilation context folded from schema_meta capabilities."""
        return self._traits

    async def run(self, local_scope: Scope, mapped_scopes: ScopeMap) -> None:
        validate_local_scope_is_linked_to_node_scopes(local_scope, mapped_scopes)

        run_state = _RunState(
            pending=dict(self._graph_info.initial_pending),
            pending_lock=threading.Lock(),
            remaining_finals=len(self._graph_info.final_nodes),
            remaining_lock=threading.Lock(),
            active_finals=set(self._graph_info.final_nodes),
            done_event=threading.Event(),
            error=None,
            error_lock=threading.Lock(),
            local_scope=local_scope,
            mapped_scopes=mapped_scopes,
            node_completed={},
            node_completed_lock=threading.Lock(),
        )

        if not self._graph_info.all_nodes:
            return

        self._run_state = run_state
        with run_state.remaining_lock:
            self._living = set(self._graph_info.all_nodes)

        pool = _create_pool(self._n_workers)
        self._pool = pool
        _start_pool(pool, run_state, self._graph_info)

        for node in self._graph_info.ready_roots:
            node_scope = mapped_scopes.get(node, local_scope)
            _submit_task(pool, _Task(node, node_scope, local_scope))

        caller_loop = asyncio.get_running_loop()
        await caller_loop.run_in_executor(None, run_state.done_event.wait)

        _shutdown_pool(pool)
        self._pool = None
        self._run_state = None

        if run_state.error is not None:
            raise run_state.error

    # --- Spawnable implementation ---

    def spawn(
        self,
        nodes: set[type[Node]],
        mapped_scopes: MappedScopes | None = None,
    ) -> None:
        """Add new nodes to the running work-stealing pool."""
        if self._pool is None or self._run_state is None:
            raise RuntimeError("_WorkStealingAgent.spawn() called before run()")
        run_state = self._run_state
        new_info = _build_graph_info(nodes)
        scopes = dict(run_state.mapped_scopes)
        if mapped_scopes:
            scopes.update(mapped_scopes)

        # Register new nodes in pending
        with run_state.pending_lock:
            for node in new_info.all_nodes:
                if node not in run_state.pending:
                    run_state.pending[node] = new_info.initial_pending.get(node, 0)

        # Update finals tracking — clear done so run() keeps waiting
        with run_state.remaining_lock:
            run_state.remaining_finals += len(new_info.final_nodes)
            run_state.active_finals |= new_info.final_nodes
            run_state.done_event.clear()
            self._living |= set(new_info.all_nodes)

        # Submit ready roots
        for node in new_info.ready_roots:
            node_scope = scopes.get(node, run_state.local_scope)
            _submit_task(self._pool, _Task(node, node_scope, run_state.local_scope))

    def despawn(self, nodes: set[type[Node]]) -> None:
        """Remove nodes from tracking. In-flight threaded tasks complete but don't affect done condition."""
        if self._run_state is None:
            return
        run_state = self._run_state

        # Adjust finals and living under lock
        with run_state.remaining_lock:
            for node in nodes:
                self._living.discard(node)
                if node in run_state.active_finals:
                    run_state.active_finals.discard(node)
                    run_state.remaining_finals -= 1
            if run_state.remaining_finals <= 0:
                run_state.done_event.set()

    @property
    def living_nodes(self) -> frozenset[type[Node]]:
        return frozenset(self._living)


def resolve_worker_count(n_nodes: int, workers: int | None) -> int:
    """Compute effective worker count: min(cpu_count, node_count), at least 1.

    Public module-level function for use by _policy.py.
    """
    if workers is None:
        cpu_count = os.cpu_count()
        n_workers = min(
            cpu_count if cpu_count is not None else 4,
            n_nodes,
        )
    else:
        n_workers = workers
    return max(n_workers, 1)


def build_work_stealing_agent(
    graph_info: _GraphInfo,
    n_workers: int,
    traits: TraitsMap | None = None,
) -> _WorkStealingAgent:
    """Public factory for _WorkStealingAgent.

    Used by _policy.py to construct the agent without accessing the private class directly.
    """
    return _WorkStealingAgent(graph_info=graph_info, n_workers=n_workers, traits=traits)


__all__ = ("_WorkStealingAgent", "resolve_worker_count", "build_work_stealing_agent")
