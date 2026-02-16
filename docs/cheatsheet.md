# emergent.wire + derivelib — Complete Cheatsheet

## Architecture: Sheaf over Compilation Targets

```
program = global section of a sheaf over compilation targets

Wire Application (global section)
        |
   +----+----+
   v    v    v
  CLI  HTTP  TG   <-- fibers (targets)
   |    |    |
   +----+----+
        v
    Execution     <-- shared base
    + Storage
```

One code + N annotations = N targets. Add target = add compiler.

```
wire/
+-- axis/       -- 4 orthogonal composition dimensions
|   +-- surface/   -- WHERE + HOW (endpoints, triggers, codecs)
|   +-- schema/    -- WHAT shape (type annotations -> multi-backend)
|   +-- storage/   -- HOW to persist (KV, queue, pubsub)
|   +-- query/     -- HOW to access (relational, KV, API)
+-- compile/    -- Application -> Framework (OUT)
|   +-- targets/   -- fastapi, cli, telegrinder, pure, testing
+-- bridge/     -- Framework -> Application (IN)
    +-- bridgers/  -- fastapi, asgi extractors
```

Each axis = **Semantic x Physical**:

| Axis | Semantic (Language) | Physical (Target) | Product |
|------|--------------------|--------------------|---------|
| Surface | Codec (execution shape) | Trigger (entry point) | endpoint |
| Storage | Pattern (KV, Queue...) | Backend (Redis, Memory) | store |
| Schema | Dialect (annotations) | Compiler (output) | model |
| Query | Space (Relational, KV) | Provider (SQL, Memory) | store |

---

## 1. Surface Axis — API Surface

### Primitives

```python
from emergent.wire.axis.surface import endpoint, application, empty_runner, Application

app = application()
endp = endpoint(runner).expose(trigger, codec, *capabilities)
app = app.mount(endp1, endp2, ...)
```

### Triggers — WHERE to expose

```python
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger
from emergent.wire.axis.surface.triggers.lifecycle import StartupTrigger, ShutdownTrigger
from emergent.wire.axis.surface.triggers.exception import ExceptionTrigger
from emergent.wire.axis.surface.triggers.websocket import WebSocketTrigger

HTTPRouteTrigger("POST", "/users")
CLITrigger("create-user", "Create a new user")
TelegrindTrigger(Command("start"))
StartupTrigger(order=0)
WebSocketTrigger("/ws")
```

### Codecs — execution shape

```python
from emergent.wire.axis.surface.codecs.rrc import rrc
from emergent.wire.axis.surface.codecs.stateful import stateful, Done, transition
from emergent.wire.axis.surface.codecs.delegate import delegate
from emergent.wire.axis.surface.codecs.immediate import immediate, immediate_factory

# Request/Response — standard
rrc(RegisterRequest, TokenResponse)

# Stateful — multi-turn FSM (state_type + agent_cls)
StatefulCodec(state_type=BettingFlow, agent_cls=EventLoopAgent)

# Delegate — preserve original handler signature
delegate(original_handler, response=MyResponse)

# Immediate — static/factory response (no runner needed)
immediate_factory(lambda: HealthResponse(ok=True))
```

**RRC Protocol contracts:**
```python
class Request:
    def to_domain(self) -> Op: ...     # request -> domain operation

class Response:
    @classmethod
    def from_domain(cls, dom: Result[T, E]) -> Self: ...  # result -> response
```

### Capabilities — modify endpoint behavior

```python
from emergent.wire.axis.surface.capabilities import SurfaceCapability, ScopeEnricher, EnricherNext

# Compile-time transforms
from emergent.wire.axis.surface.transforms import Prefix, StripPrefix
Prefix.of("api", "v1")  # /api/v1 prefix

# HTTP OpenAPI
from emergent.wire.axis.surface.dialects.http import (
    Tag, BearerAuth, ApiKeyAuth, OAuth2Auth,
    Summary, OperationId, Deprecated,
    ResponseStatus, CORS, GZip, TrustedHost,
)

# Enrichers — runtime middleware
from emergent.wire.axis.surface.enrichers import (
    Provide, Inject, Timeout, Retry, RateLimit, Cached, Validate, Transform,
)
```

### Custom ScopeEnricher (real example from roulette)

```python
@dataclass(frozen=True, slots=True)
class Auth(SurfaceCapability, ScopeEnricher):
    request_cls: type[HasAuth]

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R | AuthErrorResponse:
        req_value = scope.get(self.request_cls)
        if req_value is None:
            return AuthErrorResponse(error="request not in scope")

        req: HasAuth = req_value.value   # CRITICAL: scope.get() returns wrapper
        auth_op = req.to_auth()
        result = await auth_runner.run(auth_op)
        match result:
            case Ok(user):
                scope.inject(AuthUser, user)
                return await call(scope)
            case Error(e):
                return AuthErrorResponse(error=e)
```

### One endpoint, multiple exposures

