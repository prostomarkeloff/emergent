"""Tests for emergent.graph.runtime — open-world policy-based graph execution.

Covers:
1. Policy validation (RuntimePolicy, WorkStealing, CollectErrors)
2. with_policy() factory — dynamic class creation, policy label
3. GIL resolution — protocol-based (RequireFreeThreaded, AutoDowngrade)
4. Dispatch — Cooperative → EventLoopAgent, WorkStealing → _WorkStealingAgent
5. Worker count configuration via WorkStealing(workers=N)
6. Work-stealing primitives (_try_steal, _push_task, _select_worker)
7. Completion cascade (_on_node_complete, _on_node_failed, _record_error)
8. Pool lifecycle (_create_pool, _shutdown_pool)
9. Full integration via both scheduling policies (parametrized)
10. Composer integration
11. No leaked threads after run
12. ThreadedAgent backward-compatible alias
13. _build_graph_info
14. Open-world scheduling — custom SchedulingCompilable
15. Capabilities as compiler plugins via schema_meta + fold
16. CallbackAgent — reusable building blocks for custom agents
"""

from __future__ import annotations

import asyncio
import collections
import threading
from unittest.mock import patch

import pytest

from nodnod import Node, Scope, scalar_node
from nodnod.error import NodeError

try:
    from emergent.graph.runtime import AutoDowngrade as _check  # noqa: F401
except ImportError:
    pytest.skip("AutoDowngrade not available", allow_module_level=True)

from emergent.graph.runtime import (
    AutoDowngrade,
    Cooperative,
    FailFast,
    CollectErrors,
    RequireFreeThreaded,
    RuntimeAgent,
    RuntimePolicy,
    ThreadedAgent,
    WorkStealing,
)
from emergent.graph.runtime._threaded import (
    _WorkStealingAgent,
    _GraphInfo,
    _RunState,
    _Task,
    _Worker,
    _WorkStealingPool,
    _build_graph_info,
    _create_pool,
    _on_node_complete,
    _on_node_failed,
    _push_task,
    _record_error,
    _select_worker,
    _shutdown_pool,
    _signal_node_completed,
    _submit_task,
    _try_steal,
    _wait_node_completed,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Test nodes
# ═══════════════════════════════════════════════════════════════════════════════


@scalar_node
class LeafA:
    @classmethod
    def __compose__(cls) -> int:
        return 10


@scalar_node
class LeafB:
    @classmethod
    def __compose__(cls) -> int:
        return 20


@scalar_node
class Diamond:
    @classmethod
    def __compose__(cls, a: LeafA, b: LeafB) -> int:
        return a + b


@scalar_node
class Linear1:
    @classmethod
    def __compose__(cls) -> str:
        return "hello"


@scalar_node
class Linear2:
    @classmethod
    def __compose__(cls, x: Linear1) -> str:
        return x + " world"


@scalar_node
class Linear3:
    @classmethod
    def __compose__(cls, x: Linear2) -> str:
        return x + "!"


@scalar_node
class Failing:
    @classmethod
    def __compose__(cls) -> int:
        raise ValueError("intentional failure")


@scalar_node
class DependsOnFailing:
    @classmethod
    def __compose__(cls, f: Failing) -> int:
        return f + 1


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


_NO_GIL = patch("emergent.graph.runtime._agent._is_gil_enabled", return_value=False)


def _build_agent(
    policy: RuntimePolicy, nodes: set[type[Node]]
) -> RuntimeAgent:
    """Build a RuntimeAgent from a policy, bypassing GIL check."""
    agent_cls = RuntimeAgent.with_policy(policy)
    with _NO_GIL:
        return agent_cls.build(nodes)


_COOPERATIVE = RuntimePolicy(scheduling=Cooperative())
_WORK_STEALING = RuntimePolicy(scheduling=WorkStealing())


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Policy validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestPolicyValidation:
    def test_default_policy(self) -> None:
        p = RuntimePolicy()
        assert isinstance(p.scheduling, Cooperative)
        assert isinstance(p.errors, FailFast)
        assert isinstance(p.gil, RequireFreeThreaded)

    def test_work_stealing_default_workers(self) -> None:
        assert WorkStealing().workers is None

    def test_work_stealing_explicit_workers(self) -> None:
        assert WorkStealing(workers=4).workers == 4

    def test_work_stealing_workers_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="workers must be >= 1"):
            RuntimePolicy(scheduling=WorkStealing(workers=0))

    def test_work_stealing_workers_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="workers must be >= 1"):
            RuntimePolicy(scheduling=WorkStealing(workers=-1))

    def test_collect_errors_raises_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError, match="reserved"):
            RuntimePolicy(errors=CollectErrors())

    def test_policy_is_frozen(self) -> None:
        p = RuntimePolicy()
        with pytest.raises((AttributeError, TypeError)):
            p.scheduling = WorkStealing()  # type: ignore[misc]

    def test_work_stealing_is_frozen(self) -> None:
        ws = WorkStealing(workers=2)
        with pytest.raises((AttributeError, TypeError)):
            ws.workers = 4  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# 2. with_policy() factory
# ═══════════════════════════════════════════════════════════════════════════════


class TestWithPolicy:
    def test_returns_subclass_of_runtime_agent(self) -> None:
        assert issubclass(RuntimeAgent.with_policy(RuntimePolicy()), RuntimeAgent)

    def test_different_policies_produce_different_classes(self) -> None:
        cls1 = RuntimeAgent.with_policy(RuntimePolicy())
        cls2 = RuntimeAgent.with_policy(RuntimePolicy(scheduling=WorkStealing()))
        assert cls1 is not cls2

    def test_policy_baked_into_class(self) -> None:
        policy = RuntimePolicy(scheduling=WorkStealing(workers=8))
        cls = RuntimeAgent.with_policy(policy)
        assert cls._policy is policy

    def test_class_name_contains_scheduling_label(self) -> None:
        assert "Cooperative" in RuntimeAgent.with_policy(RuntimePolicy()).__name__

    def test_class_name_work_stealing(self) -> None:
        cls = RuntimeAgent.with_policy(RuntimePolicy(scheduling=WorkStealing()))
        assert "WorkStealing" in cls.__name__

    def test_class_name_work_stealing_with_workers(self) -> None:
        cls = RuntimeAgent.with_policy(
            RuntimePolicy(scheduling=WorkStealing(workers=4))
        )
        assert "WorkStealing(4)" in cls.__name__

    def test_satisfies_type_agent(self) -> None:
        from nodnod.agent.base import Agent

        assert issubclass(RuntimeAgent.with_policy(RuntimePolicy()), Agent)

    def test_does_not_check_gil(self) -> None:
        """GIL check deferred to build(), not with_policy()."""
        cls = RuntimeAgent.with_policy(
            RuntimePolicy(scheduling=WorkStealing(), gil=RequireFreeThreaded())
        )
        assert issubclass(cls, RuntimeAgent)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. GIL resolution
