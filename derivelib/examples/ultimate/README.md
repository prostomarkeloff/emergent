# ultimate — boilerplate is dead

**1 dataclass. 1 decorator. 14 endpoints. 15 OpenAPI schemas. 7 orthogonal concerns. 0 boilerplate.**

```python
@derive(
    http_crud("/articles", provider_node=Articles,
        ops=(LIST, GET, CREATE, UPDATE, DELETE),
    ).chain(
        audited(_audit),
        tenant_scoped(HeaderTenantExtract()),
        soft_delete(),
        exclude_managed_fields("status"),
        with_events(event_bus, channel="articles"),
        with_import_export(),
    ),
    approval_flow(
        "/articles", provider_node=Articles, state_field="status",
        transitions=(
            Transition("submit",  ("draft",), "pending"),
            Transition("approve", ("pending",), "published"),
            Transition("reject",  ("pending",), "draft"),
            Transition("archive", ("published",), "archived"),
        ),
    ),
)
@dataclass
class Article:
    id: Annotated[int, Identity]
    tenant_id: str = ""
    title: str = ""
    body: str = ""
    status: str = "draft"
    deleted_at: str | None = None
```

30 lines of declaration. That's the entire application logic.

```
cd derivelib && PYTHONPATH=src:.. uv run python -m examples.ultimate
```

---

## Table of Contents

