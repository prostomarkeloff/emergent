# Compiler Deep-Dive: Developing & Tuning Custom Compilers

> Every example in this guide is tested in `tests/test_compiler_guide.py` (62 tests, all pass).

---

## The Mental Model

emergent compiles your application IR into runtime artifacts. The compiler infrastructure is built on **one primitive** — `fold()` — and **three concepts**:

```
IR (Application)  →  capabilities (Annotated metadata)  →  compiler (fold + assemble)  →  artifact
```

The FastAPI adapter, CLI adapter, Telegrinder adapter, and testing adapter are all built from the same primitives. This guide shows you how to build your own — from a single custom compilation phase all the way to a complete target compiler with `mqtt_compile()` that works exactly like `fastapi_compile()`.

---

## Level 1: Custom Compilation Phase

A **CompilationPhase** is the triple `(ContextType, Protocol, initial)`:

```python
@dataclass(frozen=True, slots=True)
class GraphQLContext:
    """Per-field context for GraphQL type compilation."""
    field_name: str
    field_type: type
    graphql_type: str | None = None
    nullable: bool = True
    description: str | None = None
    deprecation_reason: str | None = None


@runtime_checkable
class GraphQLCompilable(Protocol):
    def compile_graphql(self, ctx: GraphQLContext) -> GraphQLContext: ...


def _graphql_initial(name: str, field_type: type) -> GraphQLContext:
    type_map = {str: "String", int: "Int", float: "Float", bool: "Boolean"}
    return GraphQLContext(
        field_name=name,
        field_type=field_type,
        graphql_type=type_map.get(field_type),
    )

GRAPHQL_PHASE = CompilationPhase(
    GraphQLContext, GraphQLCompilable, _graphql_initial,
)
```

**Three things to define:**
1. **Context** — frozen dataclass accumulating compilation state per field
2. **Protocol** — one `compile_*` method that capabilities implement
3. **Initial** — `(field_name, field_type) → Context` factory

The method name is **auto-derived** from the protocol's `compile_*` method. No strings to keep in sync.

**Use it:**

```python
@dataclass
class User:
    name: str
    age: int

axes = Axes.default()
fields = compile_fields(User, axes, [GRAPHQL_PHASE])
fields[0][GRAPHQL_PHASE].graphql_type  # "String"
fields[1][GRAPHQL_PHASE].graphql_type  # "Int"
```

**Run alongside built-in phases** — phases are independent, order doesn't matter:

```python
fields = compile_fields(User, axes, [PYDANTIC_PHASE, GRAPHQL_PHASE])
for fc in fields:
    pydantic_ctx = fc[PYDANTIC_PHASE]   # PydanticContext
    graphql_ctx = fc[GRAPHQL_PHASE]     # GraphQLContext
```

---

## Level 2: Multi-Phase Capabilities

A capability is a frozen dataclass with one or more `compile_*` methods. **One definition site — N compilation targets:**

```python
@dataclass(frozen=True, slots=True)
class NonNull(UniversalCapability):
    """ONE capability → THREE compile_* methods → THREE compilation targets."""

    def compile_graphql(self, ctx: GraphQLContext) -> GraphQLContext:
        return replace(ctx, nullable=False)

    def compile_pydantic(self, ctx: PydanticContext) -> PydanticContext:
        return pydantic_field(ctx, lambda fi: fi.metadata.append({"required": True}))

    def compile_argparse(self, ctx: ArgparseContext) -> ArgparseContext:
        return argparse_arg(ctx, required=True)
```

**Key rule:** capabilities must inherit from `UniversalCapability` (or `SchemaCapability`, or a dialect-specific base) so that `inspect_dataclass` picks them up from `Annotated`.

**Cross-target capability:**

```python
@dataclass(frozen=True, slots=True)
class GQLDescription(UniversalCapability):
    text: str

    def compile_graphql(self, ctx: GraphQLContext) -> GraphQLContext:
        return replace(ctx, description=self.text)

    def compile_openapi(self, ctx: OpenAPIContext) -> OpenAPIContext:
        return openapi_schema(ctx, description=self.text)
```

**Usage:**

```python
@dataclass
class Product:
    name: Annotated[str, NonNull(), GQLDescription("Product name")]
```

When `compile_fields` runs with `[GRAPHQL_PHASE, OPENAPI_PHASE, ARGPARSE_PHASE]`:
- `NonNull` fires `compile_graphql`, `compile_pydantic`, `compile_argparse`
- `GQLDescription` fires `compile_graphql`, `compile_openapi`
- Each phase sees only its own `compile_*` — open-world dispatch via `isinstance`

