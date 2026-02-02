"""Unified capability processing — all adapters use this.

Single dispatcher for capability application. Each capability type
has a handler that transforms request/response or modifies behavior.

    from emergent.wire.compile._capabilities import apply_response_capabilities

    # Same for all targets
    response = await apply_response_capabilities(response, handler.capabilities, ctx)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from emergent.wire.axis.surface.capabilities import (
    SurfaceCapability,
    ResponseTransform,
)
from emergent.wire.axis._capability import FastAPIRouteContext


# ═══════════════════════════════════════════════════════════════════════════════
# Capability Context Protocol
# ═══════════════════════════════════════════════════════════════════════════════


class CapabilityContext(Protocol):
    """Context for capability processing.

    Each framework provides its own context implementation.
    Capabilities can access framework-specific data through this.
    """

    @property
    def framework(self) -> str:
        """Framework identifier: 'fastapi', 'cli', 'telegrinder'."""
        ...


@dataclass(frozen=True, slots=True)
class FastAPICapabilityContext:
    """FastAPI capability context."""

    request: Any  # fastapi.Request

    @property
    def framework(self) -> str:
        return "fastapi"


@dataclass(frozen=True, slots=True)
class CLICapabilityContext:
    """CLI capability context."""

    namespace: Any  # argparse.Namespace

    @property
    def framework(self) -> str:
        return "cli"


@dataclass(frozen=True, slots=True)
class TelegrinderCapabilityContext:
    """Telegrinder capability context."""

    ctx: Any  # telegrinder Context

    @property
    def framework(self) -> str:
        return "telegrinder"


# ═══════════════════════════════════════════════════════════════════════════════
# Response Capability Processing
# ═══════════════════════════════════════════════════════════════════════════════


def apply_response_capabilities(
    response: Any,
    capabilities: tuple[SurfaceCapability, ...],
) -> Any:
    """Apply response-transforming capabilities.

    Pure function that transforms response based on capabilities.
    Called by all adapters after execute_rrc/execute_stateful_done.

    Currently handles:
    - ResponseTransform: apply_response() method

    Args:
        response: Response to transform
        capabilities: Handler capabilities

    Returns:
        Transformed response
    """
    for cap in capabilities:
        if isinstance(cap, ResponseTransform):
            response = cap.apply_response(response)

    return response


async def apply_response_capabilities_async(
    response: Any,
    capabilities: tuple[SurfaceCapability, ...],
    ctx: CapabilityContext | None = None,
) -> Any:
    """Apply response-transforming capabilities (async version).

    Some capabilities may need async processing (e.g., EditMessage in Telegram).
    This version supports both sync and async capability handlers.

    Args:
        response: Response to transform
        capabilities: Handler capabilities
        ctx: Framework-specific context (optional, for async capabilities)

    Returns:
        Transformed response
    """
    for cap in capabilities:
        if isinstance(cap, ResponseTransform):
            response = cap.apply_response(response)

    return response


# ═══════════════════════════════════════════════════════════════════════════════
# Capability Lookup Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def find_capability[C: SurfaceCapability](
    capabilities: tuple[SurfaceCapability, ...],
    cap_type: type[C],
) -> C | None:
    """Find first capability of given type.

    Generic helper for capability lookup. Use instead of manual loops.

    Example:
        timeout = find_capability(handler.capabilities, TimeoutCapability)
        if timeout:
            handler = with_timeout(handler, timeout.seconds)
    """
    for cap in capabilities:
        if isinstance(cap, cap_type):
            return cap
    return None


def find_all_capabilities[C: SurfaceCapability](
    capabilities: tuple[SurfaceCapability, ...],
    cap_type: type[C],
) -> list[C]:
    """Find all capabilities of given type.

    Example:
        middlewares = find_all_capabilities(handler.capabilities, MiddlewareCapability)
    """
    return [cap for cap in capabilities if isinstance(cap, cap_type)]


def has_capability(
    capabilities: tuple[SurfaceCapability, ...],
    cap_type: type[SurfaceCapability],
) -> bool:
    """Check if capabilities include given type.

    Example:
        if has_capability(handler.capabilities, StreamingCapability):
            return streaming_response(...)
    """
    return any(isinstance(cap, cap_type) for cap in capabilities)


# ═══════════════════════════════════════════════════════════════════════════════
# Route Registration Context — for compile-time capabilities
# ═══════════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI Compile Context — for compile-time capabilities
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class FastAPICompileContext:
    """Context for FastAPI compilation. Tracks state during compilation."""

    app: Any  # fastapi.FastAPI
    trigger: Any  # HTTPRouteTrigger
    handler: Any  # Handler
    mounted: set[tuple[int, str]]  # (app_id, prefix) already mounted
    skip_route: bool = False  # If True, skip normal route registration


@runtime_checkable
class FastAPICompilable(Protocol):
    """Protocol for capabilities that affect FastAPI compilation."""

    def compile_fastapi(self, ctx: FastAPICompileContext) -> FastAPICompileContext:
        """Transform compile context. Self-contained — does the work."""
        ...


def apply_fastapi_capabilities(
    ctx: FastAPICompileContext,
    capabilities: tuple[SurfaceCapability, ...],
) -> FastAPICompileContext:
    """Apply FastAPI compile capabilities. Compiler just calls this."""
    for cap in capabilities:
        if isinstance(cap, FastAPICompilable):
            ctx = cap.compile_fastapi(ctx)
    return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI Route Context — for route-level capabilities (Tag, Summary, etc.)
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class FastAPIRouteCompilable(Protocol):
    """Protocol for capabilities that affect FastAPI route configuration."""

    def compile_fastapi_route(
        self, ctx: "FastAPIRouteContext"
    ) -> "FastAPIRouteContext":
        """Transform route context."""
        ...


def apply_fastapi_route_capabilities(
    ctx: "FastAPIRouteContext",
    capabilities: tuple[SurfaceCapability, ...],
) -> "FastAPIRouteContext":
    """Apply FastAPI route capabilities. Returns modified route context."""
    for cap in capabilities:
        if isinstance(cap, FastAPIRouteCompilable):
            ctx = cap.compile_fastapi_route(ctx)
    return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# Mount — self-contained ASGI mounting capability
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Mount(SurfaceCapability):
    """Mount ASGI app at prefix — self-contained capability.

    Implements compile_fastapi() which does the mounting.
    Context tracks already-mounted apps to avoid duplicates.
    Merges source app's OpenAPI schema (if available) into FastAPI's.

    Example::

        endpoint(...).expose(
            trigger,
            delegate(handler),
            Mount(django_asgi, prefix="/django", source="django"),
        )
    """

    app: Any  # ASGI app
    prefix: str = "/"
    source: str = ""
    openapi_schema: dict[str, Any] | None = None  # Pre-extracted OpenAPI

    def compile_fastapi(self, ctx: FastAPICompileContext) -> FastAPICompileContext:
        """Mount ASGI app. Self-contained — does the work."""
        key = (id(self.app), self.prefix)
        if key not in ctx.mounted:
            ctx.app.mount(self.prefix, self.app)
            ctx.mounted.add(key)

            # Add OpenAPI documentation for mount
            self._add_openapi_docs(ctx.app)

        # Skip normal route registration — ASGI app handles it
        ctx.skip_route = True
        return ctx

    def _add_openapi_docs(self, app: Any) -> None:
        """Merge source OpenAPI into FastAPI's schema."""
        original_openapi = app.openapi
        prefix = self.prefix.rstrip("/")
        source = self.source or "legacy"
        source_schema = self.openapi_schema

        def custom_openapi() -> dict[str, Any]:
            if app.openapi_schema:
                return app.openapi_schema

            openapi_schema = original_openapi()

            if source_schema:
                # Merge source OpenAPI paths with prefix
                _merge_openapi(openapi_schema, source_schema, prefix, source)
            else:
                # Fallback: generic mount documentation
                _add_generic_mount_docs(openapi_schema, prefix, source)

            app.openapi_schema = openapi_schema
            return app.openapi_schema

        app.openapi = custom_openapi


