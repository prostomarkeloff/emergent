"""Core type generation infrastructure for derivelib patterns.

Three concerns:
1. Creating types (dataclass, request/response with baked-in protocol methods)
2. Setting proper annotations (handler, __name__)

For builders (ExposureBuilder, EndpointBuilder): see _builders.py

    from derivelib._codegen import create_dataclass, create_request_type, create_response_type
"""

from __future__ import annotations

import types
from collections.abc import Mapping
from dataclasses import make_dataclass
from typing import TYPE_CHECKING, Callable, Protocol

if TYPE_CHECKING:
    from kungfu import Result

    from derivelib._ctx import OperationHandler

# Annotation value: anything Python accepts in a type annotation context.
# Includes: concrete types (int, str), union types (str | None), generic aliases (list[int]).
type AnnotationValue = type | types.UnionType | types.GenericAlias

# Field spec for make_dataclass: (name, annotation) or (name, annotation, default).
type FieldSpec = tuple[str, AnnotationValue] | tuple[str, AnnotationValue, int | str | float | bool | None]


class HasAnnotations(Protocol):
    """Protocol for objects with __annotations__ attribute."""
    __annotations__: dict[str, type]


class FieldMapper(Protocol):
    """Protocol for custom field extraction from request to dict."""
    def __call__(self, request: HasAnnotations) -> Mapping[str, str | int | float | bool | None]: ...


# ═══════════════════════════════════════════════════════════════════════════════
# 1. DATACLASS CREATION
# ═══════════════════════════════════════════════════════════════════════════════


def create_dataclass(
    name: str,
    fields: list[FieldSpec],
    *,
    frozen: bool = True,
    bases: tuple[type, ...] = (),
    namespace: dict[str, Callable[..., HasAnnotations | str | int | float | bool | None]] | None = None,
) -> type:
    """Create dataclass with proper __name__ and __qualname__.

    Wrapper around make_dataclass that ensures proper type naming.

    Args:
        name: Type name (will be set as __name__ and __qualname__)
        fields: List of (name, type) or (name, type, default) tuples
        frozen: Whether dataclass is frozen (default: True)
        bases: Base classes (default: ())
        namespace: Additional namespace dict (default: None)

    Returns:
        Dataclass with proper __name__ and __qualname__
    """
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
# 2. REQUEST / RESPONSE TYPE CREATION (namespace injection, no setattr)
# ═══════════════════════════════════════════════════════════════════════════════


def create_request_type(
    name: str,
    fields: list[FieldSpec],
    op_type: type,
    *,
    mapper: FieldMapper | None = None,
    frozen: bool = True,
) -> type:
    """Create Request dataclass with to_domain() baked into namespace.

    No setattr — method injected at creation time via make_dataclass namespace.
    """
    _op = op_type

    if mapper is None:
        def to_domain(self: HasAnnotations) -> HasAnnotations:
            return _op(**{k: getattr(self, k) for k in type(self).__annotations__})
    else:
        def to_domain(self: HasAnnotations) -> HasAnnotations:
            return _op(**mapper(self))

    return create_dataclass(name, fields, frozen=frozen, namespace={"to_domain": to_domain})


def create_response_type(
    name: str,
    fields: list[FieldSpec],
    converter: Callable[..., HasAnnotations],
    *,
    frozen: bool = True,
) -> type:
    """Create Response dataclass with from_domain() baked into namespace.

    No setattr — classmethod injected at creation time via make_dataclass namespace.
    """
    _conv = converter

    @classmethod
    def from_domain(cls: type, domain_result: HasAnnotations) -> HasAnnotations:
        return _conv(cls, domain_result)

    return create_dataclass(name, fields, frozen=frozen, namespace={"from_domain": from_domain})


# ═══════════════════════════════════════════════════════════════════════════════
# 3. HANDLER ANNOTATION
# ═══════════════════════════════════════════════════════════════════════════════


def annotate_handler[T, E](
    handler: OperationHandler[T, E],
    op_type: type,
) -> OperationHandler[T, E]:
    """Wrap handler with proper __annotations__ for emergent.ops runner.

    The wrapper must use an explicit ``op`` parameter (not ``**kwargs``)
    so that ``inspect.signature`` and ``get_type_hints`` agree.
    The ops runner reads both to wire nodnod dependencies — a mismatch
    causes nodnod to see ``inspect._empty`` as the injection type.
    """

    async def annotated(op: op_type) -> Result[T, E]:  # type: ignore[valid-type]
        return await handler(op)

    annotated.__annotations__ = {'op': op_type}
    return annotated


# ═══════════════════════════════════════════════════════════════════════════════
# Re-exports from split modules
# ═══════════════════════════════════════════════════════════════════════════════

from derivelib._builders import (  # noqa: F401, E402
    EndpointBuilder,
    ExposureBuilder,
    endpoint_builder,
    exposure,
)


__all__ = (
    # Type creation
    "create_dataclass",
    "set_type_name",
    # Request/Response creation (namespace injection)
    "create_request_type",
    "create_response_type",
    # Handler annotation
    "annotate_handler",
    # Re-exports from _builders
    "ExposureBuilder",
    "exposure",
    "EndpointBuilder",
    "endpoint_builder",
)
