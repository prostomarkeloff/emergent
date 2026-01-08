"""
On-failure policies.
"""

from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class ContinuePolicy:
    """Continue execution on failure (best-effort)."""
    pass

def continue_() -> ContinuePolicy:
    """Continue on failure."""
    return ContinuePolicy()


@dataclass(frozen=True, slots=True)
class AbortPolicy:
    """Abort immediately on failure."""
    pass

def abort() -> AbortPolicy:
    """Abort on failure."""
    return AbortPolicy()


__all__ = ("ContinuePolicy", "continue_", "AbortPolicy", "abort")

