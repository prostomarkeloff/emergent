"""Wire composition axes.

Axes are orthogonal dimensions of composition:
- surface: API surface (endpoints, apps, stacks)
- storage: data persistence (kv, queue, pubsub)
- schema: dataclass annotations → backend-specific models
- query: typed query building (relational, kv, document, api spaces)

Fundamentals (codecs, triggers) define WHAT.
Axes define HOW to compose and WHERE to put.
"""

from emergent.wire.axis import surface, storage, schema, query

__all__ = ("surface", "storage", "schema", "query")
