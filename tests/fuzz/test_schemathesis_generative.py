# pyright: reportPrivateUsage=false
"""Schemathesis on GENERATED emergent programs — heavy fuzzing.

Two layers:
  1. FIXED edge-case configs — hardcoded dangerous combos that random rarely hits
  2. RANDOM configs — high-volume hypothesis generation biased toward complexity

Custom open-world capabilities alongside built-in ones.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Annotated, Any

import hypothesis.strategies as st
from hypothesis import given, settings, HealthCheck, find
import pytest

from emergent.wire.derive import derive, build_application_from_decorated, memory_node, http_crud

import schemathesis
import schemathesis.openapi

from emergent.wire.axis._capability import (
    Capability,
    OpenAPIContext,
    ConstraintsContext,
    openapi_schema,
)
from emergent.wire.axis.schema._universal import (
    Identity,
    Min,
    Max,
    MinLen,
    MaxLen,
    OneOf,
    Unique,
    Doc,
    ExclusiveMin,
    ExclusiveMax,
    MultipleOf,
    Pattern,
)
from emergent.wire.derive._transforms import Paginated, Readonly
from emergent.wire.compile import targets
from emergent.wire.compile.targets.fastapi import install_rfc7807_validation_handler


# ═══════════════════════════════════════════════════════════════════════════════
# Custom open-world capabilities
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class CustomTag(Capability):
    """User-defined: arbitrary tag metadata."""
    tag: str

    def compile_openapi(self, ctx: OpenAPIContext) -> OpenAPIContext:
        return openapi_schema(ctx, **{"x-custom-tag": self.tag})

    def compile_constraints(self, ctx: ConstraintsContext) -> ConstraintsContext:
        return ctx


@dataclass(frozen=True, slots=True)
class CustomPriority(Capability):
    """User-defined: priority level."""
    level: int

    def compile_openapi(self, ctx: OpenAPIContext) -> OpenAPIContext:
        return openapi_schema(ctx, **{"x-priority": self.level})


@dataclass(frozen=True, slots=True)
class CustomFormat(Capability):
    """User-defined: format hint."""
    fmt: str

    def compile_openapi(self, ctx: OpenAPIContext) -> OpenAPIContext:
        return openapi_schema(ctx, format=self.fmt)


@dataclass(frozen=True, slots=True)
class NoopCap(Capability):
    """Does nothing. Tests that fold handles no-op caps without corruption."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# App builder
# ═══════════════════════════════════════════════════════════════════════════════


def _compile_app(*entity_specs: tuple[str, dict[str, Any], list[Any]]) -> Any:
    """Build FastAPI app from entity specs.

    Each spec: (path, annotations_dict, transforms_list)
    annotations_dict must include "id": Annotated[int, Identity].
    """
    entities: list[type] = []
    for path, annotations, xforms in entity_specs:
        name = path.strip("/").title().rstrip("s")
        provider = memory_node()
        ns: dict[str, Any] = {"__annotations__": dict(annotations)}
        cls = dataclass(type(name, (), ns))
        cls = derive(http_crud(path, provider_node=provider), *xforms)(cls)
        entities.append(cls)

    wire_app = build_application_from_decorated(*entities)
    fa = targets.fastapi.compile(wire_app)
    install_rfc7807_validation_handler(fa)
    return fa


def _fuzz_app(fa_app: Any, requests_per_endpoint: int = 10) -> None:
    """Fuzz every endpoint, assert no 500s."""
    schema = schemathesis.openapi.from_asgi("/openapi.json", app=fa_app)

    for op_result in schema.get_all_operations():
        op = op_result.ok()
        strategy = op.as_strategy()

        for _ in range(requests_per_endpoint):
            try:
                case = find(strategy, lambda _c: True, settings=settings(
                    max_examples=1, suppress_health_check=list(HealthCheck), database=None,
                ))
            except Exception:
                continue

            response = case.call()
            assert response.status_code < 500, (
                f"500 on {op.method.upper()} {op.path}: {response.text[:300]}"
            )


