from typing import Self
from emergent.wire._endpoint import Endpoint


class Application:
    def __init__(self) -> None:
        self.endpoints: list[Endpoint] = []

    def mount(self, *endps: Endpoint) -> Self:
        self.endpoints.append(*endps)
        return self


def application() -> Application:
    return Application()