---

## Level 3: Custom Handlers (Override Protocol Dispatch)

Sometimes a capability type doesn't implement the protocol, but you want to intercept it in a specific phase. Use **handlers**:

```python
@dataclass(frozen=True, slots=True)
class SpecialFormat(UniversalCapability):
    """Does NOT have compile_graphql — but handler intercepts it."""
    pattern: str


def special_format_handler(cap: Capability, ctx: GraphQLContext) -> GraphQLContext:
    assert isinstance(cap, SpecialFormat)
    return replace(ctx, description=f"format: {cap.pattern}")


phase_with_handler = GRAPHQL_PHASE.with_handlers(
    {SpecialFormat: special_format_handler}
)
```

**How it works in `fold()`:**
1. For each item, check `handlers` dict by `type(item)` — if present, call handler
2. Otherwise, check `isinstance(item, protocol)` — if True, call `compile_*`
3. Otherwise, **silently skip** (open-world)

Handlers take priority over protocol dispatch. They're useful for:
- Intercepting third-party capabilities you can't modify
- Adding phase-specific behavior to generic capabilities
- Testing/debugging with mock handlers

---

## Level 4: SchemaCompiler Algebra

`SchemaCompiler` is an ordered set of phases with algebraic operations:

```python
GRAPHQL_SCHEMA = SchemaCompiler(phases=(GRAPHQL_PHASE,))

# Compose: 3 phases (Pydantic + OpenAPI + GraphQL)
fullstack = FASTAPI_SCHEMA + GRAPHQL_SCHEMA

# Override right-biased
custom = GRAPHQL_SCHEMA | SchemaCompiler(phases=(my_custom_phase,))

# Remove
reduced = fullstack - GRAPHQL_PHASE

# Intersect
common = (FASTAPI_SCHEMA + GRAPHQL_SCHEMA) & (GRAPHQL_SCHEMA + CLI_SCHEMA)
# → only GRAPHQL_PHASE

# Lookup
phase = fullstack[GraphQLContext]
```

**Laws:**
- `A + A == A` (idempotent, keyed by `context_type`)
- `(A + B) + C == A + (B + C)` (associative)
- `A + empty == A` (identity)

**Use `.compile()` for full entity compilation:**

```python
ec = fullstack.compile(User, axes)
for fc in ec:
    fc[PYDANTIC_PHASE]   # PydanticContext
    fc[OPENAPI_PHASE]    # OpenAPIContext
    fc[GRAPHQL_PHASE]    # GraphQLContext
```

---

## Level 5: `fold()` — The Universal Primitive

Everything is built on one function:

```python
def fold[Ctx](
    items: Iterable[Any],
    initial: Ctx,
    protocol: type,
    method: str,
    handlers: Mapping[type, ItemHandler[Ctx]] | None = None,
    *,
    trace: TraceCollector | None = None,
) -> Ctx
```

**Properties:**
- **Open-world:** unknown items silently skipped
- **Left-to-right:** last matching capability's effect wins for overwritten fields
- **Zero-overhead tracing:** `trace=None` → one branch prediction, no allocations
- **Handler priority:** `handlers[type(item)]` checked before `isinstance(item, protocol)`

```python
# Schema compilation: fold over field capabilities
ctx = fold_field(field_info, initial_ctx, PydanticCompilable, "compile_pydantic")

# Target compilation: fold over surface capabilities
ctx = fold(capabilities, wrap_ctx, FastAPIPipelineCompilable, "compile_fastapi_pipeline")

# Derivation: fold over derivation steps
ctx = fold(steps, schema_ctx, SchemaDerivable, "derive_schema")
```

Same primitive. Three domains. Zero code duplication.

---

## Level 6: Traced Compilation

Enable tracing to see exactly what happens during compilation:

```python
from emergent.wire.compile._trace import ListCollector

collector = ListCollector()
axes = Axes.traced(collector)
compile_fields(User, axes, [GRAPHQL_PHASE])

# What was recorded:
collector.field_phases    # per-field per-phase traces
collector.fold_steps      # every fold step (per item)
collector.scan_events     # target compiler scan events
collector.wrap_events     # target compiler wrap events
```

Each `FieldPhaseTrace` includes a `FoldTrace` with per-item steps:

```python
fp = collector.field_phases[0]
fp.field_name     # "name"
fp.phase          # "GraphQLContext"
fp.fold.items_applied  # how many capabilities matched
fp.fold.steps     # FoldStep per capability (before/after context, changed flag)
```

