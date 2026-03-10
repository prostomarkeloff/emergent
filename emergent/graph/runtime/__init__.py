"""Multi-runtime graph execution with policy-driven scheduling.

    from emergent.graph.runtime import RuntimeAgent, RuntimePolicy, WorkStealing

    agent_cls = RuntimeAgent.with_policy(RuntimePolicy(
        scheduling=WorkStealing(workers=4),
    ))
    pipeline = graph(ProcessOrder, agent_cls=agent_cls)

    # Or use the pre-configured ThreadedAgent alias:
    from emergent.graph.runtime import ThreadedAgent

    pipeline = graph(ProcessOrder, agent_cls=ThreadedAgent)
"""

from emergent.graph.runtime._agent import RuntimeAgent
from emergent.graph.runtime._helpers import (
    CallbackAgent,
    GraphInfo,
    NodeExecutor,
    build_graph_info,
    default_executor,
)
from emergent.graph.runtime._spawnable import Spawnable
from emergent.graph.runtime._policy import (
    AutoDowngrade,
    CollectErrors,
    Cooperative,
    ErrorPolicy,
    FailFast,
    GILResolvable,
    RequireFreeThreaded,
    RuntimePolicy,
    SchedulingCompilable,
    WorkStealing,
    WorkStealingCompilable,
    WorkStealingContext,
)

ThreadedAgent = RuntimeAgent.with_policy(RuntimePolicy(
    scheduling=WorkStealing(),
    errors=FailFast(),
    gil=RequireFreeThreaded(),
))

__all__ = (
    "RuntimeAgent",
    "ThreadedAgent",
    "RuntimePolicy",
    "Spawnable",
    "SchedulingCompilable",
    "Cooperative",
    "WorkStealing",
    "WorkStealingContext",
    "WorkStealingCompilable",
    "FailFast",
    "CollectErrors",
    "ErrorPolicy",
    "GILResolvable",
    "RequireFreeThreaded",
    "AutoDowngrade",
    "GraphInfo",
    "build_graph_info",
    "NodeExecutor",
    "default_executor",
    "CallbackAgent",
)
