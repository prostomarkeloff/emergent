"""
Codecs — convert transport payloads to domain ops and back.

    from emergent.wire.axis.surface import codecs

    # RRC: Request/Response pattern
    codec = codecs.rrc(RegisterRequest, RegisterResponse).use(auth_mw).build()

    # Stateful: FSM-based conversations
    codec = codecs.stateful(BetFlow, BetStart).key(ChatId).build()

    # Multi-transport stateful: multiple @transition methods
    from emergent.wire.axis.surface.codecs import transition

    @dataclass
    class BetFlow:
        @transition
        async def http(self, inp: Option[BetInput]) -> Self | Done: ...

        @transition
        async def telegram(self, msg: MessageCute) -> Self | Done: ...
"""

from emergent.wire.axis.surface.codecs.rrc import (
    RequestResponseCodec,
    RRCBuilder,
    ToDomain,
    FromDomain,
    rrc,
)
from emergent.wire.axis.surface.codecs.stateful import (
    StatefulCodec,
    StatefulBuilder,
    Done,
    StateStore,
    stateful,
    transition,
    get_transitions,
    has_transitions,
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
    "stateful",
    # Multi-transition
    "transition",
    "get_transitions",
    "has_transitions",
)
