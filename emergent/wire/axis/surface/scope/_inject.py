"""Middleware builder — inject values into scope.

Middleware's PURPOSE is to inject a typed value into scope.
Everything else is HOW: which runner, how to build op, how to format errors.

Usage::

    # RRC middleware (from request)
    auth_mw = (
        inject(AuthUser)
            .using(auth_runner)
            .from_request(HasAuth, HasAuth.to_auth)
            .on_reject(AuthErrorResponse.from_domain)
            .build()
    )

    # Stateful middleware (from state, can skip via None)
    tg_auth_mw = (
        inject(AuthUser)
            .using(auth_runner)
            .from_state(HasChatId, lambda s: TelegramIdentity(s.chat_id) if s.chat_id else None)
            .on_reject(AuthErrorResponse.from_domain)
            .build()
    )
"""

from __future__ import annotations

from typing import Callable, Generic, TypeVar

from kungfu import Result

from emergent.ops._graph import Op, Runner
from emergent.wire.axis.surface.scope._protocol import Middleware, StatefulMiddleware


# ─── Type Variables ──────────────────────────────────────────────────────────

T = TypeVar("T")  # Type to inject (success type)
E = TypeVar("E")  # Error type
Req = TypeVar("Req")  # Request type
State = TypeVar("State")  # State type
Resp = TypeVar("Resp")  # Response type


# ─── Concrete Implementations ────────────────────────────────────────────────


class ConcreteMiddleware(Generic[Req, T, E, Resp]):
    """Concrete Middleware for RRC codecs."""

    __slots__ = ("_runner", "_inject_as", "_build_fn", "_reject_fn")

    def __init__(
        self,
        inject_as: type[T],
        runner: Runner,
        build_fn: Callable[[Req], Op[T, E]],
        reject_fn: Callable[[Result[T, E]], Resp],
    ) -> None:
        self._runner = runner
        self._inject_as = inject_as
        self._build_fn = build_fn
        self._reject_fn = reject_fn

    @property
    def runner(self) -> Runner:
        return self._runner

    @property
    def inject_as(self) -> type[T]:
        return self._inject_as

    def build(self, request: Req, /) -> Op[T, E]:
        return self._build_fn(request)

    def reject(self, result: Result[T, E], /) -> Resp:
        return self._reject_fn(result)


class ConcreteStatefulMiddleware(Generic[State, T, E, Resp]):
    """Concrete Middleware for Stateful codecs."""

    __slots__ = ("_runner", "_inject_as", "_build_fn", "_reject_fn")

    def __init__(
        self,
        inject_as: type[T],
        runner: Runner,
        build_fn: Callable[[State], Op[T, E] | None],
        reject_fn: Callable[[Result[T, E]], Resp],
    ) -> None:
        self._runner = runner
        self._inject_as = inject_as
        self._build_fn = build_fn
        self._reject_fn = reject_fn

    @property
    def runner(self) -> Runner:
        return self._runner

    @property
    def inject_as(self) -> type[T]:
        return self._inject_as

    def build(self, state: State, /) -> Op[T, E] | None:
        return self._build_fn(state)

    def reject(self, result: Result[T, E], /) -> Resp:
        return self._reject_fn(result)


# ─── Builders ────────────────────────────────────────────────────────────────


class InjectBuilder(Generic[T]):
    """First stage: inject(Type).using(runner)"""

    __slots__ = ("_inject_as",)

    def __init__(self, inject_as: type[T]) -> None:
        self._inject_as = inject_as

    def using(self, runner: Runner) -> InjectBuilderWithRunner[T]:
        """Which runner executes the op."""
        return InjectBuilderWithRunner(self._inject_as, runner)


class InjectBuilderWithRunner(Generic[T]):
    """Second stage: .from_request() or .from_state()"""

    __slots__ = ("_inject_as", "_runner")

    def __init__(self, inject_as: type[T], runner: Runner) -> None:
        self._inject_as = inject_as
        self._runner = runner

    def from_request(
        self,
        request_type: type[Req],
        build_fn: Callable[[Req], Op[T, E]],
    ) -> InjectBuilderRRC[Req, T, E]:
        """Build op from request -> creates RRC middleware.

        Args:
            request_type: Protocol/type the request must satisfy
            build_fn: Function to build Op from request

        Example::
            .from_request(HasAuth, HasAuth.to_auth)
            .from_request(HasAuth, lambda req: req.to_auth())
        """
        return InjectBuilderRRC(self._inject_as, self._runner, build_fn)

    def from_state(
        self,
        state_type: type[State],
        build_fn: Callable[[State], Op[T, E] | None],
    ) -> InjectBuilderStateful[State, T, E]:
        """Build op from state -> creates Stateful middleware.

        Return None from build_fn to skip this middleware.

        Args:
            state_type: Type of the flow state
            build_fn: Function to build Op from state (or None to skip)

        Example::
            .from_state(HasToken, lambda s: Authenticate(s.token) if s.token else None)
        """
        return InjectBuilderStateful(self._inject_as, self._runner, build_fn)


