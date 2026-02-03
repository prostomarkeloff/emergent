"""FastAPI-specific bridge capabilities.

These capabilities know about FastAPI patterns like Depends(), route decorators, etc.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field

from emergent.wire.bridge._capabilities import (
    AnyHandler,
    AsyncHandler,
    BridgeCapability,
    call_handler,
    ensure_async,
)
from emergent.wire.bridge.bridgers.fastapi._scanner import find_depends_param


# ═══════════════════════════════════════════════════════════════════════════════
# Default Factories
# ═══════════════════════════════════════════════════════════════════════════════


def _empty_depends_map() -> dict[Callable[..., object], Callable[[], object]]:
    return {}


def _empty_scope_map() -> dict[Callable[..., object], type]:
    return {}


# ═══════════════════════════════════════════════════════════════════════════════
# MapDepends — Handle FastAPI Depends() parameters
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class MapDepends(BridgeCapability):
    """Map FastAPI Depends() parameters to factories or scope retrieval.

    FastAPI's Depends() creates runtime dependencies that FastAPI resolves.
    When bridging, we need to provide alternative resolution.

    Options:
    1. Map to factory: dependency resolved by calling factory at runtime
    2. Map to scope type: dependency retrieved from nodnod Scope

    Example::

        # Map get_db dependency to a factory
        MapDepends(
            depends_map={
                get_db: lambda: create_session(),  # Called per-request
            },
        )

        # Map to scope type (for compose dialect integration)
        MapDepends(
            scope_map={
                get_current_user: User,  # Retrieved from Scope via compose.Retrieve
            },
        )

    Note: For handlers going back to FastAPI via WrapAsDelegate, Depends()
    continues to work — FastAPI handles resolution. MapDepends is for
    handlers compiled to OTHER targets (CLI, Telegram, etc.).
    """

    depends_map: dict[Callable[..., object], Callable[[], object]] = field(
        default_factory=_empty_depends_map
    )
    scope_map: dict[Callable[..., object], type] = field(
        default_factory=_empty_scope_map
    )

    def purify[**P, R](self, handler: AnyHandler[P, R]) -> AsyncHandler[P, R]:
        """Wrap handler to resolve Depends() at runtime."""
        depends_factories = self.depends_map

        if not depends_factories and not self.scope_map:
            return ensure_async(handler)

        @functools.wraps(handler)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            # Resolve depends via factories
            for dep_func, factory in depends_factories.items():
                # Find param name that uses this Depends
                param_name = find_depends_param(handler, dep_func)
                if param_name and param_name not in kwargs:
                    result = factory()
                    if inspect.iscoroutine(result):
                        result = await result
                    kwargs[param_name] = result

            return await call_handler(handler, *args, **kwargs)

        return wrapped


# ═══════════════════════════════════════════════════════════════════════════════
# Future FastAPI-Specific Capabilities
# ═══════════════════════════════════════════════════════════════════════════════

# TODO: RouteModifier — modify route metadata (tags, summary, etc.)
# TODO: DependsAnalyzer — auto-discover Depends() in handlers
# TODO: BackgroundTasksMapper — handle BackgroundTasks parameter


__all__ = ("MapDepends",)
