"""Capability helpers — pure functions for querying and composing capabilities.

    from emergent.wire.axis.surface.capabilities import helpers

    # Find specific capability
    timeout = helpers.find_capability(caps, Timeout)

    # Get all enrichers
    enrichers = helpers.find_all_capabilities(caps, ScopeEnricher)

    # Merge capability tuples
    merged = helpers.merge_capabilities(base_caps, override_caps)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from emergent.wire.axis.surface.capabilities._base import SurfaceCapability


# ── Named type alias (house style: alias instead of inline dict[...]) ──
type CapabilityByType = dict[type, "SurfaceCapability"]


# ═══════════════════════════════════════════════════════════════════════════════
# Find capabilities
# ═══════════════════════════════════════════════════════════════════════════════


def find_capability[C](
    caps: tuple[SurfaceCapability, ...],
    cap_type: type[C],
) -> C | None:
    """Get first capability of specific type.

    Args:
        caps: Tuple of capabilities to search
        cap_type: Type to find

    Returns:
        First matching capability or None

    Example:
        timeout = find_capability(handler.capabilities, Timeout)
        if timeout:
            print(f"Timeout: {timeout.seconds}s")
    """
    for cap in caps:
        if isinstance(cap, cap_type):
            return cap
    return None


def find_all_capabilities[C](
    caps: tuple[SurfaceCapability, ...],
    cap_type: type[C],
) -> tuple[C, ...]:
    """Get all capabilities of specific type.

    Args:
        caps: Tuple of capabilities to search
        cap_type: Type to find (can be base class or Protocol)

    Returns:
        Tuple of matching capabilities

    Example:
        enrichers = find_all_capabilities(caps, ScopeEnricher)
        for e in enrichers:
            print(type(e).__name__)
    """
    return tuple(cap for cap in caps if isinstance(cap, cap_type))


def has_capability(
    caps: tuple[SurfaceCapability, ...],
    cap_type: type[SurfaceCapability],
) -> bool:
    """Check if capability of type exists.

    Args:
        caps: Tuple of capabilities to search
        cap_type: Type to check for

    Returns:
        True if capability exists
    """
    return any(isinstance(cap, cap_type) for cap in caps)


# ═══════════════════════════════════════════════════════════════════════════════
# Merge and compose capabilities
# ═══════════════════════════════════════════════════════════════════════════════


def merge_capabilities(
    *cap_tuples: tuple[SurfaceCapability, ...],
) -> tuple[SurfaceCapability, ...]:
    """Merge capability tuples, later overrides earlier by type.

    When same capability type appears in multiple tuples,
    the last one wins (override semantics).

    Args:
        *cap_tuples: Variable number of capability tuples

    Returns:
        Merged tuple with one capability per type

    Example:
        base = (Timeout(10), Tag("users"))
        override = (Timeout(5),)  # Override timeout
        merged = merge_capabilities(base, override)
        # Result: (Tag("users"), Timeout(5))
    """
    seen: CapabilityByType = {}
    for caps in cap_tuples:
        for cap in caps:
            seen[type(cap)] = cap
    return tuple(seen.values())


def override_capability(
    caps: tuple[SurfaceCapability, ...],
    new_cap: SurfaceCapability,
) -> tuple[SurfaceCapability, ...]:
    """Replace capability of same type with new one.

    Args:
        caps: Original capabilities
        new_cap: New capability to insert (replaces same type)

    Returns:
        New tuple with capability replaced

    Example:
        caps = (Timeout(10), Tag("users"))
        new_caps = override_capability(caps, Timeout(5))
        # Result: (Tag("users"), Timeout(5))
    """
    cap_type = type(new_cap)
    result = [cap for cap in caps if not isinstance(cap, cap_type)]
    result.append(new_cap)
    return tuple(result)


def remove_capability(
    caps: tuple[SurfaceCapability, ...],
    cap_type: type[SurfaceCapability],
) -> tuple[SurfaceCapability, ...]:
    """Remove all capabilities of specific type.

    Args:
        caps: Original capabilities
        cap_type: Type to remove

    Returns:
        New tuple without capabilities of that type
    """
    return tuple(cap for cap in caps if not isinstance(cap, cap_type))


def deduplicate_capabilities(
    caps: tuple[SurfaceCapability, ...],
) -> tuple[SurfaceCapability, ...]:
    """Remove duplicate capabilities (by type, keep last).

    Delegates to merge_capabilities — same semantics for single tuple.

    Args:
        caps: Capabilities that may have duplicates

    Returns:
        Deduplicated tuple (last of each type wins)
    """
    return merge_capabilities(caps)


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
