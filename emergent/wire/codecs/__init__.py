"""
Codecs — convert transport payloads to domain ops and back.

    from emergent.wire.codecs import rrc, stateful

    # RRC: Request/Response pattern
    codec = rrc(RegisterRequest, RegisterResponse).use(auth_mw).build()

    # Stateful: FSM-based conversations
    codec = stateful(BetFlow, BetStart).key(ChatId).build()
"""

from emergent.wire.codecs.rrc import (
    RequestResponseCodec,
    RRCBuilder,
    ToDomain,
    FromDomain,
    rrc,
)
from emergent.wire.codecs.stateful import (
    StatefulCodec,
    StatefulBuilder,
    Done,
    StateStore,
    MemoryStateStore,
    stateful,
)

__all__ = (
    # RRC
    "RequestResponseCodec",
    "RRCBuilder",
    "ToDomain",
    "FromDomain",
    "rrc",
    # Stateful
    "StatefulCodec",
    "StatefulBuilder",
    "Done",
    "StateStore",
    "MemoryStateStore",
    "stateful",
)
