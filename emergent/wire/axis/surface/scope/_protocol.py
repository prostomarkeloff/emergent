"""Middleware protocols — scope enrichment contracts.

Middleware is a vertical composition axis that enriches request context
before the main handler runs. It's orthogonal to:
- Codecs (execution shapes)
- Triggers (attachment points)

Two protocol variants:
- Middleware: for RRC codec (always extracts Op)
- StatefulMiddleware: for Stateful codec (can skip via None)
"""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from kungfu import Result

from emergent.ops._graph import Op, Runner


# ─── Type Variables ──────────────────────────────────────────────────────────

Req = TypeVar("Req", contravariant=True)  # Request/State protocol
T = TypeVar("T")  # Success type (injected into scope)
E = TypeVar("E")  # Error type
Resp = TypeVar("Resp", covariant=True)  # Rejection response type


# ─── RRC Middleware Protocol ─────────────────────────────────────────────────


@runtime_checkable
class Middleware(Protocol[Req, T, E, Resp]):
    """Scope enricher for request-response codecs.

    Generic parameters:
        Req:  Protocol the request must satisfy (e.g., HasAuth)
        T:    Success type (injected into handler scope on Ok)
        E:    Error type (middleware owns its error formatting)
        Resp: Rejection response type produced by reject()

    Flow:
        request[Req] → extract() → Op[T, E] → runner.run() →
            Ok(T) → scope[inject_as] = value
            Error(E) → reject() → Resp
    """

    @property
    def runner(self) -> Runner:
        """Runner that executes the extracted Op."""
        ...

    @property
    def inject_as(self) -> type[T]:
        """Type key for injecting result into scope."""
        ...

    def build(self, request: Req, /) -> Op[T, E]:
        """Build Op from request. Called for every request."""
        ...

    def reject(self, result: Result[T, E], /) -> Resp:
        """Format rejection response on Error. Each middleware owns its errors."""
        ...


# ─── Stateful Middleware Protocol ────────────────────────────────────────────


@runtime_checkable
class StatefulMiddleware(Protocol[Req, T, E, Resp]):
    """Scope enricher for stateful codecs — runs when Done, before Op execution.

    Like Middleware but extract() can return None to skip (e.g., when
    authentication data isn't collected yet in the flow state).

    Generic parameters:
        Req:  State type (the flow class)
        T:    Success type (injected into scope_extras on Ok)
        E:    Error type
        Resp: Rejection response type produced by reject()
    """

    @property
    def runner(self) -> Runner:
        """Runner that executes the extracted Op."""
        ...

    @property
    def inject_as(self) -> type[T]:
        """Type key for injecting result into scope."""
        ...

    def build(self, state: Req, /) -> Op[T, E] | None:
        """Build Op from state. Return None to skip this middleware."""
        ...

    def reject(self, result: Result[T, E], /) -> Resp:
        """Format rejection response on Error."""
        ...


__all__ = ("Middleware", "StatefulMiddleware")
