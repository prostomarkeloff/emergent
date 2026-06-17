"""Application — collection of endpoints with optional global capabilities.

    app = application(
        capabilities=(CORS(origins=("*",)), RequestIdInjector()),
    ).mount(
        endpoint(runner).expose(...),
        endpoint(runner).expose(...),
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from emergent.wire.axis.surface._endpoint import Endpoint
from emergent.wire.axis.surface.capabilities._base import empty_caps as _empty_caps

if TYPE_CHECKING:
    from emergent.wire.axis.surface.capabilities import SurfaceCapability


@dataclass(frozen=True, slots=True)
class Application:
    """Wire application — endpoints + global capabilities. Immutable.

    Attributes:
        endpoints: Mounted endpoints.
        capabilities: Global capabilities applied to all endpoints (middleware).

    Example::

        app = application(
            capabilities=(
                CORS(origins=("*",)),
                GlobalTimeout(seconds=30),
            ),
        ).mount(
            endpoint(auth_runner).expose(...),
            endpoint(game_runner).expose(...),
        )
    """

    endpoints: tuple[Endpoint, ...] = ()
    capabilities: tuple[SurfaceCapability, ...] = field(default_factory=_empty_caps)

    def mount(self, *endps: Endpoint) -> Application:
        """Mount endpoints to application."""
        return Application(
            endpoints=(*self.endpoints, *endps),
            capabilities=self.capabilities,
        )

    def with_capabilities(self, *caps: SurfaceCapability) -> Application:
        """Add global capabilities."""
        return Application(
            endpoints=self.endpoints,
            capabilities=(*self.capabilities, *caps),
        )

    def __add__(self, other: Application) -> Application:
        """Combine two applications — sum endpoints and capabilities."""
        return Application(
            endpoints=(*self.endpoints, *other.endpoints),
            capabilities=(*self.capabilities, *other.capabilities),
        )

    def merge(self, *others: Application) -> Application:
        """Merge multiple applications into one."""
        all_endpoints = self.endpoints
        all_capabilities = self.capabilities
        for other in others:
            all_endpoints = (*all_endpoints, *other.endpoints)
            all_capabilities = (*all_capabilities, *other.capabilities)
        return Application(
            endpoints=all_endpoints,
            capabilities=all_capabilities,
        )


def application(
    capabilities: tuple[SurfaceCapability, ...] = (),
) -> Application:
    """Create new application with optional global capabilities.

    Args:
        capabilities: Global capabilities (middleware) applied to all endpoints.

    Example::

        app = application(
            capabilities=(CORS(origins=("*",)),),
        ).mount(...)
    """
    return Application(capabilities=capabilities)
