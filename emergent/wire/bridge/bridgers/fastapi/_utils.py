"""FastAPI utilities — helper functions for FastAPI inspection.

Provides:
- Depends() inspection utilities
- FastAPI type protocols

DESIGN: Pure functions, no hidden state.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

type ExceptionHandlerMap = Mapping[Any, Callable[..., Any]]


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI Protocols (for type safety without importing fastapi)
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class FastAPIRouterProtocol(Protocol):
    """Protocol for FastAPI router (holds lifecycle handlers)."""

    @property
    def on_startup(self) -> list[Callable[[], Any]]: ...

    @property
    def on_shutdown(self) -> list[Callable[[], Any]]: ...


@runtime_checkable
class FastAPIAppProtocol(Protocol):
    """Protocol for FastAPI app."""

    @property
    def routes(self) -> Sequence[Any]: ...

    @property
    def router(self) -> FastAPIRouterProtocol: ...

    @property
    def exception_handlers(self) -> ExceptionHandlerMap: ...

    @property
    def user_middleware(self) -> Sequence[Any]: ...


# ═══════════════════════════════════════════════════════════════════════════════
# Depends() Utilities
# ═══════════════════════════════════════════════════════════════════════════════


def is_depends(obj: Any) -> bool:
    """Check if object is FastAPI Depends instance."""
    return type(obj).__name__ == "Depends"


@runtime_checkable
class _HasDependency(Protocol):
    """A FastAPI ``Depends`` instance exposing its ``dependency`` callable."""

    @property
    def dependency(self) -> Any: ...


def get_depends_func(depends: Any) -> Any | None:
    """Get the dependency function from Depends instance."""
    return depends.dependency if isinstance(depends, _HasDependency) else None


def find_depends_param(handler: Any, depends_func: Any) -> str | None:
    """Find parameter name that uses given Depends function.

    Args:
        handler: Function to inspect.
        depends_func: Dependency function to find.

    Returns:
        Parameter name if found, None otherwise.

    Example::

        def my_handler(db: Session = Depends(get_db)):
            ...

        param_name = find_depends_param(my_handler, get_db)
        # Returns: "db"
    """
    if not callable(handler):
        return None

    try:
        sig = inspect.signature(handler)
        for name, param in sig.parameters.items():
            default = param.default
            if is_depends(default) and get_depends_func(default) is depends_func:
                return name
    except (ValueError, TypeError):
        pass

    return None


def get_all_depends(handler: Callable[..., Any]) -> list[tuple[str, Any]]:
    """Get all Depends() parameters from handler.

    Returns list of (param_name, dependency_function) tuples.

    Example::

        def my_handler(
            db: Session = Depends(get_db),
            user: User = Depends(get_current_user),
        ):
            ...

        deps = get_all_depends(my_handler)
        # Returns: [("db", get_db), ("user", get_current_user)]
    """
    if not callable(handler):
        return []

    result: list[tuple[str, Any]] = []
    try:
        sig = inspect.signature(handler)
        for name, param in sig.parameters.items():
            if is_depends(param.default):
                dep_func = get_depends_func(param.default)
                if dep_func is not None:
                    result.append((name, dep_func))
    except (ValueError, TypeError):
        pass

    return result


__all__ = (
    # Protocols
    "FastAPIAppProtocol",
    "FastAPIRouterProtocol",
    # Depends utilities
    "is_depends",
    "get_depends_func",
    "find_depends_param",
    "get_all_depends",
)
