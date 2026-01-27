from dataclasses import dataclass, field
from typing import Literal

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
