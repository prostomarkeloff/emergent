# derivelib

## Part I: Architecture

### What it is

One decorator. One dataclass. Full application.

```python
@derive(http_crud("/api/users", provider_node=Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: str
```

This generates: 5 HTTP endpoints (List, Get, Create, Update, Delete), request types with Pydantic validation, response types with domain mapping, OpenAPI schema, CLI commands — all from the shape of `User`.

derivelib is not a CRUD generator. CRUD is one dialect. The machinery underneath is a generic algebraic derivation system over wire's 4-axis IR.

### The algebra

Three types:

```
Step       = any object implementing derive_schema / derive_query / derive_storage / derive_surface
Derivation = tuple[Step, ...]
DerivationT = Derivation → Derivation
```

A **Pattern** compiles an entity into a Derivation:

```python
class Pattern(Protocol):
    def compile(self, entity: type) -> Derivation: ...
```

`@derive` stores patterns on the class. `build_application_from_decorated` compiles them.

### The pipeline

```
entity + @derive(pattern)
    ↓
pattern.compile(entity) → Derivation (tuple of steps)
    ↓
fold_derive(steps, entity) → DerivationCtx
    ↓
materialize(ctx) → Endpoint
    ↓
build_application_from_decorated → Application
    ↓
targets.fastapi.compile(app)  /  targets.cli.compile(app)
```

### The fold

Every derivation goes through a two-pass fold over 4 axes:

```
Pass 1:  Schema    — inspect entity fields, validate constraints
Pass 2:  Query → Storage → Surface  (sequential, each sees prior results)
```

Each pass folds the same tuple of steps. A step only runs in passes where it implements the matching protocol:

```python
@dataclass(frozen=True, slots=True)
class MyStep:
    def derive_schema(self, ctx: SchemaCtx) -> SchemaCtx:
        # runs in pass 1
        ...
    def derive_surface(self, ctx: SurfaceCtx) -> SurfaceCtx:
        # runs in pass 2
        ...
    # skipped in query and storage passes — doesn't implement those protocols
```

The fold uses wire's universal `fold()` primitive — isinstance check on protocol, call the method, accumulate context. Steps not matching a phase are silently skipped.

### Module structure

```
derivelib/
├── _ctx.py          ← KERNEL: SchemaCtx, QueryCtx, StorageCtx, SurfaceCtx
├── _protocols.py    ← KERNEL: SchemaDerivable, QueryDerivable, ..., HandlerTemplate
├── _derivation.py   ← KERNEL: Step, Derivation, DerivationT
├── _fold.py         ← KERNEL: DerivationPhase, fold_derive, materialize
├── _effects.py      ← KERNEL: DerivationEffect + dispatch helpers
├── _project.py      ← KERNEL: FieldProjection, ResponseSpec + implementations
├── _derive.py       ← KERNEL: Pattern, @derive, build_application_from_decorated
├── _opspec.py       ← KERNEL: OpSpec, build_from_spec
├── _errors.py       ← KERNEL: NotFound, AlreadyExists, InvalidData, ProblemDetail
├── _query_helpers.py← KERNEL: filter_by_identity, fetch_by_identity, ...
├── _handler_templates.py ← STDLIB: FetchMany, InsertNew, ...
├── _dialect.py      ← STDLIB: Op, Dialect, TriggerGen, HTTPTriggers, CLITriggers
├── _codegen.py      ← STDLIB: create_dataclass, create_request_type, ...
├── _builders.py     ← STDLIB: ExposureBuilder, EndpointBuilder
├── _error_caps.py   ← KERNEL: ErrorTransform, ProblemResponse, ERROR_CAPS
├── _explain.py      ← STDLIB: explain_entity(), entity_derivation_dict(), DERIVE_EXPLAIN
├── adapt.py         ← STDLIB: AdaptationDialect, SoftDelete/Timestamps
├── transforms.py    ← STDLIB: readonly(), paginated(), add_capability(), map_methods(), ...
├── axes/            ← STDLIB: per-axis step library
│   ├── schema.py    ← inspect_entity, require_identity, exclude_fields
│   ├── query.py     ← bind_provider, base_query, custom_base_query
│   └── surface.py   ← DeriveOp, ExposeOp, AddGlobalCap
└── patterns/        ← DIALECTS
    ├── crud.py      ← http_crud, cli_crud, LIST/GET/CREATE/UPDATE/DELETE
    ├── nested.py    ← nested_http_crud (parent/child resources)
    └── methods.py   ← methods, MethodsPattern, @post/@get/@command decorators
```

**Rule**: kernel imports only from kernel. Stdlib imports from kernel + wire. Dialects import from anything.

---

## Part II: Full Reference

### 2.1 Core Types

#### `Step`

```python
type Step = Any
```

Any object implementing one or more `derive_*` methods. The fold checks `isinstance(step, Protocol)` at runtime.

#### `Derivation`

```python
type Derivation = tuple[Step, ...]
```

Ordered tuple of steps. The fold processes them left-to-right.

#### `DerivationT`

```python
type DerivationT = Callable[[Derivation], Derivation]
```

Higher-order: transforms step tuples. Used by `Dialect.chain()` for transform composition.

---

### 2.2 Contexts

All contexts are `@dataclass(frozen=True, slots=True)`. Steps return new contexts via `dataclasses.replace()`. No mutation anywhere.

#### `SchemaCtx` (Pass 1)

```python
@dataclass(frozen=True, slots=True)
class SchemaCtx:
    entity: type                           # the entity class
    fields: dict[str, FieldInfo]           # all fields
    identity_fields: dict[str, FieldInfo]  # Identity-annotated fields
```

Methods:
- `SchemaCtx.from_entity(cls)` — create from entity type (inspects fields, discovers Identity)
- `identity_names()` — tuple of identity field names
- `non_identity_fields()` — fields excluding identity
- `field_types(exclude=())` — `{name: base_type}` dict
- `annotated_field_types(exclude=(), only=None)` — `{name: Annotated[type, *caps]}` preserving capabilities

#### `QueryCtx` (Pass 2)

```python
@dataclass(frozen=True, slots=True)
class QueryCtx:
    schema: SchemaCtx              # frozen from pass 1
    provider_node: type | None     # nodnod node TYPE
    base_query: Any | None         # relational/kv/api query
```

#### `StorageCtx` (Pass 2)

```python
@dataclass(frozen=True, slots=True)
class StorageCtx:
    schema: SchemaCtx
    backend_node: type | None
```

#### `SurfaceCtx` (Pass 2)

```python
@dataclass(frozen=True, slots=True)
class SurfaceCtx:
    schema: SchemaCtx
    query: QueryCtx | None
    storage: StorageCtx | None
    specs: tuple[OpSpec, ...]          # from DeriveOp — materialized later
    operations: tuple[Operation, ...]  # direct (OpType, handler, Exposure) tuples
    capabilities: tuple[Capability, ...]  # global capabilities
```

Methods:
- `get_base_query()` — extract base query from QueryCtx
- `add_spec(spec)` — return new ctx with OpSpec appended
- `add_operation(op)` — return new ctx with direct operation appended
- `add_exposure(builder)` — build ExposureBuilder and add resulting operation
- `add_capability(cap)` — return new ctx with global capability appended

#### `DerivationCtx`

```python
@dataclass(frozen=True, slots=True)
class DerivationCtx:
    schema: SchemaCtx
    query: QueryCtx
    storage: StorageCtx
    surface: SurfaceCtx
```

Full derivation context — all axes bundled after `fold_derive`.

---

### 2.3 Protocols

#### Axis protocols

