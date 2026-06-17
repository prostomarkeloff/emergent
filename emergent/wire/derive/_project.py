"""Field projections and response specs — derivation building blocks.

Projections describe which entity fields to include in derived types.
Response specs describe the shape of response types.

KEY DIFFERENCE from derivelib: project()/resolve() take DeriveCtx, not SchemaCtx.
No bridging needed — DeriveCtx has the same field/identity interface.

    from emergent.wire.derive._project import all_fields, id_only, entity_response
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from kungfu import Result

from emergent.wire.derive._codegen import AnnotationValue, FieldSpec, HasAnnotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from emergent.wire.derive._ctx import DeriveCtx


type FieldMap = Mapping[str, AnnotationValue]
type PaginationData = Mapping[str, Any] | Sequence[Any]


# ═══════════════════════════════════════════════════════════════════════════════
# FieldProjection — entity fields → field subset
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class FieldProjection(Protocol):
    """Project entity fields → field subset for derived types."""

    def project[EntityT](self, ctx: DeriveCtx[EntityT]) -> FieldMap: ...


@dataclass(frozen=True, slots=True)
class AllFields:
    """All entity fields."""

    def project[EntityT](self, ctx: DeriveCtx[EntityT]) -> FieldMap:
        return ctx.field_types()


@dataclass(frozen=True, slots=True)
class IdOnly:
    """All identity fields (supports composite keys)."""

    def project[EntityT](self, ctx: DeriveCtx[EntityT]) -> FieldMap:
        return {name: info.base_type for name, info in ctx.identity_fields.items()}


@dataclass(frozen=True, slots=True)
class NonId:
    """All fields except identity."""

    def project[EntityT](self, ctx: DeriveCtx[EntityT]) -> FieldMap:
        return {
            name: info.base_type
            for name, info in ctx.fields.items()
            if name not in ctx.identity_fields
        }


@dataclass(frozen=True, slots=True)
class NoFields:
    """Empty — no fields."""

    def project[EntityT](self, ctx: DeriveCtx[EntityT]) -> FieldMap:
        return {}


@dataclass(frozen=True, slots=True)
class RequiredNonId:
    """Non-identity fields without defaults — user-provided input."""

    def project[EntityT](self, ctx: DeriveCtx[EntityT]) -> FieldMap:
        return {
            name: info.base_type
            for name, info in ctx.fields.items()
            if name not in ctx.identity_fields and not info.has_default
        }


@dataclass(frozen=True, slots=True)
class ExcludeFromProjection:
    """Wrap a projection, excluding named fields from result."""

    inner: FieldProjection
    names: tuple[str, ...]

    def project[EntityT](self, ctx: DeriveCtx[EntityT]) -> FieldMap:
        result = self.inner.project(ctx)
        return {k: v for k, v in result.items() if k not in self.names}


@dataclass(frozen=True, slots=True)
class SelectFields:
    """Select specific fields by name."""

    names: tuple[str, ...]

    def project[EntityT](self, ctx: DeriveCtx[EntityT]) -> FieldMap:
        return {
            name: info.base_type
            for name, info in ctx.fields.items()
            if name in self.names
        }


@dataclass(frozen=True, slots=True)
class ExcludeFields:
    """All fields except named ones."""

    names: tuple[str, ...]

    def project[EntityT](self, ctx: DeriveCtx[EntityT]) -> FieldMap:
        return {
            name: info.base_type
            for name, info in ctx.fields.items()
            if name not in self.names
        }


@dataclass(frozen=True, slots=True)
class OptionalNonId:
    """Non-identity fields, all wrapped in Optional[type]. For PATCH endpoints."""

    def project[EntityT](self, ctx: DeriveCtx[EntityT]) -> FieldMap:
        return {
            name: info.base_type | None
            for name, info in ctx.fields.items()
            if name not in ctx.identity_fields
        }


@dataclass(frozen=True, slots=True)
class MergeProjection:
    """Union of two projections. On collision, right wins."""

    left: FieldProjection
    right: FieldProjection

    def project[EntityT](self, ctx: DeriveCtx[EntityT]) -> FieldMap:
        return {**self.left.project(ctx), **self.right.project(ctx)}


# ═══════════════════════════════════════════════════════════════════════════════
# ResponseSpec — response shape
# ═══════════════════════════════════════════════════════════════════════════════


type ResponseConverter = Callable[..., HasAnnotations]
type ResolvedResponse = tuple[list[FieldSpec], ResponseConverter]


@runtime_checkable
class ResponseProjection(Protocol):
    """Separate protocol: which fields to include in the response type.

    Query axis concern — independent of how to serialize.
    """

    def project_response[EntityT](self, ctx: DeriveCtx[EntityT]) -> list[FieldSpec]: ...


@runtime_checkable
class ResponseConverterProto(Protocol):
    """Separate protocol: how to convert domain Result to response type.

    Surface axis concern — independent of which fields.
    """

    def build_converter[EntityT](self, ctx: DeriveCtx[EntityT]) -> ResponseConverter: ...


@runtime_checkable
class ResponseSpec(Protocol):
    """Describe response shape — fields + converter. Original unified protocol."""

    def resolve[EntityT](self, ctx: DeriveCtx[EntityT]) -> ResolvedResponse: ...


@dataclass(frozen=True, slots=True)
class ComposedResponseSpec:
    """Compose separate projection and converter into a ResponseSpec."""

    projection: ResponseProjection
    converter: ResponseConverterProto

    def resolve[EntityT](self, ctx: DeriveCtx[EntityT]) -> ResolvedResponse:
        fields = self.projection.project_response(ctx)
        conv = self.converter.build_converter(ctx)
        return fields, conv


def response_fields[EntityT](spec: ResponseSpec, ctx: DeriveCtx[EntityT]) -> list[FieldSpec]:
    """Extract field specs from a ResponseSpec."""
    fields, _ = spec.resolve(ctx)
    return fields


def response_converter[EntityT](spec: ResponseSpec, ctx: DeriveCtx[EntityT]) -> ResponseConverter:
    """Extract converter from a ResponseSpec."""
    _, converter = spec.resolve(ctx)
    return converter


def _result_converter[OkT, ErrT](
    *, ok: Callable[[type, OkT], HasAnnotations], error: Callable[[type, ErrT], HasAnnotations],
) -> ResponseConverter:
    """Build Result[T, E] -> Response converter from Ok/Error handlers."""
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
    """Response = entity fields (for get/create/update)."""

    exclude: tuple[str, ...] = ()

    def resolve[EntityT](self, ctx: DeriveCtx[EntityT]) -> ResolvedResponse:
        field_types = ctx.annotated_field_types(exclude=self.exclude)
        field_specs: list[FieldSpec] = list(field_types.items())
        field_names = list(field_types.keys())
        converter = _result_converter(
            ok=lambda cls, entity: cls(**{f: getattr(entity, f) for f in field_names}),
            error=lambda _cls, err: err,
        )
        return field_specs, converter


@dataclass(frozen=True, slots=True)
class ListResponse:
    """Response = {"items": list[entity]}."""

    exclude: tuple[str, ...] = ()

    def resolve[EntityT](self, ctx: DeriveCtx[EntityT]) -> ResolvedResponse:
        if self.exclude:
            from emergent.wire.derive._codegen import create_dataclass

            field_types = ctx.annotated_field_types(exclude=self.exclude)
            names = list(field_types.keys())
            view_type = create_dataclass(
                f"{ctx.entity.__name__}View",
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

        entity = ctx.entity
        field_specs = [("items", list[entity])]
        converter = _result_converter(
            ok=lambda cls, items: cls(items=items),
            error=lambda cls, _: cls(items=[]),
        )
        return field_specs, converter


@dataclass(frozen=True, slots=True)
class OkResponse:
    """Response = {"success": bool}."""

    def resolve[EntityT](self, ctx: DeriveCtx[EntityT]) -> ResolvedResponse:
        field_specs: list[FieldSpec] = [("success", bool, True)]
        converter = _result_converter(
            ok=lambda cls, _: cls(success=True),
            error=lambda _cls, err: err,
        )
        return field_specs, converter


@dataclass(frozen=True, slots=True)
class PaginatedResponse:
    """Response = {items, total, page, page_size}."""

    def resolve[EntityT](self, ctx: DeriveCtx[EntityT]) -> ResolvedResponse:
        entity = ctx.entity
        field_specs: list[FieldSpec] = [
            ("items", list[entity]),
            ("total", int),
            ("page", int),
            ("page_size", int),
        ]

        def _paginated_ok(cls: type, data: PaginationData) -> HasAnnotations:
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
    """Response = {"count": int}."""

    def resolve[EntityT](self, ctx: DeriveCtx[EntityT]) -> ResolvedResponse:
        field_specs: list[FieldSpec] = [("count", int)]
        converter = _result_converter(
            ok=lambda cls, val: cls(count=val),
            error=lambda _cls, err: err,
        )
        return field_specs, converter


@dataclass(frozen=True, slots=True)
class BoolResponse:
    """Response = {"exists": bool}."""

    def resolve[EntityT](self, ctx: DeriveCtx[EntityT]) -> ResolvedResponse:
        field_specs: list[FieldSpec] = [("exists", bool)]
        converter = _result_converter(
            ok=lambda cls, val: cls(exists=val),
            error=lambda _cls, err: err,
        )
        return field_specs, converter


@dataclass(frozen=True, slots=True)
class EmptyResponse:
    """Response = empty (204 No Content semantics)."""

    def resolve[EntityT](self, ctx: DeriveCtx[EntityT]) -> ResolvedResponse:
        field_specs: list[FieldSpec] = []
        converter = _result_converter(
            ok=lambda cls, _: cls(),
            error=lambda _cls, err: err,
        )
        return field_specs, converter


@dataclass(frozen=True, slots=True)
class CursorPaginatedResponse:
    """Response = {items, next_cursor, has_more}."""

    def resolve[EntityT](self, ctx: DeriveCtx[EntityT]) -> ResolvedResponse:
        entity = ctx.entity
        field_specs: list[FieldSpec] = [
            ("items", list[entity]),
            ("next_cursor", str | None),
            ("has_more", bool),
        ]

        def _cursor_ok(cls: type, data: PaginationData) -> HasAnnotations:
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


def _dataclass_field_names(cls: type) -> list[str]:
    """Field names of ``cls`` if it is a dataclass, else ``[]``.

    Isolates the ``is_dataclass`` ``TypeGuard`` so it does not persistently
    narrow the caller's ``cls`` to ``type[DataclassInstance]``.
    """
    # Local import: module-level `fields` is shadowed by the projection
    # helper below, so reach the real dataclasses helpers here.
    from dataclasses import fields as dataclass_fields, is_dataclass

    if is_dataclass(cls):
        return [f.name for f in dataclass_fields(cls)]
    return []


def dict_converter[T, E](cls: type, result: Result[T, E]) -> HasAnnotations:
    """Convert Result[dict|obj, E] -> response dataclass."""
    from kungfu import Error as Err, Ok

    match result:
        case Ok(val):
            if isinstance(val, dict):
                return cls(**val)
            field_names = _dataclass_field_names(cls)
            return cls(**{f: getattr(val, f, None) for f in field_names})
        case Err(err):
            return err
        case _:
            raise TypeError(f"Expected Result, got {type(result)}")


@dataclass(frozen=True, slots=True)
class CustomResponse:
    """Response with explicit fields + converter."""

    field_specs: tuple[FieldSpec, ...]
    converter: ResponseConverter

    def resolve[EntityT](self, ctx: DeriveCtx[EntityT]) -> ResolvedResponse:
        return list(self.field_specs), self.converter


@dataclass(frozen=True, slots=True)
class EnvelopeResponse:
    """Response shape declared as a plain envelope dataclass — no hand-written specs.

    `field_specs` are read from the envelope's dataclass fields; the `data_field`
    (the list-of-entities slot) is retyped to ``list[ctx.entity]`` at compile time.
    The converter is the generic dict/obj → dataclass mapper. Lets a caller write::

        @dataclass
        class ListEnvelope:
            data: list          # retyped to list[entity]
            total: int
            next_cursor: str | None

        response_spec = EnvelopeResponse(ListEnvelope)

    instead of hand-writing a `resolve()` with field_specs + a bespoke converter.
    """

    envelope: type
    data_field: str = "data"

    def resolve[EntityT](self, ctx: DeriveCtx[EntityT]) -> ResolvedResponse:
        from dataclasses import fields as dataclass_fields
        from typing import get_type_hints

        entity = ctx.entity
        hints = get_type_hints(self.envelope)
        specs: list[FieldSpec] = []
        for f in dataclass_fields(self.envelope):
            if f.name == self.data_field:
                specs.append((f.name, list[entity]))
            else:
                specs.append((f.name, hints[f.name]))
        return specs, dict_converter


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
    return ExcludeFromProjection(inner=inner, names=names)

def exclude(*names: str) -> ExcludeFields:
    return ExcludeFields(names=names)

def optional_non_id() -> OptionalNonId:
    return OptionalNonId()

def merge(left: FieldProjection, right: FieldProjection) -> MergeProjection:
    return MergeProjection(left=left, right=right)

def entity_response() -> EntityResponse:
    return EntityResponse()

def list_response() -> ListResponse:
    return ListResponse()

def ok_response() -> OkResponse:
    return OkResponse()

def paginated_response() -> PaginatedResponse:
    return PaginatedResponse()

def count_response() -> CountResponse:
    return CountResponse()

def bool_response() -> BoolResponse:
    return BoolResponse()

def empty_response() -> EmptyResponse:
    return EmptyResponse()

def cursor_paginated_response() -> CursorPaginatedResponse:
    return CursorPaginatedResponse()

def custom_response(
    field_specs: tuple[FieldSpec, ...],
    converter: ResponseConverter,
) -> CustomResponse:
    return CustomResponse(field_specs=field_specs, converter=converter)

def envelope_response(envelope: type, data_field: str = "data") -> EnvelopeResponse:
    return EnvelopeResponse(envelope=envelope, data_field=data_field)

def composed_response(
    projection: ResponseProjection,
    converter: ResponseConverterProto,
) -> ComposedResponseSpec:
    """Compose separate projection + converter into a ResponseSpec."""
    return ComposedResponseSpec(projection=projection, converter=converter)


__all__ = (
    "FieldProjection",
    "ResponseProjection", "ResponseConverterProto", "ComposedResponseSpec",
    "ResponseSpec", "ResolvedResponse",
    "AllFields", "IdOnly", "NonId", "RequiredNonId", "NoFields",
    "ExcludeFromProjection", "SelectFields", "ExcludeFields",
    "OptionalNonId", "MergeProjection",
    "response_fields", "response_converter",
    "EntityResponse", "ListResponse", "OkResponse",
    "PaginatedResponse", "CountResponse", "BoolResponse",
    "EmptyResponse", "CursorPaginatedResponse", "CustomResponse", "EnvelopeResponse",
    "dict_converter",
    "all_fields", "id_only", "non_id", "required_non_id", "no_fields",
    "exclude_from", "fields", "exclude", "optional_non_id", "merge",
    "entity_response", "list_response", "ok_response", "paginated_response",
    "count_response", "bool_response", "empty_response",
    "cursor_paginated_response", "custom_response", "composed_response",
)
