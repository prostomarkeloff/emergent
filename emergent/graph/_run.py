"""
Fluent runner — sugar over nodnod.

Auto-discovers nodes, type-safe injection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from collections.abc import Callable, Coroutine

from nodnod import Scope, Value, EventLoopAgent, Node


# ═══════════════════════════════════════════════════════════════════════════════
# TypedScope
# ═══════════════════════════════════════════════════════════════════════════════

class TypedScope:
    """Type-safe wrapper around nodnod.Scope."""

    __slots__ = ("_scope",)

    def __init__(self, scope: Scope | None = None, detail: str = "scope") -> None:
        self._scope = scope if scope is not None else Scope(detail=detail)

    @property
    def inner(self) -> Scope:
        return self._scope

    def inject[T](self, typ: type[T], value: T) -> TypedScope:
        self._scope.push(Value(typ, value))
        return self

    def get[T](self, typ: type[T]) -> T:
        result = self._scope.get(typ)
        if result is None:
            raise KeyError(f"{typ.__name__} not found in scope")
        return cast(T, result.value)

    async def __aenter__(self) -> TypedScope:
        await self._scope.__aenter__()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self._scope.__aexit__(*args)


# ═══════════════════════════════════════════════════════════════════════════════
# Run — Fluent awaitable builder
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(slots=True)
class Run[T]:
    """
    Fluent runner for a node.

    Auto-discovers all dependent nodes from the target.
    Type-safe injection via .inject() or .given().

    Example:
        # Fluent style
        result = await (
            run(ProcessOrder)
            .inject(order_data)
            .inject(db_config)
        )

        # Short style
        result = await run(ProcessOrder).given(order, db, email)
    """
    _target: type[T]
    _injections: tuple[tuple[type[Any], Any], ...]

    def inject(self, value: object) -> Run[T]:
        """
        Inject a value. Type is inferred from runtime type.

            .inject(order_data)  # Injects as OrderData
        """
        value_type = cast(type[Any], type(value))
        return Run(
            _target=self._target,
            _injections=(*self._injections, (value_type, value)),
        )

    def inject_as[V](self, typ: type[V], value: V) -> Run[T]:
        """
        Inject with explicit type.

            .inject_as(PaymentGateway, stripe)
        """
        typed_tuple: tuple[type[Any], Any] = (typ, value)
        return Run(
            _target=self._target,
            _injections=(*self._injections, typed_tuple),
        )

    def given(self, *values: object) -> Run[T]:
        """
        Inject multiple values at once.

            .given(order, db, email)
        """
        new_inj: list[tuple[type[Any], Any]] = []
        for v in values:
            new_inj.append((cast(type[Any], type(v)), v))
        return Run(
            _target=self._target,
            _injections=(*self._injections, *new_inj),
        )

    def __await__(self) -> Any:
        return self._execute().__await__()

    async def _execute(self) -> T:
        # nodnod auto-discovers dependencies from target
        all_nodes: set[type[Node[Any, Any]]] = {
            cast(type[Node[Any, Any]], self._target)
        }
        agent = EventLoopAgent.build(all_nodes)

        async with TypedScope(detail="run") as scope:
            for typ, value in self._injections:
                scope.inject(typ, value)

            run_method = cast(
                Callable[[Scope, dict[type[Any], Scope]], Coroutine[Any, Any, None]],
                getattr(agent, "run"),
            )
            await run_method(scope.inner, {})

            return scope.get(self._target)


def run[T](target: type[T]) -> Run[T]:
    """
    Run a node with auto-discovery.

    Example:
        result = await run(ProcessOrder).given(order, db)
    """
    return Run(_target=target, _injections=())


# ═══════════════════════════════════════════════════════════════════════════════
# compose — One-shot
# ═══════════════════════════════════════════════════════════════════════════════

async def compose[T](target: type[T], *inputs: object) -> T:
    """
    One-shot composition. Shortest API.

    Example:
        result = await compose(ProcessOrder, order, db, email)
    """
    return await run(target).given(*inputs)


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = ("TypedScope", "Run", "run", "compose")