```python
@runtime_checkable
class SchemaDerivable(Protocol):
    def derive_schema(self, ctx: SchemaCtx) -> SchemaCtx: ...

@runtime_checkable
class QueryDerivable(Protocol):
    def derive_query(self, ctx: QueryCtx) -> QueryCtx: ...

@runtime_checkable
class StorageDerivable(Protocol):
    def derive_storage(self, ctx: StorageCtx) -> StorageCtx: ...

@runtime_checkable
class SurfaceDerivable(Protocol):
    def derive_surface(self, ctx: SurfaceCtx) -> SurfaceCtx: ...

class FullDerivable(SchemaDerivable, QueryDerivable, StorageDerivable, SurfaceDerivable, Protocol):
    """Step that touches ALL axes (rare)."""
```

A step can implement any subset. The fold checks `isinstance` and skips non-matching phases.

#### `HandlerTemplate`

```python
@runtime_checkable
class HandlerTemplate(Protocol):
    def build(self, spec: HandlerSpec) -> Callable[..., Awaitable[Any]]: ...
```

Builds an async handler from a `HandlerSpec`:

```python
@dataclass(frozen=True, slots=True)
class HandlerSpec:
    entity: type
    entity_name: str
    identity_names: tuple[str, ...]
    non_identity_names: tuple[str, ...]
    base_query: Any
```

#### `WrappedTemplate` / `wrap_template`

Compose handler templates — inner handler wrapped by outer function:

```python
def validate_unique(inner, spec):
    async def handler(op):
        existing = await op.provider.fetch_one(...)
        if existing:
            return Error(AlreadyExists(...))
        return await inner(op)
    return handler

VALIDATED_CREATE = Op("Create", ..., wrap_template(InsertNew(), validate_unique))
```

#### `Pattern`

```python
@runtime_checkable
class Pattern(Protocol):
    def compile(self, entity: type) -> Derivation: ...
```

#### `FieldProjection`

```python
@runtime_checkable
class FieldProjection(Protocol):
    def project(self, schema: SchemaCtx) -> dict[str, type]: ...
```

#### `ResponseSpec`

```python
@runtime_checkable
class ResponseSpec(Protocol):
    def resolve(self, schema: SchemaCtx) -> ResolvedResponse: ...

# ResolvedResponse = tuple[list[tuple[str, Any]], converter_fn]
```

---

### 2.4 Fold Machinery

#### `DerivationPhase`

```python
@dataclass(frozen=True, slots=True)
class DerivationPhase[Ctx]:
    context_type: type[Ctx]   # SchemaCtx, QueryCtx, etc.
    protocol: type            # SchemaDerivable, etc.
    handlers: Mapping[type, StepHandler[Ctx]] | None = None
```

Methods:
- `fold(steps, initial)` — run fold with this phase's protocol
- `with_handler(step_type, handler)` — return new phase with added handler
- `without_handler(step_type)` — return new phase without handler

Phase constants:

```python
SCHEMA_PHASE  = DerivationPhase(SchemaCtx,  SchemaDerivable)
QUERY_PHASE   = DerivationPhase(QueryCtx,   QueryDerivable)
STORAGE_PHASE = DerivationPhase(StorageCtx, StorageDerivable)
SURFACE_PHASE = DerivationPhase(SurfaceCtx, SurfaceDerivable)
```

#### `fold_derive(steps, entity, **phases) -> DerivationCtx`

Two-pass orchestration:

```python
# Pass 1: Schema
schema_ctx = schema_phase.fold(steps, SchemaCtx.from_entity(entity))

# Pass 2: Sequential
query_ctx   = query_phase.fold(steps, QueryCtx(schema=schema_ctx))
storage_ctx = storage_phase.fold(steps, StorageCtx(schema=schema_ctx))
surface_ctx = surface_phase.fold(steps, SurfaceCtx(schema=schema_ctx, query=query_ctx, storage=storage_ctx))
```

Override phases for custom fold behavior:

```python
custom_phase = SCHEMA_PHASE.with_handler(MyStepType, my_custom_handler)
ctx = fold_derive(steps, entity, schema_phase=custom_phase)
```

#### `materialize(ctx) -> Endpoint`

Converts `DerivationCtx` into wire `Endpoint`:
1. Direct operations (from `ExposeOp`) → ops builder + exposures
2. Specs (from `DeriveOp`) → `build_from_spec()` → types + handler + exposure
3. Merge into single `Endpoint(runner, exposures)`

---

### 2.5 OpSpec

```python
@dataclass(frozen=True, slots=True)
class OpSpec:
    name: str                          # "Get", "Create", ...
    entity_name: str                   # "User"
    input_fields: dict[str, type]      # projected fields (plain types)
    request_fields: dict[str, Any]     # annotated fields (may include Annotated)
    response_spec: ResponseSpec
    handler_template: HandlerTemplate
    trigger: Trigger
    capabilities: tuple[Capability, ...]
    effects: tuple[DerivationEffect, ...]
    codec_factory: Any                 # None → default rrc
    extra_op_fields: tuple[tuple[str, type], ...]
    extra_request_fields: tuple[tuple[str, Any], ...]
```

Pure data description of a derived operation. Steps accumulate `OpSpec`s. `materialize()` builds artifacts from them. Inspectable, transformable.

`build_from_spec(spec, ctx) -> (op_type, handler, Exposure)` — creates:
- Op type (frozen dataclass)
- Request type (with `to_domain()` baked in via namespace)
- Response type (with `from_domain()` baked in via namespace)
- Handler (from template + HandlerSpec)
- Exposure (trigger + codec + capabilities)

---

### 2.6 Field Projections

Which entity fields appear in request types:

| Projection | Constructor | Selects |
|---|---|---|
| `AllFields` | `all_fields()` | All entity fields |
| `IdOnly` | `id_only()` | Identity fields only |
| `NonId` | `non_id()` | Everything except identity |
| `RequiredNonId` | `required_non_id()` | Non-id fields without defaults |
| `NoFields` | `no_fields()` | Empty (no input) |
| `SelectFields` | `fields("name", "email")` | Named fields only |
| `ExcludeFields` | `exclude("secret")` | All except named |
| `ExcludeFromProjection` | `exclude_from(non_id(), "ts")` | Wrap projection, exclude fields |

Custom projection:

```python
@dataclass(frozen=True, slots=True)
class PublicFields:
    def project(self, schema: SchemaCtx) -> dict[str, type]:
        return {n: i.base_type for n, i in schema.fields.items()
                if not n.startswith("_")}
```

---

### 2.7 Response Specs

| Spec | Constructor | Shape |
|---|---|---|
| `EntityResponse` | `entity_response()` | Mirrors entity fields |
| `ListResponse` | `list_response()` | `{items: list[Entity]}` |
| `OkResponse` | `ok_response()` | `{success: bool}` |
| `PaginatedResponse` | `paginated_response()` | `{items, total, page, page_size}` |
| `CustomResponse` | `custom_response(fields, converter)` | Explicit fields + converter |

`EntityResponse` and `ListResponse` accept `exclude` parameter for projected views:

```python
EntityResponse(exclude=("secret",))   # all fields except secret
ListResponse(exclude=("active_at",))  # items = list[EntityView] without active_at
```

Custom response:

```python
@dataclass(frozen=True, slots=True)
class CursorResponse:
    def resolve(self, schema: SchemaCtx) -> ResolvedResponse:
        entity = schema.entity
        fields = [("items", list[entity]), ("cursor", str), ("has_more", bool)]
        converter = _result_converter(
            ok=lambda cls, result: cls(**result),
            error=lambda cls, _: cls(items=[], cursor="", has_more=False),
        )
        return fields, converter
```

---

### 2.8 Effects

Effects classify operations semantically. Transforms dispatch on effects via `isinstance` — open-world.

