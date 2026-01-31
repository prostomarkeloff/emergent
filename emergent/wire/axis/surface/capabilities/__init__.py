"""Surface capabilities — modifiers for Trigger × Codec space.

Capabilities modify endpoints at compile time. Compilers read them and apply
appropriate transformations.

Usage:
    from emergent.wire.axis.surface import capabilities as C

    endpoint(runner).expose(
        HTTPRouteTrigger("/users", "GET"),
        rrc(ListUsers, UsersResponse),
        C.Prefix.of("api", "v1"),
        C.Tag.of("users"),
        C.Timeout.seconds(30),
    )

Categories:
    - Trigger transforms: Prefix, StripPrefix
    - Handler transforms: Timeout
    - OpenAPI metadata: Tag, BearerAuth, ApiKeyAuth, OAuth2Auth, Summary, OperationId, Deprecated
"""

from emergent.wire.axis.surface.capabilities._base import (
    SurfaceCapability,
    TriggerTransform,
    HandlerTransform,
    ResponseTransform,
)

from emergent.wire.axis.surface.capabilities._trigger import (
    URLPath,
    Prefix,
    StripPrefix,
)

from emergent.wire.axis.surface.capabilities._handler import (
    Timeout,
)

from emergent.wire.axis.surface.capabilities._openapi import (
    # Tags
    Tag,
    # Security
    BearerAuth,
    ApiKeyAuth,
    OAuth2Auth,
    # Operation meta
    Summary,
    OperationId,
    Deprecated,
)

__all__ = (
    # Base
    "SurfaceCapability",
    "TriggerTransform",
    "HandlerTransform",
    "ResponseTransform",
    # Trigger transforms
    "URLPath",
    "Prefix",
    "StripPrefix",
    # Handler transforms
    "Timeout",
    # OpenAPI
    "Tag",
    "BearerAuth",
    "ApiKeyAuth",
    "OAuth2Auth",
    "Summary",
    "OperationId",
    "Deprecated",
)