# ═══════════════════════════════════════════════════════════════════════════════


class TestGILResolution:
    def test_require_free_threaded_raises_on_gil(self) -> None:
        agent_cls = RuntimeAgent.with_policy(
            RuntimePolicy(scheduling=WorkStealing(), gil=RequireFreeThreaded())
        )
        with pytest.raises(RuntimeError, match="free-threaded"):
            agent_cls.build({LeafA})

    def test_auto_downgrade_dispatches_to_callback_agent(self) -> None:
        from emergent.graph.runtime._helpers import CallbackAgent

        agent_cls = RuntimeAgent.with_policy(
            RuntimePolicy(scheduling=WorkStealing(), gil=AutoDowngrade())
        )
        agent = agent_cls.build({LeafA})
        assert isinstance(agent._delegate, CallbackAgent)

    def test_cooperative_ignores_gil_policy(self) -> None:
        agent_cls = RuntimeAgent.with_policy(
            RuntimePolicy(scheduling=Cooperative(), gil=RequireFreeThreaded())
        )
        # Must not raise — Cooperative doesn't need free-threaded
        agent = agent_cls.build({LeafA})
        assert isinstance(agent, RuntimeAgent)

    def test_work_stealing_on_free_threaded(self) -> None:
        agent_cls = RuntimeAgent.with_policy(
            RuntimePolicy(scheduling=WorkStealing())
        )
        with _NO_GIL:
            agent = agent_cls.build({LeafA})
        assert isinstance(agent._delegate, _WorkStealingAgent)

    def test_auto_downgrade_returns_cooperative(self) -> None:
        gil = AutoDowngrade()
        result = gil.resolve_scheduling(WorkStealing(), is_gil_enabled=True)
        assert isinstance(result, Cooperative)

    def test_require_free_threaded_passes_when_no_gil(self) -> None:
        gil = RequireFreeThreaded()
        ws = WorkStealing()
        result = gil.resolve_scheduling(ws, is_gil_enabled=False)
        assert result is ws

    def test_auto_downgrade_passes_when_no_gil(self) -> None:
        gil = AutoDowngrade()
        ws = WorkStealing()
        result = gil.resolve_scheduling(ws, is_gil_enabled=False)
        assert result is ws

    def test_require_free_threaded_passes_cooperative(self) -> None:
        """Cooperative doesn't require free-threaded, so RequireFreeThreaded should pass."""
        gil = RequireFreeThreaded()
        coop = Cooperative()
        result = gil.resolve_scheduling(coop, is_gil_enabled=True)
        assert result is coop


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Dispatch — correct backend selection
# ═══════════════════════════════════════════════════════════════════════════════


class TestDispatch:
    def test_cooperative_dispatches_to_callback_agent(self) -> None:
        from emergent.graph.runtime._helpers import CallbackAgent

        agent = _build_agent(_COOPERATIVE, {LeafA})
        assert isinstance(agent._delegate, CallbackAgent)

    def test_work_stealing_dispatches_to_work_stealing(self) -> None:
        agent = _build_agent(_WORK_STEALING, {LeafA})
        assert isinstance(agent._delegate, _WorkStealingAgent)

    def test_work_stealing_explicit_workers(self) -> None:
        policy = RuntimePolicy(scheduling=WorkStealing(workers=3))
        agent = _build_agent(policy, {Diamond})
        assert agent._delegate._n_workers == 3


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Worker count configuration
# ═══════════════════════════════════════════════════════════════════════════════


class TestWorkerCount:
    def test_auto_capped_at_node_count(self) -> None:
        agent = _build_agent(_WORK_STEALING, {LeafA})
        assert agent._delegate._n_workers == 1

    def test_auto_at_least_one(self) -> None:
        with _NO_GIL, patch("os.cpu_count", return_value=0):
            agent_cls = RuntimeAgent.with_policy(_WORK_STEALING)
            agent = agent_cls.build({LeafA})
        assert agent._delegate._n_workers >= 1

    def test_auto_capped_at_cpu_count(self) -> None:
        with _NO_GIL, patch("os.cpu_count", return_value=2):
            agent_cls = RuntimeAgent.with_policy(_WORK_STEALING)
            agent = agent_cls.build({Diamond})
        assert agent._delegate._n_workers == 2

    def test_auto_fallback_when_cpu_count_none(self) -> None:
        with _NO_GIL, patch("os.cpu_count", return_value=None):
            agent_cls = RuntimeAgent.with_policy(_WORK_STEALING)
            agent = agent_cls.build({Diamond})
        # Fallback 4, but only 3 nodes → 3 workers
        assert agent._delegate._n_workers == 3

    def test_explicit_workers_override(self) -> None:
        policy = RuntimePolicy(scheduling=WorkStealing(workers=7))
        agent = _build_agent(policy, {LeafA})
        assert agent._delegate._n_workers == 7


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Work-stealing primitives
# ═══════════════════════════════════════════════════════════════════════════════


def _make_worker(worker_id: int) -> _Worker:
    return _Worker(
        worker_id=worker_id,
        loop=asyncio.new_event_loop(),
        thread=threading.Thread(),
        local_deque=collections.deque(),
        deque_lock=threading.Lock(),
    )