| Effect | Category | Meaning |
|---|---|---|
| `Read()` | Semantic | Reads data |
| `Mutation()` | Semantic | Modifies data |
| `Idempotent()` | Semantic | Safe to retry |
| `Creates()` | CRUD-semantic | Inserts new entities |
| `Updates()` | CRUD-semantic | Modifies existing entities |
| `Deletes()` | CRUD-semantic | Removes entities |
| `Pageable()` | Query | Supports pagination |
| `Sortable()` | Query | Supports sorting |
| `Cacheable()` | Query | Result can be cached |

Custom effect — identical mechanism:

```python
@dataclass(frozen=True, slots=True)
class Auditable(DerivationEffect):
    level: str = "info"

# dispatch:
has_effect(op.effects, Auditable)  # bool
get_effect(op.effects, Auditable)  # Auditable instance or None
```

---

### 2.9 Handler Templates

| Template | Use | Behavior |
|---|---|---|
| `FetchMany(scope_fields=())` | List | `provider.fetch_many(query)` |
| `FetchOneById(scope_fields=())` | Get | `provider.fetch_one(filter_by_identity)` |
| `InsertNew()` | Create | Construct entity, `provider.insert()` |
| `UpdateExisting(scope_fields=())` | Update | Find by id, merge ALL fields, `provider.update()` |
| `PatchExisting(scope_fields=())` | Patch | Find by id, merge only provided (non-None) fields, `provider.update()` |
| `DeleteOne(scope_fields=())` | Delete | Find by id, `provider.delete()` |
| `PaginatedFetchMany(page_size=20)` | Paginated list | `provider.count() + paginate()` |
| `SortedFetchMany(scope_fields=())` | Sorted list | `provider.fetch_many(query.order_by(...))` |
| `CachedFetchOneById()` | Cached get | Cache check → fallback to provider |

`scope_fields` enables nested resources — pre-filters base query by parent FK.

Custom template:

```python
@dataclass(frozen=True, slots=True)
class SubmitAndProcess:
    processor: Callable[..., Awaitable[Any]]

    def build(self, spec: HandlerSpec) -> Callable[..., Awaitable[Any]]:
        entity = spec.entity
        async def handler(op):
            new = entity(**{f: getattr(op, f) for f in spec.non_identity_names})
            inserted = await op.provider.insert(new)
            await self.processor(inserted)
            return Ok(inserted)
        return handler
```

---

### 2.10 Op

Transport-agnostic operation descriptor — WHAT, not WHERE:

```python
@dataclass(frozen=True, slots=True)
class Op:
    name: str                          # display name
    input_proj: FieldProjection        # entity fields → request
    output: ResponseSpec               # response shape
    handler_template: HandlerTemplate  # how to build the handler
    capabilities: tuple[Capability, ...] = ()
    extra_op_fields: tuple[tuple[str, type], ...] = ()
    extra_request_fields: tuple[tuple[str, Any], ...] = ()
    effects: tuple[DerivationEffect, ...] = ()
    codec_factory: CodecFactory = None  # None → default rrc
```

CRUD Ops (pre-defined):

```python
LIST   = Op("List",   no_fields(),  list_response(),   FetchMany(),       effects=(Read(), Pageable(), Sortable()))
GET    = Op("Get",    id_only(),    entity_response(),  FetchOneById(),    effects=(Read(), Idempotent(), Cacheable()))
CREATE = Op("Create", non_id(),     entity_response(),  InsertNew(),       effects=(Creates(),))
UPDATE = Op("Update", all_fields(), entity_response(),  UpdateExisting(),  effects=(Updates(), Idempotent()))
PATCH  = Op("Patch",  merge(id_only(), optional_non_id()), entity_response(), PatchExisting(), effects=(Updates(), Idempotent()))
DELETE = Op("Delete", id_only(),    ok_response(),      DeleteOne(),       effects=(Deletes(), Idempotent()))

ALL_CRUD_OPS     = (LIST, GET, CREATE, UPDATE, PATCH, DELETE)
MUTATION_CRUD_OPS = (CREATE, UPDATE, PATCH, DELETE)
READ_CRUD_OPS    = (LIST, GET)
```

Note: `Creates`, `Updates`, `Deletes` extend `Mutation`, so `has_effect(effects, Mutation)` matches them automatically — no need to tag `Mutation()` separately.

Op-level transforms:

```python
with_caps(ops, CORSCap())                     # add cap to all
with_caps(ops, AuthCap(), effect=Mutation)     # add cap only to mutations
select_ops(ops, "List", "Get")                 # keep by name
exclude_ops(ops, "Delete")                     # remove by name
by_effect(ops, Mutation)                       # filter by effect
```

---

### 2.11 TriggerGen

Map `(entity, Op) → Trigger`. Transport-specific, pattern-agnostic.

```python
@runtime_checkable
class TriggerGen(Protocol):
    def __call__(self, entity: type, op: Op) -> Trigger | None: ...
```

Built-in generators:

#### `HTTPTriggers(base_path, routes=DEFAULT_REST_ROUTES)`

```python
DEFAULT_REST_ROUTES = {
    "List":   ("GET",    False),
    "Get":    ("GET",    True),
    "Create": ("POST",   False),
    "Update": ("PUT",    True),
    "Patch":  ("PATCH",  True),
    "Delete": ("DELETE", True),
}
```

Identity path params auto-built from entity's Identity fields (supports composite keys). Unknown ops → `POST /path/<name>`.

Custom routes:

```python
HTTPTriggers("/api/users", routes={**DEFAULT_REST_ROUTES, "Search": ("POST", False)})
```

#### `NestedHTTPTriggers(parent_path, scope_fields, child_segment)`

```python
NestedHTTPTriggers("/users", ("user_id",), "posts")
# GET    /users/{user_id}/posts
# GET    /users/{user_id}/posts/{id}
# POST   /users/{user_id}/posts
# PUT    /users/{user_id}/posts/{id}
# DELETE /users/{user_id}/posts/{id}
```

#### `CLITriggers(prefix)`

```python
CLITriggers("user")
# user-list, user-get, user-create, user-update, user-delete
```

Custom trigger gen:

```python
@dataclass(frozen=True, slots=True)
class MQTTTriggers:
    topic_prefix: str
    def __call__(self, entity: type, op: Op) -> Trigger:
        return MQTTTopicTrigger(f"{self.topic_prefix}/{op.name.lower()}")
```

---

### 2.12 Dialect

Generic pattern: `ops x triggers → derivation`.

```python
@dataclass(frozen=True, slots=True)
class Dialect:
    ops: tuple[Op, ...]
    triggers: TriggerGen
    capabilities: tuple[Capability, ...] = ()
    preamble: tuple[Any, ...] = ()
    shared_op_fields: tuple[tuple[str, type], ...] = ()
    shared_request_fields: tuple[tuple[str, Any], ...] = ()
    adapt: bool = True  # auto-adapt ops based on schema_meta
```

Smart constructor `dialect()` builds standard preamble (schema inspection + query setup + provider binding):

```python
my_dialect = dialect(
    LIST, GET, COUNT,
    triggers=HTTPTriggers("/api/users"),
    provider_node=UserProvider,
)
```

`Dialect.chain(*transforms)` returns a `ChainedPattern` that applies `DerivationT` transforms after compile:

```python
http_crud("/api/users", Users).chain(readonly(), paginated(20))
```

---

### 2.13 CRUD Pattern

```python
# Full CRUD
http_crud("/api/users", provider_node=Users)

# Subset
http_crud("/api/users", provider_node=Users, ops=(LIST, GET))

# CLI
cli_crud("user", provider_node=Users)

# Generic (any triggers)
crud(HTTPTriggers("/api/users"), provider_node=Users)

# With extra capabilities
http_crud("/api/users", provider_node=Users, CORSCap())
```

