"""Composition utilities for stateful codecs.

Unified composition through nodnod. Compilers only configure scope.

## Usage (Single Transition)

```python
from emergent.wire.axis.surface.codecs.resolve import get_transition_params, compose_params

# 1. Parse __transition__ signature (once at startup)
params = get_transition_params(BetFlow)

# 2. Create and configure scope (transport-specific)
async with Scope() as scope:
    scope.inject(Request, request)  # FastAPI
    # or telegrinder injects Context, Message, etc.

    # 3. Compose all params through nodnod
    composed = await compose_params(params, scope, agent_cls)

# 4. Call transition
next_state = await state.__transition__(**composed)
```

## Usage (Multiple Transitions)

```python
from emergent.wire.axis.surface.codecs.resolve import resolve_transition
from emergent.wire.axis.surface.codecs.stateful import get_transitions

# 1. Get all @transition methods
transitions = get_transitions(BetFlow)

# 2. Resolve first one whose deps are satisfiable
async with Scope() as scope:
    scope.inject(Request, request)
    result = await resolve_transition(transitions, scope, agent_cls)

match result:
    case Some((method, composed)):
        # method is the transition method, composed is the params dict
        raw_result = await method(state, **composed)
    case Nothing():
        raise RuntimeError("No transition resolvable")
```

nodnod handles Option[T], Result[T, E] automatically.
"""

from __future__ import annotations

import types
from collections.abc import Mapping
from typing import Any, Callable, get_type_hints, get_origin, get_args, TYPE_CHECKING

from kungfu import Option, Some, Nothing, Result, Ok, Error
from nodnod import Scope

if TYPE_CHECKING:
    from nodnod.agent.base import Agent

# A type annotation can be a concrete `type` or a parameterized generic alias
# (e.g. Option[int], Result[str, int]).  Python has no official TypeForm yet,
# so we define a narrow union covering the two cases that actually appear here.
TypeForm = type | types.GenericAlias

type ParamSpecMap = dict[str, tuple[TypeForm, type]]
type ParamSpecMapping = Mapping[str, tuple[TypeForm, type]]
type ComposedParams = dict[str, Any]

# ─── Wrapper Handling ────────────────────────────────────────────────────────


def unwrap(typ: TypeForm) -> tuple[type, bool]:
    """Unwrap Option[T] or Result[T, E] → (inner_type, is_optional).

    The inner type is always a concrete class (not a generic alias),
    because Option[T] and Result[T, E] wrap concrete types.

    Examples:
        unwrap(Option[HttpToken]) → (HttpToken, True)
        unwrap(Result[User, str]) → (User, True)
        unwrap(MessageCute)       → (MessageCute, False)
    """
    origin = get_origin(typ)
    if origin is Option:
        inner: type = get_args(typ)[0]
        return (inner, True)
    if origin is Result:
        inner_r: type = get_args(typ)[0]
        return (inner_r, True)
    # Plain type — not a generic alias
    assert isinstance(typ, type)
    return (typ, False)


def wrap(typ: TypeForm, success: bool, value: Any) -> Any:
    """Wrap composition result back into original type.

    Examples:
        wrap(Option[T], True, v)  → Some(v)
        wrap(Option[T], False, e) → Nothing()
        wrap(Result[T,E], True, v)  → Ok(v)
        wrap(Result[T,E], False, e) → Error(e)
        wrap(T, True, v)  → v
        wrap(T, False, e) → RuntimeError
    """
    origin = get_origin(typ)

    if origin is Option:
        return Some(value) if success else Nothing()

    if origin is Result:
        return Ok(value) if success else Error(value)

    if not success:
        raise RuntimeError(f"Required param failed: {value}")
    return value


# ─── Transition Params ───────────────────────────────────────────────────────


def get_method_params(method: Callable[..., Any]) -> ParamSpecMap:
    """Parse method signature → {name: (original_type, compose_type)}.

    Example:
        async def http(
            self,
            token: Option[HttpToken],
            amount: Result[Amount, str],
            msg: MessageCute,
        ) -> Self | Done: ...

        get_method_params(http)
        # {
        #     "token": (Option[HttpToken], HttpToken),
        #     "amount": (Result[Amount, str], Amount),
        #     "msg": (MessageCute, MessageCute),
        # }
    """
    hints = get_type_hints(method)
    params: ParamSpecMap = {}

    for name, typ in hints.items():
        if name in ("self", "return"):
            continue
        compose_type, _ = unwrap(typ)
        params[name] = (typ, compose_type)

    return params


def get_transition_params(flow: type) -> ParamSpecMap:
    """Parse __transition__ signature → {name: (original_type, compose_type)}.

    Backwards-compatible wrapper around get_method_params.
    Prefer using get_method_params directly for multiple transitions.

    Example:
        @dataclass
        class BetFlow:
            async def __transition__(
                self,
                token: Option[HttpToken],
                amount: Result[Amount, str],
                msg: MessageCute,
            ) -> Self | Done: ...

        get_transition_params(BetFlow)
        # {
        #     "token": (Option[HttpToken], HttpToken),
        #     "amount": (Result[Amount, str], Amount),
        #     "msg": (MessageCute, MessageCute),
        # }
    """
    transition_fn = getattr(flow, "__transition__", None)
    if transition_fn is None:
        return {}

    return get_method_params(transition_fn)


