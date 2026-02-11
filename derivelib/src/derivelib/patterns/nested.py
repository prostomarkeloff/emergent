"""Nested CRUD — child resources scoped by parent FK.

Auto-discovers Ref(parent) on child entity. Generates nested CRUD endpoints
where all queries are scoped by parent FK field.

    from derivelib.patterns.nested import nested_http_crud

    @derive(nested_http_crud("/users", parent=User, provider_node=Posts))
    @dataclass
    class Post:
        id: Annotated[int, Identity]
        user_id: Annotated[int, Ref(User)]
        title: str

    # Generates:
    # GET    /users/{user_id}/posts
    # GET    /users/{user_id}/posts/{id}
    # POST   /users/{user_id}/posts
    # PUT    /users/{user_id}/posts/{id}
    # DELETE /users/{user_id}/posts/{id}
"""

from __future__ import annotations

from dataclasses import dataclass

from derivelib._derivation import Derivation
from derivelib._dialect import (
    NestedHTTPTriggers,
    Op,
    dialect,
)
from derivelib._effects import Creates, Deletes, Idempotent, Read, Updates
from derivelib._project import (
    all_fields,
    entity_response,
    id_only,
    list_response,
    no_fields,
    non_id,
    ok_response,
)
from derivelib.patterns.crud import (
    CRUD_ERROR_CAPS,
    DeleteOne,
    FetchMany,
    FetchOneById,
    InsertNew,
    UpdateExisting,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Scoped CRUD Ops
# ═══════════════════════════════════════════════════════════════════════════════


def _scoped_crud_ops(
    scope: tuple[str, ...], scope_types: dict[str, type]
) -> tuple[Op, ...]:
    """CRUD ops scoped by parent FK field(s).

    List/Get/Delete: inject scope fields via extra_op_fields (not in projection).
    Create/Update: scope field already in non_id/all_fields projection.
    """
    scope_extra_op = tuple(scope_types.items())
    scope_extra_req = tuple(scope_types.items())

    return (
        Op(
            "List",
            no_fields(),
            list_response(),
            FetchMany(scope_fields=scope),
            extra_op_fields=scope_extra_op,
            extra_request_fields=scope_extra_req,
            effects=(Read(),),
        ),
        Op(
            "Get",
            id_only(),
            entity_response(),
            FetchOneById(scope_fields=scope),
            extra_op_fields=scope_extra_op,
            extra_request_fields=scope_extra_req,
            effects=(Read(), Idempotent()),
        ),
        Op(
            "Create",
            non_id(),
            entity_response(),
            InsertNew(),
            effects=(Creates(),),
        ),
        Op(
            "Update",
            all_fields(),
            entity_response(),
            UpdateExisting(scope_fields=scope),
            effects=(Updates(), Idempotent()),
        ),
        Op(
            "Delete",
            id_only(),
            ok_response(),
            DeleteOne(scope_fields=scope),
            extra_op_fields=scope_extra_op,
            extra_request_fields=scope_extra_req,
            effects=(Deletes(), Idempotent()),
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# NestedCrudPattern
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class NestedCrudPattern:
    """Nested CRUD pattern: discover FK, generate scoped endpoints.

    Discovers Ref(parent) on child entity at compile time.
    Delegates to dialect() with scoped ops + NestedHTTPTriggers.

        NestedCrudPattern(
            parent=User,
            parent_path="/users",
            provider_node=Posts,
        )
    """

    parent: type
    parent_path: str
    provider_node: type
    fk_field: str | None = None
    child_segment: str | None = None

    def compile(self, entity: type) -> Derivation:
        fk_name, fk_type = self._find_fk(entity)
        scope = (fk_name,)
        scope_types = {fk_name: fk_type}

        child_seg = self.child_segment or entity.__name__.lower() + "s"
        triggers = NestedHTTPTriggers(self.parent_path, scope, child_seg)

        d = dialect(
            *_scoped_crud_ops(scope, scope_types),
            triggers=triggers,
            provider_node=self.provider_node,
            capabilities=CRUD_ERROR_CAPS,
        )
        return d.compile(entity)

    def _find_fk(self, entity: type) -> tuple[str, type]:
        """Find FK field on child entity that references parent."""
        if self.fk_field is not None:
            from emergent.wire.axis.schema import inspect_type

            fields = inspect_type(entity)
            info = fields.get(self.fk_field)
            if info is None:
                msg = f"{entity.__name__} has no field '{self.fk_field}'"
                raise ValueError(msg)
            return self.fk_field, info.base_type

        from emergent.wire.axis.schema import get_refs

        refs = get_refs(entity)
        # Match by type identity
        for name, info, ref in refs:
            if ref.target is self.parent:
                return name, info.base_type
        # Fallback: match by string name
        parent_name = self.parent.__name__
        for name, info, ref in refs:
            if isinstance(ref.target, str) and ref.target == parent_name:
                return name, info.base_type

        msg = f"{entity.__name__} has no Ref({self.parent.__name__}) field"
        raise ValueError(msg)


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════


def nested_http_crud(
    parent_path: str,
    *,
    parent: type,
    provider_node: type,
    fk_field: str | None = None,
    child_segment: str | None = None,
) -> NestedCrudPattern:
    """Nested HTTP CRUD dialect.

        @derive(nested_http_crud("/users", parent=User, provider_node=Posts))
        @dataclass
        class Post:
            id: Annotated[int, Identity]
            user_id: Annotated[int, Ref(User)]
            title: str
            body: str

    Args:
        parent_path: Parent's base path (e.g. "/users")
        parent: Parent entity type (for FK discovery)
        provider_node: nodnod node for child provider
        fk_field: Explicit FK field name (auto-discovered from Ref if None)
        child_segment: URL segment for child (default: entity_name + "s")
    """
    return NestedCrudPattern(
        parent=parent,
        parent_path=parent_path,
        provider_node=provider_node,
        fk_field=fk_field,
        child_segment=child_segment,
    )


__all__ = (
    "NestedCrudPattern",
    "nested_http_crud",
)
