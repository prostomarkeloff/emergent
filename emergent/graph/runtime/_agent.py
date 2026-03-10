"""RuntimeAgent — policy-driven graph executor.

Dispatches to the appropriate backend via protocol dispatch.
The scheduling policy IS the compiler — it builds the agent internally.

    from emergent.graph.runtime import RuntimeAgent, RuntimePolicy, WorkStealing

    agent_cls = RuntimeAgent.with_policy(RuntimePolicy(
        scheduling=WorkStealing(workers=4),
    ))
    pipeline = graph(ProcessOrder, agent_cls=agent_cls)
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from typing import ClassVar

from nodnod.agent.base import Agent
from nodnod.node import Node
from nodnod.scope import Scope

from emergent.graph.runtime._policy import RuntimePolicy
from emergent.graph.runtime._spawnable import Spawnable


def _is_gil_enabled() -> bool:
    return getattr(sys, "_is_gil_enabled", lambda: True)()


def _policy_label(policy: RuntimePolicy) -> str:
    """Human-readable label for a policy (used in dynamic class name)."""
    sched = type(policy.scheduling).__name__
    workers = getattr(policy.scheduling, "workers", None)
    if workers is not None:
        sched = f"{sched}({workers})"
    return sched


class RuntimeAgent(Agent):
    """Policy-driven agent that dispatches to the appropriate execution backend.

    Not instantiated directly. Use ``with_policy()`` to get a configured
    ``type[Agent]`` compatible with nodnod's interface everywhere.

        agent_cls = RuntimeAgent.with_policy(RuntimePolicy(
            scheduling=WorkStealing(),
        ))
        pipeline = graph(ProcessOrder, agent_cls=agent_cls)
    """

    _policy: ClassVar[RuntimePolicy]

    def __init__(self, delegate: Agent) -> None:
        self._delegate = delegate

    @classmethod
    def with_policy(cls, policy: RuntimePolicy) -> type[RuntimeAgent]:
        """Create a configured Agent class from a policy.

        Returns a new class (subclass of RuntimeAgent) with the policy
        baked in as a class variable. Satisfies ``type[Agent]`` everywhere —
        Composer, graph(), wire compilers — with zero API changes.
        """
        configured_cls = type(
            f"RuntimeAgent[{_policy_label(policy)}]",
            (RuntimeAgent,),
            {"_policy": policy},
        )
        return configured_cls

    @classmethod
    def build(cls, nodes: set[type[Node]]) -> RuntimeAgent:
        effective = cls._policy.gil.resolve_scheduling(
            cls._policy.scheduling, _is_gil_enabled()
        )
        delegate = effective.build_agent(nodes)
        return cls(delegate)

    async def run(self, local_scope: Scope, mapped_scopes: dict[type[Node], Scope]) -> None:
        await self._delegate.run(local_scope, mapped_scopes)

    # --- Spawnable delegation ---

    def spawn(
        self,
        nodes: set[type[Node]],
        mapped_scopes: Mapping[type[Node], Scope] | None = None,
    ) -> None:
        """Delegate to inner agent. Raises TypeError if delegate isn't Spawnable."""
        if not isinstance(self._delegate, Spawnable):
            raise TypeError(
                f"Delegate {type(self._delegate).__name__} does not support Spawnable. "
                f"Use Cooperative or WorkStealing scheduling."
            )
        self._delegate.spawn(nodes, mapped_scopes)

    def despawn(self, nodes: set[type[Node]]) -> None:
        """Delegate to inner agent. Raises TypeError if delegate isn't Spawnable."""
        if not isinstance(self._delegate, Spawnable):
            raise TypeError(
                f"Delegate {type(self._delegate).__name__} does not support Spawnable."
            )
        self._delegate.despawn(nodes)

    @property
    def living_nodes(self) -> frozenset[type[Node]]:
        """Living nodes from delegate, or empty if not Spawnable."""
        if not isinstance(self._delegate, Spawnable):
            return frozenset()
        return self._delegate.living_nodes


__all__ = ("RuntimeAgent",)
