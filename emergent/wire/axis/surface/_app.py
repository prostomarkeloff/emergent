from __future__ import annotations

from dataclasses import dataclass, field

from emergent.wire.axis.surface._endpoint import Endpoint


@dataclass(slots=True)
class Application:
    endpoints: list[Endpoint] = field(default_factory=list[Endpoint])

    def mount(self, *endps: Endpoint) -> Application:
        return Application(endpoints=[*self.endpoints, *endps])


def application() -> Application:
    return Application()