Error handling: CRUD pattern includes `ErrorTransform` and `ProblemResponse` (see §2.15). Backward-compatible alias `CRUDErrorTransform` re-exported from `crud.py`.

### 2.14 Nested CRUD

Auto-discovers `Ref(parent)` FK on child entity:

```python
@derive(nested_http_crud("/users", parent=User, provider_node=Posts))
@dataclass
class Post:
    id: Annotated[int, Identity]
    user_id: Annotated[int, Ref(User)]
    title: str
    body: str

# GET    /users/{user_id}/posts
# GET    /users/{user_id}/posts/{id}
# POST   /users/{user_id}/posts
# PUT    /users/{user_id}/posts/{id}
# DELETE /users/{user_id}/posts/{id}
```

Parameters:
- `parent_path` — parent's base path
- `parent` — parent entity type (for FK discovery)
- `provider_node` — nodnod node for child provider
- `fk_field` — explicit FK field name (auto-discovered from `Ref` if None)
- `child_segment` — URL segment for child (default: `entity_name + "s"`)

---

### 2.15 Error Capabilities (`_error_caps.py`)

Generic error handling capabilities — shared by CRUD and Methods patterns.

```python
from derivelib import ErrorTransform, ProblemResponse, ERROR_CAPS
```

#### `ErrorTransform`

Calls `.to_problem()` on error responses that implement it (e.g. `NotFound`, `AlreadyExists`, `InvalidData`):

```python
@dataclass(frozen=True, slots=True)
class ErrorTransform(ResponseTransform):
    def apply_response(self, response: object) -> object:
        to_problem = getattr(response, "to_problem", None)
        if callable(to_problem):
            return to_problem()
        return response
```

#### `ProblemResponse`

Wraps `ProblemDetail` in JSONResponse with `application/problem+json` content type and correct HTTP status code. Also generates 404/409/422 error responses in OpenAPI schema.

#### `ERROR_CAPS`

```python
ERROR_CAPS: tuple[SurfaceCapability, ...] = (ErrorTransform(), ProblemResponse())
```

Both CRUD and Methods patterns use `ERROR_CAPS` by default. Custom patterns can reference `ERROR_CAPS` directly:

```python
my_pattern = dialect(*ops, triggers=..., provider_node=..., capabilities=(*caps, *ERROR_CAPS))
```

---

### 2.16 Methods Pattern

Write async methods. Decorate each with its trigger. Get endpoints.

```python
from derivelib import derive, build_application_from_decorated
from derivelib.patterns.methods import methods, post, get, command

@derive(methods)
@dataclass
class OrderService:
    @post("/api/orders")
    async def create(self, customer: str, total: float) -> Result[int, DomainError]:
        return Ok(new_id)

    @get("/api/orders")
    async def list_all(self) -> Result[list[Order], DomainError]:
        ...

app = build_application_from_decorated(OrderService)
```

Methods don't derive from entity shape — they're explicit. Each method declares its own trigger, parameters, and return type. The pattern scans the class and produces one endpoint per decorated method.

#### Trigger decorators

| Decorator | Trigger | Example |
|---|---|---|
| `@post(path)` | `HTTPRouteTrigger("POST", path)` | `@post("/api/orders")` |
| `@get(path)` | `HTTPRouteTrigger("GET", path)` | `@get("/api/orders/{id}")` |
| `@put(path)` | `HTTPRouteTrigger("PUT", path)` | `@put("/api/orders/{id}")` |
| `@patch(path)` | `HTTPRouteTrigger("PATCH", path)` | `@patch("/api/orders/{id}")` |
| `@delete(path)` | `HTTPRouteTrigger("DELETE", path)` | `@delete("/api/orders/{id}")` |
| `@command(name)` | `CLITrigger(name, description)` | `@command("order-create")` |
| `@method(trigger)` | Any trigger | `@method(MQTTTrigger(...))` |

#### Multi-target

Stack decorators for multiple exposures per method:

```python
@post("/api/orders")
@command("order-create")
async def create(self, ...) -> Result[int, DomainError]: ...
```

#### Per-method capabilities

Pass capabilities directly to trigger decorators:

```python
@post("/api/admin/users", AuthCap())
async def admin_create(self, ...) -> Result[User, DomainError]: ...
```

#### `MethodsPattern`

```python
@dataclass(frozen=True, slots=True)
class MethodsPattern:
    capabilities: tuple[SurfaceCapability, ...] = ()

    def chain(self, *transforms: DerivationT) -> ChainedPattern: ...
    def compile(self, entity: type) -> Derivation: ...
```

The `methods` default instance includes RFC 7807 error handling:

```python
methods = MethodsPattern(capabilities=ERROR_CAPS)
```

Custom capabilities (no RFC 7807):

```python
@derive(MethodsPattern(capabilities=(MyErrorHandler(),)))
@dataclass
class CustomService: ...
```

No capabilities at all:

```python
@derive(MethodsPattern())
@dataclass
class RawService: ...
```

#### `.chain()` composition

Same as `Dialect.chain()` — applies `DerivationT` transforms after compile:

```python
from derivelib.transforms import add_method_capability

@derive(methods.chain(add_method_capability(AuthCap())))
@dataclass
class SecureService: ...
```

#### `ExposeMethod` step

Each decorated method becomes an `ExposeMethod` step in the derivation. It implements `SurfaceDerivable`:

```python
@dataclass(frozen=True, slots=True)
class ExposeMethod:
    service: type
    method_name: str
    trigger: object
    capabilities: tuple[SurfaceCapability, ...]  # merged: pattern + decorator
    suffix: str

    def derive_surface(self, ctx: SurfaceCtx) -> SurfaceCtx: ...
```

At compile time, `MethodsPattern` merges pattern-level and decorator-level capabilities into a single `capabilities` field.

#### Methods-specific transforms

```python
from derivelib.transforms import map_methods, add_method_capability

# Transform all ExposeMethod steps
map_methods(fn)                  # fn(Step) -> Step, applied to ExposeMethod only

# Add capability to all methods
add_method_capability(AuthCap()) # appends to ExposeMethod.capabilities
```

#### Handler contract

Methods must return `Result[T, E]`:

```python
async def create(self, ...) -> Result[int, DomainError]:
    return Ok(42)          # success
    return Error(InvalidData(...))  # error → passed through capabilities
```

The `T` in `Result[T, E]` becomes the response type. Errors are converted by capabilities (e.g. `ErrorTransform` calls `.to_problem()`, `ProblemResponse` wraps in RFC 7807 JSON).

#### DI via `compose.Node`

Methods get dependencies via `Annotated[T, compose.Node(NodeType)]` — same DI mechanism as CRUD handlers:

```python
@post("/api/orders")
async def create(
    self,
    db: Annotated[MutatingRelationalProvider[Order], compose.Node(OrderStore)],
    customer: str,
    total: float,
) -> Result[int, DomainError]:
    ...
```

---

### 2.17 Transforms (`DerivationT`)

`DerivationT = Derivation → Derivation`. Applied via `Dialect.chain()` or `MethodsPattern.chain()`:

```python
@derive(
    http_crud("/api/users", Users)
        .chain(readonly(), paginated(20), add_capability(CORSCap()))
)
```

#### Fold primitives

| Primitive | Signature | Behavior |
|---|---|---|
| `map_by_effect(handlers)` | `dict[type, handler]` | Fold DeriveOp effects through handler table |
| `reject_by_effect(*effect_types)` | `type[Effect]...` | Remove DeriveOps with any of given effects |
| `select_by_effect(*effect_types)` | `type[Effect]...` | Keep only DeriveOps with any of given effects |
| `map_all_ops(fn)` | `fn(DeriveOp) -> DeriveOp` | Transform all DeriveOp steps |