```python
endpoint(auth_runner)
    .expose(HTTPRouteTrigger("POST", "/register"), rrc(RegisterRequest, TokenResponse))
    .expose(CLITrigger("register", "Register new user"), rrc(RegisterRequest, TokenResponse))
    .expose(TelegrindTrigger(Command("register")), rrc(RegisterRequest, TokenResponse))
```

### Self-description

```python
from emergent.wire.axis.surface import explain_application, application_dict

print(explain_application(app))
data = application_dict(app)  # structured dict for tooling
```

---

## 2. Schema Axis — Multi-Dialect Annotations

### Universal capabilities (ALL compilers understand)

```python
from emergent.wire.axis.schema import (
    # Identity & Constraints
    Identity, Unique, Nullable, ReadOnly, WriteOnly, Sensitive, Immutable, Computed,
    # Structural
    Ref, Nested, Embedded,
    # Validators
    Min, Max, ExclusiveMin, ExclusiveMax, MultipleOf,
    MinLen, MaxLen, Pattern, OneOf,
    # Documentation
    Doc, Deprecated, Alias,
    # Schema-level
    SchemaName, SchemaDoc, Abstract,
)
```

### Pre-built patterns

```python
from emergent.wire.axis.schema import Id, Email, Slug, Username, Short, Medium
from emergent.wire.axis.schema import RequiredShort, NonNegative, Percentage, Probability

@dataclass
class User:
    id: Annotated[int, *Id]              # Identity
    email: Annotated[str, *Email]        # Unique + MaxLen(255)
    name: Annotated[str, *Short]         # MaxLen(100)
    balance: Annotated[int, *NonNegative] # Min(0)
```

### Dialect-specific annotations

```python
from emergent.wire.axis.schema.dialects import cli, openapi, sql, pydantic, tg, compose

# CLI
cli.Help("Username"), cli.Flag("-v", "--verbose"), cli.Positional(), cli.Choices("a", "b")

# OpenAPI
openapi.Description("User email"), openapi.Format("email"), openapi.Example("alice@example.com")

# SQL
sql.Index(), sql.FullText(), sql.Type("varchar(100)"), sql.ServerDefault("now()"), sql.Check("balance >= 0")

# Pydantic
pydantic.Strict(), pydantic.Coerce(), pydantic.AliasPath("data", "email"), pydantic.Exclude()

# Telegram
tg.CommandArg(), tg.Bold(), tg.Code(), tg.Line(after=True), tg.Skip()
tg.Button(callback="action:{}"), tg.Keyboard(columns=2)

# Compose (nodnod node resolution)
compose.Node(UserProvider), compose.Optional(AdminNode)
compose.Fallback(CachedUser, DBUser), compose.Race(API1, API2)
compose.Retrieve(AuthUser)  # direct scope retrieval
```

### One type, three projections (from roulette)

```python
@dataclass
class RegisterRequest:
    login: Annotated[str, Doc("Login name"), cli.Help("Username"), cli.Positional(), tg.CommandArg()]
    password: Annotated[str, Doc("Password"), cli.Help("Password"), cli.Positional(), tg.CommandArg()]
```

### Schema-level capabilities

```python
from emergent.wire.axis.schema._universal import schema_meta, get_schema_meta
from emergent.wire.axis.schema.dialects.temporal import SoftDelete, Timestamps

@schema_meta(SoftDelete("deleted_at"), Timestamps("created_at", "updated_at"))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    deleted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
```

### Type inspection

```python
from emergent.wire.axis.schema import inspect_type, FieldInfo, first_match
from emergent.wire.axis.schema._inspect import (
    dataclass_inspector, pydantic_inspector, typeddict_inspector, namedtuple_inspector,
    unwrap_optional, unwrap_annotated, inspect_field, is_structured_type, unwrap_collection,
    get_nested_info, get_nested_type,
)

fields = inspect_type(User)  # works for dataclass, Pydantic, TypedDict, NamedTuple
for name, info in fields.items():
    info.base_type        # type
    info.is_optional      # bool
    info.has_default      # bool (replaces info.default)
    info.has(Identity)    # bool
    info.get(MaxLen)      # MaxLen instance or None
    info.universal        # tuple of UniversalCapability
    info.dialect(cli.CLICapability)  # tuple of CLI capabilities (takes type, not string)
```

### Helpers

All navigation helpers take optional `axes` parameter.

```python
from emergent.wire.axis.schema._helpers import (
    get_identity_field, get_required_fields, get_optional_fields,
    partition_fields, field_by_name, field_path_type,
    fields_with_capability, get_refs, fields_by_dialect,
    merge_capabilities, override_capability, remove_capability,
    deduplicate_capabilities, find_capability, find_all_capabilities,
    has_capability, filter_by_dialect, filter_universal,
    compose_schema_meta, get_nested_schema_meta,
)
```

### Self-description

```python
from emergent.wire.axis.schema import explain_schema, schema_dict
print(explain_schema(User))   # human-readable
data = schema_dict(User)      # structured dict
```

---

## 3. Query Axis — Typed Query Building

### Relational space (SQL-like)

