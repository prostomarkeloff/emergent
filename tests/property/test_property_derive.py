# pyright: reportPrivateUsage=false
"""Property-based tests for the Derive axis.

Covers DeriveCtx construction, immutability,
spec accumulation, and field inspection helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, FrozenInstanceError
from typing import Annotated

from hypothesis import given
from hypothesis import strategies as st

from emergent.wire.axis.schema import Identity, MaxLen
from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
from emergent.wire.derive._ctx import DeriveCtx


# ═══════════════════════════════════════════════════════════════════════════════
# Test-local entity types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class SimpleEntity:
    id: Annotated[int, Identity()]
    name: str


@dataclass
class MultiIdEntity:
    tenant_id: Annotated[int, Identity()]
    item_id: Annotated[int, Identity()]
    value: str
    description: str


@dataclass
class NoIdentityEntity:
    """Entity with no Identity-annotated fields."""
    label: str
    count: int


@dataclass
class AnnotatedEntity:
    """Entity with Annotated metadata on multiple fields."""
    id: Annotated[int, Identity()]
    name: Annotated[str, MaxLen(100)]
    bio: str


# ═══════════════════════════════════════════════════════════════════════════════
# Stub capability and OpSpec for accumulation tests
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class _StubCap(SurfaceCapability):
    tag: str = ""


class _StubTrigger:
    """Minimal trigger stand-in."""


class _StubTemplate:
    """Minimal handler template stand-in."""

    def build(self, spec: object) -> object:
        return lambda: None


def _make_stub_opspec(name: str) -> object:
    """Create a minimal OpSpec-like object for accumulation tests.

    We import OpSpec lazily to avoid heavy transitive deps at module level.
    """
    from emergent.wire.derive._opspec import OpSpec
    from emergent.wire.derive._project import OkResponse

    return OpSpec(
        name=name,
        entity_name="Stub",
        input_fields={},
        request_fields={},
        response_spec=OkResponse(),
        handler_template=_StubTemplate(),  # type: ignore[arg-type]
        trigger=_StubTrigger(),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. DeriveCtx.from_entity detects identity fields
# ═══════════════════════════════════════════════════════════════════════════════


def test_from_entity_detects_identity_field() -> None:
    ctx = DeriveCtx.from_entity(SimpleEntity)
    assert "id" in ctx.identity_fields
    assert len(ctx.identity_fields) == 1


def test_from_entity_detects_multiple_identity_fields() -> None:
    ctx = DeriveCtx.from_entity(MultiIdEntity)
    assert "tenant_id" in ctx.identity_fields
    assert "item_id" in ctx.identity_fields
    assert len(ctx.identity_fields) == 2


def test_from_entity_no_identity() -> None:
    ctx = DeriveCtx.from_entity(NoIdentityEntity)
    assert len(ctx.identity_fields) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. DeriveCtx.from_entity returns ctx with correct entity type
# ═══════════════════════════════════════════════════════════════════════════════


def test_from_entity_preserves_entity_type() -> None:
    ctx = DeriveCtx.from_entity(SimpleEntity)
    assert ctx.entity is SimpleEntity


def test_from_entity_preserves_entity_type_multi_id() -> None:
    ctx = DeriveCtx.from_entity(MultiIdEntity)
    assert ctx.entity is MultiIdEntity


# ═══════════════════════════════════════════════════════════════════════════════
# 3. identity_names() returns only Identity field names
# ═══════════════════════════════════════════════════════════════════════════════


def test_identity_names_simple() -> None:
    ctx = DeriveCtx.from_entity(SimpleEntity)
    names = ctx.identity_names()
    assert names == ("id",)


def test_identity_names_multi() -> None:
    ctx = DeriveCtx.from_entity(MultiIdEntity)
    names = ctx.identity_names()
    assert set(names) == {"tenant_id", "item_id"}
    assert len(names) == 2


def test_identity_names_empty_when_no_identity() -> None:
    ctx = DeriveCtx.from_entity(NoIdentityEntity)
    assert ctx.identity_names() == ()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. non_identity_fields() excludes Identity fields
# ═══════════════════════════════════════════════════════════════════════════════


def test_non_identity_fields_excludes_id() -> None:
    ctx = DeriveCtx.from_entity(SimpleEntity)
    non_id = ctx.non_identity_fields()
    assert "id" not in non_id
    assert "name" in non_id


def test_non_identity_fields_multi_id() -> None:
    ctx = DeriveCtx.from_entity(MultiIdEntity)
    non_id = ctx.non_identity_fields()
    assert "tenant_id" not in non_id
    assert "item_id" not in non_id
    assert "value" in non_id
    assert "description" in non_id


def test_non_identity_fields_no_identity_returns_all() -> None:
    ctx = DeriveCtx.from_entity(NoIdentityEntity)
    non_id = ctx.non_identity_fields()
    assert set(non_id.keys()) == {"label", "count"}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. DeriveCtx immutability: add_spec returns new ctx, original unchanged
# ═══════════════════════════════════════════════════════════════════════════════


def test_add_spec_returns_new_ctx() -> None:
    ctx = DeriveCtx.from_entity(SimpleEntity)
    spec = _make_stub_opspec("Create")
    ctx2 = ctx.add_spec(spec)  # type: ignore[arg-type]
    # Original unchanged.
    assert len(ctx.specs) == 0
    # New context has the spec.
    assert len(ctx2.specs) == 1


def test_add_spec_is_frozen() -> None:
    ctx = DeriveCtx.from_entity(SimpleEntity)
    try:
        ctx.specs = ()  # type: ignore[misc]
        raise AssertionError("Expected FrozenInstanceError")
    except FrozenInstanceError:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# 6. DeriveCtx immutability: add_capability returns new ctx
# ═══════════════════════════════════════════════════════════════════════════════


def test_add_capability_returns_new_ctx() -> None:
    ctx = DeriveCtx.from_entity(SimpleEntity)
    cap = _StubCap(tag="auth")
    ctx2 = ctx.add_capability(cap)
    assert len(ctx.capabilities) == 0
    assert len(ctx2.capabilities) == 1
    assert ctx2.capabilities[0] is cap


def test_add_capability_preserves_existing() -> None:
    ctx = DeriveCtx.from_entity(SimpleEntity)
    cap1 = _StubCap(tag="a")
    cap2 = _StubCap(tag="b")
    ctx2 = ctx.add_capability(cap1).add_capability(cap2)
    assert len(ctx2.capabilities) == 2
    assert ctx2.capabilities[0] is cap1
    assert ctx2.capabilities[1] is cap2


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Spec accumulation: adding N specs produces ctx with N specs
# ═══════════════════════════════════════════════════════════════════════════════


@given(n=st.integers(min_value=0, max_value=20))
def test_spec_accumulation_count(n: int) -> None:
    ctx = DeriveCtx.from_entity(SimpleEntity)
    for i in range(n):
        spec = _make_stub_opspec(f"Op{i}")
        ctx = ctx.add_spec(spec)  # type: ignore[arg-type]
    assert len(ctx.specs) == n


@given(n=st.integers(min_value=1, max_value=10))
def test_spec_accumulation_preserves_order(n: int) -> None:
    ctx = DeriveCtx.from_entity(SimpleEntity)
    names: list[str] = []
    for i in range(n):
        name = f"Op{i}"
        names.append(name)
        spec = _make_stub_opspec(name)
        ctx = ctx.add_spec(spec)  # type: ignore[arg-type]
    for i, spec in enumerate(ctx.specs):
        assert spec.name == names[i]


# ═══════════════════════════════════════════════════════════════════════════════
# 8. annotated_field_types() preserves Annotated metadata
# ═══════════════════════════════════════════════════════════════════════════════


def test_annotated_field_types_preserves_metadata() -> None:
    ctx = DeriveCtx.from_entity(AnnotatedEntity)
    annotated = ctx.annotated_field_types()
    # 'id' has Identity capability -> should be Annotated
    # 'name' has MaxLen(100) -> should be Annotated
    # 'bio' has no capabilities -> plain type
    assert annotated["bio"] is str
    # Fields with capabilities should NOT be plain str/int
    # They should be Annotated[base_type, ...] which is not `is str`
    assert annotated["name"] is not str


def test_annotated_field_types_exclude() -> None:
    ctx = DeriveCtx.from_entity(AnnotatedEntity)
    annotated = ctx.annotated_field_types(exclude=("id",))
    assert "id" not in annotated
    assert "name" in annotated
    assert "bio" in annotated


def test_annotated_field_types_only() -> None:
    ctx = DeriveCtx.from_entity(AnnotatedEntity)
    annotated = ctx.annotated_field_types(only={"name", "bio"})
    assert "id" not in annotated
    assert "name" in annotated
    assert "bio" in annotated
