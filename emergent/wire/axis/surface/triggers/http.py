from dataclasses import dataclass, field
from typing import Literal

from emergent.wire.axis._explain import ExplainContext, ExplainNode

# TODO: do not invent. look for http libs.


type Method = Literal["GET", "POST", "PUT", "DELETE", "PATCH"]
type Path = str
type Header = str
type Headers = frozenset[str]


@dataclass(frozen=True, slots=True)
class HTTPRouteTrigger:
    method: Method
    path: str
    headers: frozenset[str] = field(default_factory=lambda: frozenset())

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        fields: tuple[tuple[str, str | list[str]], ...] = (
            ("method", self.method),
            ("path", self.path),
        )
        if self.headers:
            fields = (*fields, ("headers", sorted(self.headers)))
        return ctx.add(ExplainNode("HTTPRouteTrigger", fields))
