# emergent.wire — Complete LLM Reference

## Architecture Overview

`emergent.wire` implements a **Sheaf Architecture**: one program definition compiles to multiple targets (FastAPI, CLI, Telegram). The system has three top-level modules:

```
emergent.wire
├── axis/       — 4 orthogonal composition dimensions
│   ├── surface/   — API surface (endpoints, triggers, codecs)
│   ├── schema/    — type annotations → multi-backend models
│   ├── storage/   — data persistence (KV, queue, pubsub)
│   └── query/     — typed query building (relational, KV, API)
├── compile/    — Application → Framework (OUT)
│   └── targets/   — fastapi, cli, telegrinder, pure, testing compilers
└── bridge/     — Framework → Application (IN)
    └── bridgers/  — fastapi, asgi extractors
```

**Core flow:**
```
Annotated dataclass + Capabilities
        ↓ (fold_field)
    Context accumulation
        ↓ (compile)
  Framework artifact (FastAPI app, CLI parser, TG bot)
```

---

## 1. Capability System (`axis/_capability.py`)

The root of the type system. Every annotation is a `Capability`.

### Root Protocol

```python
@runtime_checkable
class Capability(Protocol):
    """Root marker for all axis capabilities."""
    ...
```

### Compilation Contexts (frozen dataclasses)

**Schema axis — field-level:**

| Context | Target | Key fields |
|---------|--------|------------|
| `PydanticContext` | Pydantic FieldInfo | `field_name`, `field_type`, `field_info` |
| `OpenAPIContext` | JSON Schema dict | `field_name`, `field_type`, `schema: JsonSchemaDict` |
| `ArgparseContext` | argparse kwargs | `field_name`, `field_type`, `kwargs`, `is_positional`, `arg_names` |
| `SQLAlchemyContext` | Column config | `field_name`, `field_type`, `column_type`, `column_kwargs` |

**Schema axis — schema-level:**

| Context | Target | Key fields |
|---------|--------|------------|
| `PydanticModelContext` | Model config | `class_name`, `title`, `description`, `is_abstract` |
| `OpenAPISchemaContext` | Schema-level JSON Schema | `class_name`, `schema` |
| `SQLAlchemyTableContext` | Table config | `class_name`, `table_name`, `is_abstract`, `constraints`, `indexes` |

**Surface axis — route-level:**

| Context | Target | Key fields |
|---------|--------|------------|
| `FastAPIRouteContext` | FastAPI route | `path`, `method`, `tags`, `summary`, `description`, `deprecated`, `operation_id`, `security`, `openapi_extra` |
| `TelegrinderHandlerContext` | TG handler | `edit_message`, `answer_callback`, `silent` |
| `CLICommandContext` | CLI command | `name`, `help`, `description`, `epilog` |

**Special contexts:**

| Context | Purpose | Key fields |
|---------|---------|------------|
| `RequestBuildContext` | compose.* dialect field resolution | `field_name`, `field_type`, `compose_node`, `compose_node_default`, `compose_node_map`, `compose_optional_node`, `compose_fallback_nodes`, `compose_race_nodes`, `compose_retrieve_type` |
| `TelegrinderInputContext` | tg.CommandArg parsing | `field_name`, `field_type`, `is_command_arg`, `optional`, `greedy` |
| `TelegrinderRenderContext` | tg.Style/Line rendering | `field_name`, `field_type`, `style`, `style_language`, `line_after`, `line_before`, `skip`, `button_callback`, `button_url`, `keyboard_columns` |

**Application-level:**

| Context | Target | Key fields |
|---------|--------|------------|
| `FastAPIAppContext` | App middleware | `middleware: tuple[tuple[type, Mapping], ...]` |
| `TelegrinderBotContext` | Bot config | `error_handler`, `parse_mode` |
| `CLIAppContext` | CLI app | `prog`, `description`, `epilog` |

### Compilation Protocols

Each context has a matching protocol with a `compile_*` method:

```python
# Field-level
class PydanticCompilable(Protocol):
    def compile_pydantic(self, ctx: PydanticContext) -> PydanticContext: ...

class OpenAPICompilable(Protocol):
    def compile_openapi(self, ctx: OpenAPIContext) -> OpenAPIContext: ...

class ArgparseCompilable(Protocol):
    def compile_argparse(self, ctx: ArgparseContext) -> ArgparseContext: ...

class SQLAlchemyCompilable(Protocol):
    def compile_sqlalchemy(self, ctx: SQLAlchemyContext) -> SQLAlchemyContext: ...

# Schema-level
class PydanticModelCompilable(Protocol):
    def compile_pydantic_model(self, ctx: PydanticModelContext) -> PydanticModelContext: ...

class OpenAPISchemaCompilable(Protocol):
    def compile_openapi_schema(self, ctx: OpenAPISchemaContext) -> OpenAPISchemaContext: ...

class SQLAlchemyTableCompilable(Protocol):
    def compile_sqlalchemy_table(self, ctx: SQLAlchemyTableContext) -> SQLAlchemyTableContext: ...

# Route-level
class FastAPICompilable(Protocol):
    def compile_fastapi(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext: ...

class TelegrinderCompilable(Protocol):
    def compile_telegrinder(self, ctx: TelegrinderHandlerContext) -> TelegrinderHandlerContext: ...

class CLICompilable(Protocol):
    def compile_cli(self, ctx: CLICommandContext) -> CLICommandContext: ...

# Request build
class RequestBuildCompilable(Protocol):
    def compile_request_build(self, ctx: RequestBuildContext) -> RequestBuildContext: ...

# Telegrinder I/O
class TelegrinderInputCompilable(Protocol):
    def compile_telegrinder_input(self, ctx: TelegrinderInputContext) -> TelegrinderInputContext: ...

class TelegrinderRenderCompilable(Protocol):
    def compile_telegrinder_render(self, ctx: TelegrinderRenderContext) -> TelegrinderRenderContext: ...

# Application-level
class FastAPIAppCompilable(Protocol):
    def compile_fastapi_app(self, ctx: FastAPIAppContext) -> FastAPIAppContext: ...

class TelegrinderBotCompilable(Protocol):
    def compile_telegrinder_bot(self, ctx: TelegrinderBotContext) -> TelegrinderBotContext: ...

class CLIAppCompilable(Protocol):
    def compile_cli_app(self, ctx: CLIAppContext) -> CLIAppContext: ...
```

### Context Helpers

```python
openapi_schema(ctx, **kwargs) -> OpenAPIContext       # merge JSON Schema props
argparse_arg(ctx, **kwargs) -> ArgparseContext         # merge argparse kwargs
sqlalchemy_column(ctx, **kwargs) -> SQLAlchemyContext  # merge Column kwargs
pydantic_model(ctx, *, title=, description=, is_abstract=) -> PydanticModelContext
openapi_schema_level(ctx, **kwargs) -> OpenAPISchemaContext
sqlalchemy_table(ctx, *, table_name=, is_abstract=, add_constraint=, add_index=) -> SQLAlchemyTableContext
fastapi_route(ctx, *, tags=, summary=, description=, deprecated=, operation_id=, security=) -> FastAPIRouteContext
telegrinder_handler(ctx, *, edit_message=, answer_callback=, ...) -> TelegrinderHandlerContext
cli_command(ctx, *, help=, description=, epilog=) -> CLICommandContext
fastapi_app_middleware(ctx, middleware_cls, **kwargs) -> FastAPIAppContext
combine(*caps) -> tuple[Capability, ...]  # syntactic sugar for Annotated
```

---

## 2. Surface Axis (`axis/surface/`)

The visible API boundary. Defines HOW endpoints are exposed.

### Core Types

```python
type Trigger = object   # HTTPRouteTrigger, CLITrigger, TelegrindTrigger, etc.
type Codec = object     # RequestResponseCodec, StatefulCodec, DelegateCodec, etc.

@dataclass(frozen=True, slots=True)
class Exposure:
    trigger: Trigger
    codec: Codec
    capabilities: tuple[SurfaceCapability, ...]

@dataclass(slots=True)
class Endpoint:
    runner: Runner
    exposures: list[Exposure]

    def expose(self, trigger, codec, *capabilities) -> Endpoint: ...

@dataclass(slots=True)
class Application:
    endpoints: list[Endpoint]
    capabilities: tuple[SurfaceCapability, ...]

    def mount(self, *endpoints) -> Application: ...
    def with_capabilities(self, *caps) -> Application: ...
    def merge(self, *others) -> Application: ...
    def __add__(self, other) -> Application: ...

@dataclass(slots=True)
class Handler(Generic[C]):
    codec: C
    runner: Runner
    capabilities: tuple[SurfaceCapability, ...]
```

**Constructors:**
```python
endpoint(runner: Runner) -> Endpoint
application(capabilities=()) -> Application
app_stack() -> AppStack
empty_runner() -> Runner  # for immediate codecs
```

### Scan Functions

```python
scan(app: Application, trigger_type: type, codec: type | None = None) -> list[tuple[Trigger, Handler]]
scan_endpoint(endpoint, trigger_type: type, codec: type | None = None) -> list[tuple[Trigger, Handler]]
scan_stack(stack, trigger_type: type, codec: type | None = None) -> StackView
```

### Codecs (`surface/codecs/`)

**RRC — Request/Response Codec:**
```python
@dataclass(frozen=True, slots=True)
class RequestResponseCodec:
    request: type[ToDomain[Op]]    # has .to_domain() -> Op
    response: type[FromDomain[Result]]  # has .from_domain(result) -> Response

rrc(request, response) -> RequestResponseCodec
```

