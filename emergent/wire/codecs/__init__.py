"""
Codecs — convert transport payloads to domain ops and back.

    from emergent.wire.codecs import RequestResponseCodec

    # class Request(...): implements to_domain()
    # class Response(...): implements from_domain()
    # codec = RequestResponseCodec(Request, Response)
"""

from emergent.wire.codecs.rrc import (
    RequestResponseCodec,
    ToDomain,
    FromDomain,
)

__all__ = (
    "RequestResponseCodec",
    "ToDomain",
    "FromDomain",
)