Use `explain(axes)` for human-readable output.

---

## Level 7: TargetCompiler Algebra

`TargetCompiler` follows the same algebraic pattern as `SchemaCompiler`, but keyed by `codec_type`:

```python
compiler = TargetCompiler(
    trigger_type=MQTTTrigger,
    adapters=(
        CodecBinding(MQTTMessageCodec, mqtt_from_codec),
    ),
    pipeline_protocol=MQTTPipelineCompilable,
    pipeline_method="compile_mqtt_pipeline",
    assemble=assemble_mqtt_route,
)

# Add new codec
extended = compiler.with_binding(MQTTBinaryCodec, binary_from_codec)

# Replace how a codec is processed
replaced = compiler.replace_binding(MQTTMessageCodec, traced_from_codec)

# Remove codec support
minimal = compiler.without_binding(MQTTBinaryCodec)

# Algebra
combined = compiler_a + compiler_b   # left-biased union
merged = compiler_a | compiler_b     # right-biased override
reduced = compiler_a - CodecType     # remove by type
common = compiler_a & compiler_b     # intersection
```

---

## Level 8: Full Custom Target Compiler

A target compiler has 5 parts. Here's a complete MQTT example:

### 1. Trigger — WHERE things happen

```python
@dataclass(frozen=True, slots=True)
class MQTTTrigger:
    topic: str
    qos: int = 0
```

### 2. Codec — HOW data flows

```python
@dataclass(frozen=True, slots=True)
class MQTTPayloadCodec:
    op_type: type
    response_type: type
```

### 3. WrapContext + Pipeline Protocol — compile-time state

```python
@dataclass(frozen=True, slots=True)
class MQTTFullWrapContext:
    topic: str = ""
    qos: int = 0
    op_type: type | None = None
    response_type: type | None = None
    execute: Callable[..., Awaitable[object]] | None = None
    retain: bool = False
    max_payload_size: int | None = None


@runtime_checkable
class MQTTFullPipelineCompilable(Protocol):
    def compile_mqtt_full_pipeline(
        self, ctx: MQTTFullWrapContext,
    ) -> MQTTFullWrapContext: ...
```

### 4. from_codec — seed context from codec data

```python
def mqtt_payload_from_codec(
    codec: MQTTPayloadCodec,
    trigger: MQTTTrigger,
) -> MQTTFullWrapContext:
    return MQTTFullWrapContext(
        topic=trigger.topic,
        qos=trigger.qos,
        op_type=codec.op_type,
        response_type=codec.response_type,
        execute=_mqtt_execute,
    )
```

### 5. Assembler — context → final route artifact

```python
@dataclass(frozen=True, slots=True)
class MQTTFullRoute:
    topic: str
    qos: int
    retain: bool
    max_payload_size: int | None
    handler: Callable[[dict[str, object]], Awaitable[object]]


def assemble_mqtt_full_route(
    ctx: MQTTFullWrapContext,
    handler: Handler[MQTTPayloadCodec],
    axes: Axes,
) -> MQTTFullRoute:
    execute_fn = ctx.execute

    async def _handle_message(payload: dict[str, object]) -> object:
        return await execute_fn(handler, payload)

    return MQTTFullRoute(
        topic=ctx.topic,
        qos=ctx.qos,
        retain=ctx.retain,
        max_payload_size=ctx.max_payload_size,
        handler=_handle_message,
    )
```

### Bundle into TargetCompiler

```python
MQTT_FULL_COMPILER = TargetCompiler(
    trigger_type=MQTTTrigger,
    adapters=(
        CodecBinding(MQTTPayloadCodec, mqtt_payload_from_codec),
    ),
    pipeline_protocol=MQTTFullPipelineCompilable,
    pipeline_method="compile_mqtt_full_pipeline",
    assemble=assemble_mqtt_full_route,
)
```

### Pipeline capabilities

```python
@dataclass(frozen=True, slots=True)
class MQTTRetain(SurfaceCapability):
    def compile_mqtt_full_pipeline(self, ctx: MQTTFullWrapContext) -> MQTTFullWrapContext:
        return replace(ctx, retain=True)

@dataclass(frozen=True, slots=True)
class MQTTMaxPayload(SurfaceCapability):
    size: int
    def compile_mqtt_full_pipeline(self, ctx: MQTTFullWrapContext) -> MQTTFullWrapContext:
        return replace(ctx, max_payload_size=self.size)

@dataclass(frozen=True, slots=True)
class MQTTQoS(SurfaceCapability):
    level: int
    def compile_mqtt_full_pipeline(self, ctx: MQTTFullWrapContext) -> MQTTFullWrapContext:
        return replace(ctx, qos=self.level)
```