**Stateful — FSM Conversations:**
```python
@dataclass(frozen=True, slots=True)
class StatefulCodec:
    state_type: type         # dataclass with @transition methods + to_domain
    agent_cls: type[Agent]   # nodnod Agent class (default: EventLoopAgent)

class Done:  # terminal marker — triggers Op execution
    pass

# StateStore protocol
class StateStore(Protocol):
    async def load(self, key: str) -> Result[Any, Any]: ...
    async def save(self, key: str, value: Any) -> Result[None, Any]: ...
    async def delete(self, key: str) -> Result[None, Any]: ...

# Transition resolution uses nodnod scope-based parameter composition
get_transitions(state_cls) -> list[Callable]        # all @transition methods
resolve_transition(transitions, scope, agent_cls)    # first resolvable transition

@transition  # decorator for multi-transport transitions
def http(self, inp: Option[BetInput]) -> Self | Done: ...
```

**Delegate — Preserve Original Handler:**
```python
@dataclass(frozen=True, slots=True)
class DelegateCodec:
    handler: Callable[..., Any]
    response: Option[type]

delegate(handler, response=None) -> DelegateCodec
```

**Immediate — Static/Factory Responses:**
```python
class Producing(Protocol[R_co]):
    @classmethod
    def produce(cls) -> R_co: ...

@dataclass(frozen=True, slots=True)
class ImmediateCodec:
    response: type[Producing[Any]]

@dataclass(frozen=True, slots=True)
class ImmediateFactoryCodec:
    factory: Callable[[], Any]

immediate(response: type[Producing]) -> ImmediateCodec
immediate_factory(factory: Callable[[], R]) -> ImmediateFactoryCodec
```

### Triggers (`surface/triggers/`)

```python
# HTTP
@dataclass(frozen=True, slots=True)
class HTTPRouteTrigger:
    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"]
    path: str
    headers: frozenset[str] = frozenset()

# CLI
@dataclass(frozen=True, slots=True)
class CLITrigger:
    command: str
    description: str = ""

# Telegram
@dataclass(frozen=True, slots=True)
class TelegrindTrigger:
    rules: tuple[ABCRule, ...]   # variadic
    view: str = "message"

# Lifecycle
@dataclass(frozen=True, slots=True)
class StartupTrigger:
    order: int = 0

@dataclass(frozen=True, slots=True)
class ShutdownTrigger:
    order: int = 0

# Exception
@dataclass(frozen=True, slots=True)
class ExceptionTrigger(Generic[E]):
    exception_type: type[E]
    propagate: bool = False

# WebSocket
@dataclass(frozen=True, slots=True)
class WebSocketTrigger:
    path: str
    name: str | None = None
```

### Capabilities (`surface/capabilities/`)

```python
class SurfaceCapability(Capability, Protocol): ...  # base
```

### Enrichers (`surface/enrichers/`)

ScopeEnricher capabilities inject values into the execution scope before handler runs.

### Transforms (`surface/transforms/`)

```python
class TriggerTransform(Generic[T]):
    """Transform triggers (e.g., add path prefix)."""
    def apply_trigger(self, trigger: T) -> T: ...

class HandlerTransform(Protocol):
    def apply_handler(self, handler: Handler) -> Handler: ...

class ResponseTransform(Protocol):
    def apply_response(self, response: object) -> object: ...
```

**HTTP transforms:**
```python
Prefix.of("api", "v1")      # /api/v1 prefix
StripPrefix.of("internal")   # remove prefix
```

### Dialects (`surface/dialects/`)

**HTTP dialect (`http.py`) — route-level and app-level capabilities:**
```python
# Tags
http.Tag.of("users")                    # OpenAPI tag for endpoint grouping
http.Tag.of("users", "User management") # with description

# Security schemes
http.BearerAuth.jwt()                   # JWT bearer token
http.BearerAuth.opaque()                # opaque bearer token
http.ApiKeyAuth.header("X-API-Key")     # API key in header
http.ApiKeyAuth.query("api_key")        # API key in query param
http.OAuth2Auth.authorization_code(     # OAuth2 auth code flow
    authorization_url="...", token_url="...", scopes={...})
http.OAuth2Auth.client_credentials(token_url="...", scopes={...})
http.OAuth2Auth.password(token_url="...", scopes={...})

# Operation metadata
http.Summary.of("List users")           # OpenAPI summary + description
http.OperationId.of("listUsers")        # explicit operationId
http.Deprecated.because("Use v2")       # mark deprecated
http.Deprecated.until("2025-01-01", "Migrating to v2")

# Route configuration
http.ResponseStatus(201)                # default status code
http.ResponseHeader("X-Request-Id", "Unique request ID")
http.ContentType("text/csv")            # response content type

# Application-level middleware (on Application.capabilities)
http.CORS(origins=("*",), allow_methods=("*",))
http.TrustedHost(hosts=("example.com",))
http.GZip(minimum_size=500)
```

**Telegram dialect (`telegram.py`) — telegram-specific surface capabilities:**
```python
# Help metadata (replaces schema-level tg.help for surface)
HelpMeta(description: str, order: int = 100, hidden: bool = False)

# Message delivery modes
EditMessage()       # edit existing message instead of sending new
AnswerCallback(text: str | None = None, show_alert: bool = False, cache_time: int | None = None)
Silent()            # send without notification sound
```

### Explain (`surface/_explain.py`)

Self-description of application topology. Two layers: dict-returning (structured data) and human-readable (formatted strings).

```python
type SurfaceExplainHandler = Callable[[Any], dict[str, Any]]

# Dict layer
exposure_dict(exp, handlers=SURFACE_EXPLAIN) -> dict[str, Any]
endpoint_dict(ep, handlers=SURFACE_EXPLAIN) -> dict[str, Any]
application_dict(app, handlers=SURFACE_EXPLAIN) -> dict[str, Any]

# Human-readable layer
explain_application(app, handlers=SURFACE_EXPLAIN) -> str
explain_endpoint(ep, handlers=SURFACE_EXPLAIN) -> str

# Pre-built handler mapping
SURFACE_EXPLAIN: Mapping[type, SurfaceExplainHandler]
# Handles: HTTPRouteTrigger, CLITrigger, TelegrindTrigger,
#          RequestResponseCodec, StatefulCodec, DelegateCodec,
#          ImmediateCodec, ImmediateFactoryCodec
```

Open-world: unknown trigger/codec/capability types get generic fallback. Extend via custom `handlers` mapping.

**Example:**
```python
from emergent.wire.axis.surface import explain_application, application_dict

data = application_dict(app)    # structured dict
print(explain_application(app)) # human-readable:
# === Application (3 endpoints, 1 global cap) ===
#   global: CORS(origins=('*',))
#
#   Endpoint #1 (2 exposures):
#     [POST /api/v1/players] RequestResponseCodec
#       request: RegisterRequest, response: RegisterResponse
#       caps: RateLimit(rpm=10)
#     [register (cli)] RequestResponseCodec
#       request: RegisterRequest, response: RegisterResponse
```

---

## 3. Schema Axis (`axis/schema/`)

Type annotations that compile to multiple backends via `Annotated`.

### Universal Capabilities

```python
# Identity & Constraints
Identity()         # primary key
Unique()           # unique constraint

# Access Control
ReadOnly()         # read-only field
WriteOnly()        # write-only field
Sensitive()        # masked in repr, write-only, format: password
Immutable()        # settable on create, immutable after
Computed()         # derived/virtual field
Nullable()         # accepts null/None

# Validators
Min(value: int | float)
Max(value: int | float)
ExclusiveMin(value: int | float)
ExclusiveMax(value: int | float)
MultipleOf(value: int | float)
MinLen(value: int)
MaxLen(value: int)
Pattern(regex: str)
OneOf(*values: EnumValue)

# Structural
Ref(target: type | str, on_delete: str = "CASCADE", on_update: str = "CASCADE")
Nested(cascade: str = "all", meta: tuple[SchemaCapability, ...] = ())
Embedded(format: str = "json", meta: tuple[SchemaCapability, ...] = ())

# Documentation & Naming
Doc(text: str)
Deprecated(reason: str | None = None)
Alias(name: str)           # alternative name for serialization/storage
```

### Prebuilt Patterns

```python
Id = (Identity(),)
Email = (Unique(), MaxLen(255))
Slug = (Unique(), MaxLen(100), Pattern(r"^[a-z0-9]+(?:-[a-z0-9]+)*$"))
Username = (Unique(), MinLen(3), MaxLen(50))
Short = (MaxLen(100),)
Medium = (MaxLen(500),)
RequiredShort = (MinLen(1), MaxLen(100))
NonNegative = (Min(0),)
Percentage = (Min(0), Max(100))
Probability = (Min(0), Max(1))
UniqueValue = (Unique(),)
```

**Usage:**
```python
@dataclass
class User:
    id: Annotated[int, *Id]
    email: Annotated[str, *Email, Unique]
    name: Annotated[str, *Short]
```

### Schema-Level Capabilities

```python
SchemaName(value: str)           # override model/table/schema name
SchemaDoc(description: str)      # schema-level description
Abstract()                       # mark schema as abstract (no direct instantiation)

@schema_meta(SchemaName("users"), Timestamps())
@dataclass
class User: ...

get_schema_meta(cls) -> tuple[SchemaCapability, ...]
get_schema_capability(cls, cap_type) -> SchemaCapability | None
```

### Type Inspection

```python
@dataclass(frozen=True, slots=True)
class FieldInfo:
    name: str
    base_type: type
    is_optional: bool
    capabilities: tuple[SchemaAxisCapability, ...]
    has_default: bool = False

    @property
    def universal(self) -> tuple[UniversalCapability, ...]: ...
    def dialect[D: SchemaAxisCapability](self, base: type[D]) -> tuple[D, ...]: ...
    def has(self, cap_type: type[SchemaAxisCapability]) -> bool: ...
    def get[C: SchemaAxisCapability](self, cap_type: type[C]) -> C | None: ...
    def get_all[C: SchemaAxisCapability](self, cap_type: type[C]) -> tuple[C, ...]: ...

# Inspectors
type Inspector = Callable[[type], dict[str, FieldInfo] | None]

inspect_type(cls) -> dict[str, FieldInfo]      # auto-detect (dataclass/Pydantic/TypedDict/NamedTuple)
inspect_dataclass(cls) -> dict[str, FieldInfo]  # dataclass only (alias)
first_match(*inspectors) -> Inspector           # combinator

# Individual inspectors
dataclass_inspector(cls) -> dict[str, FieldInfo] | None
pydantic_inspector(cls) -> dict[str, FieldInfo] | None
typeddict_inspector(cls) -> dict[str, FieldInfo] | None
namedtuple_inspector(cls) -> dict[str, FieldInfo] | None

# Field-level helpers
unwrap_optional(type_hint) -> tuple[type, bool]
unwrap_annotated(type_hint) -> tuple[type, list[Any]]
extract_capabilities(annotations: list) -> tuple[SchemaAxisCapability, ...]
inspect_field(name, type_hint, *, has_default=False) -> FieldInfo

# Nested type helpers
is_structured_type(tp: type) -> bool
unwrap_collection(tp: type) -> type      # list[X] → X, set[X] → X, etc.
get_nested_info(field_info) -> dict[str, FieldInfo] | None
get_nested_type(field_info) -> type | None
```

