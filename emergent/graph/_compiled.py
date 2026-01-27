"""
Compiled graph — for repeated execution.

Pre-compile once, run many times.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from collections.abc import Callable, Coroutine

from nodnod import Scope, EventLoopAgent, Node

from emergent.graph._run import TypedScope


# ═══════════════════════════════════════════════════════════════════════════════
# CompiledRun — Fluent runner with pre-compiled agent
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class CompiledRun[T]:
    """Run with pre-compiled agent."""

    _target: type[T]
    _agent: EventLoopAgent
    _injections: tuple[tuple[type[Any], Any], ...]

    def inject(self, value: object) -> CompiledRun[T]:
        """Inject a value. Type is inferred from runtime type."""
        value_type = cast(type[Any], type(value))
        return CompiledRun(
            _target=self._target,
            _agent=self._agent,
            _injections=(*self._injections, (value_type, value)),
        )

    def inject_as[V](self, typ: type[V], value: V) -> CompiledRun[T]:
        """Inject with explicit type."""
        typed_tuple: tuple[type[Any], Any] = (typ, value)
        return CompiledRun(
            _target=self._target,
            _agent=self._agent,
            _injections=(*self._injections, typed_tuple),
        )

    def given(self, *values: object) -> CompiledRun[T]:
        """Inject multiple values at once."""
        new_inj: list[tuple[type[Any], Any]] = []
        for v in values:
            new_inj.append((cast(type[Any], type(v)), v))
        return CompiledRun(
            _target=self._target,
            _agent=self._agent,
            _injections=(*self._injections, *new_inj),
        )

    def __await__(self) -> Any:
        return self._execute().__await__()

    async def _execute(self) -> T:
        async with TypedScope(detail="compiled_run") as scope:
            for typ, value in self._injections:
                scope.inject(typ, value)

            run_method = cast(
                Callable[[Scope, dict[type[Any], Scope]], Coroutine[Any, Any, None]],
                getattr(self._agent, "run"),
            )
            await run_method(scope.inner, {})

            return scope.get(self._target)


# ═══════════════════════════════════════════════════════════════════════════════
# Compiled — Pre-compiled graph
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(slots=True, frozen=True)
class Compiled[T]:
    """
    Pre-compiled graph for repeated execution.

    Compile once at startup, execute many times.

    Example:
        # Compile
        pipeline = graph(ProcessOrder)

        # Execute (multiple ways)
        result = await pipeline(order, db, email)
        result = await pipeline.run().inject(order).inject(db)
    """

    _target: type[T]
    _agent: EventLoopAgent

    def run(self) -> CompiledRun[T]:
        """Start a fluent run."""
        return CompiledRun(
            _target=self._target,
            _agent=self._agent,
            _injections=(),
        )

    async def __call__(self, *inputs: object) -> T:
        """
        Direct call.

            result = await pipeline(order, db, email)
        """
        return await self.run().given(*inputs)


def graph[T](target: type[T]) -> Compiled[T]:
    """
    Pre-compile a graph.

    Example:
        # Compile once
        pipeline = graph(ProcessOrder)

        # Run many times
        r1 = await pipeline(order1, db)
        r2 = await pipeline(order2, db)
    """
    all_nodes: set[type[Node[Any, Any]]] = {cast(type[Node[Any, Any]], target)}
    agent = EventLoopAgent.build(all_nodes)
    return Compiled(_target=target, _agent=agent)


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = ("CompiledRun", "Compiled", "graph")
