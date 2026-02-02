"""Bridge core — protocols and universal types.

Like compile/_core.py: NO framework-specific types, NO heuristics.
All FastAPI/Django/aiogram specifics in sources/.

Bridge is symmetric to compile:
- compile: Application → Framework
- bridge:  Framework → ExtractedHandlers → Application
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ParamSpec, Protocol, TypeVar, runtime_checkable

from kungfu import Result

if TYPE_CHECKING:
    from emergent.wire.axis.surface._types import Trigger
    from emergent.wire.axis.surface.capabilities._base import SurfaceCapability


# Type variables
R = TypeVar("R")
R_co = TypeVar("R_co", covariant=True)
P = ParamSpec("P")

# Handler type aliases — generic over parameters P and return type R
type SyncHandler[**P, R] = Callable[P, R]
type AsyncHandler[**P, R] = Callable[P, Awaitable[R]]
type AnyHandler[**P, R] = SyncHandler[P, R] | AsyncHandler[P, R]


# ═══════════════════════════════════════════════════════════════════════════════
# Protocols — framework-agnostic
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class HandlerInspector(Protocol):
    """Protocol for extracting types from handler.

    Each source provides implementation for its framework.
    Like Axes.schema in compile — framework-specific introspection.
    """

    def request_type[**P, R](self, handler: AnyHandler[P, R]) -> type | None:
        """Extract request/input type from handler signature."""
        ...

    def response_type[**P, R](self, handler: AnyHandler[P, R]) -> type | None:
        """Extract response/output type from handler signature."""
        ...


@runtime_checkable
class TriggerBuilder[T](Protocol):
    """Protocol for building wire Trigger from extracted data.

    T — source-specific trigger data type (defined in sources/).
    """

    def build(self, data: T) -> Trigger:
        """Convert source-specific data to wire Trigger."""
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Bridge Axes — Extraction Context (like compile.Axes)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class BridgeAxes:
    """Extraction context — like compile.Axes but for reverse direction.

    Passed explicitly to all extraction functions. No global state.
    """

    inspector: HandlerInspector


# ═══════════════════════════════════════════════════════════════════════════════
# Extracted Handler — Universal Result
# ═══════════════════════════════════════════════════════════════════════════════


def _empty_surface_caps() -> tuple[SurfaceCapability, ...]:
    return ()


@dataclass(frozen=True, slots=True)
class ExtractedHandler[T, **P, R]:
    """Universal extracted handler.

    T — source-specific trigger data (framework defines in sources/).
    P — handler parameter spec.
    R — handler return type.

    Attributes:
        trigger_data: Source-specific trigger data (generic).
        handler: Original handler callable (always async after extraction).
        codec: Wire codec (created by capability). None = skip handler.
        op_type: Op type to register (if codec needs runner).
        op_handler: Handler for op_type (if codec needs runner).
        name: Handler name.
        description: Handler description.
        deprecated: Deprecation flag.
        surface_capabilities: Accumulated surface capabilities.
    """

    trigger_data: T
    handler: AsyncHandler[P, R]
    # Codec + runner setup — created by capabilities
    codec: object | None = None
    op_type: type | None = None
    op_handler: Callable[..., Awaitable[Result[object, object]]] | None = None
    # Metadata
    name: str | None = None
    description: str | None = None
    deprecated: bool = False
    surface_capabilities: tuple[SurfaceCapability, ...] = field(
        default_factory=_empty_surface_caps
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Bridge Result
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class BridgeResult[T, **P, R]:
    """Extraction result — collection of handlers.

    T — source-specific trigger data type.
    P — handler parameter spec.
    R — handler return type.

    Attributes:
        handlers: Extracted handler specifications.
        source: Source framework identifier.
        version: Framework version if detected.
    """

    handlers: tuple[ExtractedHandler[T, P, R], ...]
    source: str
    version: str | None = None

    def __len__(self) -> int:
        return len(self.handlers)

    def __iter__(self) -> Iterator[ExtractedHandler[T, P, R]]:
        return iter(self.handlers)

    def filter(
        self,
        predicate: Callable[[ExtractedHandler[T, P, R]], bool],
    ) -> BridgeResult[T, P, R]:
        """Filter handlers by predicate."""
        return BridgeResult(
            handlers=tuple(h for h in self.handlers if predicate(h)),
            source=self.source,
            version=self.version,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Universal Extraction Loop — like scan_all_codecs
# ═══════════════════════════════════════════════════════════════════════════════


def extract_all[T, **P, R, S](
    source: S,
    scanner: Callable[[S], tuple[tuple[T, AnyHandler[P, R]], ...]],
    register: Callable[[T, AnyHandler[P, R]], ExtractedHandler[T, P, R] | None],
) -> tuple[ExtractedHandler[T, P, R], ...]:
    """Universal extraction loop — like scan_all_codecs but reverse.

    Args:
        source: Framework app/router to scan.
        scanner: Function to extract (trigger_data, handler) pairs.
        register: Function to process each pair → ExtractedHandler or None.

    Returns:
        Tuple of extracted handlers (skipped handlers excluded).
    """
    results: list[ExtractedHandler[T, P, R]] = []
    for trigger_data, handler in scanner(source):
        extracted = register(trigger_data, handler)
        if extracted is not None:
            results.append(extracted)
    return tuple(results)


__all__ = (
    # Handler types
    "SyncHandler",
    "AsyncHandler",
    "AnyHandler",
    # Protocols
    "HandlerInspector",
    "TriggerBuilder",
    # Axes
    "BridgeAxes",
    # Core types
    "ExtractedHandler",
    "BridgeResult",
    # Extraction
    "extract_all",
)