def _merge_openapi(
    target: dict[str, Any],
    source: dict[str, Any],
    prefix: str,
    source_name: str,
) -> None:
    """Merge source OpenAPI into target with prefix."""
    # Get source base path (e.g., /api from Django)
    source_base = source.get("basePath", "").rstrip("/")

    # Merge paths
    for path, methods in source.get("paths", {}).items():
        # Build full path with prefix
        full_path = f"{prefix}{source_base}{path}"

        # Convert Swagger 2.0 to OpenAPI 3.x if needed
        converted_methods: dict[str, Any] = {}
        for method, spec in methods.items():
            if method == "parameters":
                continue  # Path-level params handled separately

            converted_spec = dict(spec)

            # Add source tag
            tags = list(converted_spec.get("tags", []))
            tags = [f"{source_name}:{t}" for t in tags] or [source_name]
            converted_spec["tags"] = tags

            # Convert Swagger 2.0 responses to OpenAPI 3.x
            if "responses" in converted_spec:
                for _code, resp in converted_spec["responses"].items():
                    if "schema" in resp and "content" not in resp:
                        schema = resp.pop("schema")
                        resp["content"] = {"application/json": {"schema": schema}}

            # Convert body parameter to requestBody (Swagger 2.0 → 3.x)
            params: list[dict[str, Any]] = converted_spec.get("parameters", [])
            new_params: list[dict[str, Any]] = []
            for param in params:
                if param.get("in") == "body":
                    converted_spec["requestBody"] = {
                        "required": param.get("required", False),
                        "content": {
                            "application/json": {"schema": param.get("schema", {})}
                        },
                    }
                else:
                    new_params.append(param)
            if new_params:
                converted_spec["parameters"] = new_params
            elif "parameters" in converted_spec and not new_params:
                del converted_spec["parameters"]

            converted_methods[method] = converted_spec

        target["paths"][full_path] = converted_methods

    # Merge definitions/components
    if "definitions" in source:
        if "components" not in target:
            target["components"] = {}
        if "schemas" not in target["components"]:
            target["components"]["schemas"] = {}

        for name, schema in source["definitions"].items():
            # Prefix schema names to avoid conflicts
            prefixed_name = f"{source_name.title()}{name}"
            target["components"]["schemas"][prefixed_name] = schema

            # Update $refs in paths
            _update_refs(
                target["paths"],
                f"#/definitions/{name}",
                f"#/components/schemas/{prefixed_name}",
            )

    # Merge tags
    if "tags" not in target:
        target["tags"] = []

    tags_list = cast(list[dict[str, Any]], target["tags"])
    source_tags = cast(list[dict[str, Any]], source.get("tags", []))
    for tag in source_tags:
        tags_list.append(
            {
                "name": f"{source_name}:{tag.get('name', '')}",
                "description": tag.get("description", ""),
            }
        )

    # Add source tag if not present
    if not any(t.get("name") == source_name for t in tags_list):
        tags_list.append(
            {
                "name": source_name,
                "description": f"Mounted {source_name} application at {prefix}",
            }
        )


