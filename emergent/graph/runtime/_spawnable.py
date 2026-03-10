"""Spawnable — live node management protocol for running agents.

Opt-in protocol. Agents that support it (CallbackAgent, _WorkStealingAgent)
implement spawn/despawn. Agents that don't (nodnod's EventLoopAgent) simply
aren't Spawnable — isinstance check returns False.

    from emergent.graph.runtime import Spawnable

    agent = RuntimeAgent.with_policy(RuntimePolicy()).build(nodes)
    if isinstance(agent, Spawnable):
        agent.spawn({NewNode})
        agent.despawn({OldNode})
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from nodnod.node import Node
from nodnod.scope import Scope


@runtime_checkable
class Spawnable(Protocol):
    """Live node management — spawn/despawn nodes in a running agent.

    Opt-in protocol. Agents that support it implement spawn/despawn.
    Agents that don't (EventLoopAgent) simply aren't Spawnable.

    spawn(): Add new nodes to a running agent. Their dependency graph is
        built and scheduled immediately. Already-resolved deps (in scope)
        are reused.

    despawn(): Remove nodes from a running agent. In-flight async tasks
        are cancelled. The agent's run loop adjusts its completion condition.

    living_nodes: Currently tracked nodes (initial + spawned - despawned).
    """

    def spawn(
        self,
        nodes: set[type[Node]],
        mapped_scopes: Mapping[type[Node], Scope] | None = None,
    ) -> None: ...

    def despawn(self, nodes: set[type[Node]]) -> None: ...

    @property
    def living_nodes(self) -> frozenset[type[Node]]: ...


__all__ = ("Spawnable",)