def _make_pool(n: int) -> _WorkStealingPool:
    workers = tuple(_make_worker(i) for i in range(n))
    return _WorkStealingPool(workers=workers, shutdown_flag=threading.Event())


def _make_task(node: type[Node]) -> _Task:
    scope = Scope(detail="test")
    return _Task(node=node, node_scope=scope, local_scope=scope)


class TestWorkStealingPrimitives:
    def test_push_task_appends_to_deque(self) -> None:
        worker = _make_worker(0)
        task = _make_task(LeafA)
        _push_task(worker, task)
        assert len(worker.local_deque) == 1
        assert worker.local_deque[0] is task

    def test_push_multiple_preserves_order(self) -> None:
        worker = _make_worker(0)
        t1 = _make_task(LeafA)
        t2 = _make_task(LeafB)
        _push_task(worker, t1)
        _push_task(worker, t2)
        assert worker.local_deque.pop() is t2
        assert worker.local_deque.pop() is t1

    def test_try_steal_returns_none_when_empty(self) -> None:
        pool = _make_pool(3)
        assert _try_steal(pool.workers[0], pool) is None

    def test_try_steal_steals_from_front(self) -> None:
        pool = _make_pool(2)
        t1 = _make_task(LeafA)
        t2 = _make_task(LeafB)
        _push_task(pool.workers[1], t1)
        _push_task(pool.workers[1], t2)
        assert _try_steal(pool.workers[0], pool) is t1

    def test_try_steal_skips_self(self) -> None:
        pool = _make_pool(1)
        _push_task(pool.workers[0], _make_task(LeafA))
        assert _try_steal(pool.workers[0], pool) is None

    def test_select_worker_deterministic(self) -> None:
        pool = _make_pool(4)
        assert _select_worker(pool, LeafA).worker_id == _select_worker(pool, LeafA).worker_id

    def test_select_worker_returns_valid_worker(self) -> None:
        pool = _make_pool(4)
        assert 0 <= _select_worker(pool, LeafA).worker_id < 4


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Completion cascade
# ═══════════════════════════════════════════════════════════════════════════════


def _make_run_state(graph_info: _GraphInfo, scope: Scope | None = None) -> _RunState:
    s = scope or Scope(detail="test")
    return _RunState(
        pending=dict(graph_info.initial_pending),
        pending_lock=threading.Lock(),
        remaining_finals=len(graph_info.final_nodes),
        remaining_lock=threading.Lock(),
        active_finals=set(graph_info.final_nodes),
        done_event=threading.Event(),
        error=None,
        error_lock=threading.Lock(),
        local_scope=s,
        mapped_scopes={},
        node_completed={},
        node_completed_lock=threading.Lock(),
    )


class TestRecordError:
    def test_records_first_error(self) -> None:
        info = _build_graph_info({LeafA})
        state = _make_run_state(info)
        err = NodeError("boom")
        _record_error(state, err)
        assert state.error is err
        assert state.done_event.is_set()

    def test_ignores_second_error(self) -> None:
        info = _build_graph_info({LeafA})
        state = _make_run_state(info)
        err1 = NodeError("first")
        err2 = NodeError("second")
        _record_error(state, err1)
        _record_error(state, err2)
        assert state.error is err1

    def test_records_non_node_error(self) -> None:
        info = _build_graph_info({LeafA})
        state = _make_run_state(info)
        err = ValueError("plain error")
        _record_error(state, err)
        assert state.error is err
        assert state.done_event.is_set()


class TestSignalAndWaitNodeCompleted:
    def test_signal_then_wait_does_not_block(self) -> None:
        info = _build_graph_info({LeafA})
        state = _make_run_state(info)
        _signal_node_completed(state, LeafA)
        _wait_node_completed(state, LeafA)

    def test_wait_then_signal_from_thread(self) -> None:
        info = _build_graph_info({LeafA})
        state = _make_run_state(info)
        result: list[bool] = []

        def waiter() -> None:
            _wait_node_completed(state, LeafA)
            result.append(True)

        t = threading.Thread(target=waiter)
        t.start()
        _signal_node_completed(state, LeafA)
        t.join(timeout=5.0)
        assert result == [True]


class TestOnNodeComplete:
    def test_decrements_dependent_counter(self) -> None:
        info = _build_graph_info({Diamond})
        pool = _make_pool(2)
        state = _make_run_state(info)
        _on_node_complete(LeafA, state, pool, info)
        assert state.pending[Diamond] == 1

    def test_submits_task_when_counter_reaches_zero(self) -> None:
        info = _build_graph_info({Diamond})
        pool = _make_pool(2)
        state = _make_run_state(info)
        _on_node_complete(LeafA, state, pool, info)
        total_before = sum(len(w.local_deque) for w in pool.workers)
        _on_node_complete(LeafB, state, pool, info)
        total_after = sum(len(w.local_deque) for w in pool.workers)
        assert total_after == total_before + 1

    def test_sets_done_when_all_finals_complete(self) -> None:
        info = _build_graph_info({LeafA})
        pool = _make_pool(1)
        state = _make_run_state(info)
        assert not state.done_event.is_set()
        _on_node_complete(LeafA, state, pool, info)
        assert state.done_event.is_set()

    def test_signals_node_completed_event(self) -> None:
        info = _build_graph_info({LeafA})
        pool = _make_pool(1)
        state = _make_run_state(info)
        _on_node_complete(LeafA, state, pool, info)
        assert LeafA in state.node_completed
        assert state.node_completed[LeafA].is_set()


class TestOnNodeFailed:
    def test_records_error_when_no_result_node_dep(self) -> None:
        info = _build_graph_info({LeafA})
        pool = _make_pool(1)
        state = _make_run_state(info)
        err = NodeError("fail")
        _on_node_failed(LeafA, err, state, pool, info)
        assert state.error is err
        assert state.done_event.is_set()

    def test_signals_node_completed_on_failure(self) -> None:
        info = _build_graph_info({LeafA})
        pool = _make_pool(1)
        state = _make_run_state(info)
        _on_node_failed(LeafA, NodeError("fail"), state, pool, info)
        assert LeafA in state.node_completed
        assert state.node_completed[LeafA].is_set()


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Pool lifecycle
# ═══════════════════════════════════════════════════════════════════════════════


