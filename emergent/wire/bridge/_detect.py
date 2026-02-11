"""Detector protocols — bridgers implement semantic classification.

Core provides protocols. Bridgers provide implementations.
NO heuristics in core. Bridger knows what things mean in their framework.

    from emergent.wire.bridge._detect import (
        BodyDetector,
        DIDetector,
        DecoratorMapper,
        DetectionResult,
    )

    # FastAPI bridger provides:
    class FastAPIDependsDetector:
        def detect(self, param: ParameterShape) -> DIDetection | None:
            if isinstance(param.default, Depends):
                return DIDetection(
                    parameter=param,
                    source=param.default.dependency,
                )
            return None

    # Django bridger provides:
    class DjangoRequestDetector:
        def detect(self, param: ParameterShape) -> DIDetection | None:
            if param.annotation is HttpRequest:
                return DIDetection(parameter=param, source=HttpRequest)
            return None
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
    from emergent.wire.bridge._introspect import (
        DecoratorInfo,
        HandlerShape,
        ParameterShape,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Detection Results — pure data
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class BodyDetection:
    """Result of body parameter detection."""

    parameter: ParameterShape
    body_type: type


@dataclass(frozen=True, slots=True)
class DIDetection:
    """Result of DI parameter detection."""

    parameter: ParameterShape
    source: object  # Depends(func), type, factory, etc.
    to_capability: SurfaceCapability | None = None


@dataclass(frozen=True, slots=True)
class DecoratorMapping:
    """Result of decorator → capability mapping."""

    decorator: DecoratorInfo
    capability: SurfaceCapability


# ═══════════════════════════════════════════════════════════════════════════════
# Detector Protocols — bridgers implement these
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class BodyDetector(Protocol):
    """Protocol for detecting request body parameter.

    Bridger implements this to identify which parameter is the body.

    Example (FastAPI):
        class FastAPIBodyDetector:
            def detect(self, param, shape):
                # Pydantic model without Depends = body
                if is_pydantic(param.annotation) and not isinstance(param.default, Depends):
                    return BodyDetection(param, param.annotation)
                return None
    """

    def detect(
        self,
        param: ParameterShape,
        shape: HandlerShape,
    ) -> BodyDetection | None:
        """Detect if parameter is request body.

        Args:
            param: Parameter to check
            shape: Full handler shape for context

        Returns:
            BodyDetection if this is body, None otherwise
        """
        ...


@runtime_checkable
class DIDetector(Protocol):
    """Protocol for detecting dependency injection.

    Bridger implements this to identify DI patterns.

    Example (FastAPI):
        class FastAPIDependsDetector:
            def detect(self, param, shape):
                if isinstance(param.default, Depends):
                    return DIDetection(param, param.default.dependency)
                return None

    Example (Django):
        class DjangoRequestDetector:
            def detect(self, param, shape):
                if param.annotation.__name__ == "HttpRequest":
                    return DIDetection(param, HttpRequest)
                return None
    """

    def detect(
        self,
        param: ParameterShape,
        shape: HandlerShape,
    ) -> DIDetection | None:
        """Detect if parameter is DI injection.

        Args:
            param: Parameter to check
            shape: Full handler shape for context

        Returns:
            DIDetection if this is DI, None otherwise
        """
        ...


@runtime_checkable
class DecoratorMapper(Protocol):
    """Protocol for mapping decorator → capability.

    Bridger implements this to map framework decorators to wire capabilities.

    Example:
        class DjangoCacheMapper:
            def map(self, decorator, shape):
                if decorator.wrapper_name == "cache_page":
                    return DecoratorMapping(decorator, enricher.Cached(...))
                return None
    """

    def map(
        self,
        decorator: DecoratorInfo,
        shape: HandlerShape,
    ) -> DecoratorMapping | None:
        """Map decorator to capability.

        Args:
            decorator: Decorator info
            shape: Full handler shape for context

        Returns:
            DecoratorMapping if mapped, None otherwise
        """
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Detection Runner — applies detectors
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class DetectionResult:
    """Combined detection results for a handler."""

    body: BodyDetection | None
    di_params: tuple[DIDetection, ...]
    decorator_capabilities: tuple[DecoratorMapping, ...]


def run_detectors(
    shape: HandlerShape,
    *,
    body_detectors: tuple[BodyDetector, ...] = (),
    di_detectors: tuple[DIDetector, ...] = (),
    decorator_mappers: tuple[DecoratorMapper, ...] = (),
) -> DetectionResult:
    """Run all detectors on handler shape.

    Detectors are provided by bridger. Core just runs them.

    Args:
        shape: Handler shape to analyze
        body_detectors: Bridger-provided body detectors
        di_detectors: Bridger-provided DI detectors
        decorator_mappers: Bridger-provided decorator mappers

    Returns:
        Combined detection results
    """
    # Find body parameter
    body: BodyDetection | None = None
    for param in shape.parameters.values():
        for detector in body_detectors:
            result = detector.detect(param, shape)
            if result is not None:
                body = result
                break
        if body is not None:
            break

    # Find DI parameters
    di_params: list[DIDetection] = []
    for param in shape.parameters.values():
        for detector in di_detectors:
            result = detector.detect(param, shape)
            if result is not None:
                di_params.append(result)
                break  # One detection per param

    # Map decorators
    decorator_capabilities: list[DecoratorMapping] = []
    for decorator in shape.decorators:
        for mapper in decorator_mappers:
            result = mapper.map(decorator, shape)
            if result is not None:
                decorator_capabilities.append(result)
                break  # One mapping per decorator

    return DetectionResult(
        body=body,
        di_params=tuple(di_params),
        decorator_capabilities=tuple(decorator_capabilities),
    )


__all__ = (
    # Results
    "BodyDetection",
    "DIDetection",
    "DecoratorMapping",
    "DetectionResult",
    # Protocols
    "BodyDetector",
    "DIDetector",
    "DecoratorMapper",
    # Runner
    "run_detectors",
)
