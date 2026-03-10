"""Nested CRUD — proxy to emergent.wire.derive.patterns.nested.

DEPRECATED: Use emergent.wire.derive.patterns.nested directly.
derivelib will be removed in emergent 1.0.0.

    from derivelib.patterns.nested import nested_http_crud

    @derive(nested_http_crud("/users", parent=User, provider_node=Posts))
    @dataclass
    class Post:
        id: Annotated[int, Identity]
        user_id: Annotated[int, Ref(User)]
        title: str
"""

from __future__ import annotations

from emergent.wire.derive.patterns.nested import (
    NestedCRUD as NestedCrudPattern,
    nested_http_crud,
)

__all__ = (
    "NestedCrudPattern",
    "nested_http_crud",
)
