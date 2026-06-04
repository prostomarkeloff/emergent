"""Composer — immutable (scope, agent_cls) pair for nodnod composition.

The single primitive for all nodnod composition in emergent.
Wraps scope + agent_cls and provides compose/retrieve operations.

    composer = Composer.create(scope, agent_cls)
    success, value = await composer.compose(MyNode)
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, cast

from kungfu import Some
from nodnod import Scope, EventLoopAgent
from nodnod.agent.base import Agent
from nodnod.node import Node


def _as_node_set(typ: type[Any]) -> set[type[Node]]:
    """Widen an arbitrary type to set[type[Node]] for Agent.build().

    At runtime, callers always pass Node subclasses. This helper
    bridges the static type gap: compose[T]() accepts unconstrained T
    (so callers don't need `T: Node` bounds), but Agent.build() requires
    set[type[Node]]. No static way to express this without cast —
    the bound lives in the runtime contract, not the type signature.
    """
    return {cast(type[Node], typ)}


@dataclass(frozen=True, slots=True)
class Composer:
    """Immutable (scope, agent_cls) pair — THE primitive for nodnod composition.

    All nodnod node types (scalar, data, either, polymorphic, generic,
    cached, option/result/union wrapper nodes) are handled automatically
    by the agent's build() + run().

    Respects nodnod's scope hierarchy: create_child(), retrieve() traversing
    parent chain, mapped_scopes.
    """

    scope: Scope
    agent_cls: type[Agent]
    mapped_scopes: Mapping[type, Scope] = field(default_factory=lambda: dict[type, Scope]())

    @classmethod
    def create(
        cls,
        scope: Scope,
        agent_cls: type[Agent] | None = None,
        mapped_scopes: Mapping[type, Scope] | None = None,
    ) -> Composer:
        """Create Composer, defaulting to EventLoopAgent."""
        return cls(
            scope=scope,
            agent_cls=agent_cls or EventLoopAgent,
            mapped_scopes=mapped_scopes if mapped_scopes is not None else {},
        )

    # --- Scope hierarchy ---

    def child(
        self,
        detail: str = "child",
        agent_cls: type[Agent] | None = None,
    ) -> Composer:
        """Create child Composer with child scope (inherits parent chain).

        Optionally override agent_cls for the child.
        """
        child_scope = self.scope.create_child(detail)
        return Composer(
            scope=child_scope,
            agent_cls=agent_cls or self.agent_cls,
            mapped_scopes=self.mapped_scopes,
        )

    def retrieve[T](self, typ: type[T]) -> tuple[bool, T | None]:
        """Retrieve value from scope (traverses parent chain).

        Returns (found, value). Unwraps nodnod Value wrapper.
        """
        result = self.scope.retrieve(typ)
        match result:
            case Some(v):
                return True, v.value
            case _:
                return False, None

    # --- Composition ---

    async def compose[T](self, node_type: type[T]) -> tuple[bool, T | str]:
        """Compose a single nodnod node.

        Builds agent for this node, runs it with the scope,
        and retrieves the result.

        Returns (success, value_or_error).
        """
        try:
            # node_type is always a Node subclass at runtime; build a typed set
            # via _as_node_set to satisfy Agent.build's signature.
            agent = self.agent_cls.build(_as_node_set(node_type))
            await agent.run(
                local_scope=self.scope,
                mapped_scopes=dict(self.mapped_scopes),
            )

            result = self.scope.retrieve(node_type)
            match result:
                case Some(value):
                    return True, value.value
                case _:
                    return False, f"Node {node_type.__name__} not composed"
        except Exception as e:
            return False, str(e)

    async def compose_batch(self, node_types: set[type]) -> None:
        """Compose multiple nodes in one agent run (auto-parallelized by nodnod)."""
        agent = self.agent_cls.build(node_types)
        await agent.run(
            local_scope=self.scope,
            mapped_scopes=dict(self.mapped_scopes),
        )

    async def resolve_params(
        self,
        handler: Callable[..., Any],
    ) -> dict[str, Any]:
        """Resolve handler params using compose dialect.

        Delegates to _delegate.resolve_handler_params with this Composer's
        scope and agent_cls.
        """
        from emergent.wire.compile._delegate import resolve_handler_params

        return await resolve_handler_params(handler, self.scope, self.agent_cls)


__all__ = ("Composer",)