class InjectBuilderRRC(Generic[Req, T, E]):
    """Third stage for RRC: .on_reject().build()"""

    __slots__ = ("_inject_as", "_runner", "_build_fn")

    def __init__(
        self,
        inject_as: type[T],
        runner: Runner,
        build_fn: Callable[[Req], Op[T, E]],
    ) -> None:
        self._inject_as = inject_as
        self._runner = runner
        self._build_fn = build_fn

    def on_reject(
        self, reject_fn: Callable[[Result[T, E]], Resp]
    ) -> InjectBuilderRRCFinal[Req, T, E, Resp]:
        """How to format rejection response on error."""
        return InjectBuilderRRCFinal(
            self._inject_as, self._runner, self._build_fn, reject_fn
        )


class InjectBuilderRRCFinal(Generic[Req, T, E, Resp]):
    """Final stage for RRC: .build()"""

    __slots__ = ("_inject_as", "_runner", "_build_fn", "_reject_fn")

    def __init__(
        self,
        inject_as: type[T],
        runner: Runner,
        build_fn: Callable[[Req], Op[T, E]],
        reject_fn: Callable[[Result[T, E]], Resp],
    ) -> None:
        self._inject_as = inject_as
        self._runner = runner
        self._build_fn = build_fn
        self._reject_fn = reject_fn

    def build(self) -> Middleware[Req, T, E, Resp]:
        """Build the RRC middleware."""
        return ConcreteMiddleware(
            inject_as=self._inject_as,
            runner=self._runner,
            build_fn=self._build_fn,
            reject_fn=self._reject_fn,
        )


class InjectBuilderStateful(Generic[State, T, E]):
    """Third stage for Stateful: .on_reject().build()"""

    __slots__ = ("_inject_as", "_runner", "_build_fn")

    def __init__(
        self,
        inject_as: type[T],
        runner: Runner,
        build_fn: Callable[[State], Op[T, E] | None],
    ) -> None:
        self._inject_as = inject_as
        self._runner = runner
        self._build_fn = build_fn

    def on_reject(
        self, reject_fn: Callable[[Result[T, E]], Resp]
    ) -> InjectBuilderStatefulFinal[State, T, E, Resp]:
        """How to format rejection response on error."""
        return InjectBuilderStatefulFinal(
            self._inject_as, self._runner, self._build_fn, reject_fn
        )


class InjectBuilderStatefulFinal(Generic[State, T, E, Resp]):
    """Final stage for Stateful: .build()"""

    __slots__ = ("_inject_as", "_runner", "_build_fn", "_reject_fn")

    def __init__(
        self,
        inject_as: type[T],
        runner: Runner,
        build_fn: Callable[[State], Op[T, E] | None],
        reject_fn: Callable[[Result[T, E]], Resp],
    ) -> None:
        self._inject_as = inject_as
        self._runner = runner
        self._build_fn = build_fn
        self._reject_fn = reject_fn

    def build(self) -> StatefulMiddleware[State, T, E, Resp]:
        """Build the Stateful middleware."""
        return ConcreteStatefulMiddleware(
            inject_as=self._inject_as,
            runner=self._runner,
            build_fn=self._build_fn,
            reject_fn=self._reject_fn,
        )


# ─── Factory ─────────────────────────────────────────────────────────────────


def inject(type_: type[T]) -> InjectBuilder[T]:
    """Create middleware that injects a typed value into scope.

    Usage::

        # RRC middleware
        auth_mw = (
            inject(AuthUser)
                .using(auth_runner)
                .from_request(HasAuth, HasAuth.to_auth)
                .on_reject(AuthErrorResponse.from_domain)
                .build()
        )

        # Stateful middleware
        tg_auth_mw = (
            inject(AuthUser)
                .using(auth_runner)
                .from_state(HasChatId, lambda s: TelegramIdentity(s.chat_id) if s.chat_id else None)
                .on_reject(AuthErrorResponse.from_domain)
                .build()
        )

    Args:
        type_: Type to inject into scope on success
    """
    return InjectBuilder(type_)


__all__ = ("inject", "InjectBuilder", "ConcreteMiddleware", "ConcreteStatefulMiddleware")