```python
from emergent.wire.axis.query import relational, relational_store

q = (relational(User)
    .filter(lambda u: u.active == True)
    .where(lambda u: u.balance > 100)       # alias for filter
    .order_by(lambda u: u.balance.desc())
    .limit(50).offset(10)
    .paginate(page=2, per_page=25)           # convenience for offset + limit
    .select(lambda u: u.name, lambda u: u.email)  # lambdas, not strings
    .distinct()
    .group_by(lambda u: u.department)        # lambdas, not strings
    .having(lambda u: u.count() > 5)
    .aggregate(total=lambda u: u.balance.sum())
    .join(Order, lambda u, o: u.id == o.user_id)        # INNER JOIN
    .left_join(Profile, lambda u, p: u.id == p.user_id)) # LEFT JOIN
```

### KV space (Redis-like)

```python
from emergent.wire.axis.query import kv, kv_store

q = kv(User, key=lambda u: u.id)
q.get("alice"), q.set("alice", user), q.delete("alice")
q.exists("alice"), q.scan("user:*"), q.keys("user:*")
```

### API space (REST-like)

```python
from emergent.wire.axis.query import api

q = (api(User).list()
    .filter(lambda u: u.active)
    .page(1, per_page=20)
    .search("alice")
    .include("orders")
    .order("name"))
```

### Providers — interpreters for query ASTs

```python
# Relational
class RelationalProvider(Protocol[T]):
    async def fetch_one(self, query) -> T | None: ...
    async def fetch_many(self, query) -> list[T]: ...
    async def count(self, query) -> int: ...

class MutatingRelationalProvider(RelationalProvider[T], Protocol):
    async def insert(self, entity) -> T: ...
    async def update(self, entity) -> T: ...
    async def delete(self, entity) -> None: ...

# Built-in
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider, MemoryKVProvider
provider = MemoryRelationalProvider(key_fn=lambda u: u.id, next_id=SequenceNextId())
```

### Store = QuerySet + Provider bundled (recommended)

```python
users = relational_store(User, provider)
result = await users.filter(lambda u: u.balance > 0).fetch_many()
user = await users.filter(lambda u: u.id == 1).first()
await users.insert(User(...))
```

### Expression AST

```python
from emergent.wire.axis.query._expr import (
    Eq, Ne, Lt, Le, Gt, Ge,          # comparison
    And, Or, Not,                      # logical
    In, Contains, StartsWith, EndsWith,# collection
    IsNull, IsNotNull,                 # null
    Between, Like, ILike, Regex,       # range/pattern
    Field, Const,                      # base
)
```

### Query fold (custom interpreters)

```python
from emergent.wire.axis.query._fold import QueryDialect, MEMORY_DIALECT

# Same query, different interpreters
result = MEMORY_DIALECT.fold(q.ops, data)
# sql_result = SQL_DIALECT.fold(q.ops, SQLPlan("users"))
```

### Expression utilities

```python
from emergent.wire.axis.query._serialize import expr_to_dict, expr_from_dict
from emergent.wire.axis.query._simplify import simplify_expr
```

### Self-description

```python
from emergent.wire.axis.query import RELATIONAL_EXPLAIN_DIALECT, format_ops, RELATIONAL_EXPLAIN

q = relational(User).filter(lambda u: u.active == True).order_by(lambda u: u.name).limit(10)
print(format_ops(q.ops, RELATIONAL_EXPLAIN))
# or via dialect:
print(RELATIONAL_EXPLAIN_DIALECT.format(q.ops))
```

---

## 4. Storage Axis — Persistence Capabilities

### Capabilities (the grammar)

```python
from emergent.wire.axis.storage import (
    # KV (Set now takes optional ttl: timedelta)
    Get, Set, Delete, SetWithTTL, SetNX,
    # Batch
    BatchGet, BatchSet, BatchDelete, DeletePattern,
    # Queue
    Push, Pop, Peek, Len,
    # PubSub (generic channel C, Subscribe is sync returning AsyncIterator)
    Publish, Subscribe,
    # Lock (uses timedelta, Extend for TTL renewal)
    Acquire, Release, Extend,
    # Counter (IncrBy for increment by amount)
    Incr, Decr, IncrBy,
)
```

### Patterns (compose capabilities + codec)

```python
from emergent.wire.axis.storage import (
    kv, kv_nx, queue, queue_full, pubsub,
    lock, lock_extend,            # lock_extend adds TTL renewal via Extend
    counter, counter_full,        # counter_full adds incr_by/decr_by
    MemoryStorage, FileStorage,   # MemoryStorage extends BaseTTLStorage
    PickleCodec, JsonCodec, IdentityCodec,
)

# KV store
users = kv(MemoryStorage(), PickleCodec[User]())
await users.set("user:1", user)
match await users.get("user:1"):
    case Ok(Some(user)): ...
    case Ok(Nothing()): ...

# Queue
orders = queue(MemoryStorage(), JsonCodec[Order]())
await orders.push(order)

# PubSub
events = pubsub(MemoryStorage(), JsonCodec[Event]())
await events.publish("channel", event)
```