---

## Level 9: Entity-Level Fold (EntityFold)

Field-level compilation handles per-field metadata. **EntityFold** handles entity-level metadata (via `@schema_meta`):

```python
@dataclass(frozen=True, slots=True)
class GraphQLTypeContext:
    class_name: str
    type_name: str | None = None
    interfaces: tuple[str, ...] = ()

@runtime_checkable
class GraphQLTypeCompilable(Protocol):
    def compile_graphql_type(self, ctx: GraphQLTypeContext) -> GraphQLTypeContext: ...

GRAPHQL_TYPE_FOLD = EntityFold(
    GraphQLTypeContext, GraphQLTypeCompilable,
    lambda name: GraphQLTypeContext(class_name=name),
)

# Attach to field-level phase
GRAPHQL_PHASE_WITH_ENTITY = GRAPHQL_PHASE.with_entity(GRAPHQL_TYPE_FOLD)
```

**Entity-level capabilities:**

```python
@dataclass(frozen=True, slots=True)
class GQLTypeName:
    name: str
    def compile_graphql_type(self, ctx: GraphQLTypeContext) -> GraphQLTypeContext:
        return replace(ctx, type_name=self.name)

@dataclass(frozen=True, slots=True)
class GQLInterface:
    interface: str
    def compile_graphql_type(self, ctx: GraphQLTypeContext) -> GraphQLTypeContext:
        return replace(ctx, interfaces=(*ctx.interfaces, self.interface))
```

**Use with `@schema_meta`:**

```python
@schema_meta(GQLTypeName("UserType"), GQLInterface("Node"))
@dataclass
class User:
    id: int
    name: str

ec = compile_entity(User, axes, [GRAPHQL_PHASE_WITH_ENTITY])
type_ctx = ec[GRAPHQL_TYPE_FOLD]
type_ctx.type_name    # "UserType"
type_ctx.interfaces   # ("Node",)
```

---

## Level 10: Full E2E — `mqtt_compile()` like `fastapi_compile()`

This is the final level: build a wire `Application`, compile it to an `MQTTApp`, dispatch messages.

### The compiled artifact

```python
@dataclass
class MQTTApp:
    subscriptions: tuple[MQTTFullRoute, ...]

    async def dispatch(self, topic: str, payload: dict[str, object]) -> object:
        for sub in self.subscriptions:
            if self._topic_matches(sub.topic, topic):
                if sub.max_payload_size is not None:
                    encoded = json.dumps(payload).encode()
                    if len(encoded) > sub.max_payload_size:
                        raise ValueError(f"Payload too large")
                return await sub.handler(payload)
        raise KeyError(f"No subscription for topic: {topic}")
```

### The compile function

```python
def mqtt_compile(
    app: Application,
    axes: Axes | None = None,
    compiler: TargetCompiler[MQTTTrigger] | None = None,
) -> MQTTApp:
    axes = axes or Axes.default()
    _compiler = compiler or MQTT_FULL_COMPILER

    routes: list[MQTTFullRoute] = []
    for trigger, handler, route in _compiler.scan_and_wrap(app, axes):
        routes.append(route)

    return MQTTApp(subscriptions=tuple(routes))
```

**That's the entire compile function.** `scan_and_wrap` does all the work:
1. Scans the Application for (MQTTTrigger, MQTTPayloadCodec) pairs
2. For each: `from_codec(codec, trigger) → ctx`
3. `fold(capabilities, ctx, MQTTFullPipelineCompilable, "compile_mqtt_full_pipeline")`
4. `assemble(ctx, handler, axes) → MQTTFullRoute`

### Wire the application

