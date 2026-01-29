"""Composition utilities for stateful codecs.

Unified composition through nodnod. Compilers only configure scope.

## Usage

```python
from emergent.wire.codecs.resolve import get_transition_params, compose_params

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

nodnod handles Option[T], Result[T, E] automatically.
"""

from __future__ import annotations

from typing import Any, get_type_hints, get_origin, get_args, TYPE_CHECKING

from kungfu import Option, Some, Nothing, Result, Ok, Error
from nodnod import Scope

if TYPE_CHECKING:
    from nodnod.agent.base import Agent


# ─── Wrapper Handling ────────────────────────────────────────────────────────


def unwrap(typ: type) -> tuple[type, bool]:
    """Unwrap Option[T] or Result[T, E] → (inner_type, is_optional).

    Examples:
        unwrap(Option[HttpToken]) → (HttpToken, True)
        unwrap(Result[User, str]) → (User, True)
        unwrap(MessageCute)       → (MessageCute, False)
    """
    origin = get_origin(typ)
    if origin is Option:
        return (get_args(typ)[0], True)
    if origin is Result:
        return (get_args(typ)[0], True)
    return (typ, False)


def wrap(typ: type, success: bool, value: Any) -> Any:
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


def get_transition_params(flow: type) -> dict[str, tuple[type, type]]:
    """Parse __transition__ signature → {name: (original_type, compose_type)}.

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

    hints = get_type_hints(transition_fn)
    params: dict[str, tuple[type, type]] = {}

    for name, typ in hints.items():
        if name in ("self", "return"):
            continue
        compose_type, _ = unwrap(typ)
        params[name] = (typ, compose_type)

    return params


def _is_nodnod_node(typ: type) -> bool:
    """Check if type is a nodnod node (has __dependencies__)."""
    return hasattr(typ, "__dependencies__")


async def compose_params(
    params: dict[str, tuple[type, type]],
    scope: Scope,
    agent_cls: type[Agent],
) -> dict[str, Any]:
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
    composed: dict[str, Any] = {}

    for name, (original_type, compose_type) in params.items():
        # First check if already injected (e.g., Pydantic models from body)
        pre_injected = scope.retrieve(compose_type)
        if isinstance(pre_injected, Some):
            composed[name] = wrap(original_type, True, pre_injected.unwrap().value)
            continue

        # Only use nodnod agent for actual nodes
        if not _is_nodnod_node(compose_type):
            composed[name] = wrap(original_type, False, f"not a node: {compose_type}")
            continue

        # Build agent for this specific type
        try:
            agent = agent_cls.build({compose_type})
            await agent.run(local_scope=scope, mapped_scopes={})

            # Retrieve result
            result = scope.retrieve(compose_type)
            match result:
                case Some(value):
                    composed[name] = wrap(original_type, True, value.value)
                case Nothing():
                    composed[name] = wrap(original_type, False, "composition failed")
        except Exception:
            # Node composition failed (e.g., NodeError for missing data)
            # For Option types, this becomes Nothing; for required, raises
            composed[name] = wrap(original_type, False, "node composition failed")

    return composed