Non-DeriveOp steps (preamble) always pass through.

#### Semantic transforms

| Transform | Effect | Description |
|---|---|---|
| `readonly()` | `reject_by_effect(Mutation)` | Remove mutation ops |
| `mutations_only()` | `select_by_effect(Mutation)` | Keep only mutations |
| `without_delete()` | `reject_by_effect(Deletes)` | Remove delete ops |
| `without_ops("Create", "Delete")` | by name | Remove named ops |
| `only_ops("List", "Get")` | by name | Keep named ops |

#### Capability injection

```python
add_capability(CORSCap())           # all ops
add_capability(AuthCap(), Mutation)  # only mutations
```

#### Response projection

```python
project_response(exclude=("active_at",))               # Read ops
project_response(exclude=("secret",), effect=Mutation)  # custom effect
```

Replaces `EntityResponse` / `ListResponse` with projected versions.

#### Handler wrapping

```python
wrap_by_effect(Mutation, lambda op: my_wrapper_factory(op.name))
```

Wraps handler templates on ops with given effect using `WrappedTemplate`.

#### Handler / trigger swaps

```python
swap_handler("Delete", SoftDeleteMark())  # replace handler by op name
swap_trigger("List", my_trigger)          # replace trigger by op name
rename_ops({"List": "Search", "Get": "Fetch"})
```

#### Query enrichment

```python
paginated(20)                     # PaginatedFetchMany on Pageable ops
sorted_list("name", "asc")       # add sort/order params to Sortable ops
```

#### Enrichers (wire ScopeEnricher capabilities)

```python
with_timeout(5.0)         # Timeout enricher, all ops
with_retry(3)             # Retry enricher, mutation ops
with_rate_limit(100)      # RateLimit enricher, all ops
```

#### Methods transforms

| Transform | Signature | Behavior |
|---|---|---|
| `map_methods(fn)` | `fn(Step) -> Step` | Transform `ExposeMethod` steps only |
| `add_method_capability(*caps)` | `SurfaceCapability...` | Append capabilities to `ExposeMethod` steps |

```python
from derivelib.transforms import map_methods, add_method_capability

# Add auth to all methods
methods.chain(add_method_capability(AuthCap()))

# Custom method transform
methods.chain(map_methods(lambda s: replace(s, suffix="_v2")))
```

Non-`ExposeMethod` steps always pass through.

#### Custom transform

```python
def audit_mutations() -> DerivationT:
    def transform(steps: Derivation) -> Derivation:
        from derivelib.axes.surface import DeriveOp
        result = []
        for s in steps:
            if isinstance(s, DeriveOp) and has_effect(s.effects, Mutation):
                s = replace(s, capabilities=(*s.capabilities, AuditCap()))
            result.append(s)
        return tuple(result)
    return transform
```

Or using primitives:

```python
def audit_mutations() -> DerivationT:
    return map_by_effect({
        Mutation: lambda _eff, op: replace(op, capabilities=(*op.capabilities, AuditCap()))
    })
```

---

### 2.18 Adaptation

Schema capabilities (`@schema_meta`) automatically adapt ops and queries.

Built-in adaptations:

| Schema Capability | Op Adaptation | Query Adaptation |
|---|---|---|
| `SoftDelete("deleted_at")` | Delete → `SoftDeleteMark` | Base query filters `deleted_at IS NULL` |
| `Timestamps("created", "updated")` | Create → auto-set both, Update → auto-set updated | — |
| `CreatedAt("created_at")` | (combined with UpdatedAt) | — |
| `UpdatedAt("updated_at")` | (combined with CreatedAt) | — |

```python
from emergent.wire.axis.schema._universal import schema_meta
from emergent.wire.axis.schema.dialects.temporal import SoftDelete, Timestamps

@schema_meta(SoftDelete("deleted_at"), Timestamps("created_at", "updated_at"))
@derive(http_crud("/api/users", Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    deleted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
```

Manual composable API:

```python
from derivelib.adapt import with_soft_delete, with_timestamps

ops = with_soft_delete(ALL_CRUD_OPS, "deleted_at")
ops = with_timestamps(ops, "created_at", "updated_at")
```

Extensible registry:

```python
from derivelib.adapt import default_adaptation

custom = default_adaptation().with_ops_handler(MyCapability, my_handler)
# Use custom adaptation in a Dialect
```

---

### 2.19 `@derive` Decorator

```python
@derive(
    *args: Pattern | Exposure | ExposureT | DerivationT,
)
```

Stores patterns on the class. Returns the original class unchanged.

Accepts:
- `Pattern` — compiled to Derivation at build time
- `Exposure` — direct exposures (added to empty endpoint)
- `ExposureT` — post-processing transform on materialized exposures
- `DerivationT` — step-level transform

```python
@derive(
    http_crud("/api/users", Users),        # Pattern
    cli_crud("user", Users),               # Pattern
    health_exposure,                        # Exposure
)
@dataclass
class User: ...
```

---

### 2.20 Application Builders

```python
# From @derive-decorated entities
app = build_application_from_decorated(User, Post, Comment)

# Explicit entity-pattern pairs
app = build_application(
    (User, http_crud("/api/users", Users)),
    (Post, http_crud("/api/posts", Posts)),
)

# Single endpoint
endpoint = build_endpoint(User, http_crud("/api/users", Users))

# Derive endpoints without building Application
endpoints = derive_endpoints(User, http_crud("/api/users", Users))
endpoints = derive_from_decorated(User, Post)
```

---

### 2.21 Axis Steps

#### Schema steps (`derivelib.axes.schema`)

| Step | Constructor | Effect |
|---|---|---|
| `InspectEntity` | `inspect_entity()` | Ensure fields inspected (no-op, explicit docs) |
| `RequireIdentity` | `require_identity()` | Validate Identity field exists |
| `ExcludeFields` | `exclude_fields("a", "b")` | Remove fields from schema ctx |
| `RequireFields` | `require_fields("name")` | Validate specific fields exist |

#### Query steps (`derivelib.axes.query`)

| Step | Constructor | Effect |
|---|---|---|
| `BindProvider` | `bind_provider(NodeType)` | Set provider_node for compose |
| `SetBaseQuery` | `base_query()` | Set `relational(entity)` as base query |
| `SetCustomBaseQuery` | `custom_base_query(factory)` | Custom query factory |

#### Surface steps (`derivelib.axes.surface`)

| Step | Constructor | Effect |
|---|---|---|
| `DeriveOp` | `derive_op(...)` | Derive operation from schema + projections |
| `ExposeOp` | `expose_op(...)` | Wire existing op/handler (no derivation) |
| `AddGlobalCap` | `add_global_cap(cap)` | Add capability to all exposures |

---

### 2.22 Codegen

Type generation infrastructure:

```python
# Plain dataclass
create_dataclass("UserGetOp", [("id", int)], frozen=True)

# Request type with to_domain() baked in
create_request_type("GetUserRequest", [("id", int)], op_type=UserGetOp)

# Response type with from_domain() baked in
create_response_type("GetUserResponse", [("id", int), ("name", str)], converter=my_converter)

# Handler annotation for emergent.ops runner
annotated_handler = annotate_handler(handler, op_type)
```

---

### 2.23 ExposureBuilder

Declarative API for building operations inside custom patterns (bypasses DeriveOp/fold):

```python
op_type, handler, exposure = (
    exposure("create", Order)
    .request(customer=str, total=float)
    .response(id=int, state=str)
    .handler(my_handler)
    .trigger(HTTPRouteTrigger("POST", "/orders"))
    .caps(AuthCap())
    .response_converter(dict_converter)
    .build()
)
```

Use with `SurfaceCtx.add_exposure()`:

