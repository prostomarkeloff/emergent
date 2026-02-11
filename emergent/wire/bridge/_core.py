"""Bridge core — handler types and wire data.

Minimal types used by capabilities.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ParamSpec, TypeVar

from kungfu import Result

if TYPE_CHECKING:
    from emergent.wire.axis.surface.capabilities._base import SurfaceCapability


# Type variables
R = TypeVar("R")
R_co = TypeVar("R_co", covariant=True)
P = ParamSpec("P")

# Handler type aliases — generic over parameters P and return type R
type SyncHandler[**P, R] = Callable[P, R]
type AsyncHandler[**P, R] = Callable[P, Awaitable[R]]
type AnyHandler[**P, R] = SyncHandler[P, R] | AsyncHandler[P, R]


# ═══════════════════════════════════════════════════════════════════════════════
# Wire Data — typed container for wire-specific extraction data
# ═══════════════════════════════════════════════════════════════════════════════


def _empty_caps() -> tuple[SurfaceCapability, ...]:
    return ()


def _empty_triggers() -> tuple[tuple[type, Callable[..., object]], ...]:
    return ()


@dataclass(frozen=True, slots=True)
class WireData:
    """Typed container for wire-specific data.

    Capabilities use replace() to update fields.
    Wire types are TYPE_CHECKING imports only.
    """

    codec: object | None = None
    surface_capabilities: tuple[SurfaceCapability, ...] = field(
        default_factory=_empty_caps
    )
    op_type: type | None = None
    op_handler: Callable[..., Awaitable[Result[object, object]]] | None = None
    # Additional triggers for cross-compilation (trigger_type, builder)
    additional_triggers: tuple[tuple[type, Callable[..., object]], ...] = field(
        default_factory=_empty_triggers
    )


__all__ = (
    # Handler types
    "SyncHandler",
    "AsyncHandler",
    "AnyHandler",
    # Wire data
    "WireData",
)
