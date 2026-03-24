# Compilation phases and the algebra

You wrote a capability. Now build the compiler infrastructure it plugs into.

## CompilationPhase

A phase is the triple (context_type, protocol, initial_factory):

```python
from emergent.wire.compile._phase import CompilationPhase

@dataclass(frozen=True, slots=True)
class GraphQLContext:
    field_name: str
    field_type: type
    graphql_type: str | None = None

@runtime_checkable
class GraphQLCompilable(Protocol):
    def compile_graphql(self, ctx: GraphQLContext) -> GraphQLContext: ...

GRAPHQL_PHASE = CompilationPhase(
    GraphQLContext,
    GraphQLCompilable,
    lambda name, tp: GraphQLContext(name, tp, _type_map.get(tp)),
)
```

Three things. Method name auto-derived from protocol (`compile_graphql`). No strings to sync.

Use it:

```python
fields = compile_fields(User, axes, [GRAPHQL_PHASE])
fields[0][GRAPHQL_PHASE].graphql_type  # "String"
```

Run alongside built-in phases — phases are independent:

```python
fields = compile_fields(User, axes, [PYDANTIC_PHASE, GRAPHQL_PHASE])
# Both contexts available on each field
```

## SchemaCompiler

Phases compose into compilers:

```python
from emergent.wire.compile._phase import SchemaCompiler

GRAPHQL_SCHEMA = SchemaCompiler(phases=(GRAPHQL_PHASE,))
FULLSTACK = FASTAPI_SCHEMA + GRAPHQL_SCHEMA + STORAGE_SCHEMA
```

The algebra is real — these are proven laws, tested with hypothesis:

```python
# Identity
A + EMPTY == A
EMPTY + A == A

# Idempotence
A + A == A

# Associativity
(A + B) + C == A + (B + C)

# Override (right-biased)
A | B  # B's phases replace A's on conflict

# Restriction
A - B  # removes B's phases from A

# Intersection
A & B  # keeps only shared phases
```

This isn't analogy. `+` is left-biased union, `|` is right-biased merge, `-` is restriction, `&` is intersection. All keyed by `context_type`. Tests verify on random compiler combinations.

### Why this matters

You can build compilers by combining existing ones:

```python
# Start with FastAPI (Pydantic + OpenAPI)
FULLSTACK = FASTAPI_SCHEMA

# Add your GraphQL phase
FULLSTACK = FULLSTACK + GRAPHQL_PHASE

# Add storage
FULLSTACK = FULLSTACK + STORAGE_SCHEMA

# Compile everything in one pass
ec = FULLSTACK.compile(User, axes)
```

One pass. All phases run. Each field gets contexts for Pydantic, OpenAPI, GraphQL, and Storage.

## TargetCompiler

Phases compile fields. TargetCompiler compiles endpoints:

```python
from emergent.wire.compile._target import TargetCompiler, CodecBinding

MQTT_COMPILER = TargetCompiler(
    trigger_type=MQTTTrigger,
    adapters=(
        CodecBinding(RequestResponseCodec, mqtt_from_rrc),
        CodecBinding(DelegateCodec, mqtt_from_delegate),
    ),
    pipeline_protocol=MQTTPipelineCompilable,
    pipeline_method="compile_mqtt_pipeline",
    assemble=assemble_mqtt_route,
)
```

Same algebra:

```python
# Extend with new codec support
MQTT_COMPILER + CodecBinding(StreamingCodec, mqtt_from_streaming)

# Override a binding
MQTT_COMPILER | CodecBinding(RequestResponseCodec, better_mqtt_from_rrc)

# Remove codec support
MQTT_COMPILER - StreamingCodec
```

The pattern: `scan_and_wrap(app, axes)` iterates endpoints, matches triggers and codecs, folds capabilities through the pipeline, assembles routes.

## Compilers over compilers

SchemaCompiler compiles fields. TargetCompiler compiles endpoints. But derive generates both:

```python
@schema_meta(http_crud("/users", Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
```

`compile_derive(User)` → fold over `@schema_meta` capabilities → generates OpSpecs → materialize into Endpoints → `targets.fastapi.compile(app)` → fold endpoints through TargetCompiler.

Three levels of fold:
1. Capabilities → field contexts (SchemaCompiler)
2. Entity capabilities → OpSpecs → Endpoints (derive)
3. Endpoints → framework routes (TargetCompiler)

Same function. Same algebra. Different data. This is the fractal.

---

← [encoding.md](encoding.md) | → [compiler-deep-dive.md](compiler-deep-dive.md)
