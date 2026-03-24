from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, get_args, get_origin

from emergent.wire.axis.schema._universal import Identity, schema_meta
from emergent.wire.axis.schema.dialects.compose import Retrieve
from emergent.wire.derive import compile_derive, http_crud
from emergent.wire.derive._opspec import OpSpec, build_from_spec
from emergent.wire.derive.auth import OwnerContext, OwnerScoped


class _AuthUser:
    def __init__(self, user_id: int):
        self.id = user_id


_FakeProvider = type("FakeProvider", (), {})


@schema_meta(
    http_crud("/owned-notes", _FakeProvider),
    OwnerScoped(_AuthUser, owner_field="owner_id"),
)
@dataclass
class _OwnedNote:
    id: Annotated[int, Identity]
    owner_id: int
    title: str


def _built_spec(name: str) -> tuple[OpSpec, type, type]:
    ctx = compile_derive(_OwnedNote)[0]
    spec = next(s for s in ctx.specs if s.name == name)
    op_type, _handler, exposure = build_from_spec(spec, ctx)
    return spec, op_type, exposure.codec.request


def _assert_retrieve_owner(annotation: object) -> None:
    assert get_origin(annotation) is Annotated
    metadata = get_args(annotation)[1:]
    retrieve = next(arg for arg in metadata if isinstance(arg, Retrieve))
    assert retrieve.from_type is OwnerContext


def test_owner_scoped_update_replaces_request_owner_with_retrieve() -> None:
    spec, op_type, request_type = _built_spec("Update")

    assert tuple(name for name, *_ in spec.extra_op_fields) == ("provider",)
    _assert_retrieve_owner(request_type.__annotations__["owner_id"])

    request = request_type(id=1, owner_id=42, title="changed", provider=object())
    op = request.to_domain()

    assert isinstance(op, op_type)
    assert op.owner_id == 42


def test_owner_scoped_create_adds_owner_to_request_and_to_domain() -> None:
    spec, op_type, request_type = _built_spec("Create")

    assert "owner_id" not in spec.request_fields
    assert "owner_id" in request_type.__annotations__
    _assert_retrieve_owner(request_type.__annotations__["owner_id"])

    request = request_type(owner_id=42, title="new", provider=object())
    op = request.to_domain()

    assert isinstance(op, op_type)
    assert op.owner_id == 42


def test_owner_scoped_list_adds_owner_scope_to_request() -> None:
    _spec, op_type, request_type = _built_spec("List")

    assert "owner_id" in request_type.__annotations__
    _assert_retrieve_owner(request_type.__annotations__["owner_id"])

    request = request_type(owner_id=42, provider=object())
    op = request.to_domain()

    assert isinstance(op, op_type)
    assert op.owner_id == 42