### Composition

```python
from emergent.wire.axis.storage._compose import prefix_kv, tiered_kv, fallback_kv, readonly_kv

cached = tiered_kv(l1_memory, l2_redis, l1_ttl=300)
prefixed = prefix_kv(inner_kv, "cache:")
safe = readonly_kv(inner_kv)
```

### Self-description

```python
from emergent.wire.axis.storage import explain_storage, storage_dict
print(explain_storage(my_tiered))
```

---

## 5. Compile Module — Application -> Framework

### Targets

```python
from emergent.wire.compile.targets import fastapi, cli, telegrinder
from emergent.wire.compile.targets import pure, testing

# FastAPI
fastapi_app = fastapi.compile(app, axes)

# CLI
parser = cli.compile(app, axes, prog="my-tool")

# Telegram
telegrinder.compile(app, axes)

# Pure (framework-agnostic lifecycle/exception/websocket)
from emergent.wire.compile.targets.pure import (
    STARTUP_COMPILER, SHUTDOWN_COMPILER, EXCEPTION_COMPILER, WEBSOCKET_COMPILER,
    LifecycleRoute, ExceptionRoute, WebSocketRoute, app_scope_lifespan,
)

# Testing (no framework needed)
routes = testing.testing_compile(app, axes)
result = await routes[0].call(fields={"name": "Alice"}, inject={AuthUser: user})

async with testing.TestApp(app, axes) as test_app:
    result = await test_app.call("POST /users", fields={...})
```

### Axes (explicit, no global state)

```python
from emergent.wire.compile import Axes

axes = Axes.default()           # standard inspection
axes = Axes.traced()            # with compilation tracing
axes = Axes(schema=my_inspector, scope_layer=my_layer)  # custom
```

### Lifetime (scope tiers)

```python
from emergent.wire.compile._lifetime import Tier, App, Request, ScopeLayer
from types import MappingProxyType

App = Tier()                # application-scoped
Request = Tier(parent=App)  # request-scoped

# Standard 2-tier:
layer = ScopeLayer(
    scopes=MappingProxyType({App: app_scope}),
    family=my_family,
    leaf=Request,
)
layer.parent   # -> app_scope (walks leaf.parent chain)
layer.compose  # -> family.types_for(Request)

# Custom tiers — arbitrary depth:
Session = Tier(parent=App)
layer.with_scope(Session, session_scope)  # add tier at runtime
```

### Type generation

```python
from emergent.wire.compile._generate import to_pydantic, to_argparse_args, to_telegram_fields
from emergent.wire.compile._schema import to_openapi_schema, to_json_schema

Model = to_pydantic(User, axes)
args = to_argparse_args(RegisterRequest, axes)
schema = to_openapi_schema(User, axes)
```

### Compilation tracing

```python
axes = Axes.traced()
Model = to_pydantic(User, axes)
fastapi_app = fastapi.compile(app, axes)

from emergent.wire.compile._explain import explain, explain_field
print(explain(axes))           # full trace
print(explain_field(axes, "email"))  # single field
```

### Compilation phases

```python
from emergent.wire.compile._phase import (
    PYDANTIC_PHASE, OPENAPI_PHASE, ARGPARSE_PHASE,
    REQUEST_BUILD_PHASE, TG_INPUT_PHASE, TG_RENDER_PHASE,
)
```

### Open-world codec dispatch (TargetCompiler)

```python
from emergent.wire.compile._target import TargetCompiler, CodecAdapter

# Each target defines: trigger_type + codec adapters
# FASTAPI_COMPILER handles: RRC, Stateful, Immediate, ImmediateFactory, Delegate
```

---

## 6. Bridge Module — Framework -> Application

Symmetric to compile: `bridge: Framework -> Application`

### Basic usage

```python
from emergent.wire.bridge import build_application
from emergent.wire.bridge.bridgers import fastapi

# Auto-detect framework
wire_app = build_application(fastapi_app)

# With capabilities
wire_app = fastapi.extract(
    fastapi_app,
    capabilities=(
        WrapAsDelegate(),
        IsolateGlobal(module_path="myapp.main", attr_name="_db", factory=create_db),
        AddTrigger(trigger_type=CLITrigger, builder=build_cli_trigger),
    ),
)
```

### Bridge capabilities

```python
from emergent.wire.bridge import (
    # BridgeCompilable — modify extraction context
    SkipDeprecated, SkipByName, IncludeOnlyByName,
    AddCapability, SetCodecByName, SetRequestTypeByName,

    # Purifiers — wrap handlers
    WrapAsync, CatchErrors,
    IsolateGlobal, IsolateGlobalAsync,  # async variant
    SetGlobal,
    InjectKwarg, InjectKwargAsync,
    WithContext, WithContextSync,        # sync variant
    SetupTeardown,
    WrapAsDelegate,

    # Trigger injection — key to cross-compilation
    AddTrigger,
)

# Pre-built patterns
from emergent.wire.bridge._patterns import (
    SKIP_DEPRECATED, SKIP_PRIVATE, SKIP_INTERNAL,
    ASYNC_ALL, DELEGATE_ALL, CLEAN,
    fastapi_default, fastapi_with_depends,
)
```

