"""Capability processing — contexts, protocols, and lookup helpers.

Compile-time capability application uses fold() directly — the universal
primitive. This module provides:

1. Contexts and protocols for compile-time capabilities (FastAPICompileContext, etc.)
2. Runtime response transform (apply_response_capabilities)
3. Capability lookup helpers (find_capability, has_capability, etc.)

Compile-time usage (in target compilers):

    from emergent.wire.compile._core import fold
    from emergent.wire.compile._capabilities import FastAPICompilable, FastAPICompileContext

    # fold() IS the universal primitive — same for schema, surface, everything
    ctx = fold(handler.capabilities, ctx, FastAPICompilable, "compile_fastapi",
               trace=axes.trace)  # tracing is automatic
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from emergent.wire.axis.surface.capabilities import (
    SurfaceCapability,
)
from emergent.wire.axis._capability import (
    FastAPIRouteContext,
    HandlerRuntimeContext,
    HandlerRuntimeCompilable,
)
from emergent.wire.compile._core import fold

type JsonObj = dict[str, Any]
type JsonObjList = list[dict[str, Any]]
type JsonNode = dict[str, Any] | list[Any] | Any


# ═══════════════════════════════════════════════════════════════════════════════
# Handler Runtime Fold
# ═══════════════════════════════════════════════════════════════════════════════


def fold_handler_runtime(
    capabilities: tuple[SurfaceCapability, ...],
) -> HandlerRuntimeContext:
    """Fold handler capabilities into runtime context (enrichers + transforms)."""
    return fold(
        capabilities,
        HandlerRuntimeContext(),
        HandlerRuntimeCompilable,
        "compile_handler_runtime",
    )


def apply_response_capabilities[T](
    response: T,
    capabilities: tuple[SurfaceCapability, ...],
) -> T:
    """Apply response-transforming capabilities via fold.

    Runtime function — transforms response after execution.
    Uses fold to extract ResponseTransform instances, then applies sequentially.
    """
    rt_ctx = fold_handler_runtime(capabilities)
    for transform in rt_ctx.response_transforms:
        response = transform.apply_response(response)
    return response


# ═══════════════════════════════════════════════════════════════════════════════
# Capability Lookup Helpers
# ═══════════════════════════════════════════════════════════════════════════════


# Capability lookup — delegate to canonical surface helpers (avoid duplication)
from emergent.wire.axis.surface.capabilities._helpers import (
    find_capability,
    find_all_capabilities,
    has_capability,
)


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI Compile Context — for compile-time capabilities
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class FastAPICompileContext:
    """Context for FastAPI compilation. Tracks state during compilation.

    Used with fold():
        ctx = fold(capabilities, ctx, FastAPICompilable, "compile_fastapi",
                   trace=axes.trace)
    """

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


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI Route Context — for route-level capabilities (Tag, Summary, etc.)
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class FastAPIRouteCompilable(Protocol):
    """Protocol for capabilities that affect FastAPI route configuration.

    Used with fold():
        route_ctx = fold(capabilities, route_ctx, FastAPIRouteCompilable,
                         "compile_fastapi_route", trace=axes.trace)
    """

    def compile_fastapi_route(
        self, ctx: "FastAPIRouteContext"
    ) -> "FastAPIRouteContext":
        """Transform route context."""
        ...


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
    openapi_schema: JsonObj | None = None  # Pre-extracted OpenAPI

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

        def custom_openapi() -> JsonObj:
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
    target: JsonObj,
    source: JsonObj,
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
        converted_methods: JsonObj = {}
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
            params: JsonObjList = converted_spec.get("parameters", [])
            new_params: JsonObjList = []
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
    obj: JsonNode, old_ref: str, new_ref: str
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
    schema: JsonObj,
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
    # FastAPI compile (app-level)
    "FastAPICompileContext",
    "FastAPICompilable",
    # FastAPI route (route-level)
    "FastAPIRouteContext",
    "FastAPIRouteCompilable",
    # Mount capability
    "Mount",
    # Handler runtime fold
    "fold_handler_runtime",
    # Runtime response processing
    "apply_response_capabilities",
    # Lookup
    "find_capability",
    "find_all_capabilities",
    "has_capability",
)
