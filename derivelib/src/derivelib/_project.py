"""Field projections and response specs — THE derivation building blocks.

Projections describe which entity fields to include in derived types.
Response specs describe the shape of response types.

These are axis-agnostic primitives. Any derivation dialect uses them.

    from derivelib._project import all_fields, id_only, non_id, entity_response

    DeriveOp("Get", id_only(), entity_response(), ...)
    DeriveOp("List", no_fields(), list_response(), ...)
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from kungfu import Result

from derivelib._codegen import AnnotationValue, FieldSpec, HasAnnotations
from derivelib._ctx import SchemaCtx


# ═══════════════════════════════════════════════════════════════════════════════
# FieldProjection — entity fields → field subset
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class FieldProjection(Protocol):
    """Project entity fields → field subset for derived types."""

    def project[EntityT](self, schema: SchemaCtx[EntityT]) -> Mapping[str, AnnotationValue]: ...


@dataclass(frozen=True, slots=True)
class AllFields:
    """All entity fields."""

    def project[EntityT](self, schema: SchemaCtx[EntityT]) -> Mapping[str, AnnotationValue]:
        return schema.field_types()


@dataclass(frozen=True, slots=True)
class IdOnly:
    """All identity fields (supports composite keys)."""

    def project[EntityT](self, schema: SchemaCtx[EntityT]) -> Mapping[str, AnnotationValue]:
        return {name: info.base_type for name, info in schema.identity_fields.items()}


@dataclass(frozen=True, slots=True)
class NonId:
    """All fields except identity (supports composite keys)."""

    def project[EntityT](self, schema: SchemaCtx[EntityT]) -> Mapping[str, AnnotationValue]:
        return {
            name: info.base_type
            for name, info in schema.fields.items()
            if name not in schema.identity_fields
        }


@dataclass(frozen=True, slots=True)
class NoFields:
    """Empty — no fields."""

    def project[EntityT](self, schema: SchemaCtx[EntityT]) -> Mapping[str, AnnotationValue]:
        return {}


@dataclass(frozen=True, slots=True)
class RequiredNonId:
    """Non-identity fields without defaults — user-provided input.

    Structurally: fields the user MUST provide.
    Identity is auto-assigned, defaulted fields are server-managed.
    """

    def project[EntityT](self, schema: SchemaCtx[EntityT]) -> Mapping[str, AnnotationValue]:
        return {
            name: info.base_type
            for name, info in schema.fields.items()
            if name not in schema.identity_fields and not info.has_default
        }


@dataclass(frozen=True, slots=True)
class ExcludeFromProjection:
    """Wrap a projection, excluding named fields from result.

    Used to remove auto-managed fields (timestamps, versions) from
    request types while preserving the inner projection's logic.

        ExcludeFromProjection(non_id(), ("created_at", "updated_at"))
    """

    inner: FieldProjection
    names: tuple[str, ...]

    def project[EntityT](self, schema: SchemaCtx[EntityT]) -> Mapping[str, AnnotationValue]:
        result = self.inner.project(schema)
        return {k: v for k, v in result.items() if k not in self.names}


@dataclass(frozen=True, slots=True)
class SelectFields:
    """Select specific fields by name."""

    names: tuple[str, ...]

    def project[EntityT](self, schema: SchemaCtx[EntityT]) -> Mapping[str, AnnotationValue]:
        return {
            name: info.base_type
            for name, info in schema.fields.items()
            if name in self.names
        }


@dataclass(frozen=True, slots=True)
class ExcludeFields:
    """All fields except named ones."""

    names: tuple[str, ...]

    def project[EntityT](self, schema: SchemaCtx[EntityT]) -> Mapping[str, AnnotationValue]:
        return {
            name: info.base_type
            for name, info in schema.fields.items()
            if name not in self.names
        }


@dataclass(frozen=True, slots=True)
class OptionalNonId:
    """Non-identity fields, all wrapped in Optional[type].

    For PATCH endpoints — user sends only fields they want to change.
    Fields not provided (None) keep their existing value.

        DeriveOp("Patch", merge(id_only(), optional_non_id()), ...)
    """

    def project[EntityT](self, schema: SchemaCtx[EntityT]) -> Mapping[str, AnnotationValue]:
        return {
            name: info.base_type | None
            for name, info in schema.fields.items()
            if name not in schema.identity_fields
        }


@dataclass(frozen=True, slots=True)
class MergeProjection:
    """Union of two projections.

    Fields from both projections are included. On collision, right wins.

        merge(id_only(), optional_non_id())  # identity (required) + others (optional)
    """

    left: FieldProjection
    right: FieldProjection

    def project[EntityT](self, schema: SchemaCtx[EntityT]) -> Mapping[str, AnnotationValue]:
        return {**self.left.project(schema), **self.right.project(schema)}


# ═══════════════════════════════════════════════════════════════════════════════
# ResponseSpec — response shape (more flexible than projection)
# ═══════════════════════════════════════════════════════════════════════════════


# Response converter: (response_cls, domain_result) → response_instance.
# WHY Callable[..., HasAnnotations]: response classes are generated at derive time via
# make_dataclass; the converter's concrete signature (cls, Result[T, E]) → response
# depends on the dynamically-generated types — not expressible statically.
type ResponseConverter = Callable[..., HasAnnotations]

# (field_specs for make_dataclass, converter function)
type ResolvedResponse = tuple[list[FieldSpec], ResponseConverter]


@runtime_checkable
class ResponseSpec(Protocol):
    """Describe response shape — fields + converter."""

    def resolve[EntityT](self, schema: SchemaCtx[EntityT]) -> ResolvedResponse: ...


def response_fields[EntityT](spec: ResponseSpec, schema: SchemaCtx[EntityT]) -> list[FieldSpec]:
    """Extract field specs from a ResponseSpec. Pure data accessor."""
    fields, _ = spec.resolve(schema)
    return fields


def response_converter[EntityT](spec: ResponseSpec, schema: SchemaCtx[EntityT]) -> ResponseConverter:
    """Extract converter from a ResponseSpec. Pure data accessor."""
    _, converter = spec.resolve(schema)
    return converter


# WHY generic ok/error: callbacks receive unwrapped Result values
# whose types depend on the handler at derive time (entity, list[entity], dict, int, etc.).
# Generic OkT/ErrT let pyright infer lambda parameter types from context.
def _result_converter[OkT, ErrT](
    *, ok: Callable[[type, OkT], HasAnnotations], error: Callable[[type, ErrT], HasAnnotations],
) -> ResponseConverter:
    """Build Result[T, E] -> Response converter from Ok/Error handlers.

    Eliminates repeated match/case boilerplate in ResponseSpec resolvers.
    """
    def converter(cls: type, result: Result[OkT, ErrT]) -> HasAnnotations:
        from kungfu import Error as Err, Ok

        match result:
            case Ok(val):
                return ok(cls, val)
            case Err(err):
                return error(cls, err)
            case _:
                raise TypeError(f"Expected Result, got {type(result)}")

    return converter


@dataclass(frozen=True, slots=True)
class EntityResponse:
    """Response = entity fields (for get/create/update).

    Optional exclude filters fields from both schema and converter::

        EntityResponse()                         # all fields
        EntityResponse(exclude=("active_at",))   # all except active_at
    """

    exclude: tuple[str, ...] = ()

    def resolve[EntityT](self, schema: SchemaCtx[EntityT]) -> ResolvedResponse:
        field_types = schema.annotated_field_types(exclude=self.exclude)
        field_specs: list[FieldSpec] = list(field_types.items())
        field_names = list(field_types.keys())
        converter = _result_converter(
            ok=lambda cls, entity: cls(**{f: getattr(entity, f) for f in field_names}),
            error=lambda _cls, err: err,
        )
        return field_specs, converter


@dataclass(frozen=True, slots=True)
class ListResponse:
    """Response = {"items": list[entity]} (for list operations).

    Optional exclude creates a projected view type::

        ListResponse()                         # items = list[Entity]
        ListResponse(exclude=("active_at",))   # items = list[EntityView] without active_at
    """

    exclude: tuple[str, ...] = ()

    def resolve[EntityT](self, schema: SchemaCtx[EntityT]) -> ResolvedResponse:
        if self.exclude:
            from derivelib._codegen import create_dataclass

            field_types = schema.annotated_field_types(exclude=self.exclude)
            names = list(field_types.keys())
            view_type = create_dataclass(
                f"{schema.entity.__name__}View",
                list(field_types.items()),
            )
            field_specs: list[FieldSpec] = [("items", list[view_type])]
            _vt = view_type
            _ns = names

            def _view_ok(cls: type, items: Sequence[HasAnnotations]) -> HasAnnotations:
                return cls(items=[_vt(**{f: getattr(e, f) for f in _ns}) for e in items])

            converter = _result_converter(
                ok=_view_ok,
                error=lambda cls, _: cls(items=[]),
            )
            return field_specs, converter

        entity = schema.entity
        field_specs = [("items", list[entity])]
        converter = _result_converter(
            ok=lambda cls, items: cls(items=items),
            error=lambda cls, _: cls(items=[]),
        )
        return field_specs, converter


@dataclass(frozen=True, slots=True)
class OkResponse:
    """Response = {"success": bool} (for delete/action operations)."""

    def resolve[EntityT](self, schema: SchemaCtx[EntityT]) -> ResolvedResponse:
        field_specs: list[FieldSpec] = [("success", bool, True)]
        converter = _result_converter(
            ok=lambda cls, _: cls(success=True),
            error=lambda _cls, err: err,
        )
        return field_specs, converter


@dataclass(frozen=True, slots=True)
class PaginatedResponse:
    """Response = {items, total, page, page_size} (for paginated list operations)."""

    def resolve[EntityT](self, schema: SchemaCtx[EntityT]) -> ResolvedResponse:
        entity = schema.entity
        field_specs: list[FieldSpec] = [
            ("items", list[entity]),
            ("total", int),
            ("page", int),
            ("page_size", int),
        ]

        def _paginated_ok(cls: type, data: Mapping[str, int | Sequence[int]] | Sequence[int]) -> HasAnnotations:
            if isinstance(data, Mapping):
                return cls(
                    items=data.get("items", []),
                    total=data.get("total", 0),
                    page=data.get("page", 1),
                    page_size=data.get("page_size", 20),
                )
            return cls(items=data if isinstance(data, list) else [data], total=0, page=1, page_size=20)

        converter = _result_converter(
            ok=_paginated_ok,
            error=lambda cls, _: cls(items=[], total=0, page=1, page_size=20),
        )
        return field_specs, converter


@dataclass(frozen=True, slots=True)
class CountResponse:
    """Response = {"count": int} — for count-only endpoints."""

    def resolve[EntityT](self, schema: SchemaCtx[EntityT]) -> ResolvedResponse:
        field_specs: list[FieldSpec] = [("count", int)]
        converter = _result_converter(
            ok=lambda cls, val: cls(count=val),
            error=lambda _cls, err: err,
        )
        return field_specs, converter


@dataclass(frozen=True, slots=True)
class EmptyResponse:
    """Response = empty (204 No Content semantics).

    Generates a type with a single hidden bool field for dataclass compatibility.
    """

    def resolve[EntityT](self, schema: SchemaCtx[EntityT]) -> ResolvedResponse:
        field_specs: list[FieldSpec] = [("success", bool, True)]
        converter = _result_converter(
            ok=lambda cls, _: cls(),
            error=lambda _cls, err: err,
        )
        return field_specs, converter


@dataclass(frozen=True, slots=True)
class CursorPaginatedResponse:
    """Response = {items, next_cursor, has_more} — cursor-based pagination."""

    def resolve[EntityT](self, schema: SchemaCtx[EntityT]) -> ResolvedResponse:
        entity = schema.entity
        field_specs: list[FieldSpec] = [
            ("items", list[entity]),
            ("next_cursor", str | None),
            ("has_more", bool),
        ]

        def _cursor_ok(cls: type, data: Mapping[str, str | bool | Sequence[str] | None] | Sequence[str]) -> HasAnnotations:
            if isinstance(data, Mapping):
                return cls(
                    items=data.get("items", []),
                    next_cursor=data.get("next_cursor"),
                    has_more=data.get("has_more", False),
                )
            return cls(
                items=data if isinstance(data, list) else [data],
                next_cursor=None,
                has_more=False,
            )

        converter = _result_converter(
            ok=_cursor_ok,
            error=lambda cls, _: cls(items=[], next_cursor=None, has_more=False),
        )
        return field_specs, converter


def dict_converter[T, E](cls: type, result: Result[T, E]) -> HasAnnotations:
    """Convert Result[dict|obj, E] → response dataclass.

    Ok(dict) → cls(**dict).
    Ok(obj) → cls(**{field: getattr(obj, field)}).
    Error → passthrough (for error transform capabilities).

    Use with ExposureBuilder.response_converter() in custom surface steps::

        exposure("create", entity)
            .request(**fields).response(id=int, status=str)
            .response_converter(dict_converter)
            .handler(handler).trigger(...)
            .build()
    """
    from kungfu import Error as Err, Ok

    match result:
        case Ok(val):
            if isinstance(val, dict):
                return cls(**val)
            dc_fields: dict[str, type] = getattr(cls, "__dataclass_fields__", {})
            return cls(**{f: getattr(val, f, None) for f in dc_fields})
        case Err(err):
            return err
        case _:
            raise TypeError(f"Expected Result, got {type(result)}")


@dataclass(frozen=True, slots=True)
class CustomResponse:
    """Response with explicit fields + converter."""

    field_specs: tuple[FieldSpec, ...]
    converter: ResponseConverter

    def resolve[EntityT](self, schema: SchemaCtx[EntityT]) -> ResolvedResponse:
        return list(self.field_specs), self.converter


# ═══════════════════════════════════════════════════════════════════════════════
# Convenience Constructors
# ═══════════════════════════════════════════════════════════════════════════════


def all_fields() -> AllFields:
    return AllFields()


def id_only() -> IdOnly:
    return IdOnly()


def non_id() -> NonId:
    return NonId()


def no_fields() -> NoFields:
    return NoFields()


def required_non_id() -> RequiredNonId:
    return RequiredNonId()


def fields(*names: str) -> SelectFields:
    return SelectFields(names=names)


def exclude_from(inner: FieldProjection, *names: str) -> ExcludeFromProjection:
    """Wrap projection, excluding named fields."""
    return ExcludeFromProjection(inner=inner, names=names)


def exclude(*names: str) -> ExcludeFields:
    return ExcludeFields(names=names)


def entity_response() -> EntityResponse:
    return EntityResponse()


def list_response() -> ListResponse:
    return ListResponse()


def ok_response() -> OkResponse:
    return OkResponse()


def paginated_response() -> PaginatedResponse:
    return PaginatedResponse()


def optional_non_id() -> OptionalNonId:
    return OptionalNonId()


def merge(left: FieldProjection, right: FieldProjection) -> MergeProjection:
    return MergeProjection(left=left, right=right)


def custom_response(
    field_specs: tuple[FieldSpec, ...],
    converter: ResponseConverter,
) -> CustomResponse:
    return CustomResponse(field_specs=field_specs, converter=converter)


def count_response() -> CountResponse:
    return CountResponse()


def empty_response() -> EmptyResponse:
    return EmptyResponse()


def cursor_paginated_response() -> CursorPaginatedResponse:
    return CursorPaginatedResponse()


__all__ = (
    # Protocols
    "FieldProjection",
    "ResponseSpec",
    "ResolvedResponse",
    # Projections
    "AllFields",
    "IdOnly",
    "NonId",
    "RequiredNonId",
    "NoFields",
    "ExcludeFromProjection",
    "SelectFields",
    "ExcludeFields",
    "OptionalNonId",
    "MergeProjection",
    # Response accessors
    "response_fields",
    "response_converter",
    # Response specs
    "EntityResponse",
    "ListResponse",
    "OkResponse",
    "PaginatedResponse",
    "CountResponse",
    "EmptyResponse",
    "CursorPaginatedResponse",
    "CustomResponse",
    # Converters
    "dict_converter",
    # Constructors
    "all_fields",
    "id_only",
    "non_id",
    "required_non_id",
    "no_fields",
    "exclude_from",
    "fields",
    "exclude",
    "optional_non_id",
    "merge",
    "entity_response",
    "list_response",
    "ok_response",
    "paginated_response",
    "count_response",
    "empty_response",
    "cursor_paginated_response",
    "custom_response",
)
