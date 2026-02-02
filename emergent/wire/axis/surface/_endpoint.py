from __future__ import annotations

from dataclasses import dataclass, field

from emergent.ops._graph import Runner
from emergent.wire.axis.surface._types import Codec, Exposure, Trigger
from emergent.wire.axis.surface.capabilities import SurfaceCapability


@dataclass(slots=True)
class Endpoint:
    runner: Runner
    exposures: list[Exposure] = field(default_factory=list[Exposure])

    @classmethod
    def from_runner(cls, runner: Runner) -> Endpoint:
        return cls(runner=runner)

    def expose(
        self,
        trigger: Trigger,
        codec: Codec,
        *capabilities: SurfaceCapability,
    ) -> Endpoint:
        exposure = Exposure(trigger, codec, capabilities)
        return Endpoint(
            runner=self.runner, exposures=[*self.exposures, exposure]
        )


def endpoint(runner: Runner) -> Endpoint:
    return Endpoint.from_runner(runner)
