"""CRUD as SchemaCapability — generates OpSpecs via compile_derive_generate.

    from emergent.wire.derive import http_crud

    @schema_meta(http_crud("/api/users", UserProvider))
    @dataclass
    class User:
        id: Annotated[int, Identity]
        name: str

    ctx = compile_derive(User)
    endpoint = materialize(ctx)
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from emergent.wire.axis.query import relational
from emergent.wire.axis.schema._universal import SchemaCapability
from emergent.wire.derive._query_strategy import ProviderInjection, RelationalStrategy
from emergent.wire.axis.surface.capabilities import SurfaceCapability
from emergent.wire.derive._ctx import DeriveCtx
from emergent.wire.derive._effects import (
    Cacheable,
    Creates,
    Deletes,
    Idempotent,
    Pageable,
    Read,
    Sortable,
    Updates,
)
from emergent.wire.derive._error_caps import ERROR_CAPS
from emergent.wire.derive._handler import (
    DeleteOne,
    FetchMany,
    FetchOneById,
    InsertNew,
    PatchExisting,
    UpdateExisting,
    UpsertExisting,
)
from emergent.wire.derive._opspec import Op, OpLike, generate_specs
from emergent.wire.derive._project import (
    all_fields,
    entity_response,
    id_only,
    list_response,
    merge,
    no_fields,
    non_id,
    ok_response,
    optional_non_id,
)
from emergent.wire.derive._trigger import CLITriggers, HTTPTriggers, TriggerGen


# ═══════════════════════════════════════════════════════════════════════════════
# CRUD Op Constants
# ═══════════════════════════════════════════════════════════════════════════════

LIST = Op("List", no_fields(), list_response(), FetchMany(), effects=(Read(), Pageable(), Sortable()))
GET = Op("Get", id_only(), entity_response(), FetchOneById(), effects=(Read(), Idempotent(), Cacheable()))
CREATE = Op("Create", non_id(), entity_response(), InsertNew(), effects=(Creates(),))
UPDATE = Op("Update", all_fields(), entity_response(), UpdateExisting(), effects=(Updates(), Idempotent()))
PATCH = Op("Patch", merge(id_only(), optional_non_id()), entity_response(), PatchExisting(), effects=(Updates(), Idempotent()))
DELETE = Op("Delete", id_only(), ok_response(), DeleteOne(), effects=(Deletes(), Idempotent()))
UPSERT = Op("Upsert", all_fields(), entity_response(), UpsertExisting(), effects=(Creates(), Updates(), Idempotent()))

ALL_CRUD_OPS: tuple[OpLike, ...] = (LIST, GET, CREATE, UPDATE, PATCH, DELETE)
MUTATION_CRUD_OPS: tuple[OpLike, ...] = (CREATE, UPDATE, PATCH, DELETE)
READ_CRUD_OPS: tuple[OpLike, ...] = (LIST, GET)


# ═══════════════════════════════════════════════════════════════════════════════
# Provider Fields
# ═══════════════════════════════════════════════════════════════════════════════


def provider_fields(
    provider_node: type,
) -> tuple[tuple[str, type], tuple[str, type]]:
    """Create provider field pair: (op_field, request_field).

    Op field is plain type. Request field has ComposeNode for runtime resolution.
    """
    import typing

    from emergent.wire.axis.query import MutatingRelationalProvider
    from emergent.wire.axis.schema.dialects.compose import Node as ComposeNode

    op_field: tuple[str, type] = ("provider", MutatingRelationalProvider)
    annotated_getitem = typing.Annotated.__getitem__
    request_field: tuple[str, type] = (
        "provider",
        annotated_getitem((MutatingRelationalProvider, ComposeNode(provider_node))),
    )
    return op_field, request_field


# ═══════════════════════════════════════════════════════════════════════════════
# CRUD SchemaCapability
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class CRUD(SchemaCapability):
    """CRUD derivation — generates endpoints from entity schema.

    Transport-agnostic. Use http_crud()/cli_crud() for convenience.
    Accepts both Op and DescriptiveTemplate (handler-as-op) via OpLike:

        http_crud('/users', Users, ops=(FetchMany(), InsertNew(), DeleteOne()))
    """

    triggers: TriggerGen
    provider_node: type
    ops: tuple[OpLike, ...] = ALL_CRUD_OPS
    capabilities: tuple[SurfaceCapability, ...] = ERROR_CAPS

    def compile_derive_generate[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        """Phase 1: generate OpSpecs from entity schema + ops."""
        if not ctx.identity_fields:
            raise ValueError(
                f"{ctx.entity.__name__} needs Annotated[T, Identity] field for CRUD"
            )

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
            ops=self.ops,
            triggers=self.triggers,
            capabilities=self.capabilities,
            source="CRUD",
            extra_op_fields=(prov_op_field,),
            extra_request_fields=(prov_req_field,),
        )


def crud(
    triggers: TriggerGen,
    provider_node: type,
    *caps: SurfaceCapability,
    ops: tuple[OpLike, ...] | None = None,
) -> CRUD:
    """CRUD capability = standard ops + error transforms.

        crud(HTTPTriggers("/api/users"), UserProvider)
        crud(CLITriggers("user"), UserProvider)
        crud(HTTPTriggers("/api/users"), UserProvider, ops=(LIST, GET))
        crud(HTTPTriggers("/api/users"), UserProvider, ops=(FetchMany(), FetchOneById()))
    """
    return CRUD(
        triggers=triggers,
        provider_node=provider_node,
        ops=ops or ALL_CRUD_OPS,
        capabilities=(*caps, *ERROR_CAPS),
    )


def http_crud(
    base_path: str,
    provider_node: type,
    *caps: SurfaceCapability,
    ops: tuple[OpLike, ...] | None = None,
) -> CRUD:
    """HTTP CRUD capability."""
    return crud(HTTPTriggers(base_path), provider_node, *caps, ops=ops)


def cli_crud(
    prefix: str,
    provider_node: type,
    *caps: SurfaceCapability,
    ops: tuple[OpLike, ...] | None = None,
) -> CRUD:
    """CLI CRUD capability."""
    return crud(CLITriggers(prefix), provider_node, *caps, ops=ops)


__all__ = (
    "LIST", "GET", "CREATE", "UPDATE", "PATCH", "DELETE", "UPSERT",
    "ALL_CRUD_OPS", "MUTATION_CRUD_OPS", "READ_CRUD_OPS",
    "CRUD",
    "crud",
    "http_crud",
    "cli_crud",
)
