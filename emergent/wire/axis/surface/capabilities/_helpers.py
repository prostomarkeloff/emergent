"""Capability helpers — pure functions for querying and composing capabilities.

    from emergent.wire.axis.surface.capabilities import helpers

    # Find specific capability
    timeout = helpers.find_capability(caps, Timeout)

    # Get all enrichers
    enrichers = helpers.find_all_capabilities(caps, ScopeEnricher)

    # Merge capability tuples
    merged = helpers.merge_capabilities(base_caps, override_caps)

NOTE: The generic capability-composition / query helpers below are the SAME
pure functions as the schema axis. They are structural (isinstance / dict by
type) and carry no schema-specific behavior, so the surface axis re-exports the
canonical implementations from `emergent.wire.axis.schema._helpers` instead of
duplicating their bodies. Surface-specific helpers (filter_by_protocol) stay
local.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Single source of truth — re-export the canonical implementations.
from emergent.wire.axis.schema._helpers import (
    merge_capabilities,
    override_capability,
    remove_capability,
    deduplicate_capabilities,
    find_capability,
    find_all_capabilities,
    has_capability,
)

if TYPE_CHECKING:
    from emergent.wire.axis.surface.capabilities._base import SurfaceCapability


# ═══════════════════════════════════════════════════════════════════════════════
# Filter by protocol
# ═══════════════════════════════════════════════════════════════════════════════


def filter_by_protocol[P](
    caps: tuple[SurfaceCapability, ...],
    protocol: type[P],
) -> tuple[P, ...]:
    """Get capabilities implementing specific protocol.

    Args:
        caps: Capabilities to filter
        protocol: Protocol type (ScopeEnricher, TriggerTransform, etc.)

    Returns:
        Tuple of capabilities implementing the protocol

    Example:
        from emergent.wire.axis.surface.capabilities import ScopeEnricher
        enrichers = filter_by_protocol(caps, ScopeEnricher)
    """
    return tuple(cap for cap in caps if isinstance(cap, protocol))


__all__ = (
    "find_capability",
    "find_all_capabilities",
    "has_capability",
    "merge_capabilities",
    "override_capability",
    "remove_capability",
    "deduplicate_capabilities",
    "filter_by_protocol",
)