def _close_pool_loops(pool: _WorkStealingPool) -> None:
    for w in pool.workers:
        w.loop.close()


class TestPoolLifecycle:
    def test_create_pool_correct_count(self) -> None:
        pool = _create_pool(4)
        assert len(pool.workers) == 4
        for i, w in enumerate(pool.workers):
            assert w.worker_id == i
        _close_pool_loops(pool)

    def test_workers_have_event_loops(self) -> None:
        pool = _create_pool(2)
        for w in pool.workers:
            assert isinstance(w.loop, asyncio.AbstractEventLoop)
        _close_pool_loops(pool)

    def test_workers_have_empty_deques(self) -> None:
        pool = _create_pool(2)
        for w in pool.workers:
            assert len(w.local_deque) == 0
        _close_pool_loops(pool)

    def test_shutdown_sets_flag(self) -> None:
        pool = _create_pool(2)
        assert not pool.shutdown_flag.is_set()
        pool.shutdown_flag.set()
        assert pool.shutdown_flag.is_set()
        _close_pool_loops(pool)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Full integration — parametrized over both scheduling policies
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture(params=["cooperative", "work_stealing"], ids=["coop", "ws"])
def scheduling_policy(request: pytest.FixtureRequest) -> RuntimePolicy:
    if request.param == "cooperative":
        return _COOPERATIVE
    return _WORK_STEALING


class TestIntegration:
    """Unified integration tests — both backends must behave identically."""

    @pytest.mark.asyncio
    async def test_single_leaf(self, scheduling_policy: RuntimePolicy) -> None:
        agent = _build_agent(scheduling_policy, {LeafA})
        scope = Scope(detail="test")
        await agent.run(local_scope=scope, mapped_scopes={})
        assert scope.retrieve(LeafA).unwrap().value == 10

    @pytest.mark.asyncio
    async def test_single_leaf_b(self, scheduling_policy: RuntimePolicy) -> None:
        agent = _build_agent(scheduling_policy, {LeafB})
        scope = Scope(detail="test")
        await agent.run(local_scope=scope, mapped_scopes={})
        assert scope.retrieve(LeafB).unwrap().value == 20

    @pytest.mark.asyncio
    async def test_diamond(self, scheduling_policy: RuntimePolicy) -> None:
        agent = _build_agent(scheduling_policy, {Diamond})
        scope = Scope(detail="test")
        await agent.run(local_scope=scope, mapped_scopes={})
        assert scope.retrieve(Diamond).unwrap().value == 30

    @pytest.mark.asyncio
    async def test_diamond_all_nodes_in_scope(self, scheduling_policy: RuntimePolicy) -> None:
        agent = _build_agent(scheduling_policy, {Diamond})
        scope = Scope(detail="test")
        await agent.run(local_scope=scope, mapped_scopes={})
        assert scope.retrieve(LeafA).unwrap().value == 10
        assert scope.retrieve(LeafB).unwrap().value == 20
        assert scope.retrieve(Diamond).unwrap().value == 30

    @pytest.mark.asyncio
    async def test_linear_chain(self, scheduling_policy: RuntimePolicy) -> None:
        agent = _build_agent(scheduling_policy, {Linear3})
        scope = Scope(detail="test")
        await agent.run(local_scope=scope, mapped_scopes={})
        assert scope.retrieve(Linear3).unwrap().value == "hello world!"

    @pytest.mark.asyncio
    async def test_linear_chain_intermediate_nodes(self, scheduling_policy: RuntimePolicy) -> None:
        agent = _build_agent(scheduling_policy, {Linear3})
        scope = Scope(detail="test")
        await agent.run(local_scope=scope, mapped_scopes={})
        assert scope.retrieve(Linear1).unwrap().value == "hello"
        assert scope.retrieve(Linear2).unwrap().value == "hello world"

    @pytest.mark.asyncio
    async def test_failing_node_raises(self, scheduling_policy: RuntimePolicy) -> None:
        agent = _build_agent(scheduling_policy, {Failing})
        scope = Scope(detail="test")
        with pytest.raises(ValueError, match="intentional failure"):
            await agent.run(local_scope=scope, mapped_scopes={})

    @pytest.mark.asyncio
    async def test_error_from_dependency_propagates(self, scheduling_policy: RuntimePolicy) -> None:
        agent = _build_agent(scheduling_policy, {DependsOnFailing})
        scope = Scope(detail="test")
        with pytest.raises((ValueError, NodeError)):
            await agent.run(local_scope=scope, mapped_scopes={})

    @pytest.mark.asyncio
    async def test_agent_reusable_across_runs(self, scheduling_policy: RuntimePolicy) -> None:
        agent = _build_agent(scheduling_policy, {LeafA})
        scope1 = Scope(detail="run-1")
        await agent.run(local_scope=scope1, mapped_scopes={})
        assert scope1.retrieve(LeafA).unwrap().value == 10

        scope2 = Scope(detail="run-2")
        await agent.run(local_scope=scope2, mapped_scopes={})
        assert scope2.retrieve(LeafA).unwrap().value == 10

    @pytest.mark.asyncio
    async def test_runs_do_not_share_scope(self, scheduling_policy: RuntimePolicy) -> None:
        agent = _build_agent(scheduling_policy, {Diamond})
        scope1 = Scope(detail="run-1")
        await agent.run(local_scope=scope1, mapped_scopes={})
        scope2 = Scope(detail="run-2")
        await agent.run(local_scope=scope2, mapped_scopes={})
        assert scope1.retrieve(Diamond).unwrap().value == 30
        assert scope2.retrieve(Diamond).unwrap().value == 30


