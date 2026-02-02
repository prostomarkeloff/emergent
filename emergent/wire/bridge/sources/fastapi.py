"""FastAPI source — ALL framework-specific code here.

Like compile/targets/fastapi.py but for extraction.

NO heuristics, NO magic type detection.
Use SetRequestType/SetResponseType capabilities for explicit mapping.

```python
from emergent.wire.bridge import sources, capabilities as BC

result = sources.fastapi(app)

for h in result:
    print(f"{h.trigger_data['method']} {h.trigger_data['path']} -> {h.request_type}")

# Convert to wire Application
wire_app = sources.fastapi_compile(result, runner)
```
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    NotRequired,
    Protocol,
    TypedDict,
    get_type_hints,
    runtime_checkable,
)

from emergent.ops._graph import Runner
from emergent.wire.bridge._capabilities import AnyHandler, BridgeCapability
from emergent.wire.bridge._convert import to_application
from emergent.wire.bridge._core import (
    BridgeAxes,
    BridgeResult,
    ExtractedHandler,
)
from emergent.wire.bridge._extract import extract_handler_unified

if TYPE_CHECKING:
    from emergent.wire.axis.surface._app import Application
    from emergent.wire.axis.surface._types import Trigger


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI-Specific Protocols (for type safety)
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class FastAPIAppProtocol(Protocol):
    """Protocol for FastAPI app — has routes attribute."""

    @property
    def routes(self) -> Sequence[object]: ...


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI-Specific Types (NOT in _core.py!)
# ═══════════════════════════════════════════════════════════════════════════════


class FastAPITriggerData(TypedDict):
    """FastAPI trigger data — like HTTPRouteTrigger fields.

    Required: method, path (always present after extraction).
    Optional: operation_id, tags, summary, deprecated.
    """

    method: str
    path: str
    operation_id: NotRequired[str | None]
    tags: NotRequired[tuple[str, ...]]
    summary: NotRequired[str | None]
    deprecated: NotRequired[bool]


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI Inspector Implementation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FastAPIInspector:
    """HandlerInspector for FastAPI endpoints.

    Extracts types from function signatures.
    NO heuristics — just reads annotations.
    """

    def request_type[**P, R](self, handler: AnyHandler[P, R]) -> type | None:
        """Extract first non-special parameter type as request type.

        Returns None if no suitable parameter found.
        Note: WrapAsRRC capability extracts types directly, so this is
        mainly for other capabilities or manual inspection.
        """
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
            # Return first typed parameter
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


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI Trigger Builder
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FastAPITriggerBuilder:
    """TriggerBuilder for FastAPI → HTTPRouteTrigger."""

    def build(self, data: FastAPITriggerData) -> Trigger:
        """Convert FastAPI trigger data to HTTPRouteTrigger."""
        from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger, Method

        method_str = data["method"]
        # Validate method - explicit match for type safety
        method: Method
        match method_str:
            case "GET" | "POST" | "PUT" | "DELETE" | "PATCH":
                method = method_str
            case _:
                method = "GET"

        return HTTPRouteTrigger(method, data["path"])


# ═══════════════════════════════════════════════════════════════════════════════
# Extraction Function
# ═══════════════════════════════════════════════════════════════════════════════


def extract[**P, R](
    app: FastAPIAppProtocol,
    capabilities: Sequence[BridgeCapability] = (),
    *,
    return_type: type[R] | None = None,
) -> BridgeResult[FastAPITriggerData, P, R]:
    """Extract handlers from FastAPI app.

    P — handler parameter spec (inferred from handlers).
    R — handler return type (inferred or specified via return_type).

    Args:
        app: FastAPI application instance.
        capabilities: Bridge capabilities to apply during extraction.
        return_type: Optional type marker for return type inference.
            If handlers return different types, use a union or base type.

    Returns:
        BridgeResult with extracted handlers.

    Raises:
        ImportError: If fastapi is not installed.

    Example::

        # With explicit return type
        result = extract(app, return_type=MyResponse)

        # With inferred type (requires type annotation)
        result: BridgeResult[FastAPITriggerData, ..., MyResponse] = extract(app)
    """
    del return_type  # Used only for type inference
    try:
        from fastapi.routing import APIRoute
    except ImportError as e:
        msg = "fastapi required for FastAPI bridge: pip install fastapi"
        raise ImportError(msg) from e

    axes = BridgeAxes(inspector=FastAPIInspector())
    handlers: list[ExtractedHandler[FastAPITriggerData, P, R]] = []

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue

        # Build trigger data
        methods = route.methods or {"GET"}
        method = next(iter(methods))

        # Convert tags to strings (FastAPI allows Enum tags)
        tags: tuple[str, ...] = ()
        if route.tags:
            tags = tuple(str(t) if not isinstance(t, str) else t for t in route.tags)

        trigger_data = FastAPITriggerData(
            method=method,
            path=route.path,
            operation_id=route.operation_id,
            tags=tags,
            summary=route.summary,
            deprecated=route.deprecated or False,
        )

        # Extract using unified function
        extracted = extract_handler_unified(
            trigger_data=trigger_data,
            handler=route.endpoint,
            axes=axes,
            capabilities=tuple(capabilities),
        )

        if extracted is not None:
            # Update deprecated from route if not already set
            if route.deprecated and not extracted.deprecated:
                from dataclasses import replace
                extracted = replace(extracted, deprecated=True)
            handlers.append(extracted)

    # Get FastAPI version
    version: str | None = None
    try:
        import fastapi

        version = fastapi.__version__
    except AttributeError:
        pass

    return BridgeResult(
        handlers=tuple(handlers),
        source="fastapi",
        version=version,
    )


def compile[**P, R](
    result: BridgeResult[FastAPITriggerData, P, R],
    runner: Runner,
) -> Application:
    """Convert extraction result to wire Application.

    Args:
        result: BridgeResult from extract().
        runner: Op runner for handlers.

    Returns:
        Wire Application with endpoints.
    """
    return to_application(
        result.handlers,
        runner,
        trigger_builder=FastAPITriggerBuilder(),
    )


# Convenience aliases
fastapi = extract
fastapi_compile = compile
extract_fastapi = extract


__all__ = (
    # Types
    "FastAPITriggerData",
    # Inspector
    "FastAPIInspector",
    # Builder
    "FastAPITriggerBuilder",
    # Functions
    "extract",
    "compile",
    # Aliases
    "fastapi",
    "fastapi_compile",
    "extract_fastapi",
)
