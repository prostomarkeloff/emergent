"""
Lift — Helpers for lifting values into emergent monads.

Re-exports from combinators.lift with emergent-specific additions.
"""

from __future__ import annotations

from collections.abc import Callable, Awaitable

from kungfu import LazyCoroResult, Result

# Re-export everything from combinators.lift
from combinators.lift import (
    pure,
    fail,
    catching_async,
    wrap_async,
    lifted,
    call,
    call_catching,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Emergent-specific helpers
# ═══════════════════════════════════════════════════════════════════════════════

def from_result[T, E](result: Result[T, E]) -> LazyCoroResult[T, E]:
    """Lift a Result into LazyCoroResult."""
    async def _run() -> Result[T, E]:
        return result
    return LazyCoroResult(_run)


def from_awaitable[T, E](
    awaitable_fn: Callable[[], Awaitable[T]],
    on_error: Callable[[Exception], E],
) -> LazyCoroResult[T, E]:
    """
    Create LazyCoroResult from async function.
    
    Alias for catching_async with clearer naming.
    """
    return catching_async(awaitable_fn, on_error=on_error)


__all__ = (
    # From combinators.lift
    "pure",
    "fail", 
    "catching_async",
    "wrap_async",
    "lifted",
    "call",
    "call_catching",
    # Emergent additions
    "from_result",
    "from_awaitable",
)