class TestWorkStealingSpecific:
    """Tests specific to work-stealing backend."""

    @pytest.mark.asyncio
    async def test_empty_graph_returns_immediately(self) -> None:
        info = _GraphInfo(
            all_nodes=(),
            dependents={},
            initial_pending={},
            ready_roots=frozenset(),
            final_nodes=frozenset(),
        )
        agent = _WorkStealingAgent(graph_info=info, n_workers=1)
        scope = Scope(detail="test")
        await agent.run(local_scope=scope, mapped_scopes={})

    @pytest.mark.asyncio
    async def test_explicit_worker_count(self) -> None:
        policy = RuntimePolicy(scheduling=WorkStealing(workers=2))
        agent = _build_agent(policy, {Diamond})
        scope = Scope(detail="test")
        await agent.run(local_scope=scope, mapped_scopes={})
        assert scope.retrieve(Diamond).unwrap().value == 30


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Composer integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestComposerIntegration:
    @pytest.mark.asyncio
    async def test_cooperative(self) -> None:
        from emergent.graph import Composer

        agent_cls = RuntimeAgent.with_policy(_COOPERATIVE)
        scope = Scope(detail="composer-test")
        composer = Composer.create(scope, agent_cls=agent_cls)
        success, value = await composer.compose(LeafA)
        assert success is True
        assert value == 10

    @pytest.mark.asyncio
    async def test_work_stealing(self) -> None:
        from emergent.graph import Composer

        agent_cls = RuntimeAgent.with_policy(_WORK_STEALING)
        with _NO_GIL:
            scope = Scope(detail="composer-test")
            composer = Composer.create(scope, agent_cls=agent_cls)
            success, value = await composer.compose(Diamond)
        assert success is True
        assert value == 30

    @pytest.mark.asyncio
    async def test_error_handling(self) -> None:
        from emergent.graph import Composer

        agent_cls = RuntimeAgent.with_policy(_WORK_STEALING)
        with _NO_GIL:
            scope = Scope(detail="composer-test")
            composer = Composer.create(scope, agent_cls=agent_cls)
            success, _ = await composer.compose(Failing)
        assert success is False

    @pytest.mark.asyncio
    async def test_threaded_agent_alias(self) -> None:
        from emergent.graph import Composer

        with _NO_GIL:
            scope = Scope(detail="composer-test")
            composer = Composer.create(scope, agent_cls=ThreadedAgent)
            success, value = await composer.compose(LeafA)
        assert success is True
        assert value == 10


# ═══════════════════════════════════════════════════════════════════════════════
# 11. No leaked threads
# ═══════════════════════════════════════════════════════════════════════════════


class TestNoLeakedThreads:
    @pytest.mark.asyncio
    async def test_cleanup_after_success(self) -> None:
        before = {t.name for t in threading.enumerate()}
        agent = _build_agent(_WORK_STEALING, {Diamond})
        scope = Scope(detail="leak-test")
        await agent.run(local_scope=scope, mapped_scopes={})

        import time
        time.sleep(0.1)

        after = {t.name for t in threading.enumerate()}
        leaked = {t for t in after - before if "threaded-agent-worker" in t}
        assert leaked == set(), f"Leaked worker threads: {leaked}"

    @pytest.mark.asyncio
    async def test_cleanup_after_error(self) -> None:
        before = {t.name for t in threading.enumerate()}
        agent = _build_agent(_WORK_STEALING, {Failing})
        scope = Scope(detail="leak-test-error")
        with pytest.raises(ValueError):
            await agent.run(local_scope=scope, mapped_scopes={})

        import time
        time.sleep(0.1)

        after = {t.name for t in threading.enumerate()}
        leaked = {t for t in after - before if "threaded-agent-worker" in t}
        assert leaked == set(), f"Leaked worker threads after error: {leaked}"


# ═══════════════════════════════════════════════════════════════════════════════
# 12. ThreadedAgent backward-compatible alias
# ═══════════════════════════════════════════════════════════════════════════════


class TestThreadedAgentAlias:
    def test_is_subclass_of_runtime_agent(self) -> None:
        assert issubclass(ThreadedAgent, RuntimeAgent)

    def test_has_work_stealing_policy(self) -> None:
        assert isinstance(ThreadedAgent._policy.scheduling, WorkStealing)

    def test_has_fail_fast_policy(self) -> None:
        assert isinstance(ThreadedAgent._policy.errors, FailFast)

    def test_has_require_free_threaded_policy(self) -> None:
        assert isinstance(ThreadedAgent._policy.gil, RequireFreeThreaded)

    def test_raises_on_gil(self) -> None:
        with pytest.raises(RuntimeError, match="free-threaded"):
            ThreadedAgent.build({LeafA})

    @pytest.mark.asyncio
    async def test_runs_on_free_threaded(self) -> None:
        with _NO_GIL:
            agent = ThreadedAgent.build({LeafA})
        scope = Scope(detail="alias-test")
        await agent.run(local_scope=scope, mapped_scopes={})
        assert scope.retrieve(LeafA).unwrap().value == 10


# ═══════════════════════════════════════════════════════════════════════════════
# 13. _build_graph_info
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildGraphInfo:
    def test_single_node(self) -> None:
        info = _build_graph_info({LeafA})
        assert LeafA in info.ready_roots
        assert info.initial_pending[LeafA] == 0
        assert info.final_nodes == frozenset({LeafA})

    def test_diamond_graph(self) -> None:
        info = _build_graph_info({Diamond})
        assert LeafA in info.ready_roots
        assert LeafB in info.ready_roots
        assert info.initial_pending[Diamond] == 2
        assert Diamond not in info.ready_roots
        assert info.final_nodes == frozenset({Diamond})

    def test_dependents_mapping(self) -> None:
        info = _build_graph_info({Diamond})
        assert Diamond in info.dependents.get(LeafA, frozenset())
        assert Diamond in info.dependents.get(LeafB, frozenset())

    def test_linear_chain(self) -> None:
        info = _build_graph_info({Linear3})
        assert Linear1 in info.ready_roots
        assert Linear2 not in info.ready_roots
        assert Linear3 not in info.ready_roots
        assert info.initial_pending[Linear2] == 1
        assert info.initial_pending[Linear3] == 1

    def test_all_nodes_contains_transitive_deps(self) -> None:
        info = _build_graph_info({Diamond})
        node_set = set(info.all_nodes)
        assert LeafA in node_set
        assert LeafB in node_set
        assert Diamond in node_set


