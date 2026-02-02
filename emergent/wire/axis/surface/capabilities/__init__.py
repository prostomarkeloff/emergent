"""Surface capabilities — modifiers for Trigger × Codec space.

Categories:
    Compile-time:
        - TriggerTransform: Prefix, StripPrefix, URLPath
        - HandlerTransform: wraps handler at compile time

    Runtime:
        - ResponseTransform: AsDict, AsStr
        - ScopeEnricher: sequential scope enrichment (middleware pattern)

    Transport-specific:
        - OpenAPI (HTTP): Tag, BearerAuth, ApiKeyAuth, OAuth2Auth, etc.
        - Telegram: tg.EditMessage, tg.AnswerCallback, tg.Silent

Usage:
    from emergent.wire.axis.surface import capabilities as C

    endpoint(runner).expose(
        HTTPRouteTrigger("/users", "GET"),
        rrc(ListUsers, UsersResponse),
        # Compile-time
        C.Prefix.of("api", "v1"),
        C.Tag.of("users"),
        # Runtime enrichers
        C.enricher.Timeout(seconds=5.0),
        C.enricher.Auth(inject=User, runner=auth_runner, ...),
        C.enricher.Retry(policy=RetryPolicy.exponential(times=3)),
    )

    # Telegram-specific
    endpoint(runner).expose(
        TelegrindTrigger(CallbackDataMarkup("game:<id>")),
        rrc(MoveRequest, Response),
        tg.EditMessage(),
        C.AsDict(),
    )

Enrichers use combinators.py for operations (timeout, retry, rate_limit)
and emergent.cache for caching.
"""

from emergent.wire.axis.surface.capabilities._base import (
    SurfaceCapability,
    TriggerTransform,
    HandlerTransform,
    ResponseTransform,
    ScopeEnricher,
    EnricherNext,
)

# Enricher implementations
from emergent.wire.axis.surface.capabilities import _enricher as enricher

from emergent.wire.axis.surface.capabilities._trigger import (
    URLPath,
    Prefix,
    StripPrefix,
)

from emergent.wire.axis.surface.capabilities._handler import (
    Timeout,
)

from emergent.wire.axis.surface.capabilities._response import (
    AsDict,
    AsStr,
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

# Transport-specific namespaces
from emergent.wire.axis.surface.capabilities import _telegrinder as tg

__all__ = (
    # Base
    "SurfaceCapability",
    "TriggerTransform",
    "HandlerTransform",
    "ResponseTransform",
    "ScopeEnricher",
    "EnricherNext",
    # Enricher implementations namespace
    "enricher",
    # Trigger transforms
    "URLPath",
    "Prefix",
    "StripPrefix",
    # Handler transforms
    "Timeout",
    # Response transforms
    "AsDict",
    "AsStr",
    # OpenAPI
    "Tag",
    "BearerAuth",
    "ApiKeyAuth",
    "OAuth2Auth",
    "Summary",
    "OperationId",
    "Deprecated",
    # Transport-specific namespaces
    "tg",
)
