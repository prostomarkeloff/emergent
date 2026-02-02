from __future__ import annotations

from dataclasses import dataclass, field

from emergent.wire.axis.surface._endpoint import Endpoint


@dataclass(slots=True)
class Application:
    endpoints: list[Endpoint] = field(default_factory=list[Endpoint])

    def mount(self, *endps: Endpoint) -> Application:
        return Application(endpoints=[*self.endpoints, *endps])

    def __add__(self, other: Application) -> Application:
        """Combine two applications — sum their endpoints."""
        return Application(endpoints=[*self.endpoints, *other.endpoints])

    def merge(self, *others: Application) -> Application:
        """Merge multiple applications into one."""
        all_endpoints = list(self.endpoints)
        for other in others:
            all_endpoints.extend(other.endpoints)
        return Application(endpoints=all_endpoints)


def application() -> Application:
    return Application()