### Schema Helpers

All navigation helpers take optional `axes` parameter.

```python
# Navigation
get_identity_field(cls, axes=None) -> FieldInfo | None
get_required_fields(cls, axes=None) -> list[FieldInfo]
get_optional_fields(cls, axes=None) -> list[FieldInfo]
partition_fields(cls, axes=None) -> tuple[list[FieldInfo], list[FieldInfo]]
field_by_name(cls, name, axes=None) -> FieldInfo | None
field_path_type(cls, path: str, axes=None) -> type | None   # resolve nested type by dot path
fields_with_capability(cls, cap_type, axes=None) -> list[tuple[str, FieldInfo, C]]
get_refs(cls, axes=None) -> list[tuple[str, FieldInfo, Ref]]
fields_by_dialect(cls, dialect: type[D], axes=None) -> list[tuple[str, FieldInfo, tuple[D, ...]]]

# Capability composition
merge_capabilities(*cap_tuples) -> tuple[SchemaAxisCapability, ...]   # later overrides earlier by type
override_capability(caps, new_cap) -> tuple[SchemaAxisCapability, ...]
remove_capability(caps, cap_type) -> tuple[SchemaAxisCapability, ...]
deduplicate_capabilities(caps) -> tuple[SchemaAxisCapability, ...]
find_capability(caps, cap_type) -> C | None
find_all_capabilities(caps, cap_type) -> tuple[C, ...]
has_capability(caps, cap_type) -> bool
filter_by_dialect(caps, dialect: type[D]) -> tuple[D, ...]
filter_universal(caps) -> tuple[UniversalCapability, ...]

# Schema meta composition
compose_schema_meta(cls, overrides=()) -> tuple[SchemaAxisCapability, ...]
get_nested_schema_meta(field_info) -> tuple[SchemaAxisCapability, ...]
```

### Dialects (`schema/dialects/`)

**CLI dialect:**
```python
cli.Help(text: str)        # argparse help text
cli.Metavar(name: str)     # display name in help (e.g., "FILE")
cli.Flag(*names)           # custom flag name(s) (e.g., "--verbose", "-v")
cli.Positional(name=None)  # positional argument
cli.Choices(*values)       # argparse choices
cli.Nargs(count)           # number of arguments ("+", "*", "?", int)
cli.Action(action: str)    # argparse action (e.g., "store_true", "count")
cli.Append()               # append action (collect multiple values)
cli.Count()                # count occurrences (-v -v -v → 3)
cli.Env(var: str)          # read from env variable
cli.Required()             # mark optional argument as required
```

**OpenAPI dialect:**
```python
openapi.Description(text)
openapi.Example(value)
openapi.Format(fmt)        # e.g., "email", "uri", "date-time"
openapi.ReadOnly()
openapi.WriteOnly()
openapi.Nullable()
```

**SQL dialect:**
```python
sql.Index(name: str | None = None, unique: bool = False)
sql.FullText()                              # full-text search index
sql.Type(sql_type: str)                     # override inferred SQL type
sql.ServerDefault(expression: str)          # server-side default (SQL expression)
sql.OnUpdate(expression: str)               # value to set on UPDATE
sql.Check(expression: str, name: str | None = None)  # CHECK constraint
sql.PrimaryKey(autoincrement: bool = True)
sql.ForeignKey(target: str, ondelete: str = "CASCADE", onupdate: str = "CASCADE")
sql.TableName(name: str)                    # override SQL table name
sql.CompositeUnique(*fields: str, name: str | None = None)
sql.CompositeIndex(*fields: str, name: str | None = None, unique: bool = False)
```

**Pydantic dialect:**
```python
pydantic.Strict()                                  # enable strict mode (no coercion)
pydantic.Coerce()                                  # explicitly allow coercion
pydantic.AliasPath(first: str, *rest: str | int)   # nested alias path
pydantic.Exclude()                                 # exclude from serialization
pydantic.Include()                                 # explicitly include in serialization
pydantic.ValidatorBefore(func)                     # run before standard validation
pydantic.ValidatorAfter(func)                      # run after standard validation
pydantic.ValidatorWrap(func)                       # wrap standard validation
```

**Compose dialect (nodnod node resolution):**
```python
compose.Node(node_type: type, default=None, map: Callable | None = None)  # compose field from nodnod node
compose.Optional(node_type: type)     # wrap in Option (Nothing if fails)
compose.Fallback(*node_types: type)   # first successful node wins (SequentialEither)
compose.Race(*node_types: type)       # concurrent race (ConcurrentEither)
compose.Retrieve(from_type: type)     # retrieve directly from scope
```

**Telegram dialect:**
```python
tg.Style("bold"|"italic"|"code"|"pre"|"strike"|"underline"|"spoiler")
tg.Bold(), tg.Italic(), tg.Code(), tg.Pre(language=), tg.Strike(), tg.Underline(), tg.Spoiler()
tg.Line(after=True, before=False)
tg.Skip()                        # exclude from TG output
tg.CommandArg(optional=, greedy=) # /command argument parsing
tg.Button(callback=, url=)       # inline keyboard button
tg.Keyboard(columns=1)           # keyboard group

# Help subdialect
tg.help.command(description, order=100)  # decorator
tg.help.hidden()                          # hide from /help
tg.help.get_command(cls) -> Command
tg.help.is_hidden(cls) -> bool
```

**Delta dialect:**
```python
# Field marker
delta.DeltaField(delta_type: Literal["numeric", "string", "collection"])

# Delta operation types
delta.NumericDelta(add=None, multiply=None, set=None)     # numeric field ops
delta.StringDelta(append=None, prepend=None, replace=None, set=None)  # string field ops
delta.CollectionDelta[T](push=(), pop=0, remove=(), insert=None, set=None)  # collection ops

# Functions
delta.delta_type(entity) -> type              # generate delta dataclass from entity
delta.apply_delta(entity, delta) -> entity    # apply delta (non-mutating)
delta.compose_deltas(*deltas) -> delta        # compose multiple deltas into one
delta.validate_delta(delta, entity_type) -> list[str]  # validate delta against entity
```

**Temporal dialect:**
```python
temporal.Versioned(version_field="version", start_version=1)
temporal.OptimisticLock
temporal.ValidFrom(field_name="valid_from")
temporal.ValidTo(field_name="valid_to")
temporal.Temporal()               # both ValidFrom + ValidTo
temporal.CreatedAt()
temporal.UpdatedAt()
temporal.Timestamps()             # both CreatedAt + UpdatedAt
temporal.SoftDelete()
temporal.temporal_filter_current()
temporal.temporal_filter_as_of(timestamp)
temporal.temporal_filter_version(version)
```

**API dialect (profile-based):**
```python
# Profile-agnostic shortcuts
api.PathParam()                                  # field in URL path: /users/{id}
api.QueryParam(name: str | None = None)          # query parameter
api.Filterable(operators: tuple[str, ...] = ())  # field can be filtered
api.Sortable()                                   # field can be sorted
api.Selectable()                                 # sparse fieldsets
api.Searchable()                                 # full-text search

# Profile-scoped builder (for multi-API profile support)
api.profile(InternalAPI).path_param().build()
api.profile(PublicAPI).query_param("q").with_filterable().with_sortable().build()

# Response shape
api.ResponseData(path: str, profile: type | None = None)
api.ResponseTotal(path: str, profile: type | None = None)
api.ResponseCursor(path: str, profile: type | None = None)
```

**Query dialect:**
```python
query.Filterable()                    # field can be filtered
query.Sortable()                      # field can be sorted
query.Selectable()                    # field can be selected (sparse fieldsets)
query.Searchable()                    # full-text search participation
query.Aggregatable(*functions: type)  # field can be aggregated
query.Operators(*operators: type)     # allowed filter operators (typed Expr subclasses)
query.JsonQueryable()                 # JSON path query support
query.ArrayQueryable()                # array operation support
query.FullTextIndexed(language: str = "english")  # full-text index
```

### Explain (`schema/_explain.py`)

Self-description of schema types. Inspects fields, groups capabilities by dialect.

```python
# Dict layer
field_info_dict(info, dialects=None) -> dict[str, Any]
schema_dict(cls, dialects=None) -> dict[str, Any]

# Human-readable layer
explain_schema(cls, dialects=None) -> str
explain_field(cls, field_name, dialects=None) -> str
```

The `dialects` parameter defaults to built-in dialect bases: `cli`, `openapi`, `sql`, `tg`, `compose`, `pydantic`, `api`, `query`. Pass custom `Mapping[str, type[SchemaAxisCapability]]` for your own dialects.

**Example:**
```python
from emergent.wire.axis.schema import schema_dict, explain_schema

data = schema_dict(Player)       # structured dict
print(explain_schema(Player))    # human-readable:
# === Player ===
#   [SchemaName('players'), Timestamps, SoftDelete, CompositeIndex('email', 'region')]
#
#   id (int):
#     [Identity, ReadOnly]
#     cli: Help('Player ID')
#     openapi: Description('Unique player identifier')
#
#   username (str):
#     [Unique, MinLen(3), MaxLen(32)]
#     cli: Help('Username'), Positional
#     openapi: Description('Public display name')
#     sql: Index('idx_username')
#     tg: Bold
#     api: Filterable, Sortable
#     query: Searchable
```

