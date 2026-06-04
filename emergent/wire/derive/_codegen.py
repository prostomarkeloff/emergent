"""Core type generation infrastructure for derivation patterns.

Three concerns:
1. Creating types (dataclass, request/response with baked-in protocol methods)
2. Setting proper annotations (handler, __name__)

    from emergent.wire.derive._codegen import create_dataclass, create_request_type
"""

from __future__ import annotations

import types
from collections.abc import Mapping
from dataclasses import dataclass, make_dataclass
from typing import Any, TYPE_CHECKING, Callable, Protocol

from kungfu import Error, Ok, Result

if TYPE_CHECKING:
    from emergent.wire.derive._ctx import OperationHandler

# Annotation value: anything Python accepts in a type annotation context.
type AnnotationValue = type | types.UnionType | types.GenericAlias

# Field spec for make_dataclass: (name, annotation) or (name, annotation, default).
# Default may be any Python value — dataclasses accept arbitrary defaults.
type FieldSpec = tuple[str, AnnotationValue] | tuple[str, AnnotationValue, object]

type AnnotationMap = dict[str, type]
type ScalarFieldMap = Mapping[str, str | int | float | bool | None]
type NamespaceMap = dict[str, Callable[..., HasAnnotations | str | int | float | bool | None]]


class HasAnnotations(Protocol):
    """Protocol for objects with __annotations__ attribute."""
    __annotations__: AnnotationMap


class FieldMapper(Protocol):
    """Protocol for custom field extraction from request to dict."""
    def __call__(self, request: HasAnnotations) -> ScalarFieldMap: ...


# ═══════════════════════════════════════════════════════════════════════════════
# DEFUNCTIONALIZED MAPPERS / CONVERTERS
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class DirectMapper:
    """Default: copy all annotated fields from request to op constructor.

    Inspectable replacement for the closure in create_request_type.
    """

    def __call__(self, request: HasAnnotations) -> ScalarFieldMap:
        return {k: getattr(request, k) for k in type(request).__annotations__}


@dataclass(frozen=True, slots=True)
class ResultConversion:
    """Defunctionalized response converter — inspectable, replaceable.

    Replaces closure-based _result_converter. Still callable for backward compat.
    """

    ok: Callable[..., HasAnnotations]
    error: Callable[..., HasAnnotations] | None = None

    def __call__(self, cls: type, result: Result[HasAnnotations, HasAnnotations]) -> HasAnnotations:
        match result:
            case Ok(val):
                return self.ok(cls, val)
            case Error(err):
                if self.error is not None:
                    return self.error(cls, err)
                return err


# ═══════════════════════════════════════════════════════════════════════════════
# 1. DATACLASS CREATION
# ═══════════════════════════════════════════════════════════════════════════════


def create_dataclass(
    name: str,
    fields: list[FieldSpec],
    *,
    frozen: bool = True,
    bases: tuple[type, ...] = (),
    namespace: NamespaceMap | None = None,
) -> type:
    """Create dataclass with proper __name__ and __qualname__."""
    cls = make_dataclass(
        name,
        fields,
        frozen=frozen,
        bases=bases,
        namespace=namespace or {},
    )
    cls.__name__ = name
    cls.__qualname__ = name
    return cls


def set_type_name(cls: type, name: str) -> None:
    """Set __name__ and __qualname__ on existing type."""
    cls.__name__ = name
    cls.__qualname__ = name


# ═══════════════════════════════════════════════════════════════════════════════
# 2. REQUEST / RESPONSE TYPE CREATION
# ═══════════════════════════════════════════════════════════════════════════════


def create_request_type(
    name: str,
    fields: list[FieldSpec],
    op_type: type,
    *,
    mapper: FieldMapper | None = None,
    frozen: bool = True,
) -> type:
    """Create Request dataclass with to_domain() baked into namespace."""
    _op = op_type

    _mapper = mapper if mapper is not None else DirectMapper()

    if isinstance(_mapper, DirectMapper):
        def to_domain(self: HasAnnotations) -> HasAnnotations:
            return _op(**{k: getattr(self, k) for k in type(self).__annotations__})
    else:
        _m = _mapper
        def to_domain(self: HasAnnotations) -> HasAnnotations:
            return _op(**_m(self))

    cls = create_dataclass(name, fields, frozen=frozen, namespace={"to_domain": to_domain})
    cls.__request_mapper__ = _mapper
    return cls


def create_response_type(
    name: str,
    fields: list[FieldSpec],
    converter: Callable[..., HasAnnotations],
    *,
    frozen: bool = True,
) -> type:
    """Create Response dataclass with from_domain() baked into namespace."""
    _conv = converter
    _fields = fields

    @classmethod
    def from_domain(cls: type, domain_result: HasAnnotations) -> HasAnnotations:
        return _conv(cls, domain_result)

    def __str__(self: HasAnnotations) -> str:
        if len(_fields) == 1:
            field_name = _fields[0][0]
            return str(getattr(self, field_name))
        parts = [str(getattr(self, f[0]))
                 for f in _fields
                 if getattr(self, f[0]) is not None]
        return "\n".join(parts)

    cls = create_dataclass(name, fields, frozen=frozen, namespace={"from_domain": from_domain, "__str__": __str__})
    cls.__response_converter__ = _conv
    return cls


# ═══════════════════════════════════════════════════════════════════════════════
# 3. HANDLER ANNOTATION
# ═══════════════════════════════════════════════════════════════════════════════


def annotate_handler[T, E](
    handler: OperationHandler[T, E],
    op_type: type,
) -> OperationHandler[T, E]:
    """Wrap handler with proper __annotations__ for emergent.ops runner.

    Creates a wrapper with a positional `op` parameter whose runtime type
    annotation is set to `op_type` via __annotations__.  The inner function
    takes a single positional arg to preserve dispatch semantics.
    """

    async def annotated(op: Any) -> Result[T, E]:
        return await handler(op)

    annotated.__annotations__ = {'op': op_type}
    return annotated


# ═══════════════════════════════════════════════════════════════════════════════
# 4. SENTINEL OPERATION
# ═══════════════════════════════════════════════════════════════════════════════


def create_sentinel_operation(
    name: str,
) -> tuple[type, Callable[..., Any]]:
    """Create a sentinel op type + noop handler for DelegateCodec exposures."""
    op_type = create_dataclass(name, [], frozen=True)

    async def _noop(**kwargs: Any) -> Result[Any, Any]:
        return Ok(kwargs.get("op"))

    return op_type, annotate_handler(_noop, op_type)


__all__ = (
    "AnnotationValue",
    "FieldSpec",
    "HasAnnotations",
    "FieldMapper",
    "DirectMapper",
    "ResultConversion",
    "create_dataclass",
    "set_type_name",
    "create_request_type",
    "create_response_type",
    "annotate_handler",
    "create_sentinel_operation",
)
