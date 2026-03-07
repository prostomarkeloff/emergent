"""Lookup operations — composable read-only utility ops.

EXISTS and COUNT are generic ops that can be mixed into any CRUD ops tuple.

    from emergent.wire.derive.patterns.lookup import EXISTS, COUNT
    from emergent.wire.derive._crud import LIST, GET, CREATE

    @schema_meta(http_crud("/api/items", Items, ops=(LIST, GET, CREATE, EXISTS, COUNT)))
"""

from emergent.wire.derive._effects import Read
from emergent.wire.derive._handler import CountAll, ExistsById
from emergent.wire.derive._opspec import Op
from emergent.wire.derive._project import BoolResponse, CountResponse, NoFields, IdOnly


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
