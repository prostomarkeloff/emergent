"""Codec construction — simple helpers, no heuristics.

Bridger decides which codec to use. Core provides construction helpers.

    from emergent.wire.bridge._codec import make_rrc, make_delegate

    # Bridger decides:
    if has_typed_request_response:
        codec = make_rrc(request_type, response_type)
    else:
        codec = make_delegate(shape.handler, response_type)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from emergent.wire.axis.surface._types import Codec


def make_rrc(request_type: type, response_type: type) -> Codec:
    """Create RRC codec from request and response types.

    Use when bridger knows both types explicitly.
    """
    from emergent.wire.axis.surface.codecs.rrc import rrc

    return rrc(request_type, response_type)


def make_delegate(
    handler: Callable[..., object],
    response_type: type | None = None,
) -> Codec:
    """Create delegate codec from handler.

    Use when bridger wants to preserve original handler signature.
    """
    from emergent.wire.axis.surface.codecs.delegate import delegate

    return delegate(handler, response=response_type)


__all__ = (
    "make_rrc",
    "make_delegate",
)
