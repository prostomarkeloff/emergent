"""Wire composition axes.

Axes are orthogonal dimensions of composition:
- surface: API surface (endpoints, apps, stacks)
- storage: data persistence (kv, queue, pubsub)
- schema: dataclass annotations → backend-specific models
- query: typed query building (relational, kv, document, api spaces)

    from emergent.wire.axis import surface, storage, schema, query
"""

from emergent.wire.axis import surface, storage, schema, query

# Root capability re-export
from emergent.wire.axis._capability import Capability

__all__ = ("surface", "storage", "schema", "query", "Capability")
