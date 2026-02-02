"""Surface capability base and protocols."""

from __future__ import annotations

from typing import Awaitable, Callable, Protocol, TypeVar, runtime_checkable, TYPE_CHECKING

from emergent.wire.axis._capability import Capability as RootCapability

if TYPE_CHECKING:
    from nodnod import Scope


T = TypeVar("T")
R = TypeVar("R")


class SurfaceCapability(RootCapability):
    """Base for all surface capabilities.

    Inherits from root axis Capability.

    Surface capabilities modify the Trigger × Codec space.
    Categories:
    - Compile-time: TriggerTransform, HandlerTransform
    - Runtime: ResponseTransform, ScopeEnricher
    """

    pass


@runtime_checkable
class TriggerTransform(Protocol[T]):
    """Capability that transforms a trigger at compile time."""

    def apply_trigger(self, trigger: T) -> T:
        """Return modified trigger."""
        ...


@runtime_checkable
class HandlerTransform(Protocol):
    """Capability that wraps handler at compile time."""

    def apply_handler[T](self, handler: T) -> T:
        """Return wrapped handler."""
        ...


@runtime_checkable
class ResponseTransform(Protocol):
    """Capability that transforms response at runtime."""

    def apply_response[T](self, response: T) -> T:
        """Return transformed response."""
        ...


# Next handler type for ScopeEnricher — generic over response type
type EnricherNext[R] = Callable[[Scope], Awaitable[R]]


@runtime_checkable
class ScopeEnricher(Protocol):
    """Capability that enriches scope at runtime (middleware pattern).

    Sequential scope enrichment before/during handler execution.
    Can short-circuit (auth failure), transform (retry, cache),
    or inject values into scope.

    Uses combinators.py for operations (timeout, retry, rate_limit).

    Example implementation::

        @dataclass(frozen=True, slots=True)
        class Auth(SurfaceCapability):
            request_cls: type[HasAuth]

            async def enrich[R](self, call: EnricherNext[R], scope: Scope):
                req = scope.get(self.request_cls)
                if req is None:
                    return AuthErrorResponse(error="not in scope")

                result = await auth_runner.run(req.value.to_auth())

                match result:
                    case Ok(user):
                        scope.inject(AuthUser, user)
                        return await call(scope)
                    case Error(e):
                        return AuthErrorResponse(error=e)

    Usage::

        endpoint(runner).expose(
            trigger,
            rrc(Request, Response),
            Auth(BalanceRequest),
            Timeout(seconds=5.0),
        )
    """

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        """Enrich scope and call next handler."""
        ...


__all__ = (
    "SurfaceCapability",
    "TriggerTransform",
    "HandlerTransform",
    "ResponseTransform",
    "ScopeEnricher",
    "EnricherNext",
)