```python
def derive_surface(self, ctx: SurfaceCtx) -> SurfaceCtx:
    return ctx.add_exposure(
        exposure("create", entity)
        .request(**fields).response(**resp_fields)
        .handler(handler).trigger(trigger)
    )
```

---

### 2.24 Query Helpers

Generic identity-based query utilities:

```python
filter_by_identity(query, op, id_names)    # chain identity filters
identity_values(op, id_names)              # extract id values (scalar or dict)
scoped_query(base, op, scope_fields)       # apply scope filters
identity_query(base, op, scope, id_names)  # scope + identity filters
not_found_error(entity_name, op, id_names) # Error(NotFound(...))
fetch_by_identity(provider, entity, op, id_names)  # build query, fetch one
serialize_op_fields(op, field_names)       # JSON-serialize op fields
provider_field(node_type)                  # Annotated provider field
id_path(id_names)                          # URL path segment: "{id}" or "{a}/{b}"
```

---

### 2.25 Domain Errors

```python
@dataclass(frozen=True, slots=True)
class NotFound:
    entity: str
    id: Any
    def to_problem(self) -> ProblemDetail: ...

@dataclass(frozen=True, slots=True)
class AlreadyExists:
    entity: str
    id: Any
    def to_problem(self) -> ProblemDetail: ...

@dataclass(frozen=True, slots=True)
class InvalidData:
    entity: str
    reason: str
    def to_problem(self) -> ProblemDetail: ...

# ProblemDetail follows RFC 7807
@dataclass(frozen=True, slots=True)
class ProblemDetail:
    type: str
    title: str
    status: int
    detail: str
    instance: str = ""

DomainError = NotFound | AlreadyExists | InvalidData
```

---

### 2.26 Explain (`_explain.py`)

Self-description of derivation pipelines. Two layers: dict-returning (structured data for tools/analysis) and human-readable (formatted strings).

Shows the **derivation plan** before materialization: what patterns are attached, what steps they produce, what OpSpecs are accumulated.

#### API

```python
type DeriveExplainHandler = Callable[[Step], dict[str, Any]]

# Dict layer
opspec_dict(spec: OpSpec) -> dict[str, Any]
step_dict(step: Step, handlers=DERIVE_EXPLAIN) -> dict[str, Any]
derivation_dict(steps: Derivation, handlers=DERIVE_EXPLAIN) -> dict[str, Any]
entity_derivation_dict(entity: type, handlers=DERIVE_EXPLAIN) -> dict[str, Any]
dialect_dict(d: Dialect) -> dict[str, Any]

# Human-readable layer
explain_opspec(spec: OpSpec) -> str
explain_derivation(steps: Derivation, handlers=DERIVE_EXPLAIN) -> str
explain_entity(entity: type, handlers=DERIVE_EXPLAIN) -> str

# Pre-built handler mapping
DERIVE_EXPLAIN: Mapping[type, DeriveExplainHandler]
# Handles: InspectEntity, RequireIdentity, ExcludeSchemaFields, RequireFields,
#          BindProvider, SetBaseQuery, SetCustomBaseQuery,
#          DeriveOp, ExposeOp, AddGlobalCap, AdaptBaseQuery
```

Open-world: unknown step types get generic `_dataclass_dict` fallback (type name + scalar fields). Extend via custom `handlers` mapping.

#### `entity_derivation_dict`

Compiles each pattern, folds through axes, shows full pipeline:

```python
data = entity_derivation_dict(User)
data["entity"]         # "User"
data["pattern_count"]  # 1
data["patterns"][0]["pattern_type"]  # "Dialect"
data["patterns"][0]["step_count"]    # 10
data["patterns"][0]["steps"]         # list of step dicts
data["patterns"][0]["specs"]         # list of OpSpec dicts
data["patterns"][0]["provider_node"] # "UserProvider"
```

#### `dialect_dict`

Shows Op descriptors + trigger configuration:

```python
data = dialect_dict(http_crud("/api/users", Users))
data["type"]       # "Dialect"
data["op_count"]   # 5
data["triggers"]   # "HTTPTriggers"
data["adapt"]      # True
data["ops"]        # list of op dicts with name, input_proj, output, effects
```

#### Human-readable output

```python
from derivelib import explain_entity

print(explain_entity(User))
```

```
=== User Derivation ===
  1 pattern

  Pattern #1: Dialect, provider=Users
    Steps (11):
      1. InspectEntity
      2. RequireIdentity
      3. BindProvider(node=Users)
      4. SetBaseQuery
      5. AdaptBaseQuery
      6. DeriveOp "List" -> GET /api/users
         effects: Read, Pageable, Sortable
      7. DeriveOp "Get" -> GET /api/users/{id}
         effects: Read, Idempotent, Cacheable
      8. DeriveOp "Create" -> POST /api/users
         effects: Creates
      9. DeriveOp "Update" -> PUT /api/users/{id}
         effects: Updates, Idempotent
     10. DeriveOp "Patch" -> PATCH /api/users/{id}
         effects: Updates, Idempotent
     11. DeriveOp "Delete" -> DELETE /api/users/{id}
         effects: Deletes, Idempotent
    OpSpecs (6):
      List: ListUserRequest -> ListUserResponse [GET /api/users]
      Get: GetUserRequest -> GetUserResponse [GET /api/users/{id}]
      Create: CreateUserRequest -> CreateUserResponse [POST /api/users]
      Update: UpdateUserRequest -> UpdateUserResponse [PUT /api/users/{id}]
      Patch: PatchUserRequest -> PatchUserResponse [PATCH /api/users/{id}]
      Delete: DeleteUserRequest -> DeleteUserResponse [DELETE /api/users/{id}]
```

#### Extending with custom handlers

```python
from derivelib import DERIVE_EXPLAIN, step_dict

@dataclass(frozen=True)
class CustomStep:
    url: str

def custom_handler(step: object) -> dict:
    return {"type": "Custom", "url": getattr(step, "url", "")}

# Merge with built-in handlers
handlers = {**dict(DERIVE_EXPLAIN.items()), CustomStep: custom_handler}
d = step_dict(CustomStep("http://example.com"), handlers=handlers)
# {"type": "Custom", "url": "http://example.com"}
```

---

## Part III: Cookbook

### 4 levels of wiring

derivelib offers a spectrum from fully derived to fully manual. Choose the level that fits.

#### Level 1: Pure Algebra (CRUD)

One dataclass, one decorator → full API. The schema drives everything.

```python
@derive(http_crud("/api/users", provider_node=Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: str
```

**You write:** entity fields + pattern choice.
**Derived:** request/response types, handlers, routes, OpenAPI, error handling.
**Best for:** standard CRUD resources, admin panels, prototyping.

#### Level 2: Algebra + Methods (Bounties)

Derive the boring parts. Write the interesting domain logic by hand.

```python
@derive(
    http_crud("/bounties", provider_node=BountyBoard, ops=(LIST, GET, BOUNTY_CREATE)),
    methods,
)
@dataclass
class Bounty:
    id: Annotated[int, Identity]
    title: str
    reward: int
    status: str = "open"
    hunter: str | None = None

    @post("/bounties/{bounty_id}/claim")
    async def claim(self, db: ..., bounty_id: int, hunter: str) -> Result[Bounty, DomainError]:
        ...  # domain logic

    @post("/bounties/{bounty_id}/complete")
    async def complete(self, db: ..., bounty_id: int) -> Result[Bounty, DomainError]:
        ...  # domain logic
```

**You write:** entity + domain methods. CRUD ops are derived, domain ops are explicit.
**Best for:** entities with both CRUD and custom behavior (state machines, workflows, actions).

#### Level 3: Pure Methods (Service)

