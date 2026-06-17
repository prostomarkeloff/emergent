"""Extractor protocol — composable route extraction.

Like Inspector in schema axis — composable functions that extract routes.

    from emergent.wire.bridge import Extractor, compose_extractors

    # Compose multiple extractors
    combined = compose_extractors(
        HTTPRouteExtractor(),
        WebSocketExtractor(),
        LifespanExtractor(),
    )

    # Use in extract()
    routes = extract(app, extractors=[combined])
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from emergent.wire.bridge._types import Extracted, RouteData


# ═══════════════════════════════════════════════════════════════════════════════
# Extractor Protocol
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class Extractor[R_co: RouteData](Protocol):
    """Protocol for extracting routes from framework.

    Composable like Inspector in schema axis.
    Each extractor handles one route kind or source type.

    Type parameter R_co is covariant — concrete route types
    are subtypes of RouteData.

    Implement for each route kind:
    - HTTPRouteExtractor
    - WebSocketExtractor
    - LifespanExtractor
    - etc.
    """

    def can_extract(self, source: Any) -> bool:
        """Check if this extractor can handle this source.

        Return True if source has the expected structure.
        """
        ...

    def extract(self, source: Any) -> Iterator[Extracted[R_co]]:
        """Yield extracted handlers from source.

        Each Extracted contains route data + handler + metadata.
        """
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Composition
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ComposedExtractor:
    """Composed extractor — runs all applicable extractors."""

    extractors: tuple[Extractor[RouteData], ...]

    def can_extract(self, source: Any) -> bool:
        """True if any inner extractor can handle source."""
        return any(e.can_extract(source) for e in self.extractors)

    def extract(self, source: Any) -> Iterator[Extracted[RouteData]]:
        """Yield from all applicable extractors."""
        for extractor in self.extractors:
            if extractor.can_extract(source):
                yield from extractor.extract(source)


def compose_extractors(*extractors: Extractor[RouteData]) -> Extractor[RouteData]:
    """Compose extractors — all applicable ones run.

    Unlike first_match (for inspectors), this runs ALL extractors
    that can handle the source. Different extractors handle different
    route kinds (HTTP, WebSocket, lifecycle, etc.).

    Example::

        combined = compose_extractors(
            HTTPRouteExtractor(),
            WebSocketExtractor(),
            LifespanExtractor(),
        )

        for extracted in combined.extract(app):
            print(extracted.route)
    """
    return ComposedExtractor(extractors=extractors)


def first_extractor(*extractors: Extractor[RouteData]) -> Extractor[RouteData]:
    """First extractor that can handle source wins.

    Use when extractors are alternatives for the same route kind,
    not different route kinds.

    Example::

        # Try modern lifespan first, fall back to legacy
        lifespan = first_extractor(
            ModernLifespanExtractor(),
            LegacyLifespanExtractor(),
        )
    """

    @dataclass(frozen=True, slots=True)
    class FirstExtractor:
        extractors: tuple[Extractor[RouteData], ...]

        def can_extract(self, source: Any) -> bool:
            return any(e.can_extract(source) for e in self.extractors)

        def extract(self, source: Any) -> Iterator[Extracted[RouteData]]:
            for extractor in self.extractors:
                if extractor.can_extract(source):
                    yield from extractor.extract(source)
                    return  # Stop after first match

    return FirstExtractor(extractors=extractors)


def filter_extractor(
    inner: Extractor[RouteData],
    predicate: Callable[[Extracted[RouteData]], bool],
) -> Extractor[RouteData]:
    """Filter extracted routes by predicate.

    Example::

        # Only non-deprecated routes
        filtered = filter_extractor(
            HTTPRouteExtractor(),
            lambda e: not e.deprecated,
        )
    """

    @dataclass(frozen=True, slots=True)
    class FilteredExtractor:
        inner: Extractor[RouteData]
        predicate: Callable[[Extracted[RouteData]], bool]

        def can_extract(self, source: Any) -> bool:
            return self.inner.can_extract(source)

        def extract(self, source: Any) -> Iterator[Extracted[RouteData]]:
            for extracted in self.inner.extract(source):
                if self.predicate(extracted):
                    yield extracted

    return FilteredExtractor(inner=inner, predicate=predicate)


__all__ = (
    "Extractor",
    "ComposedExtractor",
    "compose_extractors",
    "first_extractor",
    "filter_extractor",
)
