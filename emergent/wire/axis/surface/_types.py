"""Surface axis types — Trigger, Codec, Exposure."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from emergent.wire.axis.surface.capabilities import SurfaceCapability


# Compiler can support any possible pairs
# TODO: add more standard codecs via Protocol
type Trigger = object
type Codec = object


@dataclass(frozen=True, slots=True)
class Exposure:
    """Endpoint exposure: trigger + codec + capabilities."""

    trigger: Trigger
    codec: Codec
    capabilities: tuple[SurfaceCapability, ...] = field(default_factory=tuple)