1. [What gets generated](#what-gets-generated)
2. [The 7 transforms in detail](#the-7-transforms-in-detail)
3. [How transforms compose](#how-transforms-compose)
4. [Architecture: why this is possible](#architecture-why-this-is-possible)
5. [OpenAPI analysis](#openapi-analysis)
6. [Comparison with classical approaches](#comparison-with-classical-approaches)
7. [The boilerplate is dead thesis](#the-boilerplate-is-dead-thesis)

---

## What gets generated

From the 30 lines above, the compiler produces:

### 14 endpoints across 11 paths

| # | Method | Path | Source | Concern |
|---|--------|------|--------|---------|
| 1 | `GET` | `/articles` | CRUD | List all + tenant filter + soft-delete filter |
| 2 | `GET` | `/articles/{id}` | CRUD | Get one + tenant isolation + soft-delete reject |
| 3 | `POST` | `/articles` | CRUD | Create (auto-excludes `status`, `deleted_at` from input) |
| 4 | `PUT` | `/articles/{id}` | CRUD | Update (auto-excludes `status`, `deleted_at` from input) |
| 5 | `DELETE` | `/articles/{id}` | soft_delete | Soft delete (sets `deleted_at = now()`, doesn't remove) |
| 6 | `POST` | `/articles/{id}/restore` | soft_delete | Undo soft-delete (clears `deleted_at`) |
| 7 | `POST` | `/articles/create` | approval_flow | Create with initial state (`status = "draft"`) |
| 8 | `POST` | `/articles/{id}/submit` | approval_flow | Transition: draft → pending |
| 9 | `POST` | `/articles/{id}/approve` | approval_flow | Transition: pending → published |
| 10 | `POST` | `/articles/{id}/reject` | approval_flow | Transition: pending → draft |
| 11 | `POST` | `/articles/{id}/archive` | approval_flow | Transition: published → archived |
| 12 | `GET` | `/articles/{id}/status` | approval_flow | Read current state |
| 13 | `POST` | `/articles/import` | with_import_export | Bulk insert from JSON array |
| 14 | `GET` | `/articles/export` | with_import_export | Export all as JSON array |

### 15 OpenAPI schemas

| Schema | Fields | Source |
|--------|--------|--------|
| `Article` | id, tenant_id, title, body, status, deleted_at | Entity definition |
| `ListArticleResponse` | items: Article[] | CRUD LIST |
| `GetArticleResponse` | id, tenant_id, title, body, status, deleted_at | CRUD GET |
| `CreateArticleResponse` | id, tenant_id, title, body, status, deleted_at | CRUD CREATE |
| `UpdateArticleResponse` | id, tenant_id, title, body, status, deleted_at | CRUD UPDATE |
| `DeleteArticleResponse` | success: boolean | soft_delete |
| `RestoreArticleResponse` | success: boolean | soft_delete |
| `CreateResponse` | id, status | approval_flow create |
| `SubmitResponse` | status | approval_flow transition |
| `ApproveResponse` | status | approval_flow transition |
| `RejectResponse` | status | approval_flow transition |
| `ArchiveResponse` | status | approval_flow transition |
| `StatusResponse` | status | approval_flow status |
| `ImportResponse` | created: int, errors: string[] | import |
| `ExportResponse` | items: object[], count: int | export |

All schemas are auto-generated. None written by hand.

### Cross-cutting behaviors (invisible, automatic)

- **Every mutation** writes an `AuditEntry(timestamp, operation, entity_type, payload)` to audit storage
- **Every mutation** publishes an `Event(channel, operation, entity_type, timestamp, payload)` to EventBus
- **Every read** filters out soft-deleted entities
- **Every read with tenant header** filters by `tenant_id`
- **Every GET with wrong tenant** returns RFC 7807 `404 Not Found`
- **Every error** returns `application/problem+json` with proper status codes (404, 409, 422)
- **CREATE/UPDATE inputs** automatically exclude `status` and `deleted_at` (server-managed fields)

---

## The 7 transforms in detail

### 1. `audited(store)` — automatic audit trail

**File:** `audit_log.py` (~60 LOC)

**Mechanism:** `WrappedTemplate` — wraps the handler function. After the original handler returns `Ok(...)`, writes an audit record. On `Error(...)`, does nothing (failed ops aren't audited).

**Effect selector:** `map_by_effect({Mutation: _add})` — only wraps mutations (Create, Update, Delete). Reads pass through untouched.

**What gets logged:**
```python
AuditEntry(
    timestamp="2026-02-07T12:34:56+00:00",
    operation="Create",
    entity_type="Article",
    payload='{"tenant_id": "acme", "title": "hello", "body": "world"}'
)
```

**Design choice:** `WrappedTemplate` is correct here because audit needs to intercept the handler's return value (`Ok` vs `Error`) but doesn't need access to the runtime scope. It wraps the handler at compile time — zero runtime dispatch overhead.

### 2. `tenant_scoped(HeaderTenantExtract())` — multi-tenant isolation

**File:** `multi_tenant.py` (~80 LOC)

**Mechanism:** `ScopeEnricher` — runtime middleware that wraps the entire call chain (enricher → handler → response conversion → enricher post-processing).

**Why ScopeEnricher and not WrappedTemplate:**

This is architecturally significant. `annotate_handler()` in the codegen layer wraps all handlers as `async def handler(op) -> Any` — a single parameter function. **Handler wrappers cannot access the runtime scope** (nodnod's dependency injection context). They only see the `op` dataclass.

`ScopeEnrichers` wrap the entire call chain at a higher level. They receive `(call, scope)` where `scope` contains the HTTP request, injected types, etc. Tenant filtering MUST read `X-Tenant-Id` from the HTTP request → it MUST live in an enricher.

**The enricher chain at runtime:**
```
HeaderTenantExtract          →  TenantFilter            →  core handler
  scope.get(fastapi.Request)    result = call(scope)       normal execution
  header = "X-Tenant-Id"       post-filter by tenant
  scope.inject(TenantId)       reject if wrong tenant
```

**How it filters:**
- **LIST:** calls handler → gets response with `.items` list → filters items where `entity.tenant_id == scope_tenant_id` → mutates response
- **GET:** calls handler → gets response → checks `response.tenant_id` → if mismatch, returns `NotFound` → triggers `ProblemResponse` → 404 JSON
- **No tenant header:** enricher skips injection → `TenantFilter` sees no `TenantId` in scope → returns unfiltered

**What gets added to DeriveOps:**
- **Reads:** `capabilities += (HeaderTenantExtract, TenantFilter)` — extract + filter
- **Writes:** `capabilities += (HeaderTenantExtract,)` — extract only (tenant comes in request body)

### 3. `soft_delete(field="deleted_at")` — soft delete with restore

**File:** `soft_delete.py` (~130 LOC)

**Mechanism:** hybrid — WrappedTemplate for handler replacement + DeriveOp manipulation for new endpoints + ExcludeFromProjection for field filtering.

This is the most complex transform because it touches every aspect of the derivation:

**Per-effect behavior:**

| Effect | What happens |
|--------|-------------|
| `Deletes` | **Replaces** handler: instead of `provider.delete()`, sets `deleted_at = datetime.now(UTC).isoformat()`. **Adds** `POST /{id}/restore` endpoint. |
| `Read` | **Wraps** handler: after `Ok(list)`, filters out entities where `deleted_at is not None`. After `Ok(entity)`, rejects if `deleted_at is not None` → `Error(NotFound)`. |
| `Creates` / `Mutation` | **Excludes** `deleted_at` from input projection via `ExcludeFromProjection`. Users can't set `deleted_at` through the API — it's server-managed. |

**Restore endpoint generation:**

```python
restore_path = getattr(delete_op.trigger, "path").rstrip("/") + "/restore"
restore = replace(delete_op,
    name="Restore",
    handler_template=WrappedTemplate(inner=FetchOneById(), wrapper=restore_wrapper),
    trigger=HTTPRouteTrigger("POST", restore_path),
    effects=(),
)
```

The restore endpoint is synthesized from the delete endpoint's metadata — same path pattern, same identity fields, new handler. The `FetchOneById` template provides the fetch-by-id logic; the restore wrapper clears `deleted_at` and rejects if the entity isn't deleted (`Error(InvalidData("not deleted"))` → 422).

### 4. `exclude_managed_fields("status")` — server-managed field protection

**File:** `approval_flow.py` (~15 LOC for the helper)

**Mechanism:** `ExcludeFromProjection` on input projections of `Creates`/`Mutation` ops.

**Why it exists:**

The `status` field is managed by the approval flow state machine. Without this transform, `POST /articles` would require `"status"` in the JSON body. With it, `status` is excluded from the request schema — the entity gets `status="draft"` from its dataclass default.

This is the same mechanism `soft_delete()` uses for `deleted_at`. The pattern: when a transform "owns" a field, it excludes that field from CRUD inputs.

```python
def exclude_managed_fields(*fields):
    def transform(steps):
        for s in steps:
            if is DeriveOp and (Creates or Mutation):
                s = replace(s, input_proj=ExcludeFromProjection(s.input_proj, fields))
        return tuple(result)
    return transform
```

**Effect on OpenAPI:** The `POST /articles` request body becomes `{tenant_id, title, body}` — no `status`, no `deleted_at`. Both auto-excluded.

### 5. `with_events(bus, channel="articles")` — realtime event publishing

**File:** `realtime.py` (~80 LOC)

**Mechanism:** `WrappedTemplate`, structurally identical to `audited()`.

**Effect selector:** `map_by_effect({Mutation: _add})`.

**What gets published:**
```python
Event(
    channel="articles",
    operation="Create",
    entity_type="Article",
    timestamp="2026-02-07T12:34:56+00:00",
    payload='{"tenant_id": "acme", "title": "hello"}'
)
```

**EventBus API:**
```python
bus = EventBus()

@bus.on("articles")
async def handle(event: Event):
    print(f"{event.operation}: {event.payload}")

bus.on_all(lambda e: logger.info(e))  # subscribe to all channels
```

**Design note:** `audited()` and `with_events()` are deliberately separate transforms even though they have similar structure. Audit is for compliance (writes to persistent storage). Events are for reactivity (in-memory pub/sub). Combining them would violate single responsibility.

### 6. `with_import_export()` — bulk operations

**File:** `import_export.py` (~90 LOC)

**Mechanism:** adds new surface steps (`BulkImportStep`, `BulkExportStep`) to the derivation tuple.

**Parameter inference:** both `base_path` and `provider_node` are inferred from existing CRUD DeriveOps in the chain. You just write `.chain(with_import_export())` — no configuration.

**Import handler:**
```python
async def handler(op):
    items = op.items  # list[dict] from request body
    for item in items:
        d = {field: item[field] for field in non_id_names if field in item}
        d[id_name] = 0  # auto-assign
        await op.provider.insert(entity(**d))
    return Ok({"created": count, "errors": errors})
```

**Export handler:**
```python
async def handler(op):
    all_entities = await op.provider.fetch_many(relational(entity))
    items = [{name: getattr(e, name) for name in field_names} for e in all_entities]
    return Ok({"items": items, "count": len(items)})
```

**Both use `exposure()` builder** — the low-level API for defining operations outside the DeriveOp/dialect pipeline. This demonstrates that derivelib is not limited to CRUD patterns.

### 7. `approval_flow(...)` — state machine as validated endpoints

**File:** `approval_flow.py` (~160 LOC)

**Mechanism:** separate `Pattern` (not a `DerivationT`). Compiles independently from the CRUD chain. Produces its own derivation with schema inspection + surface steps.

**DSL:**
```python
Transition("submit",  ("draft",),     "pending")    # name, valid from_states, to_state
Transition("approve", ("pending",),   "published")
Transition("reject",  ("pending",),   "draft")
Transition("archive", ("published",), "archived")
```

**What gets compiled:**
```
inspect_entity()        → read entity schema
require_identity()      → validate identity fields exist
ApprovalCreateStep      → POST /articles/create (sets initial state)
ApprovalTransitionStep  → POST /articles/{id}/submit  (validates: draft → pending)
ApprovalTransitionStep  → POST /articles/{id}/approve (validates: pending → published)
ApprovalTransitionStep  → POST /articles/{id}/reject  (validates: pending → draft)
ApprovalTransitionStep  → POST /articles/{id}/archive (validates: published → archived)
ApprovalStatusStep      → GET  /articles/{id}/status  (read current state)
```

**Transition validation:**
```python
obj = await provider.fetch_one(query_by_id)
if obj is None:
    return Error(NotFound(...))           # → 404
current_state = getattr(obj, state_field)
if current_state not in transition.from_states:
    return Error(InvalidData(...))        # → 422
# valid — apply transition
obj_dict[state_field] = transition.to_state
await provider.update(entity(**obj_dict))
return Ok({state_field: transition.to_state})
```

**Why it's a Pattern and not a DerivationT:**

The approval flow doesn't modify CRUD operations — it adds entirely new endpoints with their own request/response schemas, handlers, and triggers. A `DerivationT` transforms existing steps; a `Pattern` creates new ones from scratch. Both go through the same `@derive()` decorator and compile to the same `Endpoint` type.

**Error handling:**

All approval endpoints have `CRUDErrorTransform` + `ProblemResponse` capabilities. The custom `_approval_converter` passes `Error(NotFound(...))` and `Error(InvalidData(...))` through to the capability chain, which converts them to RFC 7807 `application/problem+json` responses via `JSONResponse` (bypassing FastAPI's response model validation).

---

## How transforms compose

### The chain pipeline

```
http_crud(LIST, GET, CREATE, UPDATE, DELETE)
    │
    │  Derivation = (inspect_entity, require_identity, DeriveProvider,
    │                DeriveOp[List], DeriveOp[Get], DeriveOp[Create],
    │                DeriveOp[Update], DeriveOp[Delete])
    │
    ├── audited(_audit)
    │     Mutation ops: handler_template = WrappedTemplate(original, audit_wrapper)
    │
    ├── tenant_scoped(HeaderTenantExtract())
    │     Read ops: capabilities += (HeaderTenantExtract, TenantFilter)
    │     Write ops: capabilities += (HeaderTenantExtract,)
    │
    ├── soft_delete()
    │     Delete: handler_template = WrappedTemplate(original, soft_delete_wrapper)
    │             + new DeriveOp[Restore] added
    │     Read: handler_template = WrappedTemplate(original, filter_deleted_wrapper)
    │     Create/Update: input_proj = ExcludeFromProjection(original, ("deleted_at",))
    │
    ├── exclude_managed_fields("status")
    │     Create/Update: input_proj = ExcludeFromProjection(prev, ("status",))
    │
    ├── with_events(bus, channel="articles")
    │     Mutation ops: handler_template = WrappedTemplate(prev_wrapped, event_wrapper)
    │
    └── with_import_export()
          + BulkImportStep added to derivation
          + BulkExportStep added to derivation
```

### Orthogonality

Each transform operates on a different axis of the DeriveOp:

| Transform | What it touches | Axis |
|-----------|----------------|------|
| audited | `handler_template` (wraps) | Surface (handler) |
| tenant_scoped | `capabilities` (adds enrichers) | Surface (runtime middleware) |
| soft_delete | `handler_template` + new ops + `input_proj` | Surface + Schema |
| exclude_managed | `input_proj` | Schema |
| with_events | `handler_template` (wraps) | Surface (handler) |
| with_import_export | adds new steps | Surface (new operations) |
| approval_flow | separate derivation | Independent |

Handler wrapping **stacks**: the Create handler gets wrapped by audit, then by events. At runtime:
```
event_wrapper(audit_wrapper(InsertNew.handler))
  → InsertNew executes
  → audit_wrapper sees Ok → writes AuditEntry
  → event_wrapper sees Ok → publishes Event
  → response returned
```

---

## Architecture: why this is possible

### The sheaf model

emergent models a program as a **global section of a sheaf over compilation targets**:

```
Wire Application (global section)
        │
   ┌────┼────┐
   ▼    ▼    ▼
  CLI  HTTP  TG   ← fibers (targets)
   │    │    │
   └────┼────┘
        ▼
    Execution     ← shared base
    + Storage
```

One entity has **multiple projections** (one per target). One endpoint has **multiple exposures** (one per transport). The wire-level representation is transport-agnostic — the same `Endpoint(Runner, [Exposure])` compiles to FastAPI routes, CLI commands, or Telegram handlers by swapping the compiler.

### The 4-axis sheaf

derivelib's derivation folds over 4 axes of the sheaf:

```
Pass 1: Schema   → inspect entity, extract fields, validate constraints
Pass 2: Query    → set up relational queries, identity filtering
         Storage → configure storage providers
         Surface → generate operations (handlers, codecs, triggers, capabilities)
```

Each step in the derivation implements `derive_schema()`, `derive_query()`, `derive_storage()`, and/or `derive_surface()`. The fold processes all steps through each axis sequentially.

### DerivationT — the composition primitive

```python
DerivationT = Callable[[Derivation], Derivation]
# where Derivation = tuple[Step, ...]
```

A `DerivationT` is a function from a derivation to a derivation. It receives the tuple of steps and returns a new tuple — possibly with modified, added, or removed steps.

The `.chain()` method applies transforms sequentially:

```python
dialect.chain(t1, t2, t3)
# equivalent to:
t3(t2(t1(dialect.compile(entity))))
```

This is pure function composition. No inheritance, no mixins, no method resolution order. Each transform sees the full derivation and can make precise, targeted modifications.

### DeriveOp — the unit of surface derivation

```python
@dataclass(frozen=True)
class DeriveOp:
    name: str                    # "List", "Get", "Create", etc.
    input_proj: Projection       # which fields go in the request
    output_proj: Projection      # which fields go in the response
    handler_template: Template   # how to handle the operation
    trigger: Trigger             # HTTP route, CLI command, etc.
    effects: tuple[Effect, ...]  # Read, Mutation, Creates, Deletes, etc.
    capabilities: tuple[Cap, ...]# enrichers, transforms, etc.
```

Every field is independently replaceable via `dataclasses.replace()`. Transforms can surgically modify any aspect of any operation without touching the rest.

### Effects — semantic operation tags

```python
class Read: ...        # operation reads data
class Mutation: ...    # operation mutates data
class Creates: ...     # operation creates new entities
class Updates: ...     # operation updates existing entities
class Deletes: ...     # operation deletes entities
class Idempotent: ...  # operation is idempotent
class Cacheable: ...   # operation result can be cached
class Pageable: ...    # operation supports pagination
class Sortable: ...    # operation supports sorting
```

Effects are not decorators or annotations on code — they're semantic tags on derivation steps. Transforms use `has_effect(op.effects, Mutation)` to select which operations to modify. This is precise: `audited()` targets `Mutation` (creates + updates + deletes), while `soft_delete()` targets `Deletes` specifically for handler replacement but `Read` for filtering.

### Projections — field algebra

```python
non_id()                         # all fields except identity
id_only()                        # only identity fields
all_fields()                     # all fields
entity_response()                # full entity as response
list_response()                  # {items: entity[]}
ok_response()                    # {success: bool}
ExcludeFromProjection(proj, ("deleted_at",))  # remove fields from projection
SelectFields(names=("name",))    # only these fields
ExcludeFields(names=("secret",)) # all except these
```

Projections are composable. `ExcludeFromProjection` wraps another projection and removes fields. Multiple excludes stack:

```python
# After soft_delete() + exclude_managed_fields("status"):
# CREATE input = ExcludeFromProjection(
#     ExcludeFromProjection(non_id(), ("deleted_at",)),
#     ("status",)
# )
# Result: {tenant_id, title, body}  — both excluded
```

The compiler reads the final projection to generate request/response schemas. The user never writes Pydantic models — schemas are a **consequence** of projections.

### Two handler extension mechanisms

| Mechanism | Access | When to use |
|-----------|--------|-------------|
| `WrappedTemplate` | `(op) → Result` only | Before/after logic on handler result (audit, events) |
| `ScopeEnricher` | `(call, scope) → R` | When you need runtime context (HTTP request, auth, tenant) |

**WrappedTemplate** wraps at compile time. The inner handler is called, its result inspected, side effects performed.

**ScopeEnricher** wraps at runtime. The entire call chain (enrichers → handler → response) is wrapped. The enricher can:
- Inject values into scope before the handler runs (HeaderTenantExtract)
- Post-process the response after it's built (TenantFilter)
- Short-circuit with an exception (AuthenticationRequired)

### Error pipeline

```
Handler returns Error(NotFound(entity="Article", id=999))
    ↓
Response converter: Error(err) → err  (passes through)
    ↓
CRUDErrorTransform.apply_response(): hasattr(err, "to_problem") → err.to_problem()
    → ProblemDetail(type="about:blank", title="Not Found", status=404,
                    detail="Article with id 999 not found")
    ↓
ProblemResponse.apply_response(): hasattr(resp, "status_code") → JSONResponse
    → JSONResponse(status_code=404, content={...}, media_type="application/problem+json")
    ↓
FastAPI sends 404 with RFC 7807 body (bypasses response_model validation)
```

This pipeline is a capability chain — `CRUDErrorTransform` and `ProblemResponse` are `ResponseTransform` capabilities attached to each operation. They apply in order, transforming the response. No exception handlers, no middleware — it's part of the operation's codec.

---

## OpenAPI analysis

The generated `openapi.json` (OpenAPI 3.1.0) contains:

### Paths

11 unique paths, 14 operations. Every path has:
- Proper HTTP method (GET for reads, POST for mutations, PUT for updates, DELETE for deletes)
- Path parameters with types (`{id}` → `integer`)
- Request body schemas (only on operations that accept input)
- Response schemas (unique per operation)

### Error responses on CRUD + approval endpoints

Every operation that can fail has RFC 7807 error responses:

```json
"404": {
    "description": "Resource not found",
    "content": {
        "application/problem+json": {
            "schema": {
                "properties": {
                    "type": {"type": "string", "format": "uri"},
                    "title": {"type": "string"},
                    "status": {"type": "integer"},
                    "detail": {"type": "string"},
                    "instance": {"type": "string", "format": "uri"}
                },
                "required": ["type", "title", "status"]
            }
        }
    }
},
"409": {"description": "Resource conflict", ...},
"422": {"description": "Validation error", ...}
```

These come from `ProblemResponse.compile_fastapi_route()` — the capability injects OpenAPI extra into the FastAPI route context at compile time. No manual annotation.

### Smart request schemas

**CREATE request:**
```json
{
    "properties": {
        "tenant_id": {"type": "string"},
        "title": {"type": "string"},
        "body": {"type": "string"}
    },
    "required": ["tenant_id", "title", "body"]
}
```

Note: no `id` (identity, auto-assigned), no `status` (managed by approval_flow, excluded by `exclude_managed_fields`), no `deleted_at` (managed by soft_delete, excluded by `ExcludeFromProjection`). The projection algebra computed this.

**DELETE request:** no body — only path parameter `{id}`.

**Approval transition request:** only path parameter `{id}` — the transition name is encoded in the URL.

**Import request:**
```json
{
    "properties": {
        "items": {"items": {"additionalProperties": true, "type": "object"}, "type": "array"}
    },
    "required": ["items"]
}
```

### Schema reuse

`ListArticleResponse.items` references `$ref: "#/components/schemas/Article"` — the entity schema is defined once and reused. Individual response schemas (`CreateArticleResponse`, `GetArticleResponse`, etc.) inline the fields because they may differ (projections can vary per operation).

---

## Comparison with classical approaches

### The same 14 endpoints in raw FastAPI

```
endpoints/
  articles.py          — CRUD routes with dependency injection       (~150 LOC)
  articles_tenant.py   — tenant header extraction + query filters    (~80 LOC)
  articles_soft.py     — soft delete handler + restore route         (~100 LOC)
  articles_approval.py — state machine validation + transitions      (~120 LOC)
  articles_bulk.py     — import/export routes                        (~80 LOC)
middleware/
  tenant.py            — Starlette middleware for tenant extraction   (~30 LOC)
  audit.py             — middleware or dependency for audit logging   (~50 LOC)
services/
  event_bus.py         — event publishing service                    (~40 LOC)
schemas/
  article.py           — 15 Pydantic response models, manually       (~100 LOC)
  requests.py          — request models per operation                 (~60 LOC)
  errors.py            — ProblemDetail + error schemas                (~40 LOC)
```

**~850 LOC of hand-written code.**

Problems:
- Every concern cross-cuts every layer (route → service → schema → middleware)
- Adding a new concern = editing 5+ files
- N entities = N copies of this structure, with copy-paste variations
- Request/response schemas are manually kept in sync with entity definition
- OpenAPI error responses are manually annotated
- Soft delete logic leaks into every query (`WHERE deleted_at IS NULL`)
- Tenant filtering leaks into every query (`WHERE tenant_id = ?`)
- Adding a second entity (Product) means writing another 850 LOC

### The same in Django REST Framework

```python
class SoftDeleteMixin:       ...   # 40 LOC
class TenantFilterMixin:     ...   # 30 LOC
class AuditMixin:            ...   # 40 LOC
class ArticleSerializer:     ...   # 30 LOC (duplicates model fields)
class ArticleViewSet(
    SoftDeleteMixin,
    TenantFilterMixin,
    AuditMixin,
    viewsets.ModelViewSet,
):
    serializer_class = ArticleSerializer
    ...                              # 50 LOC

class ApprovalViewSet(APIView): ...  # 80 LOC (separate, doesn't fit viewset)
class BulkImportView(APIView):  ...  # 40 LOC
# + signals for events              # 30 LOC
# + permissions                     # 30 LOC
```

**~370 LOC**, but:

- **Mixin hell:** `SoftDeleteMixin` + `TenantFilterMixin` + `AuditMixin` → diamond inheritance, MRO determines execution order, implicit coupling
- **Serializer duplication:** `ArticleSerializer` manually mirrors `Article` model fields. Change one, forget the other → silent bugs
- **Signals:** Django signals for events are implicit — you can't trace what fires when without grep
- **Approval flow doesn't fit:** ViewSets are CRUD-shaped. A state machine isn't CRUD. You drop to raw APIView, losing all mixin benefits
- **Bulk ops:** another separate view, another manual serializer
- **No projection algebra:** want to exclude `deleted_at` from input? Manual serializer field exclusion

### The same in emergent/derivelib

```python
@derive(
    http_crud(...).chain(audited(), tenant_scoped(), soft_delete(), ...),
    approval_flow(...),
)
@dataclass
class Article: ...
```

**~30 LOC user code.**

The 7 transforms total ~600 LOC, written once. They apply to any entity:

```python
# Second entity? Same transforms, zero duplication:
@derive(
    http_crud("/products", provider_node=Products).chain(
        tenant_scoped(HeaderTenantExtract()),
        soft_delete(),
        with_import_export(),
    ),
)
@dataclass
class Product:
    id: Annotated[int, Identity]
    tenant_id: str
    name: str
    price: float
    deleted_at: str | None = None
```

Another 10 endpoints. Another 0 boilerplate.

### The comparison table

| Aspect | FastAPI (manual) | DRF (mixins) | derivelib |
|--------|-----------------|-------------|-----------|
| User code for Article | ~850 LOC | ~370 LOC | ~30 LOC |
| Second entity (Product) | +850 LOC | +200 LOC | +10 LOC |
| Adding new concern | Edit 5+ files | New mixin + all viewsets | Write transform, `.chain()` |
| Schema sync | Manual | Semi-manual (serializers) | By construction |
| OpenAPI errors | Manual annotation | drf-spectacular config | Automatic (ProblemResponse) |
| Non-CRUD patterns | Separate routes | Separate views (lose mixins) | Separate Pattern, same `@derive()` |
| Transport portability | HTTP only | HTTP only | Swap compiler → CLI, TG, etc. |
| Composition model | Ad-hoc middleware/deps | Mixins (inheritance) | `DerivationT` (function composition) |

---

## The boilerplate is dead thesis

### What is boilerplate?

Boilerplate is code that:
1. **Repeats** across entities with minor variations
2. **Couples** concerns that should be independent
3. **Synchronizes** representations that should be derived

### How derivelib eliminates each form

**Repetition → transforms.** `audited()`, `tenant_scoped()`, `soft_delete()` are written once and applied to any entity via `.chain()`. N entities don't mean N copies — the transform IS the abstraction.

**Coupling → effect-based selection.** `audited()` doesn't know about `tenant_scoped()`. Each transform selects operations by effect (`Mutation`, `Read`, `Deletes`) and modifies them independently. No shared state, no ordering dependencies (beyond natural chain order).

**Synchronization → projection algebra.** The entity `@dataclass` is the single source of truth. Request schemas, response schemas, and OpenAPI specs are all derived from projections over the entity fields. Change the entity → everything updates. Add `soft_delete()` → `deleted_at` is excluded from input. No manual sync.

### The three levels

```
Level 3: @derive(http_crud(...).chain(soft_delete(), ...))     ← user code
Level 2: DerivationT transforms, Dialect patterns              ← reusable library
Level 1: DeriveOp, Effect, Projection, HandlerTemplate, Codec  ← primitives
Level 0: wire (Endpoint, Runner, Exposure, Trigger, Scope)     ← runtime
```

**Users** work at Level 3. They compose pre-built transforms.

**Library authors** work at Level 2. They build transforms from primitives.

**Framework authors** work at Level 1. They define new step types and projections.

**Each level doesn't know about the levels above.** The wire layer doesn't know about CRUD. CRUD doesn't know about soft_delete. soft_delete doesn't know about Article. This is the sheaf property — **local reasoning at every level**.

### Why classical frameworks can't do this

Classical web frameworks compose via **inheritance** (DRF mixins) or **middleware** (FastAPI dependencies). Both are limited:

- **Inheritance** is linear — you can't compose N concerns without N-way diamond inheritance
- **Middleware** is per-request, not per-operation — you can't say "only wrap mutations"
- **Both** operate on the route level — they can't modify request/response schemas
- **Neither** has a concept of "projection" — field inclusion/exclusion is always manual

derivelib composes via **derivation algebra** — pure functions over typed step tuples. This gives:
- **Arbitrary composition** — chain any number of transforms
- **Per-effect targeting** — modify only operations with specific semantic tags
- **Schema-level manipulation** — projections modify what fields exist in request/response
- **Transport independence** — transforms operate on wire-level abstractions, not HTTP specifics

### The endgame

When boilerplate is dead, adding a new business concern to your API looks like this:

```python
# Before: Article with CRUD + audit + tenant + soft-delete
.chain(audited(), tenant_scoped(), soft_delete(), with_events())

# After: add rate limiting
.chain(audited(), tenant_scoped(), soft_delete(), with_events(), rate_limited(100))
```

One function call. Works on all entities. Generates correct OpenAPI. No files edited, no schemas updated, no middleware registered.

**That's what "boilerplate is dead" means.**

---

## Running the demo

```bash
cd derivelib
PYTHONPATH=src:.. uv run python -m examples.ultimate
```

```bash
# Create article
curl -X POST http://localhost:8000/articles \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-Id: acme' \
  -d '{"tenant_id":"acme","title":"hello","body":"world"}'

# List (tenant-filtered)
curl http://localhost:8000/articles -H 'X-Tenant-Id: acme'

# Soft delete
curl -X DELETE http://localhost:8000/articles/1

# Restore
curl -X POST http://localhost:8000/articles/1/restore

# Submit for approval
curl -X POST http://localhost:8000/articles/1/submit

# Approve
curl -X POST http://localhost:8000/articles/1/approve

# Check status
curl http://localhost:8000/articles/1/status

# Bulk import
curl -X POST http://localhost:8000/articles/import \
  -H 'Content-Type: application/json' \
  -d '{"items":[{"tenant_id":"acme","title":"a","body":"b"}]}'

# Export
curl http://localhost:8000/articles/export

# Error: invalid transition
curl -X POST http://localhost:8000/articles/1/submit
# → {"type":"about:blank","title":"Unprocessable Entity","status":422,
#    "detail":"Invalid Article: cannot 'submit': state is 'published', need ('draft',)"}

# Error: cross-tenant access
curl http://localhost:8000/articles/1 -H 'X-Tenant-Id: evil'
# → {"type":"about:blank","title":"Not Found","status":404,...}

# OpenAPI spec
curl http://localhost:8000/openapi.json
```