---

## 4. Storage Axis (`axis/storage/`)

Data persistence via atomic capability protocols composed into patterns.

### Capabilities (the grammar)

```python
# KV
class Get(Protocol[K, V, E]):
    async def get(self, key: K) -> Result[Option[V], E]: ...

class Set(Protocol[K, V, E]):
    async def set(self, key: K, value: V, ttl: timedelta | None = None) -> Result[None, E]: ...

class Delete(Protocol[K, E]):
    async def delete(self, key: K) -> Result[None, E]: ...

class SetWithTTL(Protocol[K, V, E]):
    async def set(self, key: K, value: V, ttl: timedelta | None = None) -> Result[None, E]: ...

class SetNX(Protocol[K, V, E]):
    async def set_nx(self, key: K, value: V, ttl: timedelta | None = None) -> Result[bool, E]: ...

# Queue
class Push(Protocol[V, E]):
    async def push(self, value: V) -> Result[None, E]: ...

class Pop(Protocol[V, E]):
    async def pop(self) -> Result[Option[V], E]: ...

class Peek(Protocol[V, E]):
    async def peek(self) -> Result[Option[V], E]: ...

class Len(Protocol[E]):
    async def length(self) -> Result[int, E]: ...

# PubSub
class Publish(Protocol[C, V, E]):
    async def publish(self, channel: C, value: V) -> Result[None, E]: ...

class Subscribe(Protocol[C, V, E]):
    def subscribe(self, channel: C) -> AsyncIterator[Result[V, E]]: ...  # sync method

# Lock
class Acquire(Protocol[K, E]):
    async def acquire(self, key: K, ttl: timedelta) -> Result[bool, E]: ...

class Release(Protocol[K, E]):
    async def release(self, key: K) -> Result[None, E]: ...

class Extend(Protocol[K, E]):
    async def extend(self, key: K, ttl: timedelta) -> Result[bool, E]: ...

# Counter
class Incr(Protocol[K, E]):
    async def incr(self, key: K) -> Result[int, E]: ...

class Decr(Protocol[K, E]):
    async def decr(self, key: K) -> Result[int, E]: ...

class IncrBy(Protocol[K, E]):
    async def incr_by(self, key: K, amount: int) -> Result[int, E]: ...

# Batch
class BatchGet(Protocol[K, V, E]):
    async def get_many(self, keys: list[K]) -> Result[dict[K, V], E]: ...

class BatchSet(Protocol[K, V, E]):
    async def set_many(self, items: dict[K, V]) -> Result[None, E]: ...

class BatchDelete(Protocol[K, E]):
    async def delete_many(self, keys: list[K]) -> Result[None, E]: ...

# Pattern
class DeletePattern(Protocol[E]):
    async def delete_pattern(self, pattern: str) -> Result[int, E]: ...
```

### Patterns (compose capabilities + codec)

```python
kv(backend, codec) -> KV[K, V, E]            # Get + Set + Delete + codec
kv_nx(backend, codec) -> KVNX[K, V, E]       # + SetNX
queue(backend, codec) -> Queue[V, E]          # Push + Pop + codec
queue_full(backend, codec) -> QueueFull[V, E] # + Peek + Len
pubsub(backend, codec) -> PubSub[V, E]       # Publish + Subscribe + codec
lock(backend) -> Lock[E]                      # Acquire + Release + hold() context manager
lock_extend(backend) -> LockExtend[E]         # + Extend (TTL renewal)
counter(backend) -> Counter[E]                # Incr + Decr
counter_full(backend) -> CounterFull[E]       # + IncrBy + DecrBy
```

### Codecs

```python
class Codec(Protocol[T]):
    def encode(self, value: T) -> bytes: ...
    def decode(self, data: bytes) -> T: ...

PickleCodec[T]()
JsonCodec[T]()
IdentityCodec()  # no transformation
```

### Implementations

```python
# BaseTTLStorage — base with built-in TTL support
class BaseTTLStorage(Generic[K, V]):
    async def get(self, key) -> Result[Option[V], Never]
    async def set(self, key, value, ttl: timedelta | None = None) -> Result[None, Never]
    async def delete(self, key) -> Result[None, Never]
    async def set_nx(self, key, value, ttl: timedelta | None = None) -> Result[bool, Never]
    async def delete_pattern(self, pattern: str) -> Result[int, Never]
    async def keys(self, pattern: str = "*") -> Result[list[K], Never]

MemoryStorage[K, V]()    # extends BaseTTLStorage, in-memory dict-based
FileStorage[K, V](path)  # pickle-to-disk
```

### KV Composition

```python
prefix_kv(inner, prefix: str) -> PrefixKV       # key prefixing
tiered_kv(l1, l2) -> TieredKV                    # L1 → L2 fallback
fallback_kv(primary, fallback) -> FallbackKV     # primary with fallback
readonly_kv(inner) -> ReadonlyKV                 # read-only wrapper
```

### Contrib

**SQLAlchemy storage:**
```python
from emergent.wire.axis.storage.contrib import sqlalchemy

UserStore = sqlalchemy.store(User, "users")  # factory pattern
users = UserStore(session)                    # bind to session
await users.set(User(id=1, email="..."))
user = await users.get(1)

# Lower-level
compile_model(entity, tablename, base=) -> type     # dataclass → SA model
compile_expr(expr, model) -> SA where clause
entity_to_model(entity, model_class) -> model
model_to_entity(model, entity_class) -> entity
```

**EventStore (event sourcing):**
```python
from emergent.wire.axis.storage.contrib.event_store import EventStore, Event

store = EventStore[int, Account, AccountDelta](Account)
await store.append(entity_id=1, delta=AccountDelta(...))
current = await store.replay(entity_id=1, initial=Account(...))
events = await store.history(entity_id=1)
await store.snapshot(entity_id=1, entity=current)
```

### Explain (`storage/_explain.py`)

Self-description of storage patterns and composition trees. Recursive: composition wrappers expand their inner stores.

```python
type StorageExplainHandler = Callable[[Any, _ExplainCtx], dict[str, Any]]

# Dict layer
storage_dict(store, handlers=STORAGE_EXPLAIN) -> dict[str, Any]

# Human-readable layer
explain_storage(store, handlers=STORAGE_EXPLAIN) -> str

# Pre-built handler mapping
STORAGE_EXPLAIN: Mapping[type, StorageExplainHandler]
# Handles: KV, KVNX, Queue, QueueFull, PubSub, Lock, LockExtend,
#          Counter, CounterFull, PrefixKV, TieredKV, FallbackKV, ReadonlyKV
```

Composition wrappers produce nested dicts — `PrefixKV` has `inner`, `TieredKV` has `l1`/`l2`, etc. Open-world: unknown types get generic fallback.

**Example:**
```python
from emergent.wire.axis.storage import storage_dict, explain_storage

data = storage_dict(my_tiered)    # structured dict with nested children
print(explain_storage(my_tiered)) # human-readable:
# TieredKV:
#   l1_ttl: 300.0s
#   l1: PrefixKV:
#     prefix: 'cache:'
#     inner: KV(codec=PickleCodec, backend=MemoryStorage)
#   l2: KV(codec=JsonCodec, backend=MemoryStorage)
```

---

## 5. Query Axis (`axis/query/`)

Free monad query system. Syntax/semantics separation: queries are pure data until interpreted.

### Expression AST

```python
# Base
class Expr: ...
Field(name: str)
Const(value: Any)

# Comparison
Eq(left, right), Ne, Lt, Le, Gt, Ge

# Logical
And(*exprs), Or(*exprs), Not(expr)

# Collection
In(field, values), Contains(field, value)
StartsWith(field, prefix), EndsWith(field, suffix)

# Null
IsNull(expr), IsNotNull(expr)

# Range/Pattern
Between(field, low, high)
Like(field, pattern), ILike(field, pattern), Regex(field, pattern)

# Array
ArrayContains(field, values), ArrayAny(field, values)
ArrayAll(field, values), ArrayOverlap(field, values)

# JSON
JsonExtract(field, path), JsonContains(field, value), JsonHasKey(field, key)
```

### Proxy (lambda-based expression building)

```python
EntityProxy[T]  # captures lambdas: lambda u: u.name == "Alice" → Eq(Field("name"), Const("Alice"))
build_expr(entity, predicate) -> Expr
build_order(entity, order_fn) -> OrderSpec
```

### Aggregates (typed, no strings)

```python
Count(), Sum(), Avg(), Min(), Max()
ArrayAgg(), StringAgg(separator=",")
AggregateExpr  # proxy for aggregate building
```

### Query Spaces

**Relational (SQL-like):**
```python
q = relational(User)
    .filter(lambda u: u.active == True)       # WHERE
    .where(lambda u: u.balance > 100)         # alias for filter
    .order_by(lambda u: u.balance.desc())     # ORDER BY
    .limit(50).offset(10)                     # LIMIT + OFFSET
    .paginate(page=2, per_page=25)            # convenience for offset + limit
    .select(lambda u: u.name, lambda u: u.email)  # SELECT projection (lambdas)
    .distinct()                               # DISTINCT
    .group_by(lambda u: u.department)         # GROUP BY (lambdas)
    .having(lambda u: u.count() > 5)          # HAVING
    .aggregate(total=lambda u: u.balance.sum())
    .join(Order, lambda u, o: u.id == o.user_id)       # INNER JOIN
    .left_join(Profile, lambda u, p: u.id == p.user_id) # LEFT JOIN

# Ops: Filter, OrderBy, Limit, Offset, Select, Join, GroupBy, Having, Distinct, Aggregate
```

**KV (Redis-like):**
```python
q = kv(User, key=lambda u: u.id)
q.get("alice")
q.set("alice", user)
q.delete("alice")
q.exists("alice")
q.scan("user:*")
q.keys("user:*")
```

