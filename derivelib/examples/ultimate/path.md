# ultimate — boilerplate is dead

Seven composable transforms. One entity definition.
Every cross-cutting concern is a `.chain()` call away.

## The Premise

A typical SaaS entity touches 7+ concerns:

| Concern | Classic boilerplate | derivelib |
|---------|-------------------|-----------|
| CRUD endpoints | N handlers × N entities | `http_crud(path)` |
| Audit logging | 5-15 lines per mutation | `.chain(audited(store))` |
| Tenant isolation | Pernicious, touches ALL code | `.chain(tenant_scoped())` |
| Soft delete | 4 handler changes + filter | `.chain(soft_delete())` |
| Realtime events | EventBus wiring per mutation | `.chain(with_events(bus))` |
| Approval workflow | State machine per entity | `approval_flow(transitions)` |
| Bulk import/export | CSV parsing + serialization | `.chain(with_import_export())` |
| API versioning | Duplicate handlers/models | `.chain(versioned(v1, v2))` |

Each concern is a **DerivationT** (Derivation -> Derivation) or a **Dialect**.
They compose orthogonally — add/remove any without touching others.

## The Files

### Transforms (DerivationT — composable via .chain())

1. **audit_log.py** — `audited(store)`
   Wraps mutation handlers. After success, writes AuditEntry (who/what/when).
   Uses `WrappedTemplate` — zero runtime overhead on reads.

2. **multi_tenant.py** — `tenant_scoped(HeaderTenantExtract())`
   Enricher extracts tenant from `X-Tenant-Id` header.
   Wraps handlers: creates inject tenant, reads filter by tenant.

3. **soft_delete.py** — `soft_delete()`
   Replaces Delete handler with set-deleted_at. Wraps List/Get to filter.
   Adds Restore + Purge ops.

4. **realtime.py** — `with_events(bus)`
   Wraps mutation handlers. After success, publishes event to bus.
   Adds SSE subscription endpoint.

5. **import_export.py** — `with_import_export()`
   Uses schema inspection to derive CSV/JSON import + export endpoints.
   Fields -> columns automatically.

6. **versioned_api.py** — `versioned(v1_fields, v2_fields)`
   Same entity, different projections. v1 = subset, v2 = full.
   One entity -> two API surfaces.

### Dialects (standalone patterns)

7. **approval_flow.py** — `approval_flow(path, transitions)`
   State machine dialect: transitions = validated endpoints.
   Not CRUD — shows derive is arbitrary business patterns.

## The Composition

```python
@derive(
    http_crud("/articles", provider_node=Articles, ops=(LIST, GET, CREATE, UPDATE, DELETE))
        .chain(
            audited(audit_store),
            tenant_scoped(HeaderTenantExtract()),
            soft_delete(),
            with_events(event_bus),
            require_auth(validate, BearerExtract()),
        ),
    approval_flow(
        "/articles", provider_node=Articles, state_field="status",
        transitions=(
            Transition("submit",  ("draft",), "pending"),
            Transition("approve", ("pending",), "published"),
            Transition("reject",  ("pending",), "draft"),
        ),
    ),
)
@dataclass
class Article:
    id: Annotated[int, Identity]
    tenant_id: str
    title: str
    body: str
    status: str = "draft"
    deleted_at: str | None = None
```

One decorator. Seven concerns. Zero boilerplate.

## The Algebra

Each transform is a function `Derivation -> Derivation`:

```
audited         : [DeriveOp, ...] -> [DeriveOp(wrapped_handler), ...]
tenant_scoped   : [DeriveOp, ...] -> [DeriveOp(+enricher, wrapped_handler), ...]
soft_delete     : [DeriveOp, ...] -> [DeriveOp(filtered), ..., RestoreOp, PurgeOp]
with_events     : [DeriveOp, ...] -> [DeriveOp(+publish), ..., SSEOp]
versioned       : [DeriveOp, ...] -> [DeriveOp(v1_proj), DeriveOp(v2_proj), ...]
```

They compose because they all operate on the same type: `tuple[Step, ...]`.
Order matters where it should (auth before audit) and doesn't where it shouldn't.

## The Point

Classic: N concerns x M entities = N*M implementations.
derivelib: N concerns (once) + M entities (schema only) = N+M.

Boilerplate is dead. Long live the sheaf.
