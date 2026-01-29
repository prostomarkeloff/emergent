from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, Protocol, Self, TypeVar

from kungfu import Result, Ok, Error

from emergent.ops._graph import Op
from emergent.wire._handler import Handler
from emergent.wire._middleware import Middleware


T_co = TypeVar("T_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)
DomainT_co = TypeVar("DomainT_co", covariant=True)
DomainT_contra = TypeVar("DomainT_contra", contravariant=True)


class ToDomain(Protocol[DomainT_co]):
    """Protocol for types that can convert to domain Ops."""

    def to_domain(self) -> DomainT_co: ...


class FromDomain(Protocol[DomainT_contra]):
    """Protocol for types that can convert from domain Results.

    Implementations should define:
        @classmethod
        def from_domain(cls, dom: Result[T, E]) -> Self: ...
    """

    @classmethod
    def from_domain(cls, dom: DomainT_contra) -> Self: ...


_R = TypeVar("_R", bound=ToDomain[Op[Any, Any]])
_MT = TypeVar("_MT")
_ME = TypeVar("_ME")
_MR = TypeVar("_MR")


@dataclass(frozen=True, slots=True)
class RequestResponseCodec:
    """Request-response codec with orthogonal middleware axes.

    Type-safe RRC:
    - request.to_domain() → Op[T, E]
    - runner.run(op) → Result[T, E]
    - response.from_domain(result) → Response

    middlewares: tuple of typed scope enrichers that run before
    the main handler. Each middleware sees the request through
    its own Protocol, builds an op, runs it, and enriches the
    handler scope with the result. On Error, the middleware
    produces its own response via reject() — axes never mix.
    """

    request: type[ToDomain[Op[Any, Any]]]
    response: type[FromDomain[Result[Any, Any]]]
    middlewares: tuple[Middleware[Any, Any, Any, Any], ...] = ()


async def execute(
    handler: Handler[RequestResponseCodec],
    request: ToDomain[Op[Any, Any]],
) -> FromDomain[Result[Any, Any]]:
    """RRC execution pipeline: middlewares → request → op → result → response.

    Co-located with the codec because the execution semantics are
    determined by the codec type. Other codecs (streaming, event, etc.)
    provide their own ``execute`` with different signatures.

    Middleware axes run first — each enriches the handler scope.
    On middleware Error, the middleware's own reject() produces a
    response — each axis owns its error formatting, axes never mix.
    """
    scope_extras: dict[type, object] = {}

    for mw in handler.codec.middlewares:
        mw_op = mw.build(request)
        mw_result = await mw.runner.run(mw_op)

        match mw_result:
            case Ok(value):
                scope_extras[mw.inject_as] = value
            case Error():
                return mw.reject(mw_result)

    op = request.to_domain()
    result = await handler.runner.run(op, scope_extras=scope_extras)
    return handler.codec.response.from_domain(result)


class RRCBuilder(Generic[_R]):
    """Type-safe RRC builder — .use(mw) verifies request satisfies middleware protocol.

    Usage::

        codec = rrc(BetRequest, BetResponse).use(auth_mw).build()

    Pyright checks that BetRequest satisfies the middleware's Req protocol
    (e.g., HasAuth). If BetRequest lacks to_auth(), pyright errors at .use().
    """

    __slots__ = ("_request", "_response", "_middlewares")

    def __init__(
        self,
        request: type[_R],
        response: type[FromDomain[Result[Any, Any]]],
    ) -> None:
        self._request = request
        self._response = response
        self._middlewares: list[Middleware[Any, Any, Any, Any]] = []

    def use(self, mw: Middleware[_R, _MT, _ME, _MR]) -> RRCBuilder[_R]:
        """Add middleware — pyright verifies request satisfies middleware's Req protocol."""
        self._middlewares.append(mw)
        return self

    def build(self) -> RequestResponseCodec:
        """Produce the codec."""
        return RequestResponseCodec(
            self._request,
            self._response,
            middlewares=tuple(self._middlewares),
        )


def rrc(
    request: type[_R],
    response: type[FromDomain[Result[Any, Any]]],
) -> RRCBuilder[_R]:
    """Type-safe RRC factory: rrc(Request, Response).use(mw).build()"""
    return RRCBuilder(request, response)
