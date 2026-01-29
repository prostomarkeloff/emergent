"""Middleware — the vertical composition axis of wire.

Mount determines WHERE an endpoint lives (spatial routing).
Middleware determines HOW a request is processed (scope enrichment).

These two axes are orthogonal:
    mount axis:      app.mount(endpoint)   — routing, grouping
    middleware axis:  codec middlewares      — scope transformation

A middleware is a typed scope enricher/guard. It sees the request
through a Protocol, builds an op, runs it via its own runner, and
injects the Ok value into the handler scope by type.
On Error the middleware produces its own response via reject() —
each axis owns its error formatting, axes never mix.
"""

from __future__ import annotations

from typing import Callable, Generic, Protocol, TypeVar, runtime_checkable

from kungfu import Result

from emergent.ops._graph import Op, Runner

Req = TypeVar("Req", contravariant=True)
T = TypeVar("T")
E = TypeVar("E")
Resp = TypeVar("Resp", covariant=True)

_Req = TypeVar("_Req")
_Resp = TypeVar("_Resp")


@runtime_checkable
class Middleware(Protocol[Req, T, E, Resp]):
    """Orthogonal typed scope enricher — a vertical axis of the codec.

    Generic parameters:
        Req:  Protocol the request must satisfy (e.g., HasAuth)
        T:    success type (injected into handler scope on Ok)
        E:    error type (middleware owns its error formatting via reject)
        Resp: rejection response type produced by reject()
    """

    @property
    def runner(self) -> Runner: ...

    @property
    def inject_as(self) -> type[T]: ...

    def build(self, request: Req, /) -> Op[T, E]: ...

    def reject(self, result: Result[T, E], /) -> Resp: ...


class middleware(Generic[_Req, T, E, _Resp]):
    """Concrete middleware from components.

    Usage::

        auth_mw = middleware(
            auth_runner,
            AuthUser,
            HasAuth.to_auth,
            AuthErrorResponse.from_domain,
        )
    """

    __slots__ = ("_runner", "_inject_as", "_build_fn", "_reject_fn")

    def __init__(
        self,
        runner: Runner,
        inject_as: type[T],
        build: Callable[[_Req], Op[T, E]],
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

    def build(self, request: _Req, /) -> Op[T, E]:
        return self._build_fn(request)

    def reject(self, result: Result[T, E], /) -> _Resp:
        return self._reject_fn(result)


__all__ = ("Middleware", "middleware")
