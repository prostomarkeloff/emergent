"""Bridge types — RouteData, Extracted.

Symmetric to surface._types (Trigger, Codec, Exposure).

    from emergent.wire.bridge import RouteData, Extracted

RouteData is the base type for source-specific route data (like Trigger).
Extracted bundles route + handler + metadata (like Handler).
"""

from __future__ import annotations

from typing import Any

from collections.abc import Callable
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════════════════════
# Base Types
# ═══════════════════════════════════════════════════════════════════════════════


# Base type for route data — like Trigger in surface axis
# Each framework defines concrete types: HTTPRouteData, WebSocketRouteData, etc.
type RouteData = object


type MetadataFactoryResult = dict[str, Any]
type MetadataMap = dict[str, object]


# ═══════════════════════════════════════════════════════════════════════════════
# Extracted — like Handler in surface
# ═══════════════════════════════════════════════════════════════════════════════


def _empty_metadata() -> MetadataFactoryResult:
    return {}


@dataclass(frozen=True, slots=True)
class Extracted[R: RouteData]:
    """Extracted handler bundle — like Handler in surface.

    Bundles route data + handler + metadata.
    Capabilities transform this via BridgeContext.

    Type parameter R is the concrete RouteData type (HTTPRouteData, etc.).

    Attributes:
        route: Source-specific route data (HTTPRouteData, WebSocketRouteData, etc.)
        handler: Original handler callable.
        name: Handler name (from __name__ or route).
        description: Handler description (from __doc__ or route).
        deprecated: Deprecation flag.
        metadata: Additional framework-specific metadata.
    """

    route: R
    handler: Callable[..., object]
    name: str | None = None
    description: str | None = None
    deprecated: bool = False
    metadata: MetadataMap = field(default_factory=_empty_metadata)


__all__ = (
    "RouteData",
    "Extracted",
)