def _update_refs(
    obj: dict[str, Any] | list[Any] | Any, old_ref: str, new_ref: str
) -> None:
    """Recursively update $ref values in object."""
    if isinstance(obj, dict):
        obj_dict = cast(dict[str, Any], obj)
        for key, value in obj_dict.items():
            if key == "$ref" and value == old_ref:
                obj_dict[key] = new_ref
            else:
                _update_refs(value, old_ref, new_ref)
    elif isinstance(obj, list):
        obj_list = cast(list[Any], obj)
        for item in obj_list:
            _update_refs(item, old_ref, new_ref)


def _add_generic_mount_docs(
    schema: dict[str, Any],
    prefix: str,
    source: str,
) -> None:
    """Add generic mount documentation when no OpenAPI available."""
    tag = f"{source}-mount"
    mount_path = f"{prefix}/{{path:path}}"

    schema["paths"][mount_path] = {
        "get": {
            "tags": [tag],
            "summary": f"[{source.upper()}] All GET requests",
            "description": f"Mounted {source} application. All requests forwarded.",
            "parameters": [
                {
                    "name": "path",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {"200": {"description": f"Response from {source}"}},
        },
        "post": {
            "tags": [tag],
            "summary": f"[{source.upper()}] All POST requests",
            "parameters": [
                {
                    "name": "path",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {"200": {"description": f"Response from {source}"}},
        },
    }

    if "tags" not in schema:
        schema["tags"] = []
    tags_list = cast(list[dict[str, Any]], schema["tags"])
    tags_list.append(
        {
            "name": tag,
            "description": f"Mounted {source} application at {prefix}",
        }
    )


__all__ = (
    # Context
    "CapabilityContext",
    "FastAPICapabilityContext",
    "CLICapabilityContext",
    "TelegrinderCapabilityContext",
    # FastAPI compile (app-level)
    "FastAPICompileContext",
    "FastAPICompilable",
    "apply_fastapi_capabilities",
    # FastAPI route (route-level)
    "FastAPIRouteContext",
    "FastAPIRouteCompilable",
    "apply_fastapi_route_capabilities",
    # Mount capability
    "Mount",
    # Processing
    "apply_response_capabilities",
    "apply_response_capabilities_async",
    # Lookup
    "find_capability",
    "find_all_capabilities",
    "has_capability",
)
