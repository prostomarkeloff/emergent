"""Transform protocols — compile-time and runtime transforms."""

from __future__ import annotations

from typing import Any, Protocol, TypeVar, runtime_checkable, TYPE_CHECKING

from emergent.wire.axis.surface.capabilities._base import SurfaceCapability

if TYPE_CHECKING:
    from emergent.wire.axis._capability import HandlerRuntimeContext


T = TypeVar("T")


@runtime_checkable
class TriggerTransform(SurfaceCapability, Protocol[T]):
    """Capability that transforms a trigger at compile time.

    Implementations must define:
        def apply_trigger(self, trigger: T) -> T: ...
    """

    def apply_trigger(self, trigger: T) -> T:
        """Return modified trigger."""
        ...


@runtime_checkable
class HandlerTransform(SurfaceCapability, Protocol):
    """Marker for capabilities that wrap handler at compile time.

    Implementations define their own apply_handler signature based on
    the handler type they transform.
    """

    ...


@runtime_checkable
class ResponseTransform(SurfaceCapability, Protocol):
    """Capability that transforms response at runtime.

    Implementations must define:
        def apply_response(self, response: T) -> R: ...

    Protocol uses Any for isinstance checks compatibility.
    Implementations can use more specific types.
    """

    def apply_response(self, response: Any) -> Any:
        """Return transformed response."""
        ...

    def compile_handler_runtime(self, ctx: "HandlerRuntimeContext") -> "HandlerRuntimeContext":
        """Default: add self to response_transforms tuple."""
        from dataclasses import replace
        return replace(ctx, response_transforms=(*ctx.response_transforms, self))


__all__ = (
    "TriggerTransform",
    "HandlerTransform",
    "ResponseTransform",
)
