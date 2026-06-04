"""Unified extraction — build_extracted() does the heavy lifting.

Bridger provides:
- route_data: RouteData
- handler: callable
- detectors: bridger-specific semantic classifiers
- to_codec: optional codec constructor

Core does:
- Handler introspection
- Run bridger's detectors
- Build Extracted with all info

    from emergent.wire.bridge._unified import build_extracted

    # In bridger:
    for route in find_routes(app):
        extracted = build_extracted(
            handler=route.endpoint,
            route_data=HTTPRouteData(method=route.method, path=route.path),
            body_detectors=(FastAPIBodyDetector(),),
            di_detectors=(FastAPIDependsDetector(),),
        )
        yield extracted
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING, Callable, Sequence

from emergent.wire.bridge._introspect import HandlerShape, analyze_handler
from emergent.wire.bridge._detect import (
    BodyDetector,
    DIDetector,
    DecoratorMapper,
    DetectionResult,
    run_detectors,
)
from emergent.wire.bridge._types import Extracted, RouteData

if TYPE_CHECKING:
    from emergent.wire.axis.surface.capabilities._base import SurfaceCapability


# ═══════════════════════════════════════════════════════════════════════════════
# Extended Extracted — with shape and detection info
# ═══════════════════════════════════════════════════════════════════════════════


type MetadataAny = dict[str, Any]
type MetadataObj = dict[str, object]


def _empty_metadata() -> MetadataAny:
    return {}


def _empty_caps() -> tuple[SurfaceCapability, ...]:
    return ()


@dataclass(frozen=True, slots=True)
class ExtractedWithShape[R: RouteData]:
    """Extracted handler with full introspection and detection results.

    Extends Extracted with:
    - shape: Full handler introspection
    - detection: Semantic detection results
    - inferred_capabilities: From decorator mappings
    """

    # From Extracted
    route: R
    handler: Callable[..., object]
    name: str | None = None
    description: str | None = None
    deprecated: bool = False
    metadata: MetadataObj = field(default_factory=_empty_metadata)

    # Extended
    shape: HandlerShape | None = None
    detection: DetectionResult | None = None
    inferred_capabilities: tuple[SurfaceCapability, ...] = field(
        default_factory=_empty_caps
    )

    def to_extracted(self) -> Extracted[R]:
        """Convert to base Extracted."""
        return Extracted(
            route=self.route,
            handler=self.handler,
            name=self.name,
            description=self.description,
            deprecated=self.deprecated,
            metadata=self.metadata,
        )

    @property
    def body_type(self) -> type | None:
        """Get detected body type if any."""
        if self.detection is not None and self.detection.body is not None:
            return self.detection.body.body_type
        return None

    @property
    def response_type(self) -> type | None:
        """Get return type from shape."""
        if self.shape is not None:
            return self.shape.return_type
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# build_extracted — main function
# ═══════════════════════════════════════════════════════════════════════════════


def build_extracted[R: RouteData](
    handler: Any,
    route_data: R,
    *,
    # Metadata
    name: str | None = None,
    description: str | None = None,
    deprecated: bool = False,
    metadata: MetadataAny | None = None,
    # Bridger-provided detectors
    body_detectors: Sequence[BodyDetector] = (),
    di_detectors: Sequence[DIDetector] = (),
    decorator_mappers: Sequence[DecoratorMapper] = (),
) -> ExtractedWithShape[R]:
    """Build Extracted with full introspection and detection.

    Core does the heavy lifting:
    1. analyze_handler() — introspect handler
    2. run_detectors() — run bridger's semantic classifiers
    3. Bundle everything into ExtractedWithShape

    Bridger provides:
    - handler: The raw handler callable
    - route_data: Framework-specific route info
    - detectors: Semantic classifiers for body, DI, decorators

    Args:
        handler: Raw handler (will be unwrapped and analyzed)
        route_data: RouteData for this handler
        name: Override name (default: from handler)
        description: Override description (default: from docstring)
        deprecated: Deprecation flag
        metadata: Additional metadata dict
        body_detectors: Bridger's body parameter detectors
        di_detectors: Bridger's DI parameter detectors
        decorator_mappers: Bridger's decorator → capability mappers

    Returns:
        ExtractedWithShape with full analysis
    """
    # 1. Introspect handler
    shape = analyze_handler(handler)

    # 2. Run bridger's detectors
    detection = run_detectors(
        shape,
        body_detectors=tuple(body_detectors),
        di_detectors=tuple(di_detectors),
        decorator_mappers=tuple(decorator_mappers),
    )

    # 3. Collect capabilities from decorator mappings
    inferred_caps = tuple(
        mapping.capability for mapping in detection.decorator_capabilities
    )

    # 4. Build result
    return ExtractedWithShape(
        route=route_data,
        handler=shape.handler,  # Use unwrapped handler
        name=name or shape.name,
        description=description or shape.handler.__doc__,
        deprecated=deprecated,
        metadata=metadata or {},
        shape=shape,
        detection=detection,
        inferred_capabilities=inferred_caps,
    )


__all__ = (
    "ExtractedWithShape",
    "build_extracted",
)
