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

## Execution Flow

When `__transition__` returns `Done`:
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
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Generic, Protocol, TypeVar, TYPE_CHECKING, cast, runtime_checkable

from kungfu import Option, Some, Nothing, Result, Ok, Error

from emergent.ops._graph import Op, Runner

if TYPE_CHECKING:
    from nodnod.agent.base import Agent


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


class StateStore(Protocol[S]):
    """Persistence protocol for conversation state."""

    @abstractmethod
    async def get(self, key: str) -> S | None:
        """Load state for key. Returns None if no state exists."""
        ...

    @abstractmethod
    async def set(self, key: str, state: S) -> None:
        """Save state for key."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Clear state for key."""
        ...


class MemoryStateStore(StateStore[S], Generic[S]):
    """In-memory state store for development/testing."""

    def __init__(self) -> None:
        self._states: dict[str, S] = {}

    async def get(self, key: str) -> S | None:
        return self._states.get(key)

    async def set(self, key: str, state: S) -> None:
        self._states[key] = state

    async def delete(self, key: str) -> None:
        self._states.pop(key, None)


# ─── Stateful Middleware (mirrors RRC Middleware) ────────────────────────────


Req = TypeVar("Req", contravariant=True)  # State type (contravariant for Protocol)
T = TypeVar("T")  # Success type to inject
E = TypeVar("E")  # Error type
Resp = TypeVar("Resp", covariant=True)  # Rejection response


@runtime_checkable
class StatefulMiddleware(Protocol[Req, T, E, Resp]):
    """Middleware for StatefulCodec — runs when Done, before Op execution.

    Mirrors RRC Middleware but sees state instead of request.

    Generic parameters:
        Req:  State type (the flow class)
        T:    Success type (injected into scope_extras on Ok)
        E:    Error type
        Resp: Rejection response type produced by reject()
    """

    @property
    def runner(self) -> Runner: ...

    @property
    def inject_as(self) -> type[T]: ...

    def build(self, state: Req, /) -> Op[T, E] | None:
        """Build op from state. Return None to skip this middleware."""
        ...

    def reject(self, result: Result[T, E], /) -> Resp: ...


_S = TypeVar("_S")  # State type for concrete middleware
_Resp = TypeVar("_Resp")  # Response type for concrete middleware


class stateful_middleware(Generic[_S, T, E, _Resp]):
    """Concrete StatefulMiddleware from components.

    Usage::

        auth_mw = stateful_middleware(
            auth_runner,
            AuthUser,
            lambda state: Authenticate(token=state.token.unwrap()) if state.token else None,
            AuthErrorResponse.from_domain,
        )

    The build function returns None to skip (e.g., when token not yet collected).
    """

    __slots__ = ("_runner", "_inject_as", "_build_fn", "_reject_fn")

    def __init__(
        self,
        runner: Runner,
        inject_as: type[T],
        build: Callable[[_S], Op[T, E] | None],
        reject: Callable[[Result[T, E]], _Resp],
    ) -> None:
        self._runner = runner
        self._inject_as = inject_as
        self._build_fn = build
        self._reject_fn = reject

    @property
    def runner(self) -> Runner:
        return self._runner

    @property
    def inject_as(self) -> type[T]:
        return self._inject_as

    def build(self, state: _S, /) -> Op[T, E] | None:
        return self._build_fn(state)

    def reject(self, result: Result[T, E], /) -> _Resp:
        return self._reject_fn(result)


async def run_middlewares(
    middlewares: tuple[StatefulMiddleware[Any, Any, Any, Any], ...],
    state: Any,
) -> tuple[dict[type, Any], Option[Any]]:
    """Execute middleware chain when Done.

    Returns:
        (scope_extras, rejection) where:
        - scope_extras: dict of {type: value} to pass to runner.run()
        - rejection: Some(response) if middleware rejected, Nothing() otherwise
    """
    scope_extras: dict[type, Any] = {}

    for mw in middlewares:
        op = mw.build(state)
        if op is None:
            continue  # Skip this middleware

        result = await mw.runner.run(op)
        match result:
            case Ok(value):
                scope_extras[mw.inject_as] = value
            case Error():
                return (scope_extras, Some(mw.reject(result)))

    return (scope_extras, Nothing())


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
        middlewares: Run when Done, before Op execution.
    """

    flow: type  # Dataclass with __transition__ + to_domain
    response: type | types.UnionType  # Response type or Union — must have from_domain
    store: StateStore[Any]
    key_node: type  # Node-like for store key
    agent_cls: type  # nodnod Agent class
    middlewares: tuple[StatefulMiddleware[Any, Any, Any, Any], ...]


# ─── Builder ────────────────────────────────────────────────────────────────


class StatefulBuilder:
    """Type-safe StatefulCodec builder.

    Usage::

        codec = stateful(BetFlow, BetResponse).key(ChatId).build()

        # With middleware:
        codec = (
            stateful(BetFlow, BetResponse)
            .key(ChatId)
            .use(auth_mw)
            .build()
        )
    """

    __slots__ = ("_flow", "_response", "_store", "_key_node", "_agent_cls", "_middlewares")

    def __init__(self, flow: type, response: type | types.UnionType) -> None:
        self._flow = flow
        self._response = response
        self._store: StateStore[Any] | None = None
        self._key_node: type | None = None
        self._agent_cls: type[Agent] | None = None
        self._middlewares: list[StatefulMiddleware[Any, Any, Any, Any]] = []

    def store(self, store: StateStore[Any]) -> StatefulBuilder:
        """Set state store (default: MemoryStateStore)."""
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

    def use(self, mw: StatefulMiddleware[Any, Any, Any, Any]) -> StatefulBuilder:
        """Add middleware (runs when Done, before Op execution)."""
        self._middlewares.append(mw)
        return self

    def build(self) -> StatefulCodec:
        """Build the codec."""
        if self._key_node is None:
            raise ValueError("key_node is required — call .key(NodeType)")

        if not hasattr(self._flow, "__transition__"):
            raise ValueError(f"{self._flow.__name__} must define __transition__")

        if not hasattr(self._flow, "to_domain"):
            raise ValueError(f"{self._flow.__name__} must define to_domain()")

        from nodnod.agent.event_loop.agent import EventLoopAgent

        return StatefulCodec(
            flow=self._flow,
            response=self._response,
            store=self._store if self._store is not None else MemoryStateStore(),
            key_node=self._key_node,
            agent_cls=self._agent_cls or EventLoopAgent,
            middlewares=tuple(self._middlewares),
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
