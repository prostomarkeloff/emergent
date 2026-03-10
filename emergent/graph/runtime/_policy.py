"""Runtime policies — open-world protocol-based configuration for graph execution.

Each scheduling policy IS a compiler: it defines its own context type,
its own compilable protocol, and builds an agent by folding schema_meta
from nodes. Follows the same pattern as FastAPI/Pydantic compilation targets.

    from emergent.graph.runtime import RuntimePolicy, WorkStealing, AutoDowngrade

    policy = RuntimePolicy(
        scheduling=WorkStealing(workers=4),
        gil=AutoDowngrade(),
    )

## Open-World Extension

Third-party scheduling policies implement SchedulingCompilable:

    @dataclass(frozen=True, slots=True)
    class RayDistributed:
        requires_free_threaded: bool = False
        def build_agent(self, nodes: set[type[Node]]) -> Agent: ...

Capabilities implement compile methods for any scheduling policy:

    @dataclass(frozen=True, slots=True)
    class Heavy(SchemaCapability):
        def compile_work_stealing(self, ctx: WorkStealingContext) -> WorkStealingContext:
            return replace(ctx, priority=10)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from nodnod.agent.base import Agent
from nodnod.node import Node


@runtime_checkable
class SchedulingCompilable(Protocol):
    """A scheduling policy = a compiler.

    Each implementation defines HOW to build an agent from nodes.
    May define its own context type and compilable protocol for
    per-node capabilities (like WorkStealingContext / WorkStealingCompilable).
    """

    @property
    def requires_free_threaded(self) -> bool: ...

    def build_agent(self, nodes: set[type[Node]]) -> Agent: ...


@runtime_checkable
class GILResolvable(Protocol):
    """GIL resolution strategy — decides what to do when GIL is enabled."""

    def resolve_scheduling(
        self,
        scheduling: SchedulingCompilable,
        is_gil_enabled: bool,
    ) -> SchedulingCompilable: ...


@dataclass(frozen=True, slots=True)
class Cooperative:
    """Single-thread asyncio scheduling (CallbackAgent — behavioral equivalent of EventLoopAgent).

    Uses CallbackAgent instead of nodnod's EventLoopAgent because CallbackAgent
    lives in emergent (modifiable) and supports Spawnable (live node management).
    Identical DAG execution semantics — same dependency tracking, same error propagation.
    """

    requires_free_threaded: bool = False

    def build_agent(self, nodes: set[type[Node]]) -> Agent:
        from emergent.graph.runtime._helpers import CallbackAgent

        return CallbackAgent.build(nodes)


@dataclass(frozen=True, slots=True)
class WorkStealingContext:
    """Compilation context for WorkStealing scheduler.

    Capabilities implement compile_work_stealing() to affect this.
    Like PydanticContext is owned by the Pydantic compiler.

        @dataclass(frozen=True, slots=True)
        class Heavy(SchemaCapability):
            def compile_work_stealing(self, ctx: WorkStealingContext) -> WorkStealingContext:
                return replace(ctx, priority=max(ctx.priority, 10))
    """

    priority: int = 0


@runtime_checkable
class WorkStealingCompilable(Protocol):
    """Protocol for capabilities that compile to WorkStealing context."""

    def compile_work_stealing(self, ctx: WorkStealingContext) -> WorkStealingContext: ...


@dataclass(frozen=True, slots=True)
class WorkStealing:
    """N OS threads with work-stealing deques. Requires free-threaded Python.

    Acts as a compiler: folds schema_meta from each node using
    WorkStealingCompilable protocol to collect per-node traits.

    workers: Number of worker threads.
        None = auto: min(cpu_count, node_count).
        Explicit int for manual control.
    """

    workers: int | None = None
    requires_free_threaded: bool = True

    def build_agent(self, nodes: set[type[Node]]) -> Agent:
        from emergent.wire.compile._core import fold_schema
        from emergent.graph.runtime._helpers import build_graph_info
        from emergent.graph.runtime._threaded import _WorkStealingAgent

        graph_info = build_graph_info(nodes)

        traits: dict[type[Node], WorkStealingContext] = {}
        for node in graph_info.all_nodes:
            ctx = fold_schema(
                node, WorkStealingContext(), WorkStealingCompilable, "compile_work_stealing"
            )
            if ctx != WorkStealingContext():
                traits[node] = ctx

        n_workers = _WorkStealingAgent._resolve_workers(len(graph_info.all_nodes), self.workers)
        return _WorkStealingAgent(graph_info=graph_info, n_workers=n_workers, traits=traits)


@dataclass(frozen=True, slots=True)
class FailFast:
    """First error kills the entire graph. Current behavior of both agents."""


@dataclass(frozen=True, slots=True)
class CollectErrors:
    """Run all independent subtrees, collect all errors.

    Reserved for future use.
    """


type ErrorPolicy = FailFast | CollectErrors


@dataclass(frozen=True, slots=True)
class RequireFreeThreaded:
    """Hard error if GIL is enabled and scheduling requires free-threaded Python."""

    def resolve_scheduling(
        self,
        scheduling: SchedulingCompilable,
        is_gil_enabled: bool,
    ) -> SchedulingCompilable:
        if scheduling.requires_free_threaded and is_gil_enabled:
            raise RuntimeError(
                "WorkStealing scheduling requires free-threaded Python (3.13t+). "
                "GIL is currently enabled. Use AutoDowngrade() GIL policy to "
                "automatically fall back to Cooperative, or run with python3.13t / "
                "set PYTHON_GIL=0."
            )
        return scheduling


@dataclass(frozen=True, slots=True)
class AutoDowngrade:
    """Silently downgrade to Cooperative if scheduling requires free-threaded and GIL is enabled."""

    def resolve_scheduling(
        self,
        scheduling: SchedulingCompilable,
        is_gil_enabled: bool,
    ) -> SchedulingCompilable:
        if scheduling.requires_free_threaded and is_gil_enabled:
            return Cooperative()
        return scheduling


@dataclass(frozen=True, slots=True)
class RuntimePolicy:
    """Complete runtime configuration for graph execution.

    All axes have sensible defaults matching current EventLoopAgent behavior.
    Pure data — inspectable, composable, defunctionalized.

        RuntimePolicy()                              # cooperative, fail-fast
        RuntimePolicy(scheduling=WorkStealing())     # work-stealing, fail-fast
        RuntimePolicy(scheduling=WorkStealing(), gil=AutoDowngrade())
    """

    scheduling: SchedulingCompilable = field(default_factory=Cooperative)
    errors: ErrorPolicy = field(default_factory=FailFast)
    gil: GILResolvable = field(default_factory=RequireFreeThreaded)

    def __post_init__(self) -> None:
        if isinstance(self.scheduling, WorkStealing):
            w = self.scheduling.workers
            if w is not None and w < 1:
                raise ValueError("WorkStealing.workers must be >= 1 or None (auto)")
        if isinstance(self.errors, CollectErrors):
            raise NotImplementedError("CollectErrors is reserved for future use. Use FailFast().")
