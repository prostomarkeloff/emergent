"""Scanning for routes — symmetric to surface._scan.

    from emergent.wire.bridge import extract

    # Extract all routes
    routes = extract(fastapi_app)

    # Extract specific route type
    http_routes = extract(fastapi_app, HTTPRouteData)

    # Custom extractors
    routes = extract(app, extractors=[MyExtractor()])

Like surface.scan() — parameterized extraction by type.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, overload

from emergent.wire.bridge._extractor import Extractor, compose_extractors
from emergent.wire.bridge._types import Extracted, RouteData


# ═══════════════════════════════════════════════════════════════════════════════
# Extract Function — like scan() in surface
# ═══════════════════════════════════════════════════════════════════════════════


@overload
def extract(
    source: Any,
    route_type: None = None,
    *,
    extractors: Sequence[Extractor[RouteData]] | None = None,
) -> list[Extracted[RouteData]]: ...


@overload
def extract[R: RouteData](
    source: Any,
    route_type: type[R],
    *,
    extractors: Sequence[Extractor[RouteData]] | None = None,
) -> list[Extracted[R]]: ...


def extract[R: RouteData](
    source: Any,
    route_type: type[R] | None = None,
    *,
    extractors: Sequence[Extractor[RouteData]] | None = None,
) -> list[Extracted[R]]:
    """Extract handlers from framework source.

    Symmetric to surface.scan():
    - scan(app, TriggerType) → [(Trigger, Handler)]
    - extract(source, RouteType) → [Extracted]

    If no extractors provided, tries to detect from source type.
    If route_type provided, filters to only matching routes.

    Args:
        source: Framework application/router to extract from.
        route_type: Optional route type to filter by.
        extractors: Optional custom extractors (auto-detected if None).

    Returns:
        List of Extracted bundles matching route_type (or all if None).

    Example::

        from emergent.wire.bridge import extract
        from emergent.wire.bridge.bridgers.fastapi import HTTPRouteData

        # All routes
        all_routes = extract(fastapi_app)

        # Only HTTP routes
        http_routes = extract(fastapi_app, HTTPRouteData)

        # Custom extractors
        routes = extract(app, extractors=[MyExtractor()])
    """
    # Get extractors — provided or auto-detect
    if extractors is not None:
        combined = compose_extractors(*extractors)
    else:
        combined = _detect_extractors(source)

    if combined is None:
        msg = f"No extractors found for source type {type(source).__name__}"
        raise ValueError(msg)

    if not combined.can_extract(source):
        return []

    # Extract all routes
    results: list[Extracted[R]] = []
    for extracted in combined.extract(source):
        # Filter by route_type if specified
        if route_type is not None:
            if not isinstance(extracted.route, route_type):
                continue
        results.append(extracted)

    return results


def _detect_extractors(source: Any) -> Extractor[RouteData] | None:
    """Auto-detect extractors based on source type.

    Uses BridgeRegistry for open-world framework detection.
    """
    from emergent.wire.bridge._registry import get_default_registry

    bridger = get_default_registry().detect(source)
    if bridger is not None:
        return bridger.extractor
    return None


__all__ = ("extract",)
