from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from kungfu import Result

from emergent.ops._graph import Op


T_co = TypeVar("T_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)
DomainT_co = TypeVar("DomainT_co", covariant=True)
DomainT_contra = TypeVar("DomainT_contra", contravariant=True)


class ToDomain(Protocol[DomainT_co]):
    def to_domain(self) -> DomainT_co: ...


class FromDomain(Protocol[DomainT_contra]):
    @classmethod
    def from_domain(cls, dom: DomainT_contra) -> "FromDomain[DomainT_contra]": ...


@dataclass(frozen=True, slots=True)
class RequestResponseCodec:
    request: type[ToDomain[Any]]
    response: type[FromDomain[Result[Any, Any]]]

    if TYPE_CHECKING:

        def __init__(
            self,
            request: type[ToDomain[Op[T_co, E_co]]],
            response: type[FromDomain[Result[T_co, E_co]]],
        ) -> None: ...
