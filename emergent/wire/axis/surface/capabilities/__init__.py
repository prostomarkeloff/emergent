"""Surface capabilities — modifiers for Trigger × Codec space.

RESTRUCTURED:
    - enrichers/   — runtime middleware (ScopeEnricher and implementations)
    - transforms/  — compile/runtime transforms (Trigger, Handler, Response)
    - dialects/    — target-specific (http, telegram)

This module re-exports for backwards compatibility.

Usage:
    from emergent.wire.axis.surface import capabilities as C
    from emergent.wire.axis.surface import enrichers
    from emergent.wire.axis.surface import transforms
    from emergent.wire.axis.surface.dialects import http, telegram

    endpoint(runner).expose(
        trigger, codec,
        # Transforms
        transforms.Prefix.of("api", "v1"),
        transforms.AsDict(),
        # Enrichers
        enrichers.Timeout(seconds=5.0),
        enrichers.Retry(policy=RetryPolicy.exponential(times=3)),
        # Dialects
        http.Tag.of("users"),
        telegram.EditMessage(),
    )
"""

# Base
from emergent.wire.axis.surface.capabilities._base import SurfaceCapability

# Enrichers (re-export for backwards compatibility)
from emergent.wire.axis.surface.enrichers import (
    ScopeEnricher,
    EnricherNext,
)
from emergent.wire.axis.surface import enrichers as enricher  # C.enricher.Timeout

# Transforms (re-export for backwards compatibility)
from emergent.wire.axis.surface.transforms import (
    TriggerTransform,
    HandlerTransform,
    ResponseTransform,
    URLPath,
    Prefix,
    StripPrefix,
    AsDict,
    AsStr,
)
from emergent.wire.axis.surface.transforms import Timeout  # compile-time handler timeout

# Dialects (re-export for backwards compatibility)
from emergent.wire.axis.surface.dialects.http import (
    Tag,
    BearerAuth,
    ApiKeyAuth,
    OAuth2Auth,
    Summary,
    OperationId,
    Deprecated,
    ResponseStatus,
    ResponseHeader,
    ContentType,
    CORS,
    TrustedHost,
    GZip,
)

# CLI dialect
from emergent.wire.axis.surface.dialects.cli import (
    Help as CLIHelp,
    Description as CLIDescription,
    Epilog as CLIEpilog,
    Hidden as CLIHidden,
)

# Helpers
from emergent.wire.axis.surface.capabilities import _helpers as helpers
from emergent.wire.axis.surface.capabilities._helpers import (
    find_capability,
    find_all_capabilities,
    has_capability,
    merge_capabilities,
    override_capability,
    remove_capability,
    deduplicate_capabilities,
    filter_by_protocol,
)

__all__: list[str] = [
    # Base
    "SurfaceCapability",
    # Enricher protocol
    "ScopeEnricher",
    "EnricherNext",
    # Enricher implementations namespace
    "enricher",
    # Transform protocols
    "TriggerTransform",
    "HandlerTransform",
    "ResponseTransform",
    # Trigger transforms
    "URLPath",
    "Prefix",
    "StripPrefix",
    # Handler transforms
    "Timeout",
    # Response transforms
    "AsDict",
    "AsStr",
    # HTTP dialect (OpenAPI)
    "Tag",
    "BearerAuth",
    "ApiKeyAuth",
    "OAuth2Auth",
    "Summary",
    "OperationId",
    "Deprecated",
    # HTTP route configuration
    "ResponseStatus",
    "ResponseHeader",
    "ContentType",
    # HTTP application-level middleware
    "CORS",
    "TrustedHost",
    "GZip",
    # CLI dialect
    "CLIHelp",
    "CLIDescription",
    "CLIEpilog",
    "CLIHidden",
    # Helpers namespace
    "helpers",
    # Helper functions
    "find_capability",
    "find_all_capabilities",
    "has_capability",
    "merge_capabilities",
    "override_capability",
    "remove_capability",
    "deduplicate_capabilities",
    "filter_by_protocol",
]

# Telegram dialect (optional)
try:
    from emergent.wire.axis.surface.dialects import telegram as tg
    __all__.append("tg")
except ImportError:
    pass
