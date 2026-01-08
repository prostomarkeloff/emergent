"""
Core types for emergent.

Re-exports from kungfu/combinators + custom type aliases.
"""

from __future__ import annotations

from typing import Never
from collections.abc import Callable, Awaitable
from dataclasses import dataclass

# Re-export from kungfu
from kungfu import Result, Ok, Error, Option, Some, Nothing, LazyCoroResult

# Re-export from combinators
from combinators import LCR, NoError

# ═══════════════════════════════════════════════════════════════════════════════
# Lazy Computation Aliases
# ═══════════════════════════════════════════════════════════════════════════════

type Lazy[T, E] = LazyCoroResult[T, E]
"""Lazy async computation that may fail."""

type Pure[T] = Lazy[T, Never]
"""Lazy computation that cannot fail."""

type Fallible[T, E] = Lazy[T, E]
"""Lazy computation that can fail with E."""

# ═══════════════════════════════════════════════════════════════════════════════
# Node Identity
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True, slots=True)
class NodeId[T]:
    """
    Type-level node identity.

    The TYPE itself is the identity — no strings needed.
    """
    node_type: type[T]

# ═══════════════════════════════════════════════════════════════════════════════
# Compensator Type (for Saga)
# ═══════════════════════════════════════════════════════════════════════════════

type Compensator = Callable[[], Awaitable[None]]
"""A compensation action that undoes a step."""

# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = (
    # Re-exports from kungfu
    "Result",
    "Ok",
    "Error",
    "Option",
    "Some",
    "Nothing",
    "LazyCoroResult",
    # Re-exports from combinators
    "LCR",
    "NoError",
    # Type aliases
    "Lazy",
    "Pure",
    "Fallible",
    # Identity
    "NodeId",
    # Saga types
    "Compensator",
)
