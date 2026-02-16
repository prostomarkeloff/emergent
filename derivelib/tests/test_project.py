"""Tests for derivelib._project — field projections and response specs."""

from __future__ import annotations

from kungfu import Error, Ok

from derivelib._project import (
    AllFields,
    CountResponse,
    EmptyResponse,
    EntityResponse,
    ExcludeFields,
    ExcludeFromProjection,
    IdOnly,
    ListResponse,
    MergeProjection,
    NoFields,
    NonId,
    OkResponse,
    OptionalNonId,
    RequiredNonId,
    SelectFields,
    all_fields,
    entity_response,
    exclude,
    exclude_from,
    fields,
    id_only,
    list_response,
    merge,
    no_fields,
    non_id,
    ok_response,
    optional_non_id,
    required_non_id,
)

from .conftest import Post, User, composite_schema, post_schema, user_schema


# ═══════════════════════════════════════════════════════════════════════════════
# Field Projections
# ═══════════════════════════════════════════════════════════════════════════════


class TestAllFields:
    def test_returns_all(self) -> None:
        schema = user_schema()
        result = AllFields().project(schema)
        assert set(result.keys()) == {"id", "name", "email"}

    def test_types(self) -> None:
        schema = user_schema()
        result = AllFields().project(schema)
        assert result["id"] is int
        assert result["name"] is str


class TestIdOnly:
    def test_single_id(self) -> None:
        schema = user_schema()
        result = IdOnly().project(schema)
        assert set(result.keys()) == {"id"}

    def test_composite_id(self) -> None:
        schema = composite_schema()
        result = IdOnly().project(schema)
        assert set(result.keys()) == {"tenant_id", "user_id"}


class TestNonId:
    def test_excludes_identity(self) -> None:
        schema = user_schema()
        result = NonId().project(schema)
        assert "id" not in result
        assert set(result.keys()) == {"name", "email"}


class TestNoFields:
    def test_empty(self) -> None:
        schema = user_schema()
        result = NoFields().project(schema)
        assert len(result) == 0


class TestRequiredNonId:
    def test_excludes_defaults(self) -> None:
        schema = post_schema()
        result = RequiredNonId().project(schema)
        assert "id" not in result
        assert "published" not in result
        assert "title" in result
        assert "body" in result


class TestSelectFields:
    def test_selects_named(self) -> None:
        schema = user_schema()
        result = SelectFields(names=("name",)).project(schema)
        assert set(result.keys()) == {"name"}

    def test_ignores_missing(self) -> None:
        schema = user_schema()
        result = SelectFields(names=("name", "nonexistent")).project(schema)
        assert set(result.keys()) == {"name"}


class TestExcludeFields:
    def test_excludes_named(self) -> None:
        schema = user_schema()
        result = ExcludeFields(names=("id",)).project(schema)
        assert "id" not in result
        assert "name" in result
        assert "email" in result


class TestOptionalNonId:
    def test_makes_optional(self) -> None:
        schema = user_schema()
        result = OptionalNonId().project(schema)
        assert "id" not in result
        for name, typ in result.items():
            assert type(None) in (typ.__args__ if hasattr(typ, "__args__") else [])


class TestMergeProjection:
    def test_merges_two(self) -> None:
        schema = user_schema()
        result = MergeProjection(IdOnly(), NonId()).project(schema)
        assert set(result.keys()) == {"id", "name", "email"}


class TestExcludeFromProjection:
    def test_wraps_inner(self) -> None:
        schema = user_schema()
        result = ExcludeFromProjection(NonId(), ("email",)).project(schema)
        assert "name" in result
        assert "email" not in result
        assert "id" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Convenience Constructors
# ═══════════════════════════════════════════════════════════════════════════════


