"""Tests for compile._capabilities — Mount, OpenAPI merge, generic mount docs, fold helpers."""

from __future__ import annotations

# Any is required here because the production functions (_merge_openapi, _update_refs, etc.)
# accept dict[str, Any] parameters — tests must match those signatures.
from typing import Any
from unittest.mock import MagicMock

from emergent.wire.compile._capabilities import (
    Mount,
    FastAPICompileContext,
    fold_handler_runtime,
    apply_response_capabilities,
    # Private helpers tested directly — accessing internals is intentional for unit tests
    _merge_openapi,  # pyright: ignore[reportPrivateUsage]  # testing internal merge logic
    _update_refs,  # pyright: ignore[reportPrivateUsage]  # testing internal ref updater
    _add_generic_mount_docs,  # pyright: ignore[reportPrivateUsage]  # testing internal doc gen
)
from emergent.wire.axis.surface.transforms._response import AsDict, Transform
from emergent.wire.axis.surface.enrichers._impl import Inject


# ═══════════════════════════════════════════════════════════════════════════════
# fold_handler_runtime / apply_response_capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class TestFoldHandlerRuntime:
    def test_empty_capabilities(self) -> None:
        ctx = fold_handler_runtime(())
        assert ctx.enrichers == ()
        assert ctx.response_transforms == ()

    def test_enricher_collected(self) -> None:
        ctx = fold_handler_runtime((Inject(type=int, value=42),))
        assert len(ctx.enrichers) == 1

    def test_response_transform_collected(self) -> None:
        ctx = fold_handler_runtime((AsDict(),))
        assert len(ctx.response_transforms) == 1


class TestApplyResponseCapabilities:
    def test_no_transforms(self) -> None:
        result = apply_response_capabilities("hello", ())
        assert result == "hello"

    def test_transform_fn_applied(self) -> None:
        result = apply_response_capabilities(
            "hello",
            (Transform[str, str](fn=lambda x: x.upper()),),
        )
        assert result == "HELLO"

    def test_multiple_transforms_chained(self) -> None:
        result = apply_response_capabilities(
            "hello",
            (
                Transform[str, str](fn=lambda x: x + "!"),
                Transform[str, str](fn=lambda x: x.upper()),
            ),
        )
        assert result == "HELLO!"


# ═══════════════════════════════════════════════════════════════════════════════
# Mount
# ═══════════════════════════════════════════════════════════════════════════════


