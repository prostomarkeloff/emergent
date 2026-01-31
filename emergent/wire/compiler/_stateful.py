"""Stateful compilation — universal multi-turn FSM handler.

Single implementation, parameterized by scope setup and wrapper.

    from emergent.wire.compiler import compile_stateful

    # FastAPI
    route = compile_stateful(handler, fastapi_scope_setup, fastapi_wrapper)
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from kungfu import Ok, Some

from emergent.wire._handler import Handler
from emergent.wire.axis.surface.codecs.stateful import (
    StatefulCodec,
    get_transitions,
    parse_transition_result,
)
from emergent.wire.axis.surface.scope import run_stateful_middlewares


T = TypeVar("T")


# ═══════════════════════════════════════════════════════════════════════════════
# Scope Setup Protocol
# ═══════════════════════════════════════════════════════════════════════════════


# ScopeSetup: (context, transitions) → dict of composed params per transition
# Returns: Option[(method, composed_params)]
ScopeSetup = Callable[
    [Any, list[Callable[..., Any]], type],  # context, transitions, agent_cls
    Any,  # Awaitable[Option[tuple[method, params]]]
]


# ═══════════════════════════════════════════════════════════════════════════════
# Universal Stateful Execution
# ═══════════════════════════════════════════════════════════════════════════════


async def execute_stateful_turn(
    handler: Handler[StatefulCodec],
    state: Any,
    resolved_method: Callable[..., Any],
    composed_params: dict[str, Any],
) -> tuple[Any, Any | None, bool]:
    """Execute single stateful turn.

    Returns: (new_state_or_done, response_or_none, is_terminal)
    """
    raw_result = await resolved_method(state, **composed_params)
    result = parse_transition_result(raw_result)

    response = result.response.unwrap() if isinstance(result.response, Some) else None

    return (result.state_or_done, response, result.is_terminal)


async def execute_stateful_done(
    handler: Handler[StatefulCodec],
    state: Any,
) -> tuple[dict[type, Any], Any | None, Any]:
    """Execute when stateful flow is Done.

    Returns: (scope_extras, rejection_response_or_none, final_response)
    """
    codec = handler.codec

    # Run middlewares
    scope_extras, rejection = await run_stateful_middlewares(codec.middlewares, state)

    if isinstance(rejection, Some):
        return (scope_extras, rejection.unwrap(), None)

    # Execute op
    op = state.to_domain()
    op_result = await handler.runner.run(op, scope_extras=scope_extras)

    # Format response
    response_type = codec.response
    if hasattr(response_type, "from_domain"):
        final_response = response_type.from_domain(op_result)  # type: ignore[reportUnknownMemberType]
    else:
        # Union type — find member with from_domain
        from typing import get_origin, get_args, Union
        origin = get_origin(response_type)
        if origin is Union:
            for member in get_args(response_type):
                if hasattr(member, "from_domain"):
                    final_response = member.from_domain(op_result)  # type: ignore[reportUnknownMemberType]
                    break
            else:
                raise TypeError(f"No from_domain in {response_type}")
        else:
            raise TypeError(f"Response type {response_type} has no from_domain")

    return (scope_extras, None, final_response)  # type: ignore[reportUnknownVariableType]


# ═══════════════════════════════════════════════════════════════════════════════
# State Management
# ═══════════════════════════════════════════════════════════════════════════════


async def load_state(codec: StatefulCodec, store_key: str) -> Any:
    """Load state from store or create initial."""
    match await codec.store.get(store_key):
        case Ok(Some(s)):
            return s
        case _:
            return codec.flow()


async def save_state(codec: StatefulCodec, store_key: str, old: Any, new: Any) -> None:
    """Save state if changed."""
    if new is not old:
        await codec.store.set(store_key, new)


async def delete_state(codec: StatefulCodec, store_key: str) -> None:
    """Delete state from store."""
    await codec.store.delete(store_key)


# ═══════════════════════════════════════════════════════════════════════════════
# Compilation
# ═══════════════════════════════════════════════════════════════════════════════


def get_stateful_metadata(handler: Handler[StatefulCodec]) -> dict[str, Any]:
    """Extract metadata for framework wrappers.

    Returns info needed by wrappers (transitions, key_node, etc.)
    """
    codec = handler.codec
    return {
        "transitions": get_transitions(codec.flow),
        "flow_cls": codec.flow,
        "response_cls": codec.response,
        "key_node": codec.key_node,
        "agent_cls": codec.agent_cls,
    }


# Note: Full compile_stateful requires framework-specific scope setup,
# so we provide building blocks rather than a single function.
# Each framework adapter composes these pieces.


__all__ = (
    "ScopeSetup",
    "execute_stateful_turn",
    "execute_stateful_done",
    "load_state",
    "save_state",
    "delete_state",
    "get_stateful_metadata",
)