**API (REST-like):**
```python
q = api(User)
    .list()
    .filter(lambda u: u.active)
    .page(1, per_page=20)
    .search("alice")
    .include("orders")
    .order("name")

# Ops: ListOp, GetOp, CreateOp, UpdateOp, DeleteOp
# Mods: FilterMod, OrderMod, PageMod, CursorMod, OffsetMod, SelectMod, SearchMod, IncludeMod
```

### Fold Layer (interpreters)

```python
type OpHandler[Ctx] = Callable[[op, Ctx], Ctx]

@dataclass(frozen=True, slots=True)
class QueryDialect(Generic[Ctx]):
    context_type: type[Ctx]
    handlers: Mapping[type, OpHandler[Ctx]]

    def fold(self, ops, initial) -> Ctx: ...
    def with_handler(self, op_type, handler) -> QueryDialect: ...
    def without_handler(self, op_type) -> QueryDialect: ...

# Built-in
MEMORY_DIALECT  # interprets on list[T]

# Usage: same query, different interpreters
result = MEMORY_DIALECT.fold(q.ops, data)
sql = SQL_DIALECT.fold(q.ops, SQLPlan("users"))
```

### Stores (QuerySet + Provider bundled)

```python
users = relational_store(User, memory_provider)
result = await users.filter(lambda u: u.active).fetch_many()
user = await users.filter(lambda u: u.id == 1).first()
await users.insert(User(...))

cache = kv_store(User, key=lambda u: u.id, provider=memory_kv)
user = await cache.get("alice")
```

### Providers

```python
class RelationalProvider(Protocol[T]):
    async def fetch_one(self, query) -> T | None: ...
    async def fetch_many(self, query) -> list[T]: ...
    async def count(self, query) -> int: ...
    async def exists(self, query) -> bool: ...

class MutatingRelationalProvider(RelationalProvider[T], Protocol):
    async def insert(self, entity) -> T: ...
    async def update(self, entity) -> T: ...
    async def delete(self, entity) -> None: ...

# Built-in
MemoryRelationalProvider[T](data=, key_fn=, next_id=)
MemoryKVProvider[T](data=)

# ID Generation
UuidNextId()
SequenceNextId(start=1)
PrefixedNextId("user_", inner)
```

### Serialization & Simplification

```python
# Expr ↔ dict
expr_to_dict(expr) -> dict
expr_from_dict(d) -> Expr
expr_fields(expr) -> set[str]
expr_complexity(expr) -> int
expr_depth(expr) -> int

# Boolean algebra optimization
simplify_expr(expr) -> Expr
flatten_and(expr) -> list[Expr]
flatten_or(expr) -> list[Expr]
```

### Contrib

**HTTP API provider:**
```python
from emergent.wire.axis.query.contrib import http

provider = (
    http.api(User, profile=InternalAPI)
    .base("https://api.example.com/users")
    .pagination(http.page_size())
    .auth(http.bearer(token))
    .build(httpx_client)
)
```

### Explain (`query/_explain.py`)

Self-description of query operations. Symmetric with `QueryDialect` — handlers passed as argument, not global.

```python
type ExplainHandler = Callable[[Any], dict[str, Any]]

# Dict layer
explain_ops(ops, handlers) -> list[dict[str, Any]]

# Human-readable layer
format_ops(ops, handlers) -> str

# Dialect wrapper (immutable, composable)
@dataclass(frozen=True, slots=True)
class ExplainDialect:
    handlers: Mapping[type, ExplainHandler]
    def explain(self, ops) -> list[dict[str, Any]]: ...
    def format(self, ops) -> str: ...
    def with_handler(self, op_type, handler) -> ExplainDialect: ...
    def without_handler(self, op_type) -> ExplainDialect: ...

# Pre-built handler sets
RELATIONAL_EXPLAIN: Mapping[type, ExplainHandler]
# Handles: Filter, OrderBy, Limit, Offset, Select, Join, GroupBy, Having, Distinct, Aggregate

API_EXPLAIN: Mapping[type, ExplainHandler]
# Handles: ListOp, GetOp, CreateOp, UpdateOp, DeleteOp,
#          FilterMod, OrderMod, PageMod, CursorMod, OffsetMod, SelectMod, SearchMod, IncludeMod

KV_EXPLAIN: Mapping[type, ExplainHandler]
# Handles: KVGet, KVSet, KVDelete, Exists, Scan, Keys

# Pre-built dialects
RELATIONAL_EXPLAIN_DIALECT: ExplainDialect
API_EXPLAIN_DIALECT: ExplainDialect
KV_EXPLAIN_DIALECT: ExplainDialect
```

**Example:**
```python
from emergent.wire.axis.query import (
    relational, RELATIONAL_EXPLAIN_DIALECT, format_ops, RELATIONAL_EXPLAIN,
)

q = relational(User).filter(lambda u: u.active == True).order_by(lambda u: u.name).limit(10)
print(format_ops(q.ops, RELATIONAL_EXPLAIN))
#   1. Filter: expr=active == True, fields=active
#   2. OrderBy: specs=name ASC
#   3. Limit: count=10

# Or via dialect
print(RELATIONAL_EXPLAIN_DIALECT.format(q.ops))

# Extend with custom handler
my = RELATIONAL_EXPLAIN_DIALECT.with_handler(MyOp, my_handler)
```

---

## 6. Compile Module (`compile/`)

Transforms wire `Application` into framework artifacts.

### Core

```python
@dataclass(frozen=True, slots=True)
class Axes:
    schema: Callable[[type], dict[str, FieldInfo]]
    trace: TraceCollector | None = None
    scope_layer: ScopeLayer | None = None

    @classmethod
    def default(cls) -> Axes: ...

    @classmethod
    def traced(cls, collector: TraceCollector | None = None) -> Axes: ...

# THE compilation primitive
def fold_field(
    field: FieldInfo,
    initial: Ctx,
    protocol: type,          # e.g., PydanticCompilable
    compile_method: str,     # e.g., "compile_pydantic"
    handlers: Mapping | None = None,
) -> Ctx: ...
```

### Lifetime (`compile/_lifetime.py`)

```python
@dataclass(frozen=True, slots=True)
class Tier:
    parent: Tier | None = None

App = Tier()                 # application-scoped
Request = Tier(parent=App)   # request-scoped

# Custom tiers — arbitrary depth:
Session = Tier(parent=App)
Turn = Tier(parent=Request)

@dataclass(frozen=True, slots=True)
class ScopeLayer:
    scopes: Mapping[Tier, Scope]      # pre-existing tier→scope mappings
    family: ScopeFamily[Tier]         # required — type→tier bindings
    leaf: Tier                        # per-execution tier (scope created at runtime)

    @property
    def parent(self) -> Scope: ...    # walks leaf.parent chain → nearest scope in `scopes`

    @property
    def compose(self) -> frozenset[type]: ...  # family.types_for(leaf)

    def with_scope(self, tier: Tier, scope: Scope) -> ScopeLayer: ...  # add tier at runtime
```

**Standard 2-tier usage (App → Request):**
```python
layer = ScopeLayer(
    scopes=MappingProxyType({App: app_scope}),
    family=family,
    leaf=Request,
)
# layer.parent → app_scope (Request.parent = App, found in scopes)
# layer.compose → family.types_for(Request)
```

**N-tier usage (App → Session → Request):**
```python
Session = Tier(parent=App)
DeepRequest = Tier(parent=Session)

family = (
    ScopeFamily[Tier]()
    .bind(App, DBPool, Config)
    .bind(Session, SessionData, RateLimiter)
    .bind(DeepRequest, CurrentUser)
)

layer = ScopeLayer(
    scopes=MappingProxyType({App: app_scope}),
    family=family,
    leaf=DeepRequest,
)
# layer.parent walks: DeepRequest → Session(missing) → App(found) → app_scope

# Add Session scope at runtime:
new_layer = layer.with_scope(Session, session_scope)
# new_layer.parent walks: DeepRequest → Session(found) → session_scope
```

### Compilation Phases

```python
@dataclass(frozen=True, slots=True)
class CompilationPhase(Generic[Ctx]):
    protocol: type
    compile_method: str
    context_factory: Callable[[str, type], Ctx]
    handlers: Mapping[type, CapabilityHandler] = {}

# Built-in phases
PYDANTIC_PHASE          # PydanticCompilable → PydanticContext
OPENAPI_PHASE           # OpenAPICompilable → OpenAPIContext
ARGPARSE_PHASE          # ArgparseCompilable → ArgparseContext
REQUEST_BUILD_PHASE     # RequestBuildCompilable → RequestBuildContext
TG_INPUT_PHASE          # TelegrinderInputCompilable → TelegrinderInputContext
TG_RENDER_PHASE         # TelegrinderRenderCompilable → TelegrinderRenderContext

# Phase sets per target
FASTAPI_PHASES = (PYDANTIC_PHASE, OPENAPI_PHASE, REQUEST_BUILD_PHASE)
CLI_PHASES = (ARGPARSE_PHASE,)
TG_PHASES = (TG_INPUT_PHASE, TG_RENDER_PHASE, REQUEST_BUILD_PHASE)
```

### Target Compiler (open-world codec dispatch)

```python
@dataclass(frozen=True, slots=True)
class CodecAdapter(Generic[T]):
    codec_type: type
    wrap: Callable[[Handler, Trigger, Axes], Any]

@dataclass(frozen=True, slots=True)
class TargetCompiler(Generic[T]):
    trigger_type: type[T]
    adapters: tuple[CodecAdapter[T], ...]

    def scan_and_wrap(self, app, axes) -> Iterator[tuple[T, Handler, Any]]: ...
```

### Type Generation

