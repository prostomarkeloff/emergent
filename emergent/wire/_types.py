from emergent.wire.codecs.rrc import RequestResponseCodec

from typing import Any


# compiler can support any possible pairs
# TODO: add more standard codecs
type Trigger = Any
type Codec = RequestResponseCodec | Any
type Exposure = tuple[Trigger, Codec]
