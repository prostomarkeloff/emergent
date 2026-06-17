"""Nested CRUD — child resources scoped by parent FK.

Auto-discovers Ref(parent) on child entity. Generates nested CRUD endpoints
where all queries are scoped by parent FK field.

    from emergent.wire.derive.patterns.nested import nested_http_crud

    @schema_meta(nested_http_crud("/users", parent=User, provider_node=Posts))
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

from dataclasses import dataclass, replace

from emergent.wire.axis.query import relational
from emergent.wire.axis.schema._universal import SchemaCapability
from emergent.wire.derive._query_strategy import ProviderInjection, RelationalStrategy
from emergent.wire.axis.surface.capabilities import SurfaceCapability
from emergent.wire.derive._ctx import DeriveCtx
from emergent.wire.derive._effects import Creates, Deletes, Idempotent, Read, Updates
from emergent.wire.derive._error_caps import ERROR_CAPS
from emergent.wire.derive._handler import (
    DeleteOne,
    FetchMany,
    FetchOneById,
    InsertNew,
    UpdateExisting,
)
from emergent.wire.derive._opspec import Op, generate_specs
from emergent.wire.derive._project import (
    all_fields,
    entity_response,
    id_only,
    list_response,
    no_fields,
    non_id,
    ok_response,
)
from emergent.wire.derive._trigger import NestedHTTPTriggers

type ScopeTypeMap = dict[str, type]


def _scoped_crud_ops(
    scope: tuple[str, ...], scope_types: ScopeTypeMap
) -> tuple[Op, ...]:
    """CRUD ops scoped by parent FK field(s)."""
    scope_extra = tuple(scope_types.items())

    return (
        Op(
            "List",
            no_fields(),
            list_response(),
            FetchMany(),
            extra_op_fields=scope_extra,
            extra_request_fields=scope_extra,
            effects=(Read(),),
            scope_fields=scope,
        ),
        Op(
            "Get",
            id_only(),
            entity_response(),
            FetchOneById(),
            extra_op_fields=scope_extra,
            extra_request_fields=scope_extra,
            effects=(Read(), Idempotent()),
            scope_fields=scope,
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
            UpdateExisting(),
            effects=(Updates(), Idempotent()),
            scope_fields=scope,
        ),
        Op(
            "Delete",
            id_only(),
            ok_response(),
            DeleteOne(),
            extra_op_fields=scope_extra,
            extra_request_fields=scope_extra,
            effects=(Deletes(), Idempotent()),
            scope_fields=scope,
        ),
    )


@dataclass(frozen=True, slots=True)
class NestedCRUD(SchemaCapability):
    """Nested CRUD — child scoped by parent FK.

    Auto-discovers Ref(parent) on child entity. Generates scoped endpoints.

        @schema_meta(NestedCRUD(parent=User, parent_path="/users", provider_node=Posts))
    """

    parent: type
    parent_path: str
    provider_node: type
    fk_field: str | None = None
    child_segment: str | None = None
    capabilities: tuple[SurfaceCapability, ...] = ERROR_CAPS

    def compile_derive_generate[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        if not ctx.identity_fields:
            raise ValueError(
                f"{ctx.entity.__name__} needs Annotated[T, Identity] for NestedCRUD"
            )

        fk_name, fk_type = self._find_fk(ctx.entity)
        scope = (fk_name,)
        scope_types = {fk_name: fk_type}

        child_seg = self.child_segment or ctx.entity.__name__.lower() + "s"
        triggers = NestedHTTPTriggers(self.parent_path, scope, child_seg)

        from emergent.wire.derive._crud import provider_fields

        prov_op_field, prov_req_field = provider_fields(self.provider_node)

        ctx = replace(
            ctx,
            query_strategy=RelationalStrategy(
                provider_node=self.provider_node,
                base_query=relational(ctx.entity),
                injection=ProviderInjection(
                    op_field=prov_op_field,
                    request_field=prov_req_field,
                ),
            ),
        )

        return generate_specs(
            ctx,
            ops=_scoped_crud_ops(scope, scope_types),
            triggers=triggers,
            capabilities=self.capabilities,
            source="NestedCRUD",
            extra_op_fields=(prov_op_field,),
            extra_request_fields=(prov_req_field,),
        )

    def _find_fk(self, entity: type) -> tuple[str, type]:
        """Find FK field on child entity that references parent."""
        if self.fk_field is not None:
            from emergent.wire.axis.schema import inspect_type

            fields = inspect_type(entity)
            info = fields.get(self.fk_field)
            if info is None:
                raise ValueError(f"{entity.__name__} has no field '{self.fk_field}'")
            return self.fk_field, info.base_type

        from emergent.wire.axis.schema import get_refs

        refs = get_refs(entity)
        for name, info, ref in refs:
            if ref.target is self.parent:
                return name, info.base_type
        parent_name = self.parent.__name__
        for name, info, ref in refs:
            if isinstance(ref.target, str) and ref.target == parent_name:
                return name, info.base_type

        raise ValueError(f"{entity.__name__} has no Ref({self.parent.__name__}) field")


def nested_http_crud(
    parent_path: str,
    *,
    parent: type,
    provider_node: type,
    fk_field: str | None = None,
    child_segment: str | None = None,
) -> NestedCRUD:
    """Nested HTTP CRUD capability.

        @schema_meta(nested_http_crud("/users", parent=User, provider_node=Posts))
    """
    return NestedCRUD(
        parent=parent,
        parent_path=parent_path,
        provider_node=provider_node,
        fk_field=fk_field,
        child_segment=child_segment,
    )


__all__ = (
    "NestedCRUD",
    "nested_http_crud",
)
