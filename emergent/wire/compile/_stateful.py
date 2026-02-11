"""Stateful compilation — universal multi-turn FSM handler.

Single implementation, parameterized by scope setup and wrapper.

    from emergent.wire.compile import compile_stateful

    # FastAPI
    route = compile_stateful(handler, fastapi_scope_setup, fastapi_wrapper)

ScopeEnricher capabilities run when Done, before Op execution.
"""

from __future__ import annotations

from typing import Any, Callable, TYPE_CHECKING

from kungfu import Ok, Some

from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface.codecs.stateful import (
    StatefulCodec,
    get_transitions,
    parse_transition_result,
)
from emergent.wire.axis.surface.enrichers import chain_enrichers
from emergent.wire.compile._capabilities import fold_handler_runtime

if TYPE_CHECKING:
    from nodnod import Scope


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
    scope: Scope,
) -> Any:
    """Execute when stateful flow is Done.

    Uses ScopeEnricher capabilities from handler.capabilities.
    Enrichers wrap the core execution: state.to_domain() → Op → Result → Response.

    Returns: final response (or rejection from enricher)
    """
    codec = handler.codec

    # Core handler: state → op → result → response
    async def core_handler(scope: Scope) -> Any:
        op = state.to_domain()
        op_result = await handler.runner.run(op)

        # Format response
        response_type = codec.response
        if hasattr(response_type, "from_domain"):
            return response_type.from_domain(op_result)  # type: ignore[reportUnknownMemberType]

        # Union type — find member with from_domain
        from typing import get_origin, get_args, Union
        origin = get_origin(response_type)
        if origin is Union:
            for member in get_args(response_type):
                if hasattr(member, "from_domain"):
                    return member.from_domain(op_result)  # type: ignore[reportUnknownMemberType]
            raise TypeError(f"No from_domain in {response_type}")
        raise TypeError(f"Response type {response_type} has no from_domain")

    # Extract enrichers via fold
    rt_ctx = fold_handler_runtime(handler.capabilities)
    enrichers = rt_ctx.enrichers

    # Chain enrichers and execute
    if enrichers:
        wrapped = chain_enrichers(enrichers, core_handler)
        return await wrapped(scope)
    else:
        return await core_handler(scope)


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