### Cross-compilation pattern (from cross_compile example)

```python
# Legacy FastAPI app -> CLI via bridge
wire_app = fastapi.extract(
    legacy_app,
    capabilities=(
        WrapAsDelegate(),
        IsolateGlobal(module_path="legacy.app", attr_name="_notes", factory=create_notes),
        AddTrigger(trigger_type=CLITrigger, builder=build_cli_trigger),
    ),
)

# Add native CLI commands
wire_app = wire_app.mount(
    endpoint(empty_runner()).expose(
        CLITrigger("state", "Show storage state"),
        immediate_factory(lambda: StateResponse(data=get_state())),
    ),
)

# Compile
cli_parser = cli.compile(wire_app, prog="notes-cli")
```

---

## 7. derivelib — Algebraic Derivation System

**Not a CRUD generator.** CRUD = one dialect. The machinery = generic algebraic derivation over wire's 4-axis sheaf.

### Core types

```python
type Step = Any               # object implementing derive_* methods
type Derivation = tuple[Step, ...]
type DerivationT = Callable[[Derivation], Derivation]
```

### The pipeline

```
entity + @derive(pattern)
    |
pattern.compile(entity) -> Derivation (tuple of steps)
    |
fold_derive(steps, entity) -> DerivationCtx
    |
materialize(ctx) -> Endpoint
    |
build_application_from_decorated -> Application
    |
targets.fastapi.compile(app)  /  targets.cli.compile(app)
```

### Two-pass fold

```
Pass 1:  Schema    -- inspect entity fields, validate constraints
Pass 2:  Query -> Storage -> Surface  (sequential, each sees prior results)
```

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

### CRUD Ops

```python
from derivelib.patterns import LIST, GET, CREATE, UPDATE, PATCH, DELETE, ALL_CRUD_OPS

LIST   = Op("List",   no_fields(),  list_response(),   FetchMany())
GET    = Op("Get",    id_only(),    entity_response(),  FetchOneById())
CREATE = Op("Create", non_id(),     entity_response(),  InsertNew())
UPDATE = Op("Update", all_fields(), entity_response(),  UpdateExisting())
PATCH  = Op("Patch",  merge(id_only(), optional_non_id()), entity_response(), PatchExisting())
DELETE = Op("Delete", id_only(),    ok_response(),      DeleteOne())
```

### Field projections

| Constructor | Selects |
|---|---|
| `all_fields()` | All entity fields |
| `id_only()` | Identity fields only |
| `non_id()` | Everything except identity |
| `required_non_id()` | Non-id fields without defaults |
| `no_fields()` | Empty (no input) |
| `fields("name", "email")` | Named fields only |
| `exclude("secret")` | All except named |
| `optional_non_id()` | Non-id fields, all Optional |
| `merge(id_only(), optional_non_id())` | Union of two projections |
| `exclude_from(non_id(), "ts")` | Wrap projection, exclude fields |

### Response specs

| Constructor | Shape |
|---|---|
| `entity_response()` | Mirrors entity fields |
| `list_response()` | `{items: list[Entity]}` |
| `ok_response()` | `{success: bool}` |
| `paginated_response()` | `{items, total, page, page_size}` |
| `count_response()` | `{count: int}` |
| `empty_response()` | `{success: bool}` (204 semantics) |
| `cursor_paginated_response()` | `{items, next_cursor, has_more}` |
| `custom_response(fields, converter)` | Explicit fields + converter |

### Effects

```python
from derivelib import Read, Mutation, Creates, Updates, Deletes, Pageable, Sortable, Cacheable, Idempotent
from derivelib._effects import has_effect, get_effect, DerivationEffect

# Creates/Updates/Deletes extend Mutation
# So has_effect(effects, Mutation) matches them automatically
```

### Handler templates

| Template | Use | Behavior |
|---|---|---|
| `FetchMany(scope_fields=())` | List | `provider.fetch_many(query)` |
| `FetchOneById(scope_fields=())` | Get | `provider.fetch_one(filter_by_identity)` |
| `InsertNew()` | Create | Construct entity, `provider.insert()` |
| `UpdateExisting(scope_fields=())` | Update | Find by id, merge ALL fields |
| `PatchExisting(scope_fields=())` | Patch | Find by id, merge only non-None fields |
| `DeleteOne(scope_fields=())` | Delete | Find by id, `provider.delete()` |
| `PaginatedFetchMany(page_size=20)` | Paginated | `provider.count() + paginate()` |

### TriggerGen — map (entity, Op) -> Trigger

```python
from derivelib import HTTPTriggers, CLITriggers

HTTPTriggers("/api/users")  # REST routes
CLITriggers("user")         # user-list, user-get, user-create, ...
```

### Dialect — generic pattern

