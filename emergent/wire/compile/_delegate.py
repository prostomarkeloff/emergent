"""Delegate codec support — compose dialect resolution.

Compose dialect (compose.Node, compose.Retrieve, compose.Optional) works
by default on handler params — no capability needed.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, TYPE_CHECKING, get_type_hints, get_origin, get_args

from kungfu import Some, Nothing

if TYPE_CHECKING:
    from nodnod import Scope
    from nodnod.agent.base import Agent


type ResolvedParams = dict[str, Any]


# ═══════════════════════════════════════════════════════════════════════════════
# Compose Dialect Support — resolve handler params via compose.*
# ═══════════════════════════════════════════════════════════════════════════════
#
# This is NOT a capability — compose dialect works by default in all compilers.
# Annotate handler params with compose.Node, compose.Retrieve, compose.Optional
# and compilers will resolve them automatically.


async def resolve_handler_params(
    handler: Callable[..., Any],
    scope: Scope,
    agent_cls: type[Agent],
) -> ResolvedParams:
    """Resolve handler params using compose dialect.

    For each param:
    1. Has compose.Node → run nodnod node
    2. Has compose.Retrieve → get from scope by type
    3. Has compose.Optional → compose, wrap in Option
    4. No annotation → get from scope by type (fallback)

    Args:
        handler: Handler callable with optional compose.* annotations.
        scope: nodnod Scope with injected values.
        agent_cls: Agent class for node composition.

    Returns:
        Dict of param name → resolved value.
    """
    from emergent.wire.axis.schema.dialects.compose import (
        Node as ComposeNode,
        Optional as ComposeOptional,
        Retrieve as ComposeRetrieve,
    )

    try:
        hints = get_type_hints(handler, include_extras=True)
    except Exception:
        hints = {}

    sig = inspect.signature(handler)
    result: ResolvedParams = {}

    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue

        param_type = hints.get(name, param.annotation)
        if param_type is inspect.Parameter.empty:
            continue

        # Check for Annotated with compose capabilities
        compose_cap = _extract_compose_capability(param_type)

        if isinstance(compose_cap, ComposeNode):
            # Compose via nodnod node
            success, value = await _compose_node(compose_cap.node_type, scope, agent_cls)
            if success:
                if compose_cap.map is not None:
                    value = compose_cap.map(value)
                result[name] = value
            elif compose_cap.default is not None:
                result[name] = compose_cap.default

        elif isinstance(compose_cap, ComposeOptional):
            # Compose, wrap in Option
            success, value = await _compose_node(compose_cap.node_type, scope, agent_cls)
            if success:
                result[name] = Some(value)
            else:
                result[name] = Nothing()

        elif isinstance(compose_cap, ComposeRetrieve):
            # Direct scope retrieval by type
            inject_result = scope.retrieve(compose_cap.from_type)
            match inject_result:
                case Some(v):
                    result[name] = v.value
                case Nothing():
                    pass  # Skip if not in scope

        else:
            # Fallback: try to get by type from scope, then compose as node
            base_type = _get_base_type(param_type)
            if base_type is not None:
                inject_result = scope.retrieve(base_type)
                match inject_result:
                    case Some(v):
                        result[name] = v.value
                    case Nothing():
                        # Type not in scope — try composing as nodnod node
                        success, value = await _compose_node(base_type, scope, agent_cls)
                        if success:
                            result[name] = value

    return result


def _extract_compose_capability(param_type: Any) -> Any:
    """Extract compose capability from Annotated type."""
    from emergent.wire.axis.schema.dialects.compose import ComposeCapability

    origin = get_origin(param_type)
    if origin is not None:
        # Check if it's Annotated
        try:
            from typing import Annotated
            if origin is Annotated:
                args = get_args(param_type)
                if len(args) >= 2:
                    for arg in args[1:]:
                        if isinstance(arg, ComposeCapability):
                            return arg
        except ImportError:
            pass
    return None


def _get_base_type(param_type: Any) -> type | None:
    """Get base type from possibly Annotated type."""
    origin = get_origin(param_type)
    if origin is not None:
        try:
            from typing import Annotated
            if origin is Annotated:
                args = get_args(param_type)
                if args:
                    return args[0] if isinstance(args[0], type) else None
        except ImportError:
            pass
    return param_type if isinstance(param_type, type) else None


def _extract_compose_result(raw: tuple[bool, Any]) -> tuple[bool, Any]:
    """Extract compose result — breaks Unknown propagation from generic T.

    Composer.compose[T] returns tuple[bool, T | str]. When T is Unknown
    (from bare `type`), the entire result carries Unknown. This function
    has a concrete signature that pyright trusts, cutting the chain.
    """
    return raw[0], raw[1]


async def _compose_node(
    node_type: type,
    scope: Scope,
    agent_cls: type[Agent],
) -> tuple[bool, Any]:
    """Compose a nodnod node and return its value."""
    from emergent.graph._compose import Composer

    composer = Composer.create(scope, agent_cls)
    # Composer.compose is generic: compose[T](node_type: type[T]) -> tuple[bool, T | str].
    # With bare `type` (no type param), T resolves to Unknown — unavoidable since the
    # node_type is only known at runtime via reflection (get_type_hints). The composed
    # value is therefore genuinely Any; annotating `raw` pins the concrete shape so the
    # Unknown does not propagate, and _extract_compose_result keeps the chain explicit.
    raw: tuple[bool, Any] = await composer.compose(node_type)
    success, value = _extract_compose_result(raw)
    if success:
        return True, value
    return False, None


__all__ = (
    "resolve_handler_params",
)