Full control over every endpoint. No schema derivation — you write methods, derivelib wires them.

```python
@derive(methods)
@dataclass
class OrderService:
    @post("/api/orders")
    async def create(self, db: ..., customer: str, total: float) -> Result[int, DomainError]:
        ...

    @get("/api/orders")
    async def list_all(self, db: ...) -> Result[list[Order], DomainError]:
        ...
```

**You write:** every method, every trigger, every parameter.
**Derived:** request/response types, route registration, error handling, DI wiring.
**Best for:** services with non-CRUD logic, RPC-style APIs, domain services.

#### Level 4: Pure Wire (Roulette)

No derivelib at all. Write wire IR directly — endpoints, exposures, triggers, runners.

```python
from emergent.wire.axis.surface import endpoint, Application

ep = (
    endpoint(runner)
    .expose(HTTPTrigger("POST", "/login"))
    .expose(CLITrigger("login"))
    .expose(TGTrigger())
)
app = Application(endpoints=[ep, ...])
```

**You write:** everything — op types, request/response types, handlers, triggers, codecs.
**Best for:** multi-target apps (HTTP + CLI + Telegram), custom protocols, maximum control.

#### Choosing the right level

| Level | Boilerplate | Control | Schema-driven |
|---|---|---|---|
| 1. Pure Algebra | Minimal | Pattern-level | Yes |
| 2. Algebra + Methods | Low | Per-method for domain ops | Hybrid |
| 3. Pure Methods | Medium | Per-method for all ops | No |
| 4. Pure Wire | Maximum | Total | No |

Levels compose: a single `@derive(...)` can stack CRUD + methods patterns. Each level uses the same compilation pipeline and target compilers.

---

### Building a custom pattern

**RPC pattern** — expose async methods as POST endpoints:

```python
@dataclass(frozen=True, slots=True)
class ExposeMethod:
    service: type
    method_name: str
    base_path: str

    def derive_surface(self, ctx: SurfaceCtx) -> SurfaceCtx:
        method = getattr(self.service, self.method_name)
        hints = get_type_hints(method, include_extras=True)
        sig = inspect.signature(method)

        fields = {n: hints.get(n, Any) for n in sig.parameters if n != "self"}
        params = [n for n in sig.parameters if n != "self"]

        async def handler(op):
            return await method(**{n: getattr(op, n) for n in params})

        return ctx.add_exposure(
            exposure(method_name, service)
            .request(**fields).response(result=return_type)
            .handler(handler).trigger(HTTPRouteTrigger("POST", f"{base_path}/{method_name}"))
        )

@dataclass(frozen=True, slots=True)
class MethodsPattern:
    base_path: str

    def compile(self, entity: type) -> Derivation:
        steps = [inspect_entity()]
        for name in dir(entity):
            if not name.startswith("_") and inspect.iscoroutinefunction(getattr(entity, name)):
                steps.append(ExposeMethod(entity, name, self.base_path))
        return tuple(steps)

# Usage
@derive(MethodsPattern("/math"))
@dataclass
class MathService:
    @staticmethod
    async def add(a: float, b: float) -> Result[float, str]:
        return Ok(a + b)
```

### Building a custom dialect

**Task queue** — 3 ops with a custom handler:

```python
def http_task_queue(path, provider_node, processor):
    return dialect(
        Op("Create", required_non_id(), entity_response(),
           SubmitAndProcess(processor), effects=(Mutation(), Creates())),
        Op("Get", id_only(), entity_response(),
           FetchOneById(), effects=(Read(), Idempotent())),
        Op("List", no_fields(), list_response(),
           FetchMany(), effects=(Read(),)),
        triggers=HTTPTriggers(path),
        provider_node=provider_node,
    )

@derive(http_task_queue("/tasks", Tasks, processor=resize_image))
@dataclass
class ImageResize:
    id: Annotated[int, Identity]
    url: str
    width: int
    height: int
    status: str = "pending"
    result: str = ""
    error: str = ""
```

### Building a workflow pattern

**State machine** from transition map:

```python
@dataclass(frozen=True, slots=True)
class Transition:
    name: str
    from_states: tuple[str, ...]
    to_state: str

@dataclass(frozen=True, slots=True)
class WorkflowPattern:
    base_path: str
    provider_node: type
    state_field: str
    transitions: tuple[Transition, ...]

    def compile(self, entity: type) -> Derivation:
        return (
            inspect_entity(), require_identity(),
            WorkflowCreateStep(self.base_path, self.state_field, "draft", self.provider_node),
            *(TransitionStep(self.base_path, tr, self.state_field, self.provider_node)
              for tr in self.transitions),
        )

@derive(WorkflowPattern(
    "/orders", provider_node=Orders, state_field="status",
    transitions=(
        Transition("submit",  ("draft",), "pending"),
        Transition("approve", ("pending",), "approved"),
        Transition("ship",    ("approved",), "shipped"),
    ),
))
@dataclass
class Order:
    id: Annotated[int, Identity]
    customer: str
    amount: float
    status: str = "draft"
```

### Custom codec

**SSE streaming** — custom op with `codec_factory`:

```python
STREAM = Op(
    "Stream",
    no_fields(),
    entity_response(),
    FetchMany(),
    effects=(Read(), Streams()),
    codec_factory=sse,  # custom codec instead of rrc
)

@derive(EventStreamAPI("/sensors", provider_node=Sensors))
@dataclass
class Sensor:
    id: Annotated[int, Identity]
    name: str
    value: float
```

### Custom effect end-to-end

```python
# 1. Define effect
@dataclass(frozen=True, slots=True)
class MindBorn(DerivationEffect):
    """A new mind emerges after this operation."""

# 2. Put on an op
CREATE_MIND = Op(
    "Create", required_non_id(), entity_response(),
    InsertNew(),
    effects=(Mutation(), Creates(), MindBorn()),
)

# 3. Build transform
def on_mind_born(callback) -> DerivationT:
    def _wrap(_eff, op):
        return replace(op, handler_template=wrap_template(
            op.handler_template,
            lambda inner, spec: _after(inner, callback),
        ))
    return map_by_effect({MindBorn: _wrap})

# 4. Use
@derive(
    dialect(CREATE_MIND, GET, LIST,
        triggers=HTTPTriggers("/api/minds"),
        provider_node=Minds,
    ).chain(on_mind_born(celebrate))
)
@dataclass
class Mind:
    id: Annotated[int, Identity]
    name: str
```

### Multi-target

One entity, every target:

```python
@derive(
    http_crud("/products", provider_node=Store),
    cli_crud("product", provider_node=Store),
)
@dataclass
class Product:
    id: Annotated[int, Identity]
    name: str
    price: float
```

Compile to HTTP:
```python
fastapi_app = targets.fastapi.compile(app)
```

Compile to CLI:
```python
parser = targets.cli.cli_compile(app, prog="shop")
targets.cli.cli_run(parser, sys.argv[1:])
```

### CRUD + Methods hybrid

Derive the CRUD, write the domain logic:

```python
from derivelib import derive, build_application_from_decorated, memory_node, fields
from derivelib.patterns.crud import http_crud, LIST, GET, CREATE
from derivelib.patterns.methods import methods, post

BountyBoard = memory_node()
BOUNTY_CREATE = replace(CREATE, input_proj=fields("title", "reward"))

@derive(
    http_crud("/bounties", provider_node=BountyBoard, ops=(LIST, GET, BOUNTY_CREATE)),
    methods,
)
@dataclass
class Bounty:
    id: Annotated[int, Identity]
    title: str
    reward: int
    status: str = "open"

    @post("/bounties/{bounty_id}/claim")
    async def claim(
        self,
        db: Annotated[MutatingRelationalProvider[Bounty], compose.Node(BountyBoard)],
        bounty_id: int,
        hunter: str,
    ) -> Result[Bounty, DomainError]:
        bounty = await db.fetch_one(relational(Bounty).filter(lambda b: b.id == bounty_id))
        if bounty is None:
            return Error(InvalidData(entity="Bounty", reason=f"not found"))
        updated = replace(bounty, status="claimed", hunter=hunter)
        await db.update(updated)
        return Ok(updated)
```