```python
to_pydantic(cls, axes) -> type[BaseModel]           # dataclass → Pydantic model
to_argparse_args(cls, axes) -> list[ArgSpec]         # dataclass → argparse args
to_openapi_schema(cls, axes) -> dict                 # dataclass → OpenAPI JSON Schema
to_json_schema(cls, axes) -> dict                    # dataclass → JSON Schema
to_telegram_fields(cls, axes) -> list[TelegramField] # dataclass → TG render fields
to_datanode(cls, field_name, axes) -> type            # field → nodnod DataNode
```

### Execution Functions

```python
# Unified execution (compose dialect → nodnod scope → handler)
execute_delegate_unified(handler, composer: Composer) -> response
execute_stateful_unified(handler, composer: Composer, state_store) -> response
execute_immediate_unified(handler) -> response

type ScopeInjector = Callable[[Scope], None]

# Request building (compose dialect)
build_request(cls, axes, scope) -> instance
build_request_sync(cls, axes, get_value) -> instance
```

### Capability Utilities

```python
apply_response_capabilities(response, capabilities) -> response
find_capability(caps, cap_type) -> cap | None
find_all_capabilities(caps, cap_type) -> tuple[cap, ...]
has_capability(caps, cap_type) -> bool
```

### FastAPI Compile Capabilities

```python
@dataclass
class FastAPICompileContext:
    app: FastAPI
    trigger: HTTPRouteTrigger
    handler: Handler
    mounted: set[tuple[int, str]]
    skip_route: bool = False

class FastAPICompilable(Protocol):
    def compile_fastapi(self, ctx: FastAPICompileContext) -> FastAPICompileContext: ...

class FastAPIRouteCompilable(Protocol):
    def compile_fastapi_route(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext: ...

# Mount capability — mount ASGI app at prefix
Mount()  # implements compile_fastapi
```

### Constraint Extraction

```python
@dataclass(frozen=True, slots=True)
class FieldConstraints:
    min_length, max_length: int | None
    min_value, max_value: float | None
    pattern: str | None
    choices: tuple | None
    is_identity, is_unique, is_optional: bool

extract_constraints(field_info) -> FieldConstraints
extract_all_constraints(cls, axes) -> dict[str, tuple[type, FieldConstraints]]
```

### Targets (`compile/targets/`)

**FastAPI:**
```python
from emergent.wire.compile.targets import fastapi

app = fastapi.compile(wire_app, axes: Axes)  # Application → FastAPI
```

**CLI:**
```python
from emergent.wire.compile.targets import cli

parser = cli.compile(wire_app, axes: Axes, prog: str | None = None)  # Application → argparse
```

**Telegrinder:**
```python
from emergent.wire.compile.targets import telegrinder

telegrinder.compile(wire_app, axes: Axes)  # Application → telegrinder Dispatch
```

**Pure (framework-agnostic lifecycle/exception/websocket):**
```python
from emergent.wire.compile.targets import pure

# Compilers for non-HTTP triggers
STARTUP_COMPILER       # StartupTrigger → LifecycleRoute
SHUTDOWN_COMPILER      # ShutdownTrigger → LifecycleRoute
EXCEPTION_COMPILER     # ExceptionTrigger → ExceptionRoute
WEBSOCKET_COMPILER     # WebSocketTrigger → WebSocketRoute

# Route types
LifecycleRoute(handler, order)
ExceptionRoute(exception_type, handler, propagate)
WebSocketRoute(path, handler, name)

# Lifespan context manager for app-scope
app_scope_lifespan(scope_layer: ScopeLayer) -> AsyncContextManager
```

**Testing:**
```python
from emergent.wire.compile.targets import testing

# Compile for testing (no framework needed)
routes = testing.testing_compile(wire_app, axes: Axes) -> list[TestRoute]

# TestRoute — call endpoints directly
route = routes[0]
result = await route.call(fields={"name": "Alice"}, inject={AuthUser: user})

# TestApp — full test harness with scope management
async with TestApp(wire_app, axes) as app:
    result = await app.call("POST /users", fields={...})
```

---

## 7. Bridge Module (`bridge/`)

Reverse of compile: extracts wire `Application` from existing framework apps.

### Main Functions

```python
# Extract specific route types
routes = extract(fastapi_app, HTTPRouteData)

# Build wire Application (auto-detect framework)
wire_app = build_application(fastapi_app, capabilities=(), axes=None)
```

### Core Types

```python
type RouteData = object  # HTTPRouteData, WebSocketRouteData, etc.

@dataclass(frozen=True, slots=True)
class Extracted(Generic[R]):
    route: R
    handler: Callable
    name: str | None
    description: str | None
    deprecated: bool = False
    metadata: dict[str, Any] = {}
```

### Extractor Protocol

```python
class Extractor(Protocol[R]):
    def can_extract(self, source: object) -> bool: ...
    def extract(self, source: object) -> Iterator[Extracted[R]]: ...

compose_extractors(*extractors) -> ComposedExtractor
filter_extractor(inner, predicate) -> Extractor
first_extractor(*extractors) -> Extractor
```

### ToWire (route data → wire types)

```python
class ToWire(Protocol[R]):
    def to_trigger(self, route: R) -> Trigger: ...
    def to_codec(self, route: R, handler: Callable) -> Codec: ...

compose_to_wire(*pairs) -> ComposedToWire
```

### Handler Introspection

```python
@dataclass(frozen=True, slots=True)
class HandlerShape:
    parameters: tuple[ParameterShape, ...]
    return_type: type | None
    is_async: bool
    is_generator: bool
    decorators: tuple[DecoratorInfo, ...]
    source_module: str | None

analyze_handler(handler, skip_params=DEFAULT_SKIP_PARAMS) -> HandlerShape
unwrap_handler(handler) -> Callable  # unwrap decorators/closures
```

### Detection Protocols

```python
class BodyDetector(Protocol):
    def detect_body(self, param: ParameterShape) -> BodyDetection | None: ...

class DIDetector(Protocol):
    def detect_di(self, param: ParameterShape) -> DIDetection | None: ...

class DecoratorMapper(Protocol):
    def map_decorator(self, info: DecoratorInfo) -> DecoratorMapping | None: ...

run_detectors(shape, body_detectors, di_detectors, decorator_mappers) -> DetectionResult
```

### Bridge Capabilities

```python
class BridgeCapability: ...      # base
class BridgeCompilable(Protocol):
    def compile_bridge(self, ctx: BridgeContext) -> BridgeContext: ...

class Purifier(Protocol):
    def purify(self, handler: Callable) -> Callable: ...

# Built-in BridgeCompilable capabilities
SkipDeprecated()
SkipByName(*names)
IncludeOnlyByName(*names)
AddCapability(capability)
SetCodecByName(name, codec)
SetRequestTypeByName(name, type)
SetResponseTypeByName(name, type)

# Purifier capabilities
WrapAsync()
CatchErrors(handler)
IsolateGlobal(module, attr, value)
IsolateGlobalAsync(value)             # async variant
SetGlobal(module, attr, value)
InjectKwarg(name, value)
InjectKwargAsync(name, factory)
WithContext(context_manager_factory)
WithContextSync()                      # sync context manager variant
SetupTeardown(setup, teardown)
WrapAsDelegate()
```

### Pre-Built Patterns

```python
from emergent.wire.bridge._patterns import (
    SKIP_DEPRECATED,      # skip deprecated routes
    SKIP_PRIVATE,         # skip private routes
    SKIP_INTERNAL,        # skip internal routes
    ASYNC_ALL,            # wrap all handlers as async
    DELEGATE_ALL,         # wrap all as delegates
    CLEAN,                # clean extraction (no deprecated, no private)
    fastapi_default(),    # default FastAPI bridge pattern
    fastapi_with_depends(),  # FastAPI bridge preserving Depends
)
```

### Registry (open-world framework detection)

```python
@dataclass(frozen=True, slots=True)
class FrameworkBridger:
    name: str
    detector: Callable[[object], bool]
    extractor: Extractor
    to_wire: ToWire
    axes: BridgeAxes

class BridgeRegistry:
    def register(self, bridger: FrameworkBridger) -> None: ...
    def detect(self, source: object) -> FrameworkBridger | None: ...

get_default_registry() -> BridgeRegistry  # includes FastAPI
```

### FastAPI Bridger (`bridge/bridgers/fastapi/`)

```python
# Route data types
HTTPRouteData(method, path, name, tags, deprecated, response_model, status_code, ...)
WebSocketRouteData(path, name)
LifespanData(kind, order)
ExceptionHandlerData(exception_type)
MiddlewareData(middleware_class, options)

# Extractors
HTTPRouteExtractor()
WebSocketExtractor()
LifespanExtractor()
ExceptionHandlerExtractor()
MountedAppExtractor(inner)
create_fastapi_extractors() -> Extractor
FASTAPI_EXTRACTORS  # default composed

# ToWire converters
HTTPToWire(), WebSocketToWire(), LifespanToWire(), ExceptionHandlerToWire()
FASTAPI_TO_WIRE  # default composed

# Utilities
is_depends(obj) -> bool
get_depends_func(depends) -> object | None
find_depends_param(handler, depends_func) -> str | None
get_all_depends(handler) -> list[tuple[str, object]]
```

---

## 8. Complete Usage Example

```python
from dataclasses import dataclass
from typing import Annotated

from emergent.wire.axis.schema import Identity, MaxLen, Doc
from emergent.wire.axis.schema.dialects import cli, tg
from emergent.wire.axis.schema.dialects import openapi
from emergent.wire.axis.surface import endpoint, application
from emergent.wire.axis.surface.codecs import rrc
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger
from emergent.wire.compile.targets import fastapi, cli as cli_target

# ONE type, THREE projections
@dataclass
class RegisterRequest:
    login: Annotated[str, MaxLen(50), cli.Help("Username"), openapi.Description("User login"), tg.CommandArg()]
    password: Annotated[str, MaxLen(100), cli.Help("Password"), tg.CommandArg()]

# ONE endpoint, THREE exposures
endp = (
    endpoint(runner)
    .expose(HTTPRouteTrigger("POST", "/register"), rrc(RegisterRequest, RegisterResponse))
    .expose(CLITrigger("register"), rrc(RegisterRequest, RegisterResponse))
    .expose(TelegrindTrigger(Command("register")), rrc(RegisterRequest, RegisterResponse))
)

app = application().mount(endp)

# Compile to targets
fastapi_app = fastapi.compile(app)
cli_parser = cli_target.compile(app)
```