class TestMount:
    def _make_ctx(self) -> FastAPICompileContext:
        mock_app = MagicMock()
        mock_app.openapi_schema = None
        mock_app.openapi = MagicMock(return_value={"paths": {}, "info": {"title": "Test"}})
        return FastAPICompileContext(
            app=mock_app,
            trigger=MagicMock(),
            handler=MagicMock(),
            mounted=set(),
        )

    def test_mount_calls_app_mount(self) -> None:
        ctx = self._make_ctx()
        asgi_app = MagicMock()
        mount = Mount(app=asgi_app, prefix="/legacy")
        result = mount.compile_fastapi(ctx)
        ctx.app.mount.assert_called_once_with("/legacy", asgi_app)
        assert result.skip_route is True

    def test_mount_deduplication(self) -> None:
        ctx = self._make_ctx()
        asgi_app = MagicMock()
        mount = Mount(app=asgi_app, prefix="/legacy")
        mount.compile_fastapi(ctx)
        mount.compile_fastapi(ctx)
        # Should only mount once
        assert ctx.app.mount.call_count == 1

    def test_mount_replaces_openapi(self) -> None:
        ctx = self._make_ctx()
        asgi_app = MagicMock()
        mount = Mount(app=asgi_app, prefix="/api", source="django")
        mount.compile_fastapi(ctx)
        # openapi function should have been replaced
        assert ctx.app.openapi is not None

    def test_mount_with_openapi_schema(self) -> None:
        ctx = self._make_ctx()
        asgi_app = MagicMock()
        source_schema: dict[str, Any] = {
            "paths": {
                "/users": {
                    "get": {
                        "summary": "List users",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
            "definitions": {
                "User": {"type": "object", "properties": {"id": {"type": "integer"}}},
            },
            "tags": [{"name": "users", "description": "User endpoints"}],
        }
        mount = Mount(
            app=asgi_app, prefix="/api", source="django", openapi_schema=source_schema
        )
        mount.compile_fastapi(ctx)
        # Call the replaced openapi function to trigger merge
        result = ctx.app.openapi()
        # The merged schema should have the source paths
        assert "/api/users" in result["paths"]


# ═══════════════════════════════════════════════════════════════════════════════
# _merge_openapi
# ═══════════════════════════════════════════════════════════════════════════════


class TestMergeOpenAPI:
    def test_merge_paths_with_prefix(self) -> None:
        target: dict[str, Any] = {"paths": {}, "tags": []}
        source: dict[str, Any] = {
            "paths": {
                "/items": {
                    "get": {"summary": "List", "responses": {"200": {"description": "OK"}}},
                }
            },
        }
        _merge_openapi(target, source, "/api", "myapp")
        assert "/api/items" in target["paths"]

    def test_merge_paths_with_base_path(self) -> None:
        target: dict[str, Any] = {"paths": {}, "tags": []}
        source: dict[str, Any] = {
            "basePath": "/v1",
            "paths": {
                "/users": {
                    "get": {"summary": "Users", "responses": {"200": {"description": "OK"}}},
                }
            },
        }
        _merge_openapi(target, source, "/api", "myapp")
        assert "/api/v1/users" in target["paths"]

    def test_tags_prefixed_with_source(self) -> None:
        target: dict[str, Any] = {"paths": {}, "tags": []}
        source: dict[str, Any] = {
            "paths": {
                "/x": {"get": {"tags": ["alpha"], "responses": {}}},
            },
        }
        _merge_openapi(target, source, "/api", "myapp")
        method = target["paths"]["/api/x"]["get"]
        assert method["tags"] == ["myapp:alpha"]

    def test_default_tag_when_none(self) -> None:
        target: dict[str, Any] = {"paths": {}, "tags": []}
        source: dict[str, Any] = {
            "paths": {
                "/x": {"get": {"responses": {}}},
            },
        }
        _merge_openapi(target, source, "/api", "myapp")
        method = target["paths"]["/api/x"]["get"]
        assert method["tags"] == ["myapp"]

    def test_swagger_response_conversion(self) -> None:
        target: dict[str, Any] = {"paths": {}, "tags": []}
        source: dict[str, Any] = {
            "paths": {
                "/items": {
                    "get": {
                        "responses": {
                            "200": {"schema": {"type": "object"}, "description": "OK"}
                        },
                    },
                }
            },
        }
        _merge_openapi(target, source, "/api", "myapp")
        resp = target["paths"]["/api/items"]["get"]["responses"]["200"]
        assert "content" in resp
        assert "application/json" in resp["content"]

    def test_swagger_body_param_conversion(self) -> None:
        target: dict[str, Any] = {"paths": {}, "tags": []}
        source: dict[str, Any] = {
            "paths": {
                "/items": {
                    "post": {
                        "parameters": [
                            {"in": "body", "required": True, "schema": {"type": "object"}},
                            {"in": "query", "name": "q"},
                        ],
                        "responses": {},
                    },
                }
            },
        }
        _merge_openapi(target, source, "/api", "myapp")
        method = target["paths"]["/api/items"]["post"]
        assert "requestBody" in method
        assert len(method.get("parameters", [])) == 1
        assert method["parameters"][0]["name"] == "q"

    def test_body_only_params_cleaned(self) -> None:
        target: dict[str, Any] = {"paths": {}, "tags": []}
        source: dict[str, Any] = {
            "paths": {
                "/items": {
                    "post": {
                        "parameters": [
                            {"in": "body", "required": True, "schema": {"type": "object"}},
                        ],
                        "responses": {},
                    },
                }
            },
        }
        _merge_openapi(target, source, "/api", "myapp")
        method = target["paths"]["/api/items"]["post"]
        assert "parameters" not in method  # Cleaned up since no non-body params

    def test_definitions_merged_to_components(self) -> None:
        target: dict[str, Any] = {"paths": {}, "tags": []}
        source: dict[str, Any] = {
            "paths": {},
            "definitions": {
                "Item": {"type": "object"},
            },
        }
        _merge_openapi(target, source, "/api", "myapp")
        assert "Myapp" + "Item" in target["components"]["schemas"]

    def test_source_tags_merged(self) -> None:
        target: dict[str, Any] = {"paths": {}, "tags": []}
        source: dict[str, Any] = {
            "paths": {},
            "tags": [{"name": "users", "description": "User API"}],
        }
        _merge_openapi(target, source, "/api", "myapp")
        tag_names = [t["name"] for t in target["tags"]]
        assert "myapp:users" in tag_names
        assert "myapp" in tag_names

    def test_path_level_params_skipped(self) -> None:
        target: dict[str, Any] = {"paths": {}, "tags": []}
        source: dict[str, Any] = {
            "paths": {
                "/items": {
                    "parameters": [{"in": "path", "name": "id"}],
                    "get": {"responses": {}},
                }
            },
        }
        _merge_openapi(target, source, "/api", "myapp")
        # "parameters" key should not appear as a method
        assert "parameters" not in target["paths"]["/api/items"]


# ═══════════════════════════════════════════════════════════════════════════════
# _update_refs
# ═══════════════════════════════════════════════════════════════════════════════


class TestUpdateRefs:
    def test_update_ref_in_dict(self) -> None:
        obj: dict[str, Any] = {"$ref": "#/definitions/User"}
        _update_refs(obj, "#/definitions/User", "#/components/schemas/MyUser")
        assert obj["$ref"] == "#/components/schemas/MyUser"

    def test_update_ref_in_nested_dict(self) -> None:
        obj: dict[str, Any] = {
            "schema": {"$ref": "#/definitions/Item"},
        }
        _update_refs(obj, "#/definitions/Item", "#/components/schemas/MyItem")
        assert obj["schema"]["$ref"] == "#/components/schemas/MyItem"

    def test_update_ref_in_list(self) -> None:
        obj: dict[str, Any] = {
            "items": [{"$ref": "#/definitions/X"}],
        }
        _update_refs(obj, "#/definitions/X", "#/components/schemas/X")
        assert obj["items"][0]["$ref"] == "#/components/schemas/X"

    def test_no_match_no_change(self) -> None:
        obj: dict[str, Any] = {"$ref": "#/definitions/Other"}
        _update_refs(obj, "#/definitions/User", "#/components/schemas/User")
        assert obj["$ref"] == "#/definitions/Other"


# ═══════════════════════════════════════════════════════════════════════════════
# _add_generic_mount_docs
# ═══════════════════════════════════════════════════════════════════════════════


class TestAddGenericMountDocs:
    def test_adds_paths(self) -> None:
        schema: dict[str, Any] = {"paths": {}}
        _add_generic_mount_docs(schema, "/api", "legacy")
        mount_path = "/api/{path:path}"
        assert mount_path in schema["paths"]
        assert "get" in schema["paths"][mount_path]
        assert "post" in schema["paths"][mount_path]

    def test_adds_tag(self) -> None:
        schema: dict[str, Any] = {"paths": {}}
        _add_generic_mount_docs(schema, "/api", "legacy")
        assert "tags" in schema
        tag_names = [t["name"] for t in schema["tags"]]
        assert "legacy-mount" in tag_names

    def test_get_summary_contains_source(self) -> None:
        schema: dict[str, Any] = {"paths": {}}
        _add_generic_mount_docs(schema, "/api", "django")
        get_spec = schema["paths"]["/api/{path:path}"]["get"]
        assert "DJANGO" in get_spec["summary"]

    def test_post_summary_contains_source(self) -> None:
        schema: dict[str, Any] = {"paths": {}}
        _add_generic_mount_docs(schema, "/api", "django")
        post_spec = schema["paths"]["/api/{path:path}"]["post"]
        assert "DJANGO" in post_spec["summary"]

    def test_existing_tags_preserved(self) -> None:
        schema: dict[str, Any] = {"paths": {}, "tags": [{"name": "existing"}]}
        _add_generic_mount_docs(schema, "/api", "legacy")
        tag_names = [t["name"] for t in schema["tags"]]
        assert "existing" in tag_names
        assert "legacy-mount" in tag_names