5 endpoints: 3 derived (List, Get, Create) + 2 hand-written (claim, complete). Shared provider node, shared error handling.

### Secured methods service

```python
from derivelib.transforms import add_method_capability

@derive(methods.chain(add_method_capability(AuthCap())))
@dataclass
class AdminService:
    @post("/admin/reset")
    async def reset(self, db: ...) -> Result[bool, DomainError]:
        ...

    @get("/admin/stats")
    async def stats(self, db: ...) -> Result[dict, DomainError]:
        ...
```

### Response projection with auth

```python
@derive(
    # Public: LIST + GET + CREATE, response without active_at
    http_crud("/users", provider_node=UserStore, ops=(LIST, GET, CREATE)).chain(
        project_response(exclude=("active_at",))
    ),
    # Authorized: GET with all fields (requires Bearer token)
    http_crud("/users/me", provider_node=UserStore, ops=(GET,)).chain(auth),
)
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, Unique]
    active_at: str | None = None
```

---

## Part IV: Cheatsheet

### Minimal CRUD

```python
from derivelib import derive, build_application_from_decorated
from derivelib.patterns import http_crud

@derive(http_crud("/users", provider_node=Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: str

app = build_application_from_decorated(User)
fastapi_app = targets.fastapi.compile(app)
```

### Methods service

```python
from derivelib import derive, build_application_from_decorated
from derivelib.patterns.methods import methods, post, get

@derive(methods)
@dataclass
class MyService:
    @post("/api/things")
    async def create(self, name: str) -> Result[int, DomainError]:
        return Ok(1)

    @get("/api/things")
    async def list_all(self) -> Result[list[Thing], DomainError]:
        return Ok([])

app = build_application_from_decorated(MyService)
fastapi_app = targets.fastapi.compile(app)
```

### Common transforms

```python
# Read-only API
http_crud("/users", Users).chain(readonly())

# Paginated list
http_crud("/users", Users).chain(paginated(20))

# No delete
http_crud("/users", Users).chain(without_delete())

# Compose
http_crud("/users", Users).chain(
    readonly(),
    paginated(50),
    add_capability(CORSCap()),
    with_timeout(5.0),
)
```

### Subset of ops

```python
# Only List + Get
http_crud("/users", Users, ops=(LIST, GET))

# Using transform
http_crud("/users", Users).chain(only_ops("List", "Get"))
```

### Provider setup (nodnod node)

```python
from nodnod import scalar_node

@scalar_node
class Users:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider[Any]:
        return MemoryRelationalProvider(key_fn=lambda x: x.id, next_id=SequenceNextId())
```

### Extending ops

```python
# Add auth to mutations
with_caps(ALL_CRUD_OPS, AuthRequired(), effect=Mutation)

# Custom op
SEARCH = Op("Search", fields("query"), list_response(), CustomSearchHandler(),
            effects=(Read(),))
```

### Import map

```python
# Core
from derivelib import derive, build_application_from_decorated
from derivelib import Op, Dialect, dialect, HTTPTriggers, CLITriggers

# Projections
from derivelib import all_fields, id_only, non_id, no_fields, required_non_id
from derivelib import fields, exclude, optional_non_id, merge, exclude_from

# Response specs
from derivelib import entity_response, list_response, ok_response, paginated_response, custom_response

# Effects
from derivelib import Read, Mutation, Creates, Updates, Deletes, Pageable, Sortable, Cacheable

# Handler templates
from derivelib import FetchMany, FetchOneById, InsertNew, UpdateExisting, PatchExisting, DeleteOne

# Protocols
from derivelib import HandlerTemplate, FieldProjection, ResponseSpec, Pattern

# Transforms
from derivelib.transforms import readonly, mutations_only, without_delete, paginated
from derivelib.transforms import add_capability, swap_handler, rename_ops, map_by_effect
from derivelib.transforms import map_methods, add_method_capability

# CRUD pattern
from derivelib.patterns import http_crud, cli_crud, LIST, GET, CREATE, UPDATE, PATCH, DELETE, ALL_CRUD_OPS

# Nested
from derivelib.patterns import nested_http_crud

# Methods pattern
from derivelib.patterns import methods, MethodsPattern, method, post, get, put, delete, patch, command

# Codegen (for custom patterns)
from derivelib import exposure, endpoint_builder, create_dataclass

# Error capabilities
from derivelib import ErrorTransform, ProblemResponse, ERROR_CAPS

# Errors
from derivelib import NotFound, AlreadyExists, InvalidData, ProblemDetail

# Query helpers
from derivelib import filter_by_identity, fetch_by_identity, scoped_query, identity_query
from derivelib import provider_field, id_path

# Explain
from derivelib import (
    explain_entity, explain_derivation, explain_opspec,
    entity_derivation_dict, derivation_dict, opspec_dict, step_dict, dialect_dict,
    DERIVE_EXPLAIN, DeriveExplainHandler,
)
```

### Best practices

1. **Effects over names.** Dispatch on effects (`has_effect(op.effects, Mutation)`), not op names (`op.name == "Create"`). Effects are structural, names are display-only.

2. **Frozen everything.** All custom steps, effects, templates — `@dataclass(frozen=True, slots=True)`. Use `dataclasses.replace()` for modification.

3. **Steps accumulate, materialize builds.** Steps should accumulate descriptions (OpSpec, context data). Don't generate types inside steps.

4. **Transforms compose.** Chain transforms via `Dialect.chain()`. Each transform is `Derivation -> Derivation`. They compose left-to-right.

5. **ExposureBuilder for hand-crafted ops.** Use `exposure("name", entity).request(...).response(...).handler(...).trigger(...).build()` when you need direct control, bypassing the DeriveOp/fold pipeline.

6. **Provider via compose.Node.** Provider fields use `Annotated[T, compose.Node(ProviderNodeType)]` for runtime DI resolution via nodnod.

7. **Custom dialects, not modified CRUD.** Don't hack CRUD ops — build your own dialect from `Op` + `dialect()`. CRUD is just 5 ops; your dialect is N ops with your handler templates.

8. **Open-world extension.** New effects, triggers, handler templates, projections, response specs — all follow the same protocol pattern. No derivelib source modification needed.

9. **Adapt via schema_meta.** Use `@schema_meta(SoftDelete(...))` for automatic adaptation. The adaptation system folds schema capabilities through handler tables — open-world, extensible via `AdaptationDialect.with_ops_handler()`.

10. **scope_fields for nested resources.** Handler templates (`FetchMany`, `FetchOneById`, etc.) accept `scope_fields` to pre-filter queries by parent FK.

11. **Methods for domain logic, CRUD for shape-driven ops.** Use `http_crud` when the entity shape defines the API (list/get/create/update/delete). Use `methods` when the logic is the API (claim, cancel, approve). Stack both on the same entity when you need both.

12. **Methods return `Result[T, E]`.** Every method must return `Result[T, E]`. The `T` becomes the response type. Errors pass through capabilities (`ErrorTransform` → `ProblemResponse` → RFC 7807 JSON). Never raise — always return `Error(...)`.

13. **`ERROR_CAPS` is shared.** Both CRUD and Methods patterns use `ERROR_CAPS = (ErrorTransform(), ProblemResponse())` by default. Custom patterns should reference `ERROR_CAPS` rather than defining their own error handling.