```python
# Domain
@dataclass(frozen=True, slots=True)
class RecordReading(Op[Ack, str]):
    device_id: str
    value: float
    unit: str

async def handle_record(req: RecordReading) -> Result[Ack, str]:
    reading = SensorReading(req.device_id, req.value, req.unit)
    store[req.device_id] = reading
    return Ok(Ack(ok=True, message=f"recorded {req.device_id}"))

# Build runner
runner = ops().on(RecordReading, handle_record).on(GetLastReading, handle_get_last).compile()

# Build application — same API as FastAPI target
app = application().mount(
    endpoint(runner)
        .expose(
            MQTTTrigger("sensors/+/record", qos=1),
            MQTTPayloadCodec(RecordReading, Ack),
            MQTTRetain(),
            MQTTMaxPayload(4096),
        )
        .expose(
            MQTTTrigger("sensors/+/last"),
            MQTTPayloadCodec(GetLastReading, SensorReading),
        )
)

# Compile — just like fastapi_compile(app)
mqtt = mqtt_compile(app)

# Dispatch — your runtime
result = await mqtt.dispatch("sensors/temp-01/record", {
    "device_id": "temp-01", "value": 23.5, "unit": "celsius",
})
assert result.unwrap().ok is True
```

### What you get for free

- **Tracing:** pass `Axes.traced()` → all scan/wrap/fold events recorded
- **Capability pipeline:** `MQTTRetain`, `MQTTMaxPayload`, `MQTTQoS` fold into every route
- **Open-world codecs:** `MQTT_FULL_COMPILER.with_binding(MQTTBinaryCodec, ...)` — no emergent changes
- **Compiler algebra:** `+`, `|`, `-`, `&` on `TargetCompiler` to compose/override/restrict
- **Testing:** use the same Application with `testing_compile()` for unit tests
- **Multi-target:** same Application compiles to FastAPI, CLI, MQTT, anything

---

## Tuning Reference

### When to use what

| You want to... | Use... |
|---|---|
| Add field metadata for a new output format | `CompilationPhase` |
| Make a capability affect multiple targets | Multiple `compile_*` methods on one dataclass |
| Override how a capability compiles in one phase | `phase.with_handlers({CapType: handler_fn})` |
| Combine phases for a fullstack compiler | `SchemaCompiler` algebra (`+`, `\|`) |
| Project Application IR to a new runtime | `TargetCompiler` with from_codec + fold + assemble |
| Add entity-level metadata | `EntityFold` + `@schema_meta` |
| Add a new codec to existing target | `compiler.with_binding(NewCodec, from_codec_fn)` |
| Replace how a codec processes | `compiler.replace_binding(ExistingCodec, new_fn)` |
| Debug compilation | `Axes.traced()` + `ListCollector` |

### The 3-step target compilation pipeline

Every target compiler does the same thing:

```
from_codec(codec, trigger) → WrapContext
    ↓
fold(capabilities, ctx, PipelineProtocol, "compile_*_pipeline")
    ↓
assemble(ctx, handler, axes) → Route
```

`from_codec` reads DATA from the codec (types, trigger config).
`fold` applies BEHAVIOR from capabilities (middleware, auth, caching).
`assemble` builds the ARTIFACT for the target runtime.

### Capability inheritance hierarchy

```
Capability (root Protocol)
├── SchemaAxisCapability     ← for Annotated field metadata
│   ├── UniversalCapability  ← visible to ALL phases
│   └── dialect bases...     ← per-dialect
└── SurfaceCapability        ← for endpoint-level behavior
    ├── compile_fastapi_pipeline(ctx) → ctx
    ├── compile_cli_pipeline(ctx) → ctx
    ├── compile_mqtt_full_pipeline(ctx) → ctx   ← your custom one
    └── ...
```

**Schema capabilities** go in `Annotated[type, Cap()]` → picked up by `inspect_dataclass`.
**Surface capabilities** go in `.expose(trigger, codec, Cap())` → picked up by `scan_and_wrap`.

### Performance tuning

- `fold()` with `trace=None` is one isinstance check per item per pass — fast
- `compile_fields` runs all phases in **one pass** over fields (not N passes)
- `SchemaCompiler.compile()` calls `compile_entity()` once for all phases
- `TargetCompiler.scan_and_wrap()` is a generator — lazy, no pre-allocation
- For schema compilation: phases are order-independent (each fold is isolated)
- For target compilation: capabilities fold left-to-right (last write wins)

### Error patterns

| Symptom | Cause | Fix |
|---|---|---|
| Capability not picked up from Annotated | Missing inheritance from `SchemaAxisCapability` | Inherit `UniversalCapability` or dialect base |
| `compile_*` method not called | Capability doesn't `isinstance` match the phase protocol | Add the `compile_*` method to capability |
| Handler not firing | Handler keyed by wrong type | Key by `type(capability_instance)`, not base class |
| Duplicate context_type error | Two phases with same context type | Use `SchemaCompiler` algebra to merge/override |
| `NameError` in Annotated with local classes | `from __future__ import annotations` + `get_type_hints` | Define Annotated dataclasses at module level |
