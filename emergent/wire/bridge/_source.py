"""Source protocol — common interface for all bridge sources.

Like compile targets follow the same pattern, bridge sources
implement this protocol for unified extraction.

    from emergent.wire.bridge._source import SourceProtocol

    class MySource(SourceProtocol[MyTriggerData]):
        def scan_http(self) -> Iterable[tuple[MyTriggerData, Callable]]:
            ...
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal, Protocol, TypeVar, runtime_checkable

from emergent.wire.bridge._core import HandlerInspector, TriggerBuilder


# ═══════════════════════════════════════════════════════════════════════════════
# Common Data Types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class LifecycleData:
    """Common lifecycle trigger data."""

    phase: Literal["startup", "shutdown"]
    order: int = 0


@dataclass(frozen=True, slots=True)
class ExceptionData:
    """Common exception trigger data."""

    exception_type: type[Exception]


@dataclass(frozen=True, slots=True)
class WebSocketData:
    """Common websocket trigger data."""

    path: str
    name: str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Source Protocol
# ═══════════════════════════════════════════════════════════════════════════════


T = TypeVar("T")  # Source-specific HTTP trigger data


@runtime_checkable
class SourceProtocol(Protocol[T]):
    """Protocol for bridge sources.

    All sources implement this for unified extraction.
    T is the source-specific HTTP trigger data type.

    Example implementation:

        @dataclass
        class FastAPISource:
            app: FastAPI

            def scan_http(self) -> Iterable[tuple[FastAPITriggerData, Callable]]:
                for route in self.app.routes:
                    if isinstance(route, APIRoute):
                        yield FastAPITriggerData(...), route.endpoint

            def scan_lifecycle(self) -> Iterable[tuple[LifecycleData, Callable]]:
                for i, handler in enumerate(self.app.router.on_startup):
                    yield LifecycleData("startup", i), handler
                ...

            def get_inspector(self) -> HandlerInspector:
                return FastAPIInspector()

            def get_trigger_builder(self) -> TriggerBuilder[FastAPITriggerData]:
                return FastAPITriggerBuilder()
    """

    def scan_http(self) -> Iterable[tuple[T, Callable[..., object]]]:
        """Scan HTTP routes.

        Yields:
            (trigger_data, handler) pairs for each HTTP route
        """
        ...

    def scan_lifecycle(self) -> Iterable[tuple[LifecycleData, Callable[..., object]]]:
        """Scan lifecycle handlers.

        Yields:
            (LifecycleData, handler) pairs for startup/shutdown handlers
        """
        ...

    def scan_websockets(self) -> Iterable[tuple[WebSocketData, Callable[..., object]]]:
        """Scan websocket handlers.

        Yields:
            (WebSocketData, handler) pairs for each websocket endpoint
        """
        ...

    def scan_exceptions(self) -> Iterable[tuple[ExceptionData, Callable[..., object]]]:
        """Scan exception handlers.

        Yields:
            (ExceptionData, handler) pairs for each exception handler
        """
        ...

    def get_inspector(self) -> HandlerInspector:
        """Get handler inspector for this source.

        Returns:
            HandlerInspector for extracting types from handlers
        """
        ...

    def get_trigger_builder(self) -> TriggerBuilder[T]:
        """Get trigger builder for this source.

        Returns:
            TriggerBuilder for converting trigger data to wire Trigger
        """
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Source Info
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """Metadata about a source."""

    name: str  # e.g., "fastapi", "django", "flask"
    version: str | None  # Framework version if detected
    supports_http: bool = True
    supports_websocket: bool = False
    supports_lifecycle: bool = False
    supports_exceptions: bool = False


@runtime_checkable
class SourceWithInfo(Protocol):
    """Extended source protocol with metadata."""

    def get_info(self) -> SourceInfo:
        """Get source metadata."""
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Source Utilities
# ═══════════════════════════════════════════════════════════════════════════════


def count_extractable[T](source: SourceProtocol[T]) -> dict[str, int]:
    """Count extractable items from a source.

    Args:
        source: Source to count from

    Returns:
        Dict with counts: {"http": N, "lifecycle": N, ...}
    """
    return {
        "http": sum(1 for _ in source.scan_http()),
        "lifecycle": sum(1 for _ in source.scan_lifecycle()),
        "websocket": sum(1 for _ in source.scan_websockets()),
        "exception": sum(1 for _ in source.scan_exceptions()),
    }


def get_all_handlers[T](
    source: SourceProtocol[T],
) -> list[Callable[..., object]]:
    """Get all handlers from a source.

    Args:
        source: Source to extract from

    Returns:
        List of all handler callables
    """
    handlers: list[Callable[..., object]] = []

    for _, handler in source.scan_http():
        handlers.append(handler)

    for _, handler in source.scan_lifecycle():
        handlers.append(handler)

    for _, handler in source.scan_websockets():
        handlers.append(handler)

    for _, handler in source.scan_exceptions():
        handlers.append(handler)

    return handlers


__all__ = (
    # Data types
    "LifecycleData",
    "ExceptionData",
    "WebSocketData",
    # Protocols
    "SourceProtocol",
    "SourceInfo",
    "SourceWithInfo",
    # Utilities
    "count_extractable",
    "get_all_handlers",
)
