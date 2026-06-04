"""Handler signature analysis — composable introspection.

Reuses schema axis patterns for type unwrapping.

    from emergent.wire.bridge import analyze_signature, HandlerSignature

    sig = analyze_signature(my_handler)
    request_type = sig.body_type()
    response_type = sig.return_type
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, get_type_hints

from emergent.wire.axis.schema import (
    SchemaAxisCapability,
    extract_capabilities,
    unwrap_annotated,
    unwrap_optional,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Handler Parameter
# ═══════════════════════════════════════════════════════════════════════════════


def _empty_caps() -> tuple[SchemaAxisCapability, ...]:
    return ()


@dataclass(frozen=True, slots=True)
class HandlerParameter:
    """Parsed handler parameter."""

    name: str
    base_type: type | None
    is_optional: bool
    default: object
    capabilities: Sequence[SchemaAxisCapability] = field(default_factory=_empty_caps)

    def has_default(self) -> bool:
        """Check if parameter has a default value."""
        return self.default is not inspect.Parameter.empty


# ═══════════════════════════════════════════════════════════════════════════════
# Handler Signature
# ═══════════════════════════════════════════════════════════════════════════════


def _empty_params() -> dict[str, HandlerParameter]:
    return {}


@dataclass(frozen=True, slots=True)
class HandlerSignature:
    """Extracted handler signature.

    Provides structured access to handler parameters and return type.
    Uses schema axis utilities for type unwrapping.
    """

    parameters: dict[str, HandlerParameter] = field(default_factory=_empty_params)
    return_type: type | None = None
    return_capabilities: Sequence[SchemaAxisCapability] = field(default_factory=_empty_caps)
    is_async: bool = False

    def body_type(self) -> type | None:
        """Get first non-primitive parameter type (likely request body).

        Returns None if no body parameter found.
        """
        for param in self.parameters.values():
            if param.base_type is not None and _is_complex_type(param.base_type):
                return param.base_type
        return None

    def required_parameters(self) -> dict[str, HandlerParameter]:
        """Get parameters without defaults."""
        return {
            name: param
            for name, param in self.parameters.items()
            if not param.has_default()
        }

    def optional_parameters(self) -> dict[str, HandlerParameter]:
        """Get parameters with defaults."""
        return {
            name: param for name, param in self.parameters.items() if param.has_default()
        }


def _is_complex_type(t: type) -> bool:
    """Check if type is complex (not a primitive)."""
    primitives = (str, int, float, bool, bytes, type(None))
    return t not in primitives


# ═══════════════════════════════════════════════════════════════════════════════
# Signature Analyzer
# ═══════════════════════════════════════════════════════════════════════════════


# Type alias for analyzer function
type SignatureAnalyzer = Callable[[Callable[..., object]], HandlerSignature | None]


def analyze_signature(handler: Callable[..., Any]) -> HandlerSignature:
    """Analyze handler signature using schema axis utilities.

    Extracts:
    - Parameter names, types, defaults
    - Capabilities from Annotated markers
    - Return type and its capabilities
    - Async status

    Example::

        async def create_user(user: Annotated[UserCreate, Body()]) -> User:
            ...

        sig = analyze_signature(create_user)
        # sig.parameters["user"].base_type == UserCreate
        # sig.return_type == User
        # sig.is_async == True
    """
    if not callable(handler):
        return HandlerSignature()

    # Get type hints with extras (Annotated preserved)
    try:
        hints = get_type_hints(handler, include_extras=True)
    except Exception:
        hints = {}

    # Get signature for defaults
    try:
        sig = inspect.signature(handler)
    except (ValueError, TypeError):
        return HandlerSignature()

    # Parse parameters
    parameters: dict[str, HandlerParameter] = {}
    for name, param in sig.parameters.items():
        annotation = hints.get(name)
        parameters[name] = _parse_parameter(name, annotation, param.default)

    # Parse return type
    return_annotation = hints.get("return")
    return_type: type | None = None
    return_capabilities: Sequence[SchemaAxisCapability] = ()

    if return_annotation is not None:
        base, annotations = unwrap_annotated(return_annotation)
        base, _ = unwrap_optional(base)
        if isinstance(base, type):
            return_type = base
        return_capabilities = extract_capabilities(annotations)

    return HandlerSignature(
        parameters=parameters,
        return_type=return_type,
        return_capabilities=return_capabilities,
        is_async=inspect.iscoroutinefunction(handler),
    )


def _parse_parameter(
    name: str,
    annotation: Any,
    default: Any,
) -> HandlerParameter:
    """Parse single parameter using schema utilities."""
    if annotation is None:
        return HandlerParameter(
            name=name,
            base_type=None,
            is_optional=default is not inspect.Parameter.empty,
            default=default,
        )

    # Use schema axis utilities
    base_type, annotations = unwrap_annotated(annotation)
    base_type, is_optional = unwrap_optional(base_type)

    # Ensure base_type is actually a type
    if not isinstance(base_type, type):
        base_type = None

    capabilities = extract_capabilities(annotations)

    return HandlerParameter(
        name=name,
        base_type=base_type,
        is_optional=is_optional or default is not inspect.Parameter.empty,
        default=default,
        capabilities=capabilities,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Composable Analyzers
# ═══════════════════════════════════════════════════════════════════════════════


def first_analyzer(*analyzers: SignatureAnalyzer) -> SignatureAnalyzer:
    """Compose analyzers — first non-None result wins.

    Like schema.first_match for inspectors.

    Example::

        analyzer = first_analyzer(
            fastapi_analyzer,   # Try FastAPI-specific first
            standard_analyzer,  # Fall back to standard
        )

        sig = analyzer(handler)
    """

    def combined(handler: Callable[..., Any]) -> HandlerSignature:
        for analyzer in analyzers:
            result = analyzer(handler)
            if result is not None:
                return result
        # Fallback to standard
        return analyze_signature(handler)

    return combined


__all__ = (
    "HandlerParameter",
    "HandlerSignature",
    "SignatureAnalyzer",
    "analyze_signature",
    "first_analyzer",
)
