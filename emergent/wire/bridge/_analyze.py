"""Handler analysis — introspect handlers to extract metadata.

Reverse of compile/_generate.py. Analyzes handler signatures,
extracts type information.

FRAMEWORK-AGNOSTIC — no FastAPI/Django specific detection.
Dependency detection is done by source inspectors.

    from emergent.wire.bridge._analyze import analyze_handler

    analysis = analyze_handler(my_handler)
    print(analysis.parameters)
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, get_type_hints


# ═══════════════════════════════════════════════════════════════════════════════
# Data Types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ParameterInfo:
    """Information about a handler parameter."""

    name: str
    annotation: type | None
    default: Any
    has_default: bool
    kind: str  # "positional", "keyword", "var_positional", "var_keyword"


@dataclass(frozen=True, slots=True)
class HandlerAnalysis:
    """Complete analysis result for a handler.

    Framework-agnostic — contains only what Python introspection provides.
    """

    name: str
    module: str | None
    parameters: tuple[ParameterInfo, ...]
    return_type: type | None
    is_async: bool
    is_generator: bool
    docstring: str | None


# ═══════════════════════════════════════════════════════════════════════════════
# Analysis Functions
# ═══════════════════════════════════════════════════════════════════════════════


def analyze_handler(handler: Callable[..., object]) -> HandlerAnalysis:
    """Analyze handler and extract metadata.

    FRAMEWORK-AGNOSTIC — only uses Python introspection.

    Args:
        handler: Any callable (function, method, class)

    Returns:
        HandlerAnalysis with extracted metadata
    """
    name = getattr(handler, "__name__", "<anonymous>")
    module = getattr(handler, "__module__", None)
    docstring = getattr(handler, "__doc__", None)

    # Analyze parameters
    parameters = analyze_parameters(handler)

    # Extract return type
    return_type = _extract_return_type(handler)

    # Check async/generator
    is_async = inspect.iscoroutinefunction(handler)
    is_generator = inspect.isgeneratorfunction(handler) or inspect.isasyncgenfunction(
        handler
    )

    return HandlerAnalysis(
        name=name,
        module=module,
        parameters=parameters,
        return_type=return_type,
        is_async=is_async,
        is_generator=is_generator,
        docstring=docstring,
    )


def analyze_parameters(handler: Callable[..., object]) -> tuple[ParameterInfo, ...]:
    """Extract parameter info from handler signature.

    Args:
        handler: Callable to analyze

    Returns:
        Tuple of ParameterInfo for each parameter
    """
    if not callable(handler):
        return ()

    try:
        sig = inspect.signature(handler)
    except (ValueError, TypeError):
        return ()

    # Try to get type hints
    try:
        hints = get_type_hints(handler)
    except Exception:
        hints = {}

    result: list[ParameterInfo] = []

    for name, param in sig.parameters.items():
        # Get annotation
        annotation = hints.get(name)

        # Map parameter kind to string
        kind = _map_param_kind(param)

        # Check if has default
        has_default = param.default is not inspect.Parameter.empty
        default = param.default if has_default else None

        result.append(
            ParameterInfo(
                name=name,
                annotation=annotation,
                default=default,
                has_default=has_default,
                kind=kind,
            )
        )

    return tuple(result)


def get_parameter_names(analysis: HandlerAnalysis) -> tuple[str, ...]:
    """Get all parameter names from analysis."""
    return tuple(p.name for p in analysis.parameters)


def get_required_parameters(analysis: HandlerAnalysis) -> tuple[ParameterInfo, ...]:
    """Get parameters without defaults."""
    return tuple(p for p in analysis.parameters if not p.has_default)


def get_optional_parameters(analysis: HandlerAnalysis) -> tuple[ParameterInfo, ...]:
    """Get parameters with defaults."""
    return tuple(p for p in analysis.parameters if p.has_default)


# ═══════════════════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════════════════


def _extract_return_type(handler: Callable[..., object]) -> type | None:
    """Extract return type annotation from handler."""
    try:
        hints = get_type_hints(handler)
        ret = hints.get("return")
        if isinstance(ret, type):
            return ret
        return None
    except Exception:
        return None


def _map_param_kind(param: inspect.Parameter) -> str:
    """Map parameter kind to string."""
    if param.kind == inspect.Parameter.POSITIONAL_ONLY:
        return "positional"
    if param.kind == inspect.Parameter.VAR_POSITIONAL:
        return "var_positional"
    if param.kind == inspect.Parameter.VAR_KEYWORD:
        return "var_keyword"
    return "keyword"


__all__ = (
    # Data types
    "ParameterInfo",
    "HandlerAnalysis",
    # Analysis functions
    "analyze_handler",
    "analyze_parameters",
    "get_parameter_names",
    "get_required_parameters",
    "get_optional_parameters",
)
