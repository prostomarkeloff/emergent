"""Lookup operations — composable read-only utility ops.

EXISTS and COUNT are generic ops that can be mixed into any dialect.
They use identity-based lookup and base_query counting respectively.

    from derivelib.patterns.crud import LIST, GET, CREATE
    from derivelib.patterns.lookup import EXISTS, COUNT

    @derive(dialect(
        LIST, GET, CREATE, EXISTS, COUNT,
        triggers=HTTPTriggers("/api/items"),
        provider_node=Items,
    ))
    @dataclass
    class Item: ...
"""

from derivelib._dialect import Op
from derivelib._effects import Read
from derivelib._handler_templates import ExistsById, CountAll
from derivelib._project import IdOnly, NoFields, BoolResponse, CountResponse

EXISTS = Op(
    "Exists",
    IdOnly(),
    BoolResponse(),
    ExistsById(),
    effects=(Read(),),
)

COUNT = Op(
    "Count",
    NoFields(),
    CountResponse(),
    CountAll(),
    effects=(Read(),),
)


__all__ = (
    "EXISTS",
    "COUNT",
)
