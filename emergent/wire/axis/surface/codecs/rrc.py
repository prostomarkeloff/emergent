from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Self, TypeVar, runtime_checkable

from kungfu import Result

from emergent.ops._graph import Op
from emergent.wire.axis.surface._handler import Handler


T_co = TypeVar("T_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)
DomainT_co = TypeVar("DomainT_co", covariant=True)
DomainT_contra = TypeVar("DomainT_contra", contravariant=True)


class ToDomain(Protocol[DomainT_co]):
    """Protocol for types that can convert to domain Ops."""

    def to_domain(self) -> DomainT_co: ...


@runtime_checkable
class FromDomain(Protocol[DomainT_contra]):
    """Protocol for types that can convert from domain Results.

    Implementations should define:
        @classmethod
        def from_domain(cls, dom: Result[T, E]) -> Self: ...
    """

    @classmethod
    def from_domain(cls, dom: DomainT_contra) -> Self: ...


_R = TypeVar("_R", bound=ToDomain[Op[Any, Any]])


@dataclass(frozen=True, slots=True)
class RequestResponseCodec:
    """Request-response codec — pure types only.

    Type-safe RRC:
    - request.to_domain() → Op[T, E]
    - runner.run(op) → Result[T, E]
    - response.from_domain(result) → Response

    All behavior (auth, cache, timeout, retry) lives in capabilities
    attached to the endpoint via Handler.capabilities.

    Use ScopeEnricher capabilities for middleware-like behavior:

        endpoint(runner).expose(
            trigger,
            rrc(Request, Response),
            C.enricher.Auth(...),
            C.enricher.Timeout(seconds=5.0),
        )
    """

    request: type[ToDomain[Op[Any, Any]]]
    response: type[FromDomain[Result[Any, Any]]]


async def execute(
    handler: Handler[RequestResponseCodec],
    request: ToDomain[Op[Any, Any]],
) -> FromDomain[Result[Any, Any]]:
    """RRC execution pipeline: request → op → result → response.

    Co-located with the codec because the execution semantics are
    determined by the codec type. Other codecs (streaming, event, etc.)
    provide their own ``execute`` with different signatures.

    Note: ScopeEnricher capabilities are handled by the compiler adapter,
    not here. This is the core execution without enrichers.
    """
    op = request.to_domain()
    result = await handler.runner.run(op)
    return handler.codec.response.from_domain(result)


def rrc(
    request: type[_R],
    response: type[FromDomain[Result[Any, Any]]],
) -> RequestResponseCodec:
    """Create RRC codec — pure types only.

    Usage::

        endpoint(runner).expose(
            trigger,
            rrc(Request, Response),
            C.enricher.Auth(...),      # auth via capability
            C.enricher.Timeout(5.0),   # timeout via capability
        )

    All behavior (auth, cache, timeout) lives in capabilities,
    not in the codec itself.
    """
    return RequestResponseCodec(request, response)
