"""Scope enricher protocol and base."""

from __future__ import annotations

from typing import Awaitable, Callable, Protocol, runtime_checkable, TYPE_CHECKING

from emergent.wire.axis.surface.capabilities._base import SurfaceCapability

if TYPE_CHECKING:
    from nodnod import Scope
    from emergent.wire.axis._capability import HandlerRuntimeContext


# Next handler type for ScopeEnricher — generic over response type
type EnricherNext[R] = Callable[[Scope], Awaitable[R]]


@runtime_checkable
class ScopeEnricher(SurfaceCapability, Protocol):
    """Capability that enriches scope at runtime (middleware pattern).

    Sequential scope enrichment before/during handler execution.
    Can short-circuit (auth failure), transform (retry, cache),
    or inject values into scope.

    Example::

        @dataclass(frozen=True, slots=True)
        class Auth(ScopeEnricher):
            request_cls: type[HasAuth]

            async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
                req = scope.get(self.request_cls)
                if req is None:
                    return AuthErrorResponse(error="not in scope")
                # ... auth logic ...
                return await call(scope)
    """

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        """Enrich scope and call next handler."""
        ...

    def compile_handler_runtime(self, ctx: "HandlerRuntimeContext") -> "HandlerRuntimeContext":
        """Default: add self to enrichers tuple."""
        from dataclasses import replace
        return replace(ctx, enrichers=(*ctx.enrichers, self))


__all__ = (
    "ScopeEnricher",
    "EnricherNext",
)
