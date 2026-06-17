"""Surface capability base — root marker only.

All concrete protocols moved to:
- enrichers/ — ScopeEnricher
- transforms/ — TriggerTransform, HandlerTransform, ResponseTransform
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from emergent.wire.axis._capability import Capability as RootCapability


@runtime_checkable
class SurfaceCapability(RootCapability, Protocol):
    """Root marker for all surface capabilities.

    Inherits from root axis Capability.

    Surface capabilities modify the Trigger × Codec space.

    Hierarchy:
        SurfaceCapability (this)
        ├── ScopeEnricher — runtime middleware (enrichers/)
        ├── TriggerTransform — compile-time trigger modification (transforms/)
        ├── HandlerTransform — compile-time handler wrapping (transforms/)
        └── ResponseTransform — runtime response transformation (transforms/)

    Target-specific capabilities live in dialects/:
        - dialects/http — OpenAPI, security schemes
        - dialects/telegram — Telegrinder-specific
    """

    ...


def empty_caps() -> tuple[SurfaceCapability, ...]:
    """Empty tuple of surface capabilities — shared default_factory."""
    return ()


__all__ = (
    "SurfaceCapability",
    "empty_caps",
)
