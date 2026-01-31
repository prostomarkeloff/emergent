"""Surface capability base and protocols."""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable


T = TypeVar("T")


class SurfaceCapability:
    """Base for all surface capabilities.

    Surface capabilities modify the Trigger × Codec space at compile time.
    Compilers check isinstance() and call appropriate methods.
    """

    pass


@runtime_checkable
class TriggerTransform(Protocol[T]):
    """Capability that transforms a trigger at compile time."""

    def apply_trigger(self, trigger: T) -> T:
        """Return modified trigger."""
        ...


@runtime_checkable
class HandlerTransform(Protocol):
    """Capability that wraps handler at compile time."""

    def apply_handler[T](self, handler: T) -> T:
        """Return wrapped handler."""
        ...


@runtime_checkable
class ResponseTransform(Protocol):
    """Capability that transforms response at runtime."""

    def apply_response[T](self, response: T) -> T:
        """Return transformed response."""
        ...


__all__ = (
    "SurfaceCapability",
    "TriggerTransform",
    "HandlerTransform",
    "ResponseTransform",
)