```python
from derivelib import dialect, Dialect

my_dialect = dialect(
    LIST, GET, CREATE,
    triggers=HTTPTriggers("/api/users"),
    provider_node=Users,
)
```

### Transforms (DerivationT)

```python
from derivelib.transforms import (
    readonly, mutations_only, without_delete,
    without_ops, only_ops,
    add_capability, paginated, sorted_list,
    project_response, swap_handler, rename_ops,
    map_by_effect, reject_by_effect, select_by_effect,
    wrap_by_effect, map_all_ops,
    with_timeout, with_retry, with_rate_limit,
)

# Compose via .chain()
http_crud("/users", Users).chain(
    readonly(),
    paginated(50),
    add_capability(CORSCap()),
    project_response(exclude=("secret",)),
)
```

### Subset of ops

```python
# Via constructor
http_crud("/users", Users, ops=(LIST, GET))

# Via transform
http_crud("/users", Users).chain(only_ops("List", "Get"))
```

### Nested CRUD

```python
from derivelib.patterns import nested_http_crud

@derive(nested_http_crud("/users", parent=User, provider_node=Posts))
@dataclass
class Post:
    id: Annotated[int, Identity]
    user_id: Annotated[int, Ref(User)]
    title: str
    body: str
# -> GET/POST /users/{user_id}/posts, GET/PUT/DELETE /users/{user_id}/posts/{id}
```

### Multi-target

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

### Adaptation (auto-adapt from schema_meta)

```python
from emergent.wire.axis.schema._universal import schema_meta
from emergent.wire.axis.schema.dialects.temporal import SoftDelete, Timestamps

@schema_meta(SoftDelete("deleted_at"), Timestamps("created_at", "updated_at"))
@derive(http_crud("/users", Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    deleted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
# Delete -> SoftDeleteMark, Create -> auto-set timestamps, base query filters deleted_at IS NULL
```

### Op-level transforms

```python
from derivelib import with_caps, select_ops, exclude_ops, by_effect

with_caps(ALL_CRUD_OPS, AuthRequired(), effect=Mutation)  # auth only for mutations
select_ops(ALL_CRUD_OPS, "List", "Get")
exclude_ops(ALL_CRUD_OPS, "Delete")
by_effect(ALL_CRUD_OPS, Mutation)
```

### Custom Op

```python
SEARCH = Op(
    "Search",
    fields("query"),
    list_response(),
    CustomSearchHandler(),
    effects=(Read(),),
)
```

### Custom handler template

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

### Custom pattern (RPC)

```python
@dataclass(frozen=True, slots=True)
class MethodsPattern:
    base_path: str

    def compile(self, entity: type) -> Derivation:
        steps = [inspect_entity()]
        for name in dir(entity):
            if not name.startswith("_") and inspect.iscoroutinefunction(getattr(entity, name)):
                steps.append(ExposeMethod(entity, name, self.base_path))
        return tuple(steps)
```

### Custom effect end-to-end

```python
# 1. Define
@dataclass(frozen=True, slots=True)
class Auditable(DerivationEffect):
    level: str = "info"

# 2. Check
has_effect(op.effects, Auditable)   # bool
get_effect(op.effects, Auditable)   # instance or None

# 3. Transform
def audit_mutations() -> DerivationT:
    return map_by_effect({
        Mutation: lambda _eff, op: replace(op, capabilities=(*op.capabilities, AuditCap()))
    })
```

### ExposureBuilder — bypass fold for hand-crafted ops

```python
from derivelib import exposure

op_type, handler, exp = (
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

### Application builders

```python
from derivelib import (
    build_application_from_decorated,  # from @derive entities
    build_application,                  # explicit (entity, pattern) pairs
    build_endpoint,                     # single endpoint
    derive_endpoints,                   # endpoints without Application
    derive_from_decorated,              # derive without building Application
)
```

### Self-description

```python
from derivelib import explain_entity, entity_derivation_dict, dialect_dict

print(explain_entity(User))
data = entity_derivation_dict(User)
data = dialect_dict(http_crud("/users", Users))
```

---

## 8. Graph Module (Composer + ScopeFamily)

### Composer — unified nodnod composition

```python
from emergent.graph import Composer

# Create from nodnod scope
composer = Composer.create(scope, agent_cls=EventLoopAgent)

# Compose nodes
ok, value = await composer.compose(MyNode)

# Batch compose
await composer.compose_batch({Node1, Node2, Node3})

# Retrieve from scope (no composition, just lookup)
found, value = composer.retrieve(MyType)

# Resolve handler params via nodnod
params = await composer.resolve_params(handler)

# Create child scope
child = composer.child(detail="request")
```

### ScopeFamily — type→tier mapping

```python
from emergent.graph import ScopeFamily
from emergent.wire.compile._lifetime import App, Request

family = (
    ScopeFamily[Tier]()
    .bind(App, DBPool, Config)
    .bind(Request, CurrentUser, Session)
)

# Compose families
combined = family1 | family2