class TestConvenience:
    def test_all_fields(self) -> None:
        assert isinstance(all_fields(), AllFields)

    def test_id_only(self) -> None:
        assert isinstance(id_only(), IdOnly)

    def test_non_id(self) -> None:
        assert isinstance(non_id(), NonId)

    def test_no_fields(self) -> None:
        assert isinstance(no_fields(), NoFields)

    def test_required_non_id(self) -> None:
        assert isinstance(required_non_id(), RequiredNonId)

    def test_fields_constructor(self) -> None:
        proj = fields("name", "email")
        assert isinstance(proj, SelectFields)
        assert proj.names == ("name", "email")

    def test_exclude_constructor(self) -> None:
        proj = exclude("id")
        assert isinstance(proj, ExcludeFields)

    def test_exclude_from_constructor(self) -> None:
        proj = exclude_from(non_id(), "email")
        assert isinstance(proj, ExcludeFromProjection)

    def test_merge_constructor(self) -> None:
        proj = merge(id_only(), non_id())
        assert isinstance(proj, MergeProjection)

    def test_optional_non_id_constructor(self) -> None:
        assert isinstance(optional_non_id(), OptionalNonId)


# ═══════════════════════════════════════════════════════════════════════════════
# Response Specs
# ═══════════════════════════════════════════════════════════════════════════════


class TestEntityResponse:
    def test_resolve_fields(self) -> None:
        schema = user_schema()
        field_specs, _converter = EntityResponse().resolve(schema)
        names = [f[0] for f in field_specs]
        assert "id" in names
        assert "name" in names
        assert "email" in names

    def test_resolve_with_exclude(self) -> None:
        schema = user_schema()
        field_specs, _converter = EntityResponse(exclude=("email",)).resolve(schema)
        names = [f[0] for f in field_specs]
        assert "email" not in names
        assert "id" in names

    def test_converter_ok(self) -> None:
        schema = user_schema()
        field_specs, converter = EntityResponse().resolve(schema)
        from derivelib._codegen import create_dataclass

        ResponseType = create_dataclass("UserResp", field_specs)
        user = User(id=1, name="Alice", email="alice@example.com")
        result = converter(ResponseType, Ok(user))
        assert result.id == 1
        assert result.name == "Alice"

    def test_converter_error(self) -> None:
        from derivelib._errors import NotFound
        schema = user_schema()
        _, converter = EntityResponse().resolve(schema)
        from derivelib._codegen import create_dataclass

        ResponseType = create_dataclass("UserResp", [("id", int), ("name", str), ("email", str)])
        err = NotFound(entity="User", id={"id": 99})
        result = converter(ResponseType, Error(err))
        assert isinstance(result, NotFound)


class TestListResponse:
    def test_resolve_fields(self) -> None:
        schema = user_schema()
        field_specs, _ = ListResponse().resolve(schema)
        assert field_specs[0][0] == "items"

    def test_converter_ok(self) -> None:
        schema = user_schema()
        field_specs, converter = ListResponse().resolve(schema)
        from derivelib._codegen import create_dataclass
        ResponseType = create_dataclass("ListResp", field_specs)

        users = [User(id=1, name="A", email="a@b"), User(id=2, name="B", email="b@c")]
        result = converter(ResponseType, Ok(users))
        assert len(result.items) == 2


class TestOkResponse:
    def test_resolve_fields(self) -> None:
        schema = user_schema()
        field_specs, _ = OkResponse().resolve(schema)
        assert field_specs[0][0] == "success"

    def test_converter_ok(self) -> None:
        schema = user_schema()
        field_specs, converter = OkResponse().resolve(schema)
        from derivelib._codegen import create_dataclass
        ResponseType = create_dataclass("OkResp", field_specs)
        result = converter(ResponseType, Ok(True))
        assert result.success is True


class TestCountResponse:
    def test_resolve_fields(self) -> None:
        schema = user_schema()
        field_specs, _ = CountResponse().resolve(schema)
        assert field_specs[0][0] == "count"

    def test_converter_ok(self) -> None:
        schema = user_schema()
        field_specs, converter = CountResponse().resolve(schema)
        from derivelib._codegen import create_dataclass
        ResponseType = create_dataclass("CountResp", field_specs)
        result = converter(ResponseType, Ok(42))
        assert result.count == 42


class TestEmptyResponse:
    def test_resolve_fields(self) -> None:
        schema = user_schema()
        field_specs, _ = EmptyResponse().resolve(schema)
        assert len(field_specs) == 1