def _is_nodnod_node(typ: TypeForm) -> bool:
    """Check if type is a nodnod node (has __dependencies__)."""
    return hasattr(typ, "__dependencies__")


async def compose_params(
    params: ParamSpecMapping,
    scope: Scope,
    agent_cls: type[Agent],
) -> ComposedParams:
    """Compose all __transition__ params through nodnod.

    Args:
        params: From get_transition_params()
        scope: Pre-configured scope with injected dependencies
        agent_cls: nodnod Agent class (EventLoopAgent, etc.)

    Returns:
        {name: wrapped_value} ready to pass to __transition__

    Example:
        async with Scope() as scope:
            scope.inject(Request, request)
            composed = await compose_params(params, scope, EventLoopAgent)
        await state.__transition__(**composed)

    Note:
        For pre-injected types (Pydantic models, etc.), retrieves from scope directly.
        For nodnod nodes, uses agent to compose.
    """
    from emergent.graph._compose import Composer

    composer = Composer.create(scope, agent_cls)
    composed: ComposedParams = {}

    for name, (original_type, compose_type) in params.items():
        # First check if already injected (e.g., Pydantic models from body)
        # compose_type is bare `type` — cast to type[object] for generic resolution
        typed: type[Any] = compose_type
        # nodnod's Value.value is untyped, so retrieve/compose return partially
        # unknown tuples; explicit annotations make the types known to pyright.
        found: bool
        value: Any | None
        found, value = composer.retrieve(typed)
        if found:
            composed[name] = wrap(original_type, True, value)
            continue

        # Only use nodnod agent for actual nodes
        if not _is_nodnod_node(compose_type):
            composed[name] = wrap(original_type, False, f"not a node: {compose_type}")
            continue

        # Compose through Composer
        success: bool
        result: Any | str
        success, result = await composer.compose(typed)
        if success:
            composed[name] = wrap(original_type, True, result)
        else:
            composed[name] = wrap(original_type, False, "node composition failed")

    return composed


# ─── Multi-Transition Resolution ─────────────────────────────────────────────


async def try_compose_params(
    params: ParamSpecMapping,
    scope: Scope,
    agent_cls: type[Agent],
) -> Option[ComposedParams]:
    """Try to compose params; return Some if all required params succeed.

    Like compose_params but returns Nothing if any required (non-Option, non-Result)
    param fails to compose. This enables routing to fallback transitions.

    Returns:
        Some(composed_dict) if all required params composed successfully
        Nothing() if any required param failed
    """
    from emergent.graph._compose import Composer

    composer = Composer.create(scope, agent_cls)
    composed: ComposedParams = {}

    for name, (original_type, compose_type) in params.items():
        origin = get_origin(original_type)
        is_optional = origin is Option or origin is Result

        # First check if already injected
        # compose_type is bare `type` — cast to type[object] for generic resolution
        typed: type[Any] = compose_type
        # nodnod's Value.value is untyped; explicit annotations avoid Unknown
        found: bool
        pre_value: Any | None
        found, pre_value = composer.retrieve(typed)
        if found:
            composed[name] = wrap(original_type, True, pre_value)
            continue

        # Non-node types: fail if required
        if not _is_nodnod_node(compose_type):
            if is_optional:
                composed[name] = wrap(original_type, False, f"not a node: {compose_type}")
                continue
            return Nothing()

        # Try to compose through Composer
        success: bool
        result: Any | str
        success, result = await composer.compose(typed)
        if success:
            composed[name] = wrap(original_type, True, result)
        elif is_optional:
            composed[name] = wrap(original_type, False, "node composition failed")
        else:
            return Nothing()

    return Some(composed)


async def resolve_transition(
    transitions: list[Callable[..., Any]],
    scope: Scope,
    agent_cls: type[Agent],
) -> Option[tuple[Callable[..., Any], ComposedParams]]:
    """Resolve first transition whose deps are satisfiable.

    Tries each transition in order (like SequentialEither).
    Returns first one where all required params compose successfully.

    Args:
        transitions: List of transition methods from get_transitions()
        scope: Pre-configured scope with injected dependencies
        agent_cls: nodnod Agent class

    Returns:
        Some((method, composed_params)) for first resolvable transition
        Nothing() if no transition is resolvable

    Example::

        transitions = get_transitions(BetFlow)
        result = await resolve_transition(transitions, scope, EventLoopAgent)

        match result:
            case Some((method, composed)):
                raw_result = await method(state, **composed)
            case Nothing():
                raise RuntimeError("No transition resolvable")
    """
    for method in transitions:
        params = get_method_params(method)
        composed = await try_compose_params(params, scope, agent_cls)

        match composed:
            case Some(params_dict):
                return Some((method, params_dict))
            case Nothing():
                continue  # Try next transition

    return Nothing()