# Query
family.tier_of(DBPool)              # -> App
family.types_for(Request)           # -> frozenset({CurrentUser, Session})
groups = family.to_groups()         # -> {App: frozenset({...}), Request: frozenset({...})}
scoped = family.materialize(scopes) # -> {DBPool: app_scope, CurrentUser: req_scope, ...}
```

---

## 9. Provider Setup (nodnod)

```python
from nodnod import scalar_node
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
from emergent.wire.axis.query._provider import SequenceNextId

@scalar_node
class Users:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider[Any]:
        return MemoryRelationalProvider(key_fn=lambda x: x.id, next_id=SequenceNextId())
```

---

## 10. Scope API Gotcha

```python
# scope.get(Type) returns a WRAPPER, not the value directly
scope.get(AuthToken)          # -> wrapper object (or None)
scope.get(AuthToken).value    # -> the actual AuthToken instance
scope.get(AuthToken).value.value  # -> the token string (if AuthToken has .value)
```

---

## 11. Import Maps

### wire core

```python
# Surface
from emergent.wire.axis.surface import endpoint, application, empty_runner, Application
from emergent.wire.axis.surface.codecs.rrc import rrc
from emergent.wire.axis.surface.codecs.stateful import stateful, Done
from emergent.wire.axis.surface.codecs.delegate import delegate
from emergent.wire.axis.surface.codecs import immediate_factory
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger
from emergent.wire.axis.surface.capabilities import SurfaceCapability, ScopeEnricher, EnricherNext

# Schema
from emergent.wire.axis.schema import (
    Identity, Unique, Ref, Doc, Min, Max, MinLen, MaxLen, Pattern, OneOf,
    ReadOnly, WriteOnly, Sensitive, Immutable, Nullable, Computed, Alias,
    Nested, Embedded, Deprecated, SchemaName, SchemaDoc, Abstract,
)
from emergent.wire.axis.schema import Id, Email, Slug, Username, Short
from emergent.wire.axis.schema import inspect_type, FieldInfo
from emergent.wire.axis.schema._universal import schema_meta
from emergent.wire.axis.schema.dialects import cli, openapi, sql, pydantic, tg, compose

# Query
from emergent.wire.axis.query import relational, relational_store, kv, kv_store, api
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider, MemoryKVProvider
from emergent.wire.axis.query._provider import SequenceNextId, UuidNextId

# Storage
from emergent.wire.axis.storage import kv as storage_kv, queue, pubsub, lock, lock_extend, counter, counter_full
from emergent.wire.axis.storage import MemoryStorage, FileStorage, PickleCodec, JsonCodec

# Compile
from emergent.wire.compile import Axes
from emergent.wire.compile._lifetime import Tier, App, Request, ScopeLayer
from emergent.wire.compile.targets import fastapi, cli as cli_target, telegrinder
from emergent.wire.compile.targets import pure, testing

# Graph
from emergent.graph import Composer, ScopeFamily, graph, node

# Bridge
from emergent.wire.bridge import build_application, WrapAsDelegate, IsolateGlobal, IsolateGlobalAsync, AddTrigger
from emergent.wire.bridge.bridgers import fastapi as fastapi_bridger
from emergent.wire.bridge._patterns import SKIP_DEPRECATED, CLEAN, fastapi_default
```

### derivelib

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

# Transforms
from derivelib.transforms import readonly, mutations_only, without_delete, paginated
from derivelib.transforms import add_capability, swap_handler, rename_ops, map_by_effect

# CRUD pattern
from derivelib.patterns import http_crud, cli_crud, nested_http_crud
from derivelib.patterns import LIST, GET, CREATE, UPDATE, PATCH, DELETE, ALL_CRUD_OPS

# Errors
from derivelib import NotFound, AlreadyExists, InvalidData, ProblemDetail

# Query helpers
from derivelib import filter_by_identity, fetch_by_identity, provider_field, id_path

# Codegen
from derivelib import exposure, create_dataclass

# Explain
from derivelib import explain_entity, entity_derivation_dict, dialect_dict
```

---

## 12. Best Practices

### Architecture

1. **One code, N annotations, N targets.** Never duplicate logic across targets.
2. **Axes are not independent.** Surface depends on Schema; Query depends on Schema+Storage. The sheaf structure preserves these dependencies.
3. **Capabilities are self-contained compiler plugins.** They transform context via `compile_*()` methods. Compiler just assembles.
4. **No no-op methods.** If a capability has no effect for a target, don't implement that `compile_*()` method.

### Schema axis

5. **Universal for shared, dialect for specific.** Use `Identity`, `Unique`, `MaxLen` for universal constraints. Use `cli.Help`, `openapi.Format`, `sql.Index` for target-specific.
6. **Patterns for common combos.** `Id`, `Email`, `Slug`, `Username` save repetition.
7. **schema_meta for class-level.** `SoftDelete`, `Timestamps`, `SchemaName` go on the class.

### Query axis

