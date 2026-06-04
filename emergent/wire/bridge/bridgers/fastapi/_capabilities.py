"""FastAPI-specific bridge capabilities.

DESIGN PRINCIPLE: Understand FastAPI's ACTUAL type system, don't guess.
Reuse emergent.wire.axis.schema inspection infrastructure.

FastAPI determines parameter sources via:
1. Decorator path template — `/users/{user_id}` defines path params
2. Depends() — dependency injection
3. Annotated[T, Query/Path/Body/Header/Cookie()] — explicit source markers
4. Plain Pydantic model param — implicit Body()
5. Return type annotation — response model

This module provides:
- InferFromFastAPI — single generic capability that parses FastAPI's type system
- MapDepends — resolve Depends() for cross-compilation
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, get_type_hints

from emergent.wire.axis.schema import (
    unwrap_annotated,
    unwrap_optional,
    pydantic_inspector,
    dataclass_inspector,
)
from emergent.wire.bridge._capabilities import (
    AnyHandler,
    AsyncHandler,
    BridgeCapability,
    BridgeContext,
    call_handler,
    ensure_async,
)
from emergent.wire.bridge.bridgers.fastapi._utils import find_depends_param


type DependsMapAny = dict[Callable[..., Any], Callable[[], Any]]
type ScopeMapAny = dict[Callable[..., Any], type]
type DependsMap = dict[Callable[..., object], Callable[[], object]]
type ScopeMap = dict[Callable[..., object], type]
type GroupedParams = dict[str, list["ParsedParam"]]


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI Type System Parsing (reuses schema inspection)
# ═══════════════════════════════════════════════════════════════════════════════


# FastAPI marker class names
_FASTAPI_MARKERS: frozenset[str] = frozenset(
    {
        "Query",
        "Path",
        "Body",
        "Header",
        "Cookie",
        "Form",
        "File",
    }
)

# FastAPI/Starlette special type names
_SPECIAL_TYPE_NAMES: frozenset[str] = frozenset(
    {
        "Request",
        "Response",
        "WebSocket",
        "BackgroundTasks",
        "HTTPConnection",
    }
)


def _get_fastapi_marker(annotations: list[Any]) -> str | None:
    """Find FastAPI marker in annotations list.

    Returns marker name ("Body", "Query", etc.) or None.
    """
    for ann in annotations:
        type_name = type(ann).__name__
        if type_name in _FASTAPI_MARKERS:
            return type_name
    return None


def _is_special_fastapi_type(t: type | None) -> bool:
    """Check if type is a FastAPI/Starlette special type."""
    if t is None:
        return False
    name = t.__name__
    module = t.__module__

    if name in _SPECIAL_TYPE_NAMES:
        return True
    if module.startswith(("fastapi.", "starlette.")):
        return True
    return False


def _is_pydantic_model(t: Any) -> bool:
    """Check if type is a Pydantic BaseModel (using schema inspector)."""
    if t is None or not isinstance(t, type):
        return False
    return pydantic_inspector(t) is not None


def _is_dataclass_type(t: Any) -> bool:
    """Check if type is a dataclass (using schema inspector)."""
    if t is None or not isinstance(t, type):
        return False
    return dataclass_inspector(t) is not None


def _is_depends(obj: Any) -> bool:
    """Check if object is FastAPI Depends instance."""
    return type(obj).__name__ == "Depends"


@dataclass(frozen=True, slots=True)
class ParsedParam:
    """Parsed FastAPI parameter info."""

    name: str
    base_type: type | None
    source: str  # "body", "query", "path", "header", "cookie", "depends", "special", "unknown"
    is_optional: bool
    default: object


def _parse_handler_params(handler: Callable[..., Any]) -> list[ParsedParam]:
    """Parse all parameters from a FastAPI handler.

    Uses schema inspection utilities for type unwrapping.

    Determines source for each parameter:
    - Depends() default → "depends"
    - Annotated[T, Body()] → "body"
    - Annotated[T, Query()] → "query"
    - Annotated[T, Path()] → "path"
    - Annotated[T, Header()] → "header"
    - Annotated[T, Cookie()] → "cookie"
    - Plain Pydantic/dataclass → "body" (FastAPI default behavior)
    - Special types (Request, etc.) → "special"
    - Primitives → "unknown" (could be query or path based on route)
    """
    if not callable(handler):
        return []

    try:
        hints = get_type_hints(handler, include_extras=True)
        sig = inspect.signature(handler)
    except Exception:
        return []

    result: list[ParsedParam] = []

    for name, param in sig.parameters.items():
        annotation = hints.get(name)
        default = param.default

        # Check Depends() first
        if _is_depends(default):
            result.append(ParsedParam(name, None, "depends", False, default))
            continue

        if annotation is None:
            result.append(ParsedParam(name, None, "unknown", False, default))
            continue

        # Use schema inspection to unwrap
        base_type, annotations = unwrap_annotated(annotation)
        base_type, is_optional = unwrap_optional(base_type)

        # Ensure base_type is actually a type
        if not isinstance(base_type, type):
            base_type = None

        # Check for FastAPI marker in annotations
        marker = _get_fastapi_marker(annotations)

        if marker is not None:
            source = marker.lower()  # "Body" → "body"
            result.append(ParsedParam(name, base_type, source, is_optional, default))
            continue

        # No explicit marker — use FastAPI's implicit rules
        if base_type is not None:
            if _is_special_fastapi_type(base_type):
                result.append(
                    ParsedParam(name, base_type, "special", is_optional, default)
                )
            elif _is_pydantic_model(base_type) or _is_dataclass_type(base_type):
                # Pydantic/dataclass without marker → Body (FastAPI default)
                result.append(
                    ParsedParam(name, base_type, "body", is_optional, default)
                )
            else:
                # Primitive or unknown → could be query/path, depends on route
                result.append(
                    ParsedParam(name, base_type, "unknown", is_optional, default)
                )
        else:
            result.append(ParsedParam(name, None, "unknown", is_optional, default))

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Generic FastAPI Type Inference
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class InferFromFastAPI(BridgeCapability):
    """Infer request/response types by parsing FastAPI's type system.

    GENERIC INFERENCE that understands FastAPI's actual mechanics.
    Uses emergent.wire.axis.schema inspection for type unwrapping.

    Request type inference (in priority order):
    1. Explicit Body() marker: `Annotated[User, Body()]` → User
    2. Implicit body (Pydantic/dataclass param without marker) → that type
    3. None if no body parameter found

    Response type inference:
    1. Return annotation if it's a concrete type
    2. None otherwise

    This is the SINGLE capability you need for FastAPI type inference.

    Example::

        # All these work correctly:

        async def create_user(user: UserCreate) -> User:  # body=UserCreate, response=User
            ...

        async def get_user(user_id: int) -> User:  # body=None, response=User
            ...

        async def update_user(
            user_id: Annotated[int, Path()],
            user: Annotated[UserUpdate, Body()],
        ) -> User:  # body=UserUpdate, response=User
            ...
    """

    # If True, also consider dataclasses as body types (not just Pydantic)
    include_dataclass: bool = True

    def compile_bridge[T, **P, R](
        self, ctx: BridgeContext[T, P, R]
    ) -> BridgeContext[T, P, R]:
        # Parse handler parameters
        params = _parse_handler_params(ctx.handler)

        # Infer request type (body parameter)
        request_type = ctx.request_type
        if request_type is None:
            for param in params:
                if param.source == "body" and param.base_type is not None:
                    if _is_pydantic_model(param.base_type):
                        request_type = param.base_type
                        break
                    if self.include_dataclass and _is_dataclass_type(param.base_type):
                        request_type = param.base_type
                        break

        # Infer response type (return annotation)
        response_type = ctx.response_type
        if response_type is None:
            response_type = self._get_return_type(ctx.handler)

        return replace(ctx, request_type=request_type, response_type=response_type)

    def _get_return_type(self, handler: Callable[..., Any]) -> type | None:
        """Extract return type from handler using schema inspection."""
        if not callable(handler):
            return None
        try:
            hints = get_type_hints(handler)
            ret = hints.get("return")
            if ret is None:
                return None

            # Use schema inspection to unwrap
            base_type, _ = unwrap_annotated(ret)
            base_type, _ = unwrap_optional(base_type)

            if isinstance(base_type, type):
                return base_type
        except Exception:
            pass
        return None


# Convenience alias
DEFAULT_INFERENCE: tuple[BridgeCapability, ...] = (InferFromFastAPI(),)


# ═══════════════════════════════════════════════════════════════════════════════
# MapDepends — Handle FastAPI Depends() parameters
# ═══════════════════════════════════════════════════════════════════════════════


def _empty_depends_map() -> DependsMapAny:
    return {}


def _empty_scope_map() -> ScopeMapAny:
    return {}


@dataclass(frozen=True, slots=True)
class MapDepends(BridgeCapability):
    """Map FastAPI Depends() parameters to factories or scope retrieval.

    FastAPI's Depends() creates runtime dependencies that FastAPI resolves.
    When bridging to OTHER targets (CLI, Telegram), we need alternative resolution.

    Options:
    1. depends_map: dependency → factory (called per-request)
    2. scope_map: dependency → type (retrieved from nodnod Scope)

    Example::

        MapDepends(
            depends_map={
                get_db: lambda: create_session(),
            },
            scope_map={
                get_current_user: User,  # From Scope via compose.Retrieve
            },
        )

    Note: For handlers compiled back to FastAPI, Depends() works normally.
    MapDepends is for cross-compilation to non-FastAPI targets.
    """

    depends_map: DependsMap = field(
        default_factory=_empty_depends_map
    )
    scope_map: ScopeMap = field(
        default_factory=_empty_scope_map
    )

    def purify[**P, R](self, handler: AnyHandler[P, R]) -> AsyncHandler[P, R]:
        """Wrap handler to resolve Depends() at runtime."""
        depends_factories = self.depends_map

        if not depends_factories and not self.scope_map:
            return ensure_async(handler)

        @functools.wraps(handler)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            for dep_func, factory in depends_factories.items():
                param_name = find_depends_param(handler, dep_func)
                if param_name and param_name not in kwargs:
                    result = factory()
                    if inspect.iscoroutine(result):
                        result = await result
                    kwargs[param_name] = result

            return await call_handler(handler, *args, **kwargs)

        return wrapped


# ═══════════════════════════════════════════════════════════════════════════════
# Introspection utilities (for advanced use)
# ═══════════════════════════════════════════════════════════════════════════════


def parse_fastapi_handler(
    handler: Callable[..., Any],
) -> GroupedParams:
    """Parse FastAPI handler and group parameters by source.

    Returns dict with keys: "body", "query", "path", "header", "depends", "special", "unknown"

    Useful for:
    - Debugging type inference
    - Building custom inference logic
    - Understanding handler structure

    Example::

        params = parse_fastapi_handler(my_handler)
        body_params = params.get("body", [])
        depends_params = params.get("depends", [])
    """
    all_params = _parse_handler_params(handler)
    grouped: GroupedParams = {
        "body": [],
        "query": [],
        "path": [],
        "header": [],
        "cookie": [],
        "form": [],
        "file": [],
        "depends": [],
        "special": [],
        "unknown": [],
    }
    for param in all_params:
        grouped.setdefault(param.source, []).append(param)
    return grouped


__all__ = (
    # Main inference capability
    "InferFromFastAPI",
    "DEFAULT_INFERENCE",
    # Depends handling
    "MapDepends",
    # Introspection
    "ParsedParam",
    "parse_fastapi_handler",
)