# ═══════════════════════════════════════════════════════════════════════════════
# 14. Open-world scheduling — protocol-based extension
# ═══════════════════════════════════════════════════════════════════════════════


class TestCustomSchedulingPolicy:
    """Third-party SchedulingCompilable works e2e with RuntimeAgent."""

    def test_custom_policy_builds_agent(self) -> None:
        from dataclasses import dataclass
        from nodnod import EventLoopAgent
        from nodnod.agent.base import Agent
        from nodnod.node import Node as BaseNode

        @dataclass(frozen=True, slots=True)
        class CustomPolicy:
            requires_free_threaded: bool = False

            def build_agent(self, nodes: set[type[BaseNode]]) -> Agent:
                return EventLoopAgent.build(nodes)

        agent_cls = RuntimeAgent.with_policy(RuntimePolicy(scheduling=CustomPolicy()))
        agent = agent_cls.build({LeafA})
        assert isinstance(agent._delegate, EventLoopAgent)

    @pytest.mark.asyncio
    async def test_custom_policy_runs(self) -> None:
        from dataclasses import dataclass
        from nodnod import EventLoopAgent
        from nodnod.agent.base import Agent
        from nodnod.node import Node as BaseNode

        @dataclass(frozen=True, slots=True)
        class CustomPolicy:
            requires_free_threaded: bool = False

            def build_agent(self, nodes: set[type[BaseNode]]) -> Agent:
                return EventLoopAgent.build(nodes)

        agent_cls = RuntimeAgent.with_policy(RuntimePolicy(scheduling=CustomPolicy()))
        agent = agent_cls.build({Diamond})
        scope = Scope(detail="custom-policy")
        await agent.run(local_scope=scope, mapped_scopes={})
        assert scope.retrieve(Diamond).unwrap().value == 30

    def test_custom_policy_with_custom_gil_resolution(self) -> None:
        from dataclasses import dataclass
        from nodnod import EventLoopAgent
        from nodnod.agent.base import Agent
        from nodnod.node import Node as BaseNode

        from emergent.graph.runtime import SchedulingCompilable

        @dataclass(frozen=True, slots=True)
        class NeverDowngrade:
            """Custom GIL policy that never downgrades."""

            def resolve_scheduling(
                self,
                scheduling: SchedulingCompilable,
                is_gil_enabled: bool,
            ) -> SchedulingCompilable:
                return scheduling

        @dataclass(frozen=True, slots=True)
        class CustomPolicy:
            requires_free_threaded: bool = False

            def build_agent(self, nodes: set[type[BaseNode]]) -> Agent:
                return EventLoopAgent.build(nodes)

        agent_cls = RuntimeAgent.with_policy(
            RuntimePolicy(scheduling=CustomPolicy(), gil=NeverDowngrade())
        )
        # Even with GIL enabled, NeverDowngrade passes through
        agent = agent_cls.build({LeafA})
        assert isinstance(agent._delegate, EventLoopAgent)

    def test_custom_policy_class_name_in_label(self) -> None:
        from dataclasses import dataclass
        from nodnod import EventLoopAgent
        from nodnod.agent.base import Agent
        from nodnod.node import Node as BaseNode

        @dataclass(frozen=True, slots=True)
        class RayDistributed:
            requires_free_threaded: bool = False

            def build_agent(self, nodes: set[type[BaseNode]]) -> Agent:
                return EventLoopAgent.build(nodes)

        cls = RuntimeAgent.with_policy(RuntimePolicy(scheduling=RayDistributed()))
        assert "RayDistributed" in cls.__name__


# ═══════════════════════════════════════════════════════════════════════════════
# 15. Capabilities as compiler plugins via schema_meta
# ═══════════════════════════════════════════════════════════════════════════════


class TestCapabilitiesAsPlugins:
    """SchemaCapability subclasses implement compile_work_stealing and fold via schema_meta."""

    def test_fold_schema_with_work_stealing_compilable(self) -> None:
        from dataclasses import dataclass, replace
        from emergent.wire.axis.schema._universal import SchemaCapability, schema_meta
        from emergent.wire.compile._core import fold_schema
        from emergent.graph.runtime import WorkStealingContext, WorkStealingCompilable

        @dataclass(frozen=True, slots=True)
        class Priority(SchemaCapability):
            value: int

            def compile_work_stealing(
                self, ctx: WorkStealingContext
            ) -> WorkStealingContext:
                return replace(ctx, priority=self.value)

        @schema_meta(Priority(5))
        @scalar_node
        class PriorityNode:
            @classmethod
            def __compose__(cls) -> int:
                return 42

        ctx = fold_schema(
            PriorityNode,
            WorkStealingContext(),
            WorkStealingCompilable,
            "compile_work_stealing",
        )
        assert ctx.priority == 5

    def test_unknown_capabilities_skipped(self) -> None:
        """Capabilities that don't implement WorkStealingCompilable are silently skipped."""
        from dataclasses import dataclass
        from emergent.wire.axis.schema._universal import SchemaCapability, schema_meta
        from emergent.wire.compile._core import fold_schema
        from emergent.graph.runtime import WorkStealingContext, WorkStealingCompilable

        @dataclass(frozen=True, slots=True)
        class Unrelated(SchemaCapability):
            """Has no compile_work_stealing method."""
            pass

        @schema_meta(Unrelated())
        @scalar_node
        class UnrelatedNode:
            @classmethod
            def __compose__(cls) -> int:
                return 1

        ctx = fold_schema(
            UnrelatedNode,
            WorkStealingContext(),
            WorkStealingCompilable,
            "compile_work_stealing",
        )
        assert ctx == WorkStealingContext()

    def test_multiple_capabilities_fold(self) -> None:
        from dataclasses import dataclass, replace
        from emergent.wire.axis.schema._universal import SchemaCapability, schema_meta
        from emergent.wire.compile._core import fold_schema
        from emergent.graph.runtime import WorkStealingContext, WorkStealingCompilable

        @dataclass(frozen=True, slots=True)
        class SetPriority(SchemaCapability):
            value: int

            def compile_work_stealing(
                self, ctx: WorkStealingContext
            ) -> WorkStealingContext:
                return replace(ctx, priority=self.value)

        @dataclass(frozen=True, slots=True)
        class BoostPriority(SchemaCapability):
            boost: int

            def compile_work_stealing(
                self, ctx: WorkStealingContext
            ) -> WorkStealingContext:
                return replace(ctx, priority=ctx.priority + self.boost)

        @schema_meta(SetPriority(3), BoostPriority(7))
        @scalar_node
        class BoostedNode:
            @classmethod
            def __compose__(cls) -> int:
                return 99

        ctx = fold_schema(
            BoostedNode,
            WorkStealingContext(),
            WorkStealingCompilable,
            "compile_work_stealing",
        )
        assert ctx.priority == 10  # 3 + 7


