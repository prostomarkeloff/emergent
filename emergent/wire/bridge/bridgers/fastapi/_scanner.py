"""FastAPI scanner — inspect FastAPI apps and handlers.

Provides:
- FastAPIAppProtocol: type-safe protocol for FastAPI app
- FastAPIInspector: extract types and metadata from handlers
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, get_type_hints, runtime_checkable

from emergent.wire.bridge._core import AnyHandler


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI Protocols (for type safety without importing fastapi)
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class FastAPIRouterProtocol(Protocol):
    """Protocol for FastAPI router (holds lifecycle handlers)."""

    @property
    def on_startup(self) -> list[Callable[[], object]]: ...

    @property
    def on_shutdown(self) -> list[Callable[[], object]]: ...


@runtime_checkable
class FastAPIAppProtocol(Protocol):
    """Protocol for FastAPI app."""

    @property
    def routes(self) -> Sequence[object]: ...

    @property
    def router(self) -> FastAPIRouterProtocol: ...

    @property
    def exception_handlers(self) -> Mapping[object, Callable[..., object]]: ...

    @property
    def user_middleware(self) -> Sequence[object]: ...


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI Inspector
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FastAPIInspector:
    """HandlerInspector for FastAPI endpoints.

    Extracts types and FastAPI-specific metadata from handlers.
    """

    def request_type[**P, R](self, handler: AnyHandler[P, R]) -> type | None:
        """Extract first typed parameter as request type."""
        if not callable(handler):
            return None

        try:
            hints = get_type_hints(handler)
        except Exception:
            return None

        sig = inspect.signature(handler)
        for name in sig.parameters:
            param_type = hints.get(name)
            if param_type is None:
                continue
            if isinstance(param_type, type):
                return param_type

        return None

    def response_type[**P, R](self, handler: AnyHandler[P, R]) -> type | None:
        """Extract response type from return annotation."""
        if not callable(handler):
            return None

        try:
            hints = get_type_hints(handler)
            ret = hints.get("return")
            if isinstance(ret, type):
                return ret
            return None
        except Exception:
            return None

    def get_depends_params[**P, R](
        self, handler: AnyHandler[P, R]
    ) -> list[tuple[str, object]]:
        """Get all Depends() parameters from handler.

        Returns list of (param_name, dependency_function) tuples.
        """
        if not callable(handler):
            return []

        result: list[tuple[str, object]] = []
        try:
            sig = inspect.signature(handler)
            for name, param in sig.parameters.items():
                if _is_depends(param.default):
                    dep_func = getattr(param.default, "dependency", None)
                    if dep_func is not None:
                        result.append((name, dep_func))
        except (ValueError, TypeError):
            pass

        return result

    def inspect_extra[**P, R](self, handler: AnyHandler[P, R]) -> dict[str, object]:
        """Extract FastAPI-specific metadata."""
        return {
            "depends_params": self.get_depends_params(handler),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI-Specific Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _is_depends(obj: object) -> bool:
    """Check if object is FastAPI Depends instance."""
    return type(obj).__name__ == "Depends"


def _get_depends_func(depends: object) -> object | None:
    """Get the dependency function from Depends instance."""
    return getattr(depends, "dependency", None)


def _find_depends_param(handler: object, depends_func: object) -> str | None:
    """Find parameter name that uses given Depends function."""
    if not callable(handler):
        return None

    try:
        sig = inspect.signature(handler)
        for name, param in sig.parameters.items():
            default = param.default
            if _is_depends(default) and _get_depends_func(default) is depends_func:
                return name
    except (ValueError, TypeError):
        pass

    return None


# Public aliases
find_depends_param = _find_depends_param
is_depends = _is_depends
get_depends_func = _get_depends_func


__all__ = (
    # Protocols
    "FastAPIAppProtocol",
    "FastAPIRouterProtocol",
    # Inspector
    "FastAPIInspector",
    # Helpers (public)
    "find_depends_param",
    "is_depends",
    "get_depends_func",
)