---

## 9. Graph Module (`emergent/graph/`)

Computation graph with auto-parallelization, built on nodnod DI.

### Composer

Immutable `(scope, agent_cls)` pair — THE single primitive for nodnod composition in compile targets.

```python
@dataclass(frozen=True, slots=True)
class Composer:
    scope: Scope
    agent_cls: type[Agent]
    mapped_scopes: Mapping[type, Scope] = {}

    @classmethod
    def create(cls, scope, agent_cls=None, mapped_scopes=None) -> Composer: ...
    def child(self, detail="child", agent_cls=None) -> Composer: ...
    def retrieve[T](self, typ: type[T]) -> tuple[bool, T | None]: ...
    async def compose[T](self, node_type: type[T]) -> tuple[bool, T | str]: ...
    async def compose_batch(self, node_types: set[type]) -> None: ...
    async def resolve_params(self, handler) -> dict[str, object]: ...
```

### ScopeFamily

Composable type→tier mapping algebra. Used by compile targets to organize nodnod types into scope tiers.

```python
@dataclass(frozen=True, slots=True)
class ScopeFamily[K]:
    bindings: Mapping[type, K] = {}

    def bind(self, key: K, *types: type) -> ScopeFamily[K]: ...
    def unbind(self, *types: type) -> ScopeFamily[K]: ...
    def __or__(self, other: ScopeFamily[K]) -> ScopeFamily[K]: ...
    def types_for(self, key: K) -> frozenset[type]: ...
    def tier_of(self, typ: type) -> K | None: ...
    def to_groups(self) -> Mapping[K, frozenset[type]]: ...
    def materialize(self, scopes: Mapping[K, Scope]) -> Mapping[type, Scope]: ...
```

### Graph Functions

```python
graph(fn, *, agent_cls: type[Agent] | None = None) -> CompiledRun
run(fn, scope) -> result
compose(node_type, scope) -> instance
```

### Visualization

```python
to_mermaid(graph) -> str
to_tree(graph) -> str
to_text(graph) -> str
to_ascii(graph) -> str
visualize(graph) -> str
get_layers(graph) -> list
get_dependencies(graph) -> dict
```

---

## 10. File Index

### Root
- `wire/__init__.py` — re-exports `axis`, `compile`

### axis/ (4 files)
- `axis/__init__.py` — re-exports surface, storage, schema, query, Capability
- `axis/_capability.py` — ROOT Capability, all contexts, all protocols, all helpers

### axis/query/
- `_expr.py` — Expression AST (30+ node types)
- `_proxy.py` — EntityProxy, FieldProxy, build_expr, build_order
- `_aggregate.py` — Count, Sum, Avg, Min, Max, ArrayAgg, StringAgg
- `_space.py` — Space, RelationalSpace, KVSpace, DocumentSpace, APISpace
- `_base_qs.py` — RelationalMixin (shared filter/select/join/group_by methods)
- `_relational.py` — RelationalQuerySet, relational(), ops (Filter, OrderBy, etc.)
- `_sql.py` — SQL-specific query extensions
- `_window.py` — Window function support
- `_kv.py` — KVQuerySet, kv(), ops (KVGet, KVSet, etc.)
- `_api.py` — APIQuerySet, api(), ops + mods
- `_provider.py` — Provider protocols, NextId generators
- `_store.py` — RelationalStore, KVStore (bundled query+provider)
- `_fold.py` — QueryDialect, fold_query, MEMORY_DIALECT
- `_explain.py` — explain_ops, format_ops, ExplainDialect, RELATIONAL/API/KV_EXPLAIN
- `_serialize.py` — expr_to_dict, expr_from_dict
- `_simplify.py` — simplify_expr, flatten_and/or
- `providers/memory.py` — MemoryRelationalProvider, MemoryKVProvider
- `contrib/http.py` — HTTP API provider (requires httpx)
- `contrib/sqlalchemy.py` — SQLAlchemyRelationalProvider, SQLAlchemyRelationalStore
- `contrib/_impls/_http.py` — HTTPAPIBuilder, pagination, auth, filters

### axis/schema/
- `_universal.py` — SchemaAxisCapability, UniversalCapability, Identity, Unique, ReadOnly, WriteOnly, Sensitive, Immutable, Nullable, Computed, Alias, Min, Max, MinLen, MaxLen, Pattern, OneOf, Doc, Ref, Nested, Embedded, Deprecated, SchemaName, SchemaDoc, Abstract
- `_inspect.py` — FieldInfo, Inspector, inspect_type, first_match, dataclass/pydantic/typeddict/namedtuple inspectors, unwrap_optional, unwrap_annotated, inspect_field, is_structured_type, unwrap_collection, get_nested_info, get_nested_type
- `_compilable.py` — OpenAPISchema, SQLAlchemyConfig, ProtobufSchema
- `_patterns.py` — Id, Email, Slug, Username, Short, Medium, Positive, etc.
- `_helpers.py` — get_identity_field, partition_fields, merge_capabilities, field_path_type, fields_by_dialect, deduplicate_capabilities, filter_by_dialect, filter_universal, compose_schema_meta, get_nested_schema_meta
- `_explain.py` — schema_dict, field_info_dict, explain_schema, explain_field
- `dialects/cli.py` — Help, Metavar, Flag, Positional, Choices, Nargs, Action, Append, Count, Env, Required
- `dialects/openapi.py` — Description, Example, Format, ReadOnly, etc.
- `dialects/sql.py` — Index, FullText, Type, ServerDefault, OnUpdate, Check, PrimaryKey, ForeignKey, TableName, CompositeUnique, CompositeIndex
- `dialects/pydantic.py` — Strict, Coerce, AliasPath, Exclude, Include, ValidatorBefore, ValidatorAfter, ValidatorWrap
- `dialects/compose.py` — Node, Optional, Fallback, Race, Retrieve
- `dialects/tg/__init__.py` — Style, Bold, Italic, Code, Pre, Strike, Underline, Spoiler, Line, Skip, CommandArg, Button, Keyboard
- `dialects/tg/help.py` — Command, command(), hidden(), get_command()
- `dialects/delta.py` — DeltaField, NumericDelta, StringDelta, CollectionDelta, delta_type, apply_delta, compose_deltas, validate_delta
- `dialects/temporal.py` — Versioned, Temporal, Timestamps, SoftDelete
- `dialects/api.py` — ProfileConfig, profile(), PathParam, QueryParam, Filterable, Sortable, Selectable, Searchable, ResponseData, ResponseTotal, ResponseCursor
- `dialects/query.py` — Filterable, Sortable, Selectable, Searchable, Aggregatable, Operators, JsonQueryable, ArrayQueryable, FullTextIndexed

### axis/storage/
- `_capabilities.py` — Get, Set, Delete, SetWithTTL, SetNX, Push, Pop, Peek, Len, Publish, Subscribe, Acquire, Release, Extend, Incr, Decr, IncrBy, BatchGet, BatchSet, BatchDelete, DeletePattern
- `_codec.py` — Codec, PickleCodec, JsonCodec, IdentityCodec
- `_memory.py` — BaseTTLStorage, MemoryStorage
- `_file.py` — FileStorage
- `_kv.py` — KV, kv(), KVBackend
- `_queue.py` — Queue, queue(), QueueBackend
- `_pubsub.py` — PubSub, pubsub(), PubSubBackend
- `_lock.py` — Lock, LockExtend, lock(), lock_extend(), LockBackend, LockBackendExtend
- `_counter.py` — Counter, CounterFull, counter(), counter_full(), CounterBackend, CounterBackendFull
- `_compose.py` — PrefixKV, TieredKV, FallbackKV, ReadonlyKV
- `_explain.py` — storage_dict, explain_storage, STORAGE_EXPLAIN
- `_result.py` — map_option, map_result
- `contrib/sqlalchemy.py` — SQLAlchemy storage (lazy import)
- `contrib/_impls/_sqlalchemy.py` — compile_model, SQLAlchemyStorage, SQLAlchemyStore
- `contrib/event_store.py` — EventStore, Event, Snapshot, PersistentEventStore

### axis/surface/
- `_types.py` — Trigger, Codec, Exposure
- `_endpoint.py` — Endpoint, endpoint()
- `_app.py` — Application, application()
- `_handler.py` — Handler[C]
- `_scan.py` — scan(), scan_endpoint(), scan_stack(), StackView (now with codec filter)
- `_explain.py` — application_dict, endpoint_dict, exposure_dict, explain_application, explain_endpoint, SURFACE_EXPLAIN
- `_stack.py` — AppStack, app_stack()
- `capabilities/__init__.py`, `_base.py`, `_helpers.py` — SurfaceCapability base
- `codecs/rrc.py` — RequestResponseCodec, rrc(), ToDomain, FromDomain
- `codecs/stateful.py` — StatefulCodec, Done, transition, StateStore, get_transitions, resolve_transition
- `codecs/delegate.py` — DelegateCodec, delegate()
- `codecs/immediate.py` — ImmediateCodec, immediate()
- `codecs/resolve.py` — compose_params, resolve_transition, unwrap/wrap utilities
- `enrichers/_base.py`, `_impl.py` — ScopeEnricher
- `transforms/_base.py`, `_handler.py`, `_response.py`, `_trigger.py` — transforms
- `dialects/http.py` — Tag, BearerAuth, ApiKeyAuth, OAuth2Auth, Summary, OperationId, Deprecated, ResponseStatus, ResponseHeader, ContentType, CORS, TrustedHost, GZip
- `dialects/telegram.py` — HelpMeta, EditMessage, AnswerCallback, Silent
- `triggers/http.py` — HTTPRouteTrigger
- `triggers/cli.py` — CLITrigger
- `triggers/telegrinder.py` — TelegrindTrigger
- `triggers/lifecycle.py` — StartupTrigger, ShutdownTrigger
- `triggers/exception.py` — ExceptionTrigger
- `triggers/websocket.py` — WebSocketTrigger

