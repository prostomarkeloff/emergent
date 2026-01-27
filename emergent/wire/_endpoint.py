from __future__ import annotations

from dataclasses import dataclass, field

from emergent.ops._graph import Runner
from emergent.wire._types import Codec, Exposure, Trigger


@dataclass(slots=True)
class Endpoint:
    runner: Runner
    exposures: list[Exposure] = field(default_factory=list[Exposure])

    @classmethod
    def from_runner(cls, runner: Runner) -> Endpoint:
        return cls(runner=runner)

    def expose(self, trigger: Trigger, codec: Codec) -> Endpoint:
        return Endpoint(
            runner=self.runner, exposures=[*self.exposures, (trigger, codec)]
        )


def endpoint(runner: Runner) -> Endpoint:
    return Endpoint.from_runner(runner)
