"""ASGI-specific bridge capabilities.

These capabilities know about ASGI patterns and compiler integration.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from emergent.wire.bridge._capabilities import BridgeCapability, BridgeContext


@dataclass(frozen=True, slots=True)
class MountASGI(BridgeCapability):
    """Mount ASGI app instead of calling individual handlers.

    Adds the Mount compiler capability to extracted handlers.
    The compiler will mount the ASGI app ONCE at the specified prefix.
    Individual route registrations are skipped — ASGI app handles all routes.

    Example::

        from django.core.asgi import get_asgi_application
        from emergent.wire.bridge.bridgers import asgi

        django_asgi = get_asgi_application()

        result = bridgers.django.extract(
            urlpatterns,
            capabilities=(
                asgi.MountASGI(django_asgi, prefix="/django", source="django"),
                WrapAsDelegate(),
            ),
        )
    """

    app: object  # ASGI app
    prefix: str = "/"
    source: str = ""

    def compile_bridge[T, **P, R](
        self, ctx: BridgeContext[T, P, R]
    ) -> BridgeContext[T, P, R]:
        """Add Mount compiler capability to surface capabilities."""
        from emergent.wire.compile._capabilities import Mount

        mount_cap = Mount(self.app, self.prefix, self.source)
        new_wire = replace(
            ctx.wire,
            surface_capabilities=(*ctx.wire.surface_capabilities, mount_cap),
        )
        return replace(ctx, wire=new_wire)


__all__ = ("MountASGI",)