### compile/
- `_core.py` — Axes (with scope_layer field), fold_field, FieldConstraints, extract_constraints
- `_lifetime.py` — Tier, App, Request, ScopeLayer
- `_phase.py` — CompilationPhase, PYDANTIC_PHASE, OPENAPI_PHASE, etc.
- `_target.py` — CodecAdapter, TargetCompiler
- `_explain.py` — trace_dict, field_dict, type_dict, explain, explain_field, explain_type, get_field_trace, changed_fields, active_capabilities
- `_capabilities.py` — apply_response_capabilities, find_capability, FastAPICompileContext, FastAPICompilable, FastAPIRouteCompilable, Mount
- `_generate.py` — to_pydantic, to_argparse_args, to_datanode, to_telegram_fields
- `_schema.py` — to_openapi_schema, to_json_schema
- `_rrc.py` — execute_rrc
- `_stateful.py` — execute_stateful_turn, execute_stateful_done, load/save/delete_state
- `_execute.py` — execute_delegate_unified, execute_stateful_unified, execute_immediate_unified, ScopeInjector
- `_request.py` — build_request, build_request_sync
- `_delegate.py` — resolve_handler_params
- `targets/fastapi.py` — fastapi_compile
- `targets/cli.py` — cli_compile, CLIRoute, wrap_rrc_cli
- `targets/telegrinder.py` — telegrinder_compile
- `targets/pure.py` — STARTUP/SHUTDOWN/EXCEPTION/WEBSOCKET_COMPILER, LifecycleRoute, ExceptionRoute, WebSocketRoute, app_scope_lifespan
- `targets/testing.py` — TestRoute, TestApp, testing_compile

### bridge/
- `_core.py` — WireData, handler type aliases
- `_types.py` — RouteData, Extracted
- `_axes.py` — BridgeAxes
- `_registry.py` — BridgeRegistry, FrameworkBridger
- `_extractor.py` — Extractor protocol, compose_extractors
- `_to_wire.py` — ToWire protocol, compose_to_wire
- `_build.py` — build_application()
- `_scan.py` — extract()
- `_capabilities.py` — BridgeCapability, fold_bridge, all purifiers (+ IsolateGlobalAsync, WithContextSync)
- `_introspect.py` — HandlerShape, analyze_handler, unwrap_handler
- `_detect.py` — BodyDetector, DIDetector, DecoratorMapper
- `_codec.py` — make_rrc, make_delegate
- `_signature.py` — HandlerSignature, analyze_signature
- `_patterns.py` — SKIP_DEPRECATED, SKIP_PRIVATE, SKIP_INTERNAL, ASYNC_ALL, DELEGATE_ALL, CLEAN, fastapi_default, fastapi_with_depends
- `_unified.py` — build_extracted
- `bridgers/_base.py` — base bridger
- `bridgers/asgi/__init__.py`, `_capabilities.py` — ASGI bridger
- `bridgers/fastapi/__init__.py` — FastAPI bridger
- `bridgers/fastapi/_capabilities.py` — FastAPI-specific bridge capabilities
- `bridgers/fastapi/_extractors.py` — HTTP/WS/Lifespan/Exception extractors
- `bridgers/fastapi/_routes.py` — HTTPRouteData, WebSocketRouteData, etc.
- `bridgers/fastapi/_to_wire.py` — HTTPToWire, FASTAPI_TO_WIRE
- `bridgers/fastapi/_utils.py` — Depends utilities, FastAPI protocols

### graph/
- `__init__.py` — exports: node, Composer, ScopeFamily, TypedScope, Run, run, compose, CompiledRun, Compiled, graph, visualization utils
- `_compose.py` — Composer (immutable scope+agent_cls pair, compose/retrieve/resolve_params)
- `_family.py` — ScopeFamily[K] (composable type→tier mapping algebra: bind/unbind/types_for/tier_of/materialize)
- `_compiled.py` — CompiledRun, Compiled (uses Composer internally)
- `_run.py` — Run, run (uses Composer internally)

---

## 11. Tracing & Self-Description (`compile/_trace.py`, `compile/_explain.py`)

The compilation process is **self-describing**. Enable tracing to see atom-by-atom how capabilities transform contexts, how phases compose, how codecs get wrapped.

### Enable Tracing

```python
from emergent.wire.compile import Axes, explain

# One line change — everything else works the same
axes = Axes.traced()

Model = to_pydantic(User, axes)
fastapi_app = fastapi.compile(wire_app, axes)

# Now explain what happened
print(explain(axes))
```

**Zero overhead when disabled** — `Axes.default()` sets `trace=None`, the production hot path (`fold()`) is literally unchanged.

### Trace Events

```python
# Compilation hierarchy:
TypeTrace           # one per compile_fields() call
  └─ FieldTrace     # one per field
       └─ FieldPhaseTrace  # one per field × phase
            └─ FoldTrace    # one fold() invocation
                 └─ FoldStep  # one capability dispatch

# Surface events:
ScanEvent           # (trigger, handler) match from scan_and_wrap
WrapEvent           # codec adapter wrapping
CapabilityEvent     # runtime capability application (response transforms, route config)
```

### Explain API

```python
# Dict layer
trace_dict(axes) -> dict[str, Any]             # full compilation trace
field_dict(axes, field_name) -> dict | None     # one field's trace
type_dict(axes, cls_name) -> dict | None        # one type's trace

# Human-readable layer
explain(axes) -> str              # full compilation trace
explain_field(axes, "email") -> str    # one field
explain_type(axes, "User") -> str      # one type

# Structured query (raw trace events)
get_field_trace(axes, "email") -> FieldTrace | None
get_phase_trace(axes, "email", "PydanticContext") -> FieldPhaseTrace | None
changed_fields(axes, "PydanticContext") -> list[str]      # fields that actually changed
active_capabilities(axes, "email") -> list[str]           # caps that had effect
```

**Example output:**
```
=== User ===

  id (int):
    [Identity]
    PydanticContext: Identity (skipped)
    OpenAPIContext:  Identity (skipped)

  email (str):
    [MaxLen, Unique, Description]
    PydanticContext: MaxLen (protocol) [changed] | Unique (skipped) | Description (skipped)
    OpenAPIContext:  MaxLen (protocol) [changed] | Unique (skipped) | Description (protocol) [changed]

=== Scan ===
  HTTPRouteTrigger(POST, /users) -> RequestResponseCodec  [3 caps]

=== Wrap ===
  RequestResponseCodec -> FastAPIRoute  (POST /users)
```

### Programmatic Inspection

```python
ft = get_field_trace(axes, "email")
for phase in ft.phases:
    print(f"Phase: {phase.phase}")
    for step in phase.fold.steps:
        if step.changed:
            print(f"  {step.item_type}: {step.context_before} -> {step.context_after}")
```

### TraceCollector Protocol

```python
class TraceCollector(Protocol):
    def fold_step(self, step: FoldStep) -> None: ...
    def fold_complete(self, trace: FoldTrace) -> None: ...
    def field_phase(self, trace: FieldPhaseTrace) -> None: ...
    def field_complete(self, trace: FieldTrace) -> None: ...
    def type_complete(self, trace: TypeTrace) -> None: ...
    def scan(self, event: ScanEvent) -> None: ...
    def wrap(self, event: WrapEvent) -> None: ...
    def capability(self, event: CapabilityEvent) -> None: ...

# Built-in: ListCollector (accumulates to lists, used by explain())
# Custom: implement protocol for streaming, logging, etc.
axes = Axes.traced(my_custom_collector)
```

### Open-World Design

Tracing is open-world — any code that uses `fold()` gets tracing for free:

```python
from emergent.wire.compile import fold

# Schema compilation (compile_fields uses fold internally)
compiled = compile_fields(User, axes, [PYDANTIC_PHASE, OPENAPI_PHASE])

# Surface capability compilation — fold() directly
ctx = fold(handler.capabilities, ctx, FastAPICompilable, "compile_fastapi",
           trace=axes.trace)

# Custom target — same pattern, tracing automatic
ctx = fold(handler.capabilities, ctx, MyTargetCompilable, "compile_my_target",
           trace=axes.trace)
```

No special `apply_*` wrapper functions needed. `fold()` IS the one universal primitive for both schema and surface capability compilation.

### Integration Points

| Function | Trace Emission | Events |
|----------|---------------|--------|
| `fold(..., trace=axes.trace)` | When `trace` kwarg set | FoldStep, FoldTrace |
| `fold()` (no trace kwarg) | Zero overhead | — |
| `compile_fields()` | Checks `axes.trace` internally | FieldPhaseTrace, FieldTrace, TypeTrace |
| `scan_and_wrap()` | Checks `axes.trace` internally | ScanEvent, WrapEvent |
| `apply_response_capabilities()` | Runtime, no tracing | — |

---

## 12. Key Design Principles

1. **Capabilities over inheritance**: All behavior via `Annotated[T, Cap1, Cap2, ...]`
2. **fold_field is THE primitive**: Every compilation = fold capabilities into context
3. **Syntax/semantics separation**: Queries/annotations are pure data, interpreters give meaning
4. **Open-world dispatch**: `TargetCompiler` / `QueryDialect` / `BridgeRegistry` — add new types without modifying existing code
5. **No global state**: `Axes` passed explicitly to all compiler functions
6. **Symmetric compile/bridge**: `compile: Application → Framework`, `bridge: Framework → Application`
7. **One type, N projections**: Same dataclass field has CLI, HTTP, TG, SQL annotations simultaneously
8. **Self-describing**: Every axis has an explain module (schema, surface, storage, query, compile). Two-layer pattern: dict-returning (structured data) + human-readable (formatted strings). Open-world: unknown types get generic fallback, never crash. Handler dispatch via `Mapping[type, Handler]` — extensible by users
