"""Stateful codec primitives — single-class FSM with pattern matching.

Mirrors RRC but across multiple turns:
- RRC: `request.to_domain()` → Op → `response.from_domain(result)`
- Stateful: accumulate state → `state.to_domain()` → Op → `response.from_domain(result)`

## Single-Class FSM Pattern

```python
from kungfu import Option, Some, Nothing
from dataclasses import dataclass, field, replace

@dataclass
class BetFlow:
    token: Option[str] = field(default_factory=Nothing)
    bet_type: Option[str] = field(default_factory=Nothing)
    amount: Option[int] = field(default_factory=Nothing)

    async def __transition__(
        self,
        token: Option[HttpToken],
        bet_type: Option[BetType],
        amount: Option[BetAmount],
        msg: MessageCute,
    ) -> Self | tuple[Self, str] | Done:
        '''State transitions + UI side effects.'''

        # Collect data across turns...
        match (self.token, self.bet_type, amount):
            case (Some(_), Some(_), Some(amt)):
                return Done()  # Ready — triggers to_domain()

        return self

    def to_domain(self) -> PlaceBet:
        '''Called when Done — constructs Op from accumulated state.'''
        return PlaceBet(
            bet=self.bet_type.unwrap(),
            amount=self.amount.unwrap(),
        )
```

## Multiple Transitions (Multi-Transport)

When different transports need different parameters, use multiple `@transition` methods.
nodnod routes by node types in signature — first resolvable wins (like SequentialEither).

```python
from emergent.wire.axis.surface.codecs import transition, Done

@dataclass
class BetFlow:
    bet_type: Option[str] = field(default_factory=Nothing)
    amount: Option[int] = field(default_factory=Nothing)

    @transition
    async def http(
        self,
        bet_input: Option[BetInput],
        request: fastapi.Request,
    ) -> Self | tuple[Self, TokenAcceptedResponse] | Done:
        '''HTTP: parse from Pydantic body.'''
        match bet_input:
            case Some(inp):
                return replace(self, bet_type=Some(inp.bet), amount=Some(inp.amount))
        return self

    @transition
    async def telegram(
        self,
        bet_type: Option[BetType],
        msg: MessageCute,
    ) -> Self | Done:
        '''Telegram: compose from nodnod nodes + UI.'''
        if not self.bet_type:
            await msg.answer("🎰 Choose:", reply_markup=keyboard)
        match (self.bet_type, bet_type):
            case (Nothing(), Some(bt)):
                await msg.answer(f"Bet: {bt}. Enter amount:")
                return replace(self, bet_type=Some(bt))
        return Done()

    @transition
    async def cli(
        self,
        bet_type: Option[str],
        amount: Option[int],
    ) -> Self | tuple[Self, str] | Done:
        '''CLI: prompt for values.'''
        match (self.bet_type, bet_type):
            case (Nothing(), Some(bt)):
                return replace(self, bet_type=Some(bt)), "Enter amount:"
        return self

    def to_domain(self) -> PlaceBet:
        '''Shared across all transports.'''
        return PlaceBet(bet=self.bet_type.unwrap(), amount=self.amount.unwrap())
```

## Execution Flow

When transition returns `Done`:
1. Middlewares run → build scope_extras (e.g., AuthUser)
2. `state.to_domain()` → Op
3. `runner.run(op, scope_extras)` → Result
4. `response.from_domain(result)` → final response

## Codec Usage

```python
stateful(BetFlow, BetResponse).key(ChatId).use(auth_mw).build()
#        ↑ flow   ↑ response
```

"""

from __future__ import annotations

import types
from dataclasses import dataclass
from typing import Any, Callable, Generic, Never, Protocol, TypeVar, TYPE_CHECKING, cast

from kungfu import Option, Some, Nothing

from emergent.wire.axis.storage import Get, Set, Delete, MemoryStorage

if TYPE_CHECKING:
    from nodnod.agent.base import Agent


# ─── Transition Decorator ────────────────────────────────────────────────────


_TRANSITION_MARKER = "__is_transition__"


