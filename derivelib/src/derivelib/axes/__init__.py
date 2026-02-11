"""Per-axis step libraries — pre-built steps for pattern authors.

    from derivelib.axes import schema, query, surface

    # Schema steps
    schema.inspect_entity()
    schema.require_identity()

    # Query steps
    query.bind_provider(MyProviderNode)
    query.base_query()

    # Surface steps (generic — used by ALL dialects)
    surface.derive_op("Get", id_only(), entity_response(), handler, trigger)
    surface.expose_op(OpType, handler, ReqType, RespType, trigger)
    surface.add_global_cap(some_cap)
"""

from derivelib.axes import schema
from derivelib.axes import query
from derivelib.axes import surface

__all__ = ("schema", "query", "surface")
