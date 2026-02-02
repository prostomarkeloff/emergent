"""Unified capability processing — all adapters use this.

Single dispatcher for capability application. Each capability type
has a handler that transforms request/response or modifies behavior.

    from emergent.wire.compile._capabilities import apply_response_capabilities

    # Same for all targets
    response = await apply_response_capabilities(response, handler.capabilities, ctx)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TYPE_CHECKING

from emergent.wire.axis.surface.capabilities import (
    SurfaceCapability,
    ResponseTransform,
)

if TYPE_CHECKING:
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Capability Context Protocol
# ═══════════════════════════════════════════════════════════════════════════════


class CapabilityContext(Protocol):
    """Context for capability processing.

    Each framework provides its own context implementation.
    Capabilities can access framework-specific data through this.
    """

    @property
    def framework(self) -> str:
        """Framework identifier: 'fastapi', 'cli', 'telegrinder'."""
        ...


@dataclass(frozen=True, slots=True)
class FastAPICapabilityContext:
    """FastAPI capability context."""

    request: Any  # fastapi.Request

    @property
    def framework(self) -> str:
        return "fastapi"


@dataclass(frozen=True, slots=True)
class CLICapabilityContext:
    """CLI capability context."""

    namespace: Any  # argparse.Namespace

    @property
    def framework(self) -> str:
        return "cli"


@dataclass(frozen=True, slots=True)
class TelegrinderCapabilityContext:
    """Telegrinder capability context."""

    ctx: Any  # telegrinder Context

    @property
    def framework(self) -> str:
        return "telegrinder"


# ═══════════════════════════════════════════════════════════════════════════════
# Response Capability Processing
# ═══════════════════════════════════════════════════════════════════════════════


def apply_response_capabilities(
    response: Any,
    capabilities: tuple[SurfaceCapability, ...],
) -> Any:
    """Apply response-transforming capabilities.

    Pure function that transforms response based on capabilities.
    Called by all adapters after execute_rrc/execute_stateful_done.

    Currently handles:
    - ResponseTransform: apply_response() method

    Args:
        response: Response to transform
        capabilities: Handler capabilities

    Returns:
        Transformed response
    """
    for cap in capabilities:
        if isinstance(cap, ResponseTransform):
            response = cap.apply_response(response)

    return response


async def apply_response_capabilities_async(
    response: Any,
    capabilities: tuple[SurfaceCapability, ...],
    ctx: CapabilityContext | None = None,
) -> Any:
    """Apply response-transforming capabilities (async version).

    Some capabilities may need async processing (e.g., EditMessage in Telegram).
    This version supports both sync and async capability handlers.

    Args:
        response: Response to transform
        capabilities: Handler capabilities
        ctx: Framework-specific context (optional, for async capabilities)

    Returns:
        Transformed response
    """
    for cap in capabilities:
        if isinstance(cap, ResponseTransform):
            response = cap.apply_response(response)

    return response


# ═══════════════════════════════════════════════════════════════════════════════
# Capability Lookup Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def find_capability[C: SurfaceCapability](
    capabilities: tuple[SurfaceCapability, ...],
    cap_type: type[C],
) -> C | None:
    """Find first capability of given type.

    Generic helper for capability lookup. Use instead of manual loops.

    Example:
        timeout = find_capability(handler.capabilities, TimeoutCapability)
        if timeout:
            handler = with_timeout(handler, timeout.seconds)
    """
    for cap in capabilities:
        if isinstance(cap, cap_type):
            return cap
    return None


def find_all_capabilities[C: SurfaceCapability](
    capabilities: tuple[SurfaceCapability, ...],
    cap_type: type[C],
) -> list[C]:
    """Find all capabilities of given type.

    Example:
        middlewares = find_all_capabilities(handler.capabilities, MiddlewareCapability)
    """
    return [cap for cap in capabilities if isinstance(cap, cap_type)]


def has_capability(
    capabilities: tuple[SurfaceCapability, ...],
    cap_type: type[SurfaceCapability],
) -> bool:
    """Check if capabilities include given type.

    Example:
        if has_capability(handler.capabilities, StreamingCapability):
            return streaming_response(...)
    """
    return any(isinstance(cap, cap_type) for cap in capabilities)


__all__ = (
    # Context
    "CapabilityContext",
    "FastAPICapabilityContext",
    "CLICapabilityContext",
    "TelegrinderCapabilityContext",
    # Processing
    "apply_response_capabilities",
    "apply_response_capabilities_async",
    # Lookup
    "find_capability",
    "find_all_capabilities",
    "has_capability",
)
