"""Trigger transform capabilities."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from ._base import TriggerTransform

if TYPE_CHECKING:
    from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger


@dataclass(frozen=True, slots=True)
class URLPath:
    """Typed URL path using PurePosixPath semantics.

    Usage:
        path = URLPath.of("api", "v1")  # /api/v1
        path = URLPath.root() / "api" / "v1"  # /api/v1
        full = path / "users"  # /api/v1/users
    """

    _path: PurePosixPath

    def __post_init__(self) -> None:
        # Validate: must be absolute
        if not self._path.is_absolute():
            object.__setattr__(self, "_path", PurePosixPath("/") / self._path)

    @classmethod
    def of(cls, *segments: str) -> URLPath:
        """Create path from segments: URLPath.of("api", "v1") → /api/v1"""
        return cls(PurePosixPath("/").joinpath(*segments))

    @classmethod
    def root(cls) -> URLPath:
        """Root path: /"""
        return cls(PurePosixPath("/"))

    def __truediv__(self, segment: str) -> URLPath:
        """Append segment: path / "users" → /api/v1/users"""
        return URLPath(self._path / segment)

    def join(self, other: str) -> str:
        """Join with another path string, preserving other's leading slash behavior."""
        if other.startswith("/"):
            return str(self._path) + other
        return str(self._path / other)

    def __str__(self) -> str:
        return str(self._path)


@dataclass(frozen=True, slots=True)
class Prefix(TriggerTransform["HTTPRouteTrigger"]):
    """Add path prefix to HTTP trigger.

    Usage:
        Prefix.of("api", "v1")  # adds /api/v1 prefix
        Prefix(URLPath.of("api", "v1"))
    """

    path: URLPath

    @classmethod
    def of(cls, *segments: str) -> Prefix:
        """Create prefix from segments: Prefix.of("api", "v1")"""
        return cls(URLPath.of(*segments))

    def apply_trigger(self, trigger: "HTTPRouteTrigger") -> "HTTPRouteTrigger":
        """Prepend prefix to trigger path."""
        new_path = self.path.join(trigger.path)
        return replace(trigger, path=new_path)


@dataclass(frozen=True, slots=True)
class StripPrefix(TriggerTransform["HTTPRouteTrigger"]):
    """Remove path prefix from HTTP trigger (for nested routers).

    Usage:
        StripPrefix.of("internal")  # removes /internal prefix
    """

    path: URLPath

    @classmethod
    def of(cls, *segments: str) -> StripPrefix:
        """Create strip prefix from segments."""
        return cls(URLPath.of(*segments))

    def apply_trigger(self, trigger: "HTTPRouteTrigger") -> "HTTPRouteTrigger":
        """Strip prefix from trigger path if present."""
        prefix_str = str(self.path)
        if trigger.path.startswith(prefix_str):
            new_path = trigger.path[len(prefix_str):] or "/"
            return replace(trigger, path=new_path)
        return trigger


__all__ = (
    "URLPath",
    "Prefix",
    "StripPrefix",
)