def _check_openapi(fa_app: Any, expected_paths: list[str]) -> None:
    """Verify OpenAPI schema is valid and contains expected paths."""
    openapi = fa_app.openapi()
    assert isinstance(openapi, dict)
    assert "paths" in openapi
    for p in expected_paths:
        assert p in openapi["paths"], (
            f"Missing {p}. Got: {list(openapi['paths'].keys())}"
        )


def _check_no_mutations(fa_app: Any) -> None:
    """Verify readonly app has no mutation methods."""
    openapi = fa_app.openapi()
    skip = {"/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}
    for path, methods in openapi["paths"].items():
        if path in skip:
            continue
        bad = set(methods.keys()) & {"post", "put", "patch", "delete"}
        assert not bad, f"Readonly app has {bad} on {path}"


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 1: FIXED edge-case configs
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.slow
class TestEdgeCaseConfigs:
    """Hardcoded dangerous combos that random generation rarely produces."""

    def test_minimal_entity_one_field(self) -> None:
        """Entity with ONLY identity field — minimum viable."""
        app = _compile_app(("/things", {"id": Annotated[int, Identity]}, []))
        _fuzz_app(app, 15)

    def test_all_string_caps_on_one_field(self) -> None:
        """Every string capability stacked on a single field."""
        app = _compile_app(("/items", {
            "id": Annotated[int, Identity],
            "name": Annotated[str, MinLen(1), MaxLen(50), Doc("all caps"), Unique, CustomTag("heavy"), CustomFormat("name")],
        }, []))
        _fuzz_app(app, 15)

    def test_all_numeric_caps_on_one_field(self) -> None:
        """Every numeric capability stacked."""
        app = _compile_app(("/items", {
            "id": Annotated[int, Identity],
            "value": Annotated[int, Min(1), Max(100), ExclusiveMin(0), ExclusiveMax(101), MultipleOf(1), CustomPriority(5)],
        }, []))
        _fuzz_app(app, 15)

    def test_enum_field_with_other_caps(self) -> None:
        """OneOf + other caps — tests Literal type interaction."""
        app = _compile_app(("/items", {
            "id": Annotated[int, Identity],
            "status": Annotated[str, OneOf("draft", "published", "archived"), Doc("status field"), CustomTag("enum")],
        }, []))
        _fuzz_app(app, 15)

    def test_max_fields_entity(self) -> None:
        """8 fields — maximum in our pool."""
        app = _compile_app(("/items", {
            "id": Annotated[int, Identity],
            "name": Annotated[str, MinLen(1), MaxLen(100)],
            "title": Annotated[str, MaxLen(200)],
            "age": Annotated[int, Min(0), Max(200)],
            "score": Annotated[int, Min(0), Max(10000)],
            "price": Annotated[float, Min(0.0), Max(1000000.0)],
            "tag": Annotated[str, OneOf("a", "b", "c")],
            "note": str,
        }, []))
        _fuzz_app(app, 15)

    def test_readonly_paginated_together(self) -> None:
        """Readonly + Paginated — no mutation endpoints, but list is paginated."""
        app = _compile_app(("/items", {
            "id": Annotated[int, Identity],
            "name": Annotated[str, MinLen(1), MaxLen(100)],
            "value": Annotated[int, Min(0)],
        }, [Readonly(), Paginated(5)]))
        _check_no_mutations(app)
        _fuzz_app(app, 15)

    def test_custom_caps_only_no_builtin(self) -> None:
        """Entity with ONLY custom open-world capabilities — no built-in constraints."""
        app = _compile_app(("/items", {
            "id": Annotated[int, Identity],
            "data": Annotated[str, CustomTag("raw"), CustomFormat("custom"), NoopCap()],
            "rank": Annotated[int, CustomPriority(3), NoopCap()],
        }, []))
        _fuzz_app(app, 15)

    def test_three_entities_max_fields(self) -> None:
        """3 entities, each with many fields — multi-entity stress test."""
        app = _compile_app(
            ("/users", {
                "id": Annotated[int, Identity],
                "name": Annotated[str, MinLen(1), MaxLen(100)],
                "email": Annotated[str, Unique, MaxLen(255)],
                "age": Annotated[int, Min(0), Max(200)],
                "role": Annotated[str, OneOf("admin", "user", "mod")],
            }, []),
            ("/posts", {
                "id": Annotated[int, Identity],
                "title": Annotated[str, MinLen(1), MaxLen(200)],
                "body": str,
                "score": Annotated[int, Min(0), Max(10000)],
            }, [Paginated(10)]),
            ("/tags", {
                "id": Annotated[int, Identity],
                "label": Annotated[str, MinLen(1), MaxLen(50), Unique],
            }, []),
        )
        _check_openapi(app, ["/users", "/posts", "/tags"])
        _fuzz_app(app, 10)

    def test_extreme_bounds(self) -> None:
        """Extreme Min/Max values — boundary stress."""
        app = _compile_app(("/items", {
            "id": Annotated[int, Identity],
            "tiny": Annotated[int, Min(0), Max(1)],
            "huge": Annotated[int, Min(0), Max(2**31 - 1)],
            "micro": Annotated[str, MinLen(0), MaxLen(1)],
            "mega": Annotated[str, MaxLen(10000)],
        }, []))
        _fuzz_app(app, 15)

    def test_float_precision(self) -> None:
        """Float fields with tight bounds — tests float precision handling."""
        app = _compile_app(("/items", {
            "id": Annotated[int, Identity],
            "ratio": Annotated[float, Min(0.0), Max(1.0)],
            "small": Annotated[float, Min(0.001), Max(0.999)],
        }, []))
        _fuzz_app(app, 15)

    def test_all_fields_same_type(self) -> None:
        """All fields are strings with different constraints."""
        app = _compile_app(("/items", {
            "id": Annotated[int, Identity],
            "a": Annotated[str, MinLen(1), MaxLen(10)],
            "b": Annotated[str, MinLen(5), MaxLen(50)],
            "c": Annotated[str, OneOf("x", "y", "z")],
            "d": str,
        }, []))
        _fuzz_app(app, 15)

    def test_entity_with_pattern(self) -> None:
        """Pattern constraint on string field."""
        app = _compile_app(("/items", {
            "id": Annotated[int, Identity],
            "slug": Annotated[str, MinLen(1), MaxLen(50), Pattern(r"^[a-z0-9-]+$")],
        }, []))
        _fuzz_app(app, 15)

    def test_paginated_small_page(self) -> None:
        """Paginated(1) — extreme small page size."""
        app = _compile_app(("/items", {
            "id": Annotated[int, Identity],
            "name": str,
        }, [Paginated(1)]))
        _fuzz_app(app, 15)


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 2: RANDOM high-volume generation biased toward complexity
# ═══════════════════════════════════════════════════════════════════════════════


# All caps that can apply to each type — biased toward MORE caps per field
STR_CAPS = [MinLen(1), MaxLen(100), Unique, Doc("fuzz"), CustomTag("t"), CustomFormat("f"), NoopCap()]
INT_CAPS = [Min(0), Max(1000), ExclusiveMin(-1), ExclusiveMax(1001), MultipleOf(1), CustomPriority(1), NoopCap()]
FLOAT_CAPS = [Min(0.0), Max(100000.0), CustomPriority(2), NoopCap()]
ENUM_CAPS = [OneOf("a", "b", "c", "d", "e"), Doc("enum"), CustomTag("enum")]

TYPED_FIELDS: list[tuple[str, type, list[Any]]] = [
    ("name", str, STR_CAPS),
    ("title", str, STR_CAPS),
    ("slug", str, [MinLen(1), MaxLen(50)]),
    ("desc", str, [MaxLen(500), Doc("description")]),
    ("tag", str, ENUM_CAPS),
    ("status", str, [OneOf("on", "off")]),
    ("age", int, INT_CAPS),
    ("score", int, INT_CAPS),
    ("rank", int, [Min(1), Max(100)]),
    ("qty", int, [Min(0)]),
    ("price", float, FLOAT_CAPS),
    ("rating", float, [Min(0.0), Max(5.0)]),
    ("weight", float, FLOAT_CAPS),
    ("note", str, [NoopCap(), CustomTag("note")]),
    ("data", str, []),
]

XFORM_POOL = [Paginated(5), Paginated(10), Paginated(20), Paginated(50), Readonly()]

NAMES = ["User", "Post", "Item", "Task", "Event", "Widget",
         "Order", "Asset", "Record", "Entry", "Thing", "Note"]


@st.composite
def heavy_entity_config(draw: st.DrawFn) -> tuple[str, dict[str, Any], list[Any]]:
    """Generate ONE entity config biased toward complexity."""
    name = draw(st.sampled_from(NAMES))
    path = f"/{name.lower()}s"

    # 3-8 fields — biased toward MORE
    n = draw(st.integers(min_value=3, max_value=min(8, len(TYPED_FIELDS))))
    indices = draw(st.lists(
        st.integers(0, len(TYPED_FIELDS) - 1),
        min_size=n, max_size=n, unique=True,
    ))

    annotations: dict[str, Any] = {"id": Annotated[int, Identity]}
    for idx in indices:
        fname, ftype, cap_pool = TYPED_FIELDS[idx]
        if fname in annotations:
            continue
        # Bias: use 50-100% of available caps (NOT 0-100%)
        if cap_pool:
            min_caps = max(1, len(cap_pool) // 2)
            n_caps = draw(st.integers(min_value=min_caps, max_value=len(cap_pool)))
            caps = cap_pool[:n_caps]
            annotations[fname] = Annotated[tuple([ftype, *caps])]
        else:
            annotations[fname] = ftype

    # 0-2 transforms
    n_xforms = draw(st.integers(0, 2))
    xform_idx = draw(st.lists(st.integers(0, len(XFORM_POOL) - 1), min_size=n_xforms, max_size=n_xforms))
    seen: set[type] = set()
    xforms: list[Any] = []
    for i in xform_idx:
        t = XFORM_POOL[i]
        if type(t) not in seen:
            seen.add(type(t))
            xforms.append(t)

    return path, annotations, xforms


@st.composite
def heavy_app_config(draw: st.DrawFn) -> list[tuple[str, dict[str, Any], list[Any]]]:
    """Generate 1-3 entity app config."""
    n = draw(st.integers(1, 3))
    configs: list[tuple[str, dict[str, Any], list[Any]]] = []
    used_paths: set[str] = set()
    for _ in range(n):
        cfg = draw(heavy_entity_config())
        path = cfg[0]
        if path in used_paths:
            continue
        used_paths.add(path)
        configs.append(cfg)
    return configs if configs else [draw(heavy_entity_config())]


@pytest.mark.slow
@given(configs=heavy_app_config())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_heavy_random_no_500(configs: list[tuple[str, dict[str, Any], list[Any]]]) -> None:
    """200 random apps, each fuzzed with 10 requests/endpoint. No 500s."""
    app = _compile_app(*configs)
    _fuzz_app(app, 10)


@pytest.mark.slow
@given(configs=heavy_app_config())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_heavy_random_openapi_valid(configs: list[tuple[str, dict[str, Any], list[Any]]]) -> None:
    """100 random apps: OpenAPI schema valid, all entity paths present."""
    app = _compile_app(*configs)
    _check_openapi(app, [cfg[0] for cfg in configs])


@pytest.mark.slow
@given(configs=heavy_app_config())
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_heavy_readonly_no_mutations(configs: list[tuple[str, dict[str, Any], list[Any]]]) -> None:
    """50 random readonly apps: no mutation endpoints."""
    forced = [(path, ann, [Readonly()]) for path, ann, _ in configs]
    app = _compile_app(*forced)
    _check_no_mutations(app)
