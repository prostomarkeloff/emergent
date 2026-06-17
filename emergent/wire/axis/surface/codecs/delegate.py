"""Delegate codec — preserves original handler signature.

Handler is preserved as-is. Use capabilities to control execution:
- Mount(app) — mount ASGI app instead of calling handler

    # Simple delegate
    delegate(get_user)

    endpoint(...).expose(
        trigger,
        delegate(handler),
    )

    # With Mount capability — mounts ASGI
    endpoint(...).expose(
        trigger,
        delegate(handler),
        Mount(django_asgi),
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from kungfu import Option, Nothing, Some

from emergent.wire.axis._explain import ExplainContext, ExplainNode, callable_name


def _nothing() -> Option[type]:
    return Nothing()


@dataclass(frozen=True, slots=True)
class DelegateCodec:
    """Delegate to original handler.

    Handler signature is preserved. Behavior controlled via capabilities:
    - Without capabilities: target framework handles params
    - With Compose(): params resolved via compose dialect
    - With Mount(): ASGI app mounted instead

    Attributes:
        handler: Original handler callable.
        response: Response type for documentation.
    """

    handler: Callable[..., Any]
    response: Option[type] = field(default_factory=_nothing)

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(
            ExplainNode("DelegateCodec", (("handler", callable_name(self.handler)),))
        )


def delegate(
    handler: Callable[..., Any],
    response: type | None = None,
) -> DelegateCodec:
    """Create delegate codec.

    Args:
        handler: Original handler callable.
        response: Response type for docs/OpenAPI.

    Examples::

        # Simple — framework handles params
        delegate(get_user)

        # With compose (via capability)
        endpoint(...).expose(trigger, delegate(handler), Compose())

        # With mount (via capability)
        endpoint(...).expose(trigger, delegate(handler), Mount(asgi_app))
    """
    resp: Option[type] = Some(response) if response is not None else Nothing()
    return DelegateCodec(handler=handler, response=resp)


__all__ = (
    "DelegateCodec",
    "delegate",
)
