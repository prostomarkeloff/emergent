"""
Codecs — convert transport payloads to domain ops and back.

    from emergent.wire.axis.surface import codecs, capabilities as C

    # RRC: Request/Response pattern (pure types)
    endpoint(runner).expose(
        trigger,
        codecs.rrc(Request, Response),
        C.enricher.Provide(type=AuthUser, ...),  # auth via capability
    )

    # Stateful: FSM-based conversations
    endpoint(runner).expose(
        trigger,
        codecs.stateful(BetFlow, BetResponse).key(ChatId).build(),
        C.enricher.Provide(type=AuthUser, ...),  # runs when Done
    )

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
from emergent.wire.axis.surface.codecs.immediate import (
    ImmediateCodec,
    ImmediateFactoryCodec,
    Producing,
    immediate,
    immediate_factory,
)
from emergent.wire.axis.surface.codecs.delegate import (
    DelegateCodec,
    delegate,
)

__all__ = (
    # RRC
    "RequestResponseCodec",
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
    # Immediate
    "ImmediateCodec",
    "ImmediateFactoryCodec",
    "Producing",
    "immediate",
    "immediate_factory",
    # Delegate
    "DelegateCodec",
    "delegate",
)