8. **Store = QuerySet + Provider.** Use `relational_store()` not raw QuerySet + Provider.
9. **Swap provider for tests.** Same queries, `MemoryRelationalProvider` in tests.
10. **Repository for domain patterns.** Encapsulate soft-delete filters, tenant isolation.
11. **QuerySet for dynamic.** User-driven search/filter -> compose QuerySet directly.

### Surface axis

12. **Codecs are pure types.** Auth, cache, timeout go in capabilities, not codecs.
13. **ScopeEnricher = the middleware pattern.** All cross-cutting concerns as enrichers.
14. **scope.get() returns wrapper.** Always `.value` to unwrap.

### Storage axis

15. **Capabilities compose.** `prefix_kv`, `tiered_kv`, `fallback_kv` build complex stores.
16. **Codecs separate.** `PickleCodec` / `JsonCodec` / `IdentityCodec` independent of backend.

### Compile

17. **Axes passed explicitly.** No global state. `Axes.default()` for production, `Axes.traced()` for debugging.
18. **fold_field is THE primitive.** Every compilation = fold capabilities into context.

### derivelib

19. **Effects over names.** Dispatch on `has_effect(op.effects, Mutation)`, not `op.name == "Create"`.
20. **Frozen everything.** All steps, effects, templates: `@dataclass(frozen=True, slots=True)`.
21. **Steps accumulate, materialize builds.** Steps accumulate OpSpec descriptions. Don't generate types inside steps.
22. **Transforms compose.** `.chain(readonly(), paginated(20), add_capability(CORSCap()))`.
23. **Custom dialects, not modified CRUD.** Build your own from `Op` + `dialect()`.
24. **Open-world extension.** New effects, triggers, templates, projections, response specs — all follow same protocol. No source modification needed.
25. **scope_fields for nested.** Handler templates accept `scope_fields` for parent FK pre-filtering.

### Bridge

26. **Symmetric to compile.** `compile: Application -> Framework`, `bridge: Framework -> Application`.
27. **AddTrigger enables cross-compilation.** Add CLI/TG triggers to bridged endpoints.
28. **Purifiers wrap handlers.** `IsolateGlobal` for symbol rewriting, `WrapAsDelegate` for signature preservation.

### General

29. **Result[T, E] everywhere.** `Ok(value)` / `Error(err)`. Pattern match with `case Ok(...) | Error(...)`.
30. **Self-describing.** Every axis has `explain_*()` functions. Use them for debugging and documentation.

---

## 13. Real-World Pattern: Full Application (roulette)

```python
# 1. Define domain ops
@dataclass
class Register(O.Returning[str, str]):
    login: str
    password: str

# 2. Build runners with DI
auth_runner = (
    O.ops()
    .on(Register, handle_register)
    .on(Login, handle_login)
    .compile()
    .inject(AuthStore, auth_store)
)

# 3. Annotated request types (ONE type, THREE projections)
@dataclass
class RegisterRequest:
    login: Annotated[str, Doc("Login"), cli.Help("Username"), cli.Positional(), tg.CommandArg()]
    password: Annotated[str, Doc("Password"), cli.Help("Password"), cli.Positional(), tg.CommandArg()]
    def to_domain(self) -> Register:
        return Register(login=self.login, password=self.password)

# 4. Build endpoints (ONE endpoint, MULTIPLE exposures)
register_ep = (
    endpoint(auth_runner)
    .expose(HTTPRouteTrigger("POST", "/register"), rrc(RegisterRequest, TokenResponse))
    .expose(CLITrigger("register", "Register"), rrc(RegisterRequest, TokenResponse))
    .expose(TelegrindTrigger(Command("register")), rrc(RegisterRequest, TokenResponse))
)

# 5. Auth enricher for protected endpoints
balance_ep = (
    endpoint(game_runner)
    .expose(HTTPRouteTrigger("GET", "/balance"), rrc(BalanceRequest, BalanceResponse), Auth(BalanceRequest))
)

# 6. Compose application
app = Application().mount(register_ep, balance_ep, ...)

# 7. Compile to ALL targets
axes = Axes.default()
fastapi_app = fastapi.compile(app, axes)
cli_parser = cli.compile(app, axes, prog="roulette")
telegram_dp = telegrinder.compile(app, axes)
```

---

## 14. Real-World Pattern: derivelib CRUD + Transforms

```python
# Full CRUD with auth, pagination, response projection, soft-delete
@schema_meta(SoftDelete("deleted_at"), Timestamps("created_at", "updated_at"))
@derive(
    http_crud("/api/users", provider_node=Users).chain(
        paginated(50),
        add_capability(BearerAuth.jwt(), Mutation),
        project_response(exclude=("deleted_at", "updated_at")),
    ),
    cli_crud("user", provider_node=Users).chain(readonly()),
)
@dataclass
class User:
    id: Annotated[int, Identity]
    name: Annotated[str, MinLen(1), MaxLen(100)]
    email: Annotated[str, Unique, MaxLen(255)]
    deleted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

app = build_application_from_decorated(User)
fastapi_app = targets.fastapi.compile(app)
```