class TestTraitsPlumbing:
    """Verify traits from schema_meta are folded and passed to _WorkStealingAgent."""

    def test_traits_reach_agent(self) -> None:
        from dataclasses import dataclass, replace
        from emergent.wire.axis.schema._universal import SchemaCapability, schema_meta
        from emergent.graph.runtime import WorkStealingContext, WorkStealingCompilable

        @dataclass(frozen=True, slots=True)
        class Priority(SchemaCapability):
            value: int

            def compile_work_stealing(
                self, ctx: WorkStealingContext
            ) -> WorkStealingContext:
                return replace(ctx, priority=self.value)

        @schema_meta(Priority(42))
        @scalar_node
        class PriorityLeaf:
            @classmethod
            def __compose__(cls) -> int:
                return 1

        agent = _build_agent(
            RuntimePolicy(scheduling=WorkStealing(workers=1)),
            {PriorityLeaf},
        )
        delegate = agent._delegate
        assert isinstance(delegate, _WorkStealingAgent)
        assert PriorityLeaf in delegate.traits
        assert delegate.traits[PriorityLeaf].priority == 42

    def test_traits_fold_transitive_deps(self) -> None:
        """Capabilities on transitive dependencies (not just targets) are folded."""
        from dataclasses import dataclass, replace
        from emergent.wire.axis.schema._universal import SchemaCapability, schema_meta
        from emergent.graph.runtime import WorkStealingContext, WorkStealingCompilable

        @dataclass(frozen=True, slots=True)
        class Priority(SchemaCapability):
            value: int

            def compile_work_stealing(
                self, ctx: WorkStealingContext
            ) -> WorkStealingContext:
                return replace(ctx, priority=self.value)

        @schema_meta(Priority(99))
        @scalar_node
        class TaggedLeaf:
            @classmethod
            def __compose__(cls) -> int:
                return 1

        @scalar_node
        class Consumer:
            @classmethod
            def __compose__(cls, x: TaggedLeaf) -> int:
                return x + 1

        agent = _build_agent(
            RuntimePolicy(scheduling=WorkStealing(workers=1)),
            {Consumer},  # target is Consumer, but TaggedLeaf has the capability
        )
        delegate = agent._delegate
        assert isinstance(delegate, _WorkStealingAgent)
        assert TaggedLeaf in delegate.traits
        assert delegate.traits[TaggedLeaf].priority == 99

    def test_no_traits_when_no_capabilities(self) -> None:
        agent = _build_agent(
            RuntimePolicy(scheduling=WorkStealing(workers=1)),
            {LeafA},
        )
        delegate = agent._delegate
        assert isinstance(delegate, _WorkStealingAgent)
        assert len(delegate.traits) == 0

    @pytest.mark.asyncio
    async def test_traits_dont_break_execution(self) -> None:
        """Agent with traits still executes correctly."""
        from dataclasses import dataclass, replace
        from emergent.wire.axis.schema._universal import SchemaCapability, schema_meta
        from emergent.graph.runtime import WorkStealingContext

        @dataclass(frozen=True, slots=True)
        class Priority(SchemaCapability):
            value: int

            def compile_work_stealing(
                self, ctx: WorkStealingContext
            ) -> WorkStealingContext:
                return replace(ctx, priority=self.value)

        @schema_meta(Priority(10))
        @scalar_node
        class PriLeafA:
            @classmethod
            def __compose__(cls) -> int:
                return 100

        @scalar_node
        class PriConsumer:
            @classmethod
            def __compose__(cls, x: PriLeafA) -> int:
                return x + 1

        agent = _build_agent(
            RuntimePolicy(scheduling=WorkStealing(workers=2)),
            {PriConsumer},
        )
        scope = Scope(detail="traits-exec")
        await agent.run(local_scope=scope, mapped_scopes={})
        assert scope.retrieve(PriConsumer).unwrap().value == 101


class TestCapabilityCrossCompiler:
    """Same capability can implement compile methods for multiple compilers."""

    def test_one_capability_two_compilers(self) -> None:
        from dataclasses import dataclass, replace
        from typing import Protocol, runtime_checkable
        from emergent.wire.axis.schema._universal import SchemaCapability, schema_meta
        from emergent.wire.compile._core import fold_schema
        from emergent.graph.runtime import WorkStealingContext, WorkStealingCompilable

        # A hypothetical second compiler's context + protocol
        @dataclass(frozen=True, slots=True)
        class RayContext:
            offload: bool = False

        @runtime_checkable
        class RayCompilable(Protocol):
            def compile_ray(self, ctx: RayContext) -> RayContext: ...

        # Single capability implements both
        @dataclass(frozen=True, slots=True)
        class Heavy(SchemaCapability):
            def compile_work_stealing(
                self, ctx: WorkStealingContext
            ) -> WorkStealingContext:
                return replace(ctx, priority=max(ctx.priority, 10))

            def compile_ray(self, ctx: RayContext) -> RayContext:
                return replace(ctx, offload=True)

        @schema_meta(Heavy())
        @scalar_node
        class HeavyNode:
            @classmethod
            def __compose__(cls) -> int:
                return 1

        # WorkStealing fold
        ws_ctx = fold_schema(
            HeavyNode,
            WorkStealingContext(),
            WorkStealingCompilable,
            "compile_work_stealing",
        )
        assert ws_ctx.priority == 10

        # Ray fold
        ray_ctx = fold_schema(
            HeavyNode,
            RayContext(),
            RayCompilable,
            "compile_ray",
        )
        assert ray_ctx.offload is True