def transition(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Mark method as a transition handler.

    Multiple @transition methods can exist on a Flow class.
    nodnod routes by node types in signature — first resolvable wins.

    Example::

        @dataclass
        class BetFlow:
            @transition
            async def http(self, inp: Option[BetInput], req: Request) -> Self | Done:
                ...

            @transition
            async def telegram(self, bt: Option[BetType], msg: MessageCute) -> Self | Done:
                ...
    """
    setattr(fn, _TRANSITION_MARKER, True)
    return fn


def get_transitions(flow: type) -> list[Callable[..., Any]]:
    """Get all transition methods from a Flow class.

    Returns @transition-decorated methods, or [__transition__] if no decorators found.
    Methods are returned in definition order (first resolvable wins).
    """
    transitions: list[Callable[..., Any]] = []

    # Scan for @transition decorated methods
    for name in dir(flow):
        if name.startswith("_"):
            continue
        attr = getattr(flow, name, None)
        if callable(attr) and getattr(attr, _TRANSITION_MARKER, False):
            transitions.append(attr)

    # Fallback to __transition__ if no decorators found
    if not transitions:
        classic = getattr(flow, "__transition__", None)
        if classic is not None:
            transitions.append(classic)

    return transitions


def has_transitions(flow: type) -> bool:
    """Check if Flow class has any transition methods."""
    return bool(get_transitions(flow))


# ─── Terminal Marker ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Done:
    """Terminal marker — signals flow complete, triggers Op execution.

    When __transition__ returns Done:
    1. Middlewares run (build scope_extras)
    2. state.to_domain() → Op
    3. runner.run(op, scope_extras) → Result
    4. response.from_domain(result) → final response

    Return types from __transition__:
    - `Self` — continue collecting, save state
    - `tuple[Self, R]` — continue + intermediate response R
    - `Done` — complete, execute Op
    """

    pass


# ─── Transition Result ───────────────────────────────────────────────────────


State = TypeVar("State")
Response = TypeVar("Response")


@dataclass(frozen=True, slots=True)
class TransitionResult(Generic[State, Response]):
    """Parsed result from __transition__ call."""

    state_or_done: State | Done
    response: Option[Response]
    is_terminal: bool


def parse_transition_result(
    result: State | Done | tuple[State, Response] | tuple[Done, Response],
) -> TransitionResult[State, Response]:
    """Parse __transition__ return value."""
    if isinstance(result, tuple):
        state_or_done = cast("State | Done", result[0])
        response: Option[Response] = Some(cast(Response, result[1]))
    else:
        state_or_done = result
        response = Nothing()

    is_terminal = isinstance(state_or_done, Done)
    return TransitionResult(state_or_done, response, is_terminal)


# ─── State Store Protocol ────────────────────────────────────────────────────


S = TypeVar("S")


class StateStore(Get[str, S, Never], Set[str, S, Never], Delete[str, Never], Protocol[S]):
    """Persistence protocol for conversation state.

    Composes storage capabilities from storage axis:
    - Get[str, S, Never]: get(key) -> Result[Option[S], Never]
    - Set[str, S, Never]: set(key, state) -> Result[None, Never]
    - Delete[str, Never]: delete(key) -> Result[None, Never]

    Error type is Never — state stores are expected to be infallible.
    Use MemoryStorage from storage axis for in-memory implementation.
    """

    ...




# ─── StatefulCodec ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class StatefulCodec:
    """Stateful conversation codec — mirrors RRC across multiple turns.

    Attributes:
        flow: Dataclass with __transition__ and to_domain methods.
        response: Response class with from_domain(Result) class method.
        store: StateStore for state persistence.
        key_node: Node-like for session routing.
        agent_cls: nodnod Agent class.

    All behavior (auth, timeout, retry) lives in Handler.capabilities,
    not in the codec itself. Enrichers run when Done, before Op execution.
    """

    flow: type  # Dataclass with __transition__ + to_domain
    response: type | types.UnionType  # Response type or Union — must have from_domain
    store: StateStore[Any]
    key_node: type  # Node-like for store key
    agent_cls: type  # nodnod Agent class


# ─── Builder ────────────────────────────────────────────────────────────────


class StatefulBuilder:
    """Type-safe StatefulCodec builder.

    Usage::

        codec = stateful(BetFlow, BetResponse).key(ChatId).build()

    All behavior (auth, timeout, retry) lives in Handler.capabilities:

        endpoint(runner).expose(
            trigger,
            stateful(BetFlow, BetResponse).key(ChatId).build(),
            C.enricher.Provide(type=AuthUser, ...),  # runs when Done
        )
    """

    __slots__ = ("_flow", "_response", "_store", "_key_node", "_agent_cls")

    def __init__(self, flow: type, response: type | types.UnionType) -> None:
        self._flow = flow
        self._response = response
        self._store: StateStore[Any] | None = None
        self._key_node: type | None = None
        self._agent_cls: type[Agent] | None = None

    def store(self, store: StateStore[Any]) -> StatefulBuilder:
        """Set state store (default: MemoryStorage from storage axis)."""
        self._store = store
        return self

    def key(self, key_node: type) -> StatefulBuilder:
        """Set key node-like for session routing (required)."""
        self._key_node = key_node
        return self

    def agent(self, agent_cls: type[Agent]) -> StatefulBuilder:
        """Set nodnod agent class (default: EventLoopAgent)."""
        self._agent_cls = agent_cls
        return self

    def build(self) -> StatefulCodec:
        """Build the codec."""
        if self._key_node is None:
            raise ValueError("key_node is required — call .key(NodeType)")

        if not has_transitions(self._flow):
            raise ValueError(
                f"{self._flow.__name__} must define __transition__ or @transition methods"
            )

        if not hasattr(self._flow, "to_domain"):
            raise ValueError(f"{self._flow.__name__} must define to_domain()")

        from nodnod.agent.event_loop.agent import EventLoopAgent

        return StatefulCodec(
            flow=self._flow,
            response=self._response,
            store=self._store if self._store is not None else MemoryStorage[str, Any](),
            key_node=self._key_node,
            agent_cls=self._agent_cls or EventLoopAgent,
        )


def stateful(flow: type, response: type | types.UnionType) -> StatefulBuilder:
    """Create StatefulCodec builder.

    Args:
        flow: Dataclass with __transition__ and to_domain methods.
        response: Response type (or Union). Must have from_domain() or contain member with it.

    Example::

        codec = stateful(BetFlow, BetResponse).key(ChatId).build()

        # Union for multiple response types (intermediate + final):
        codec = stateful(BetFlow, IntermediateResp | FinalResp).key(ChatId).build()
    """
    return StatefulBuilder(flow, response)