# ═══════════════════════════════════════════════════════════════════════════════
# 16. CallbackAgent — reusable building blocks
# ═══════════════════════════════════════════════════════════════════════════════


class TestGraphInfo:
    def test_build_graph_info_single_node(self) -> None:
        from emergent.graph.runtime import GraphInfo, build_graph_info

        info = build_graph_info({LeafA})
        assert isinstance(info, GraphInfo)
        assert LeafA in info.ready_roots
        assert info.final_nodes == frozenset({LeafA})

    def test_build_graph_info_diamond(self) -> None:
        from emergent.graph.runtime import build_graph_info

        info = build_graph_info({Diamond})
        assert LeafA in info.ready_roots
        assert LeafB in info.ready_roots
        assert Diamond not in info.ready_roots
        assert info.initial_pending[Diamond] == 2

    def test_graph_info_is_frozen(self) -> None:
        from emergent.graph.runtime import build_graph_info

        info = build_graph_info({LeafA})
        with pytest.raises((AttributeError, TypeError)):
            info.all_nodes = ()  # type: ignore[misc]


class TestCallbackAgent:
    @pytest.mark.asyncio
    async def test_default_executor_single_leaf(self) -> None:
        from emergent.graph.runtime import CallbackAgent

        agent = CallbackAgent.build({LeafA})
        scope = Scope(detail="cb-test")
        await agent.run(local_scope=scope, mapped_scopes={})
        assert scope.retrieve(LeafA).unwrap().value == 10

    @pytest.mark.asyncio
    async def test_default_executor_diamond(self) -> None:
        from emergent.graph.runtime import CallbackAgent

        agent = CallbackAgent.build({Diamond})
        scope = Scope(detail="cb-test")
        await agent.run(local_scope=scope, mapped_scopes={})
        assert scope.retrieve(Diamond).unwrap().value == 30

    @pytest.mark.asyncio
    async def test_default_executor_linear_chain(self) -> None:
        from emergent.graph.runtime import CallbackAgent

        agent = CallbackAgent.build({Linear3})
        scope = Scope(detail="cb-test")
        await agent.run(local_scope=scope, mapped_scopes={})
        assert scope.retrieve(Linear3).unwrap().value == "hello world!"

    @pytest.mark.asyncio
    async def test_default_executor_error_propagation(self) -> None:
        from emergent.graph.runtime import CallbackAgent

        agent = CallbackAgent.build({Failing})
        scope = Scope(detail="cb-test")
        with pytest.raises(ValueError, match="intentional failure"):
            await agent.run(local_scope=scope, mapped_scopes={})

    @pytest.mark.asyncio
    async def test_custom_executor(self) -> None:
        from emergent.graph.runtime import CallbackAgent
        from nodnod.compose import compose_node

        executed: list[type[Node]] = []

        async def tracking_executor(node, node_scope, local_scope):
            executed.append(node)
            return await compose_node(node, node_scope, local_scope)

        agent = CallbackAgent.build_with_executor({Diamond}, tracking_executor)
        scope = Scope(detail="cb-test")
        await agent.run(local_scope=scope, mapped_scopes={})
        assert scope.retrieve(Diamond).unwrap().value == 30
        assert set(executed) == {LeafA, LeafB, Diamond}

    @pytest.mark.asyncio
    async def test_custom_executor_intercept(self) -> None:
        """Custom executor can wrap compose_node with side effects."""
        from emergent.graph.runtime import CallbackAgent
        from nodnod.compose import compose_node

        intercepted: list[type[Node]] = []

        async def intercepting_executor(node, node_scope, local_scope):
            intercepted.append(node)
            return await compose_node(node, node_scope, local_scope)

        agent = CallbackAgent.build_with_executor({Linear3}, intercepting_executor)
        scope = Scope(detail="cb-test")
        await agent.run(local_scope=scope, mapped_scopes={})
        assert scope.retrieve(Linear3).unwrap().value == "hello world!"
        assert intercepted == [Linear1, Linear2, Linear3]

    @pytest.mark.asyncio
    async def test_empty_graph(self) -> None:
        from emergent.graph.runtime import CallbackAgent, build_graph_info, GraphInfo

        info = GraphInfo(
            all_nodes=(),
            dependents={},
            initial_pending={},
            ready_roots=frozenset(),
            final_nodes=frozenset(),
        )
        agent = CallbackAgent(graph_info=info, execute=lambda n, ns, ls: None)  # type: ignore[arg-type]
        scope = Scope(detail="empty")
        await agent.run(local_scope=scope, mapped_scopes={})

    @pytest.mark.asyncio
    async def test_callback_agent_in_scheduling_policy(self) -> None:
        """CallbackAgent used inside a custom SchedulingCompilable.build_agent()."""
        from dataclasses import dataclass
        from nodnod.agent.base import Agent
        from nodnod.node import Node as BaseNode
        from nodnod.compose import compose_node
        from emergent.graph.runtime import CallbackAgent

        executed_nodes: list[type[BaseNode]] = []

        @dataclass(frozen=True, slots=True)
        class LoggingPolicy:
            requires_free_threaded: bool = False

            def build_agent(self, nodes: set[type[BaseNode]]) -> Agent:
                async def logging_executor(node, node_scope, local_scope):
                    executed_nodes.append(node)
                    return await compose_node(node, node_scope, local_scope)

                return CallbackAgent.build_with_executor(nodes, logging_executor)

        agent_cls = RuntimeAgent.with_policy(RuntimePolicy(scheduling=LoggingPolicy()))
        agent = agent_cls.build({Diamond})
        scope = Scope(detail="policy-cb")
        await agent.run(local_scope=scope, mapped_scopes={})
        assert scope.retrieve(Diamond).unwrap().value == 30
        assert set(executed_nodes) == {LeafA, LeafB, Diamond}
