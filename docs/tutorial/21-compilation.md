# The Universal Fold

You've seen `fastapi.compile(app)` a dozen times in this tutorial. Magic function, framework out. A wire Application full of abstract endpoints, triggers, and codecs goes in. A working FastAPI app comes out. But what happens inside? How does one function turn your annotated dataclasses into Pydantic models, OpenAPI schemas, argparse parsers, and Telegram input handlers --- all from the same source?

The answer is `fold`. The same fold, everywhere.

---

## The primitive

Open `emergent/wire/compile/_core.py` and you'll find this:

```python
def fold(
    items: Iterable[Any],
    initial: Ctx,
    protocol: type,
    method: str,
    handlers: Mapping[type, ItemHandler[Ctx]] | None = None,
    *,
    trace: TraceCollector | None = None,
) -> Ctx:
```

That's the entire compilation engine. It takes a sequence of items (capabilities on a field), a starting context, a protocol to check against, and a method name. For each item that implements the protocol, it calls the method and threads the context through. Items that don't implement the protocol? Silently skipped. This is what makes emergent open-world: add a new capability, and old compilers don't break --- they just ignore what they don't recognize.

The inner loop is almost embarrassingly simple:

```python
ctx = initial
for item in items:
    if handlers and item.__class__ in handlers:
        ctx = handlers[item.__class__](item, ctx)
    elif isinstance(item, protocol):
        ctx = getattr(item, method)(ctx)
return ctx
```

No registry. No dispatch table. Just `isinstance` and `getattr`. Each capability that speaks the right protocol gets to modify the context. Each one that doesn't gets passed over.

## From fold to field

`fold_field` is a thin wrapper --- it feeds a field's capabilities into `fold`:

```python
ctx = fold_field(field_info, PydanticContext(...), PydanticCompilable, "compile_pydantic")
```

Your field `email: Annotated[str, MaxLen(255), Unique, openapi.Format("email")]` has three capabilities. The Pydantic compiler asks each one: "Do you implement `PydanticCompilable`?" `MaxLen` does --- it sets `max_length` on the context. `Unique` doesn't (it's a storage concern) --- skipped. `openapi.Format` doesn't (it's an OpenAPI concern) --- skipped.

Run the same field through the OpenAPI compiler, and the story flips. `openapi.Format` speaks `OpenAPICompilable` and sets the format. `MaxLen` speaks it too (it contributes `maxLength` to the JSON schema). `Unique` stays silent.

Same capabilities. Different questions. Different answers.

## Phases: reified compilation passes

A `CompilationPhase[Ctx]` packages the triple --- context type, protocol, initial factory --- into a first-class value:

```python
from emergent.wire.compile._phase import CompilationPhase

PYDANTIC_PHASE = CompilationPhase(
    PydanticContext, PydanticCompilable, _pydantic_initial,
)
OPENAPI_PHASE = CompilationPhase(
    OpenAPIContext, OpenAPICompilable, _openapi_initial,
)
```

A phase is identified by its context type --- no strings, no names. The compile method is auto-derived from the protocol's `compile_*` method. And phases compose:

```python
FASTAPI_SCHEMA = SchemaCompiler(phases=(PYDANTIC_PHASE, OPENAPI_PHASE))

ec = FASTAPI_SCHEMA.compile(User, axes)
for fc in ec:
    pydantic_ctx = fc[PYDANTIC_PHASE]   # typed PydanticContext
    openapi_ctx = fc[OPENAPI_PHASE]     # typed OpenAPIContext
```

`compile_entity` runs all phases in one pass over the fields. Each field gets each phase's fold applied independently. Phases are order-independent --- each fold is isolated.

`SchemaCompiler` supports algebraic operations too. Left-biased union (`+`), right-biased merge (`|`), restriction (`-`), intersection (`&`). You can build a fullstack compiler from pieces:

```python
FULLSTACK = FASTAPI_SCHEMA + STORAGE_SCHEMA
```

## Your own compilation target

Here's the real payoff. You can create a new compilation target without touching emergent:

```python
from dataclasses import dataclass
from typing import Protocol
from emergent.wire.compile._phase import CompilationPhase

@dataclass(frozen=True, slots=True)
class GraphQLContext:
    field_name: str
    field_type: type
    graphql_type: str | None = None

class GraphQLCompilable(Protocol):
    def compile_graphql(self, ctx: GraphQLContext) -> GraphQLContext: ...

GRAPHQL_PHASE = CompilationPhase(
    GraphQLContext, GraphQLCompilable,
    initial=lambda n, t: GraphQLContext(n, t),
)
```

That's a complete compilation phase. Any capability that implements `compile_graphql` now participates in GraphQL compilation. Your existing `MaxLen(50)` capability? If you add a `compile_graphql` method to it, it starts contributing to GraphQL schemas. If you don't, it's silently skipped. Open-world.

## Tracing: compilation explains itself

Swap `Axes.default()` for `Axes.traced()` and every fold step gets recorded:

```python
from emergent.wire.compile._core import Axes
from emergent.wire.compile._explain import explain

axes = Axes.traced()
ec = FASTAPI_SCHEMA.compile(User, axes)
print(explain(axes))
```

The output shows every field, every phase, every capability --- which ones were applied, which were skipped, which actually changed the context. Zero overhead when tracing is off (just one branch prediction in the hot path). Full self-description when you need it.

You can also drill into specifics:

```python
from emergent.wire.compile._explain import explain_field, active_capabilities

print(explain_field(axes, "email"))
print(active_capabilities(axes, "email"))
```

## The insight

Compilation is a catamorphism --- a fold over the free algebra of capabilities. Each capability is a generator; fold is the universal consumer. The same capability can participate in many compilations (Pydantic AND OpenAPI AND CLI AND your custom GraphQL) because each compiler asks a different question (different protocol, different method). This is why capabilities commute within an axis --- fold doesn't depend on order.

`fastapi.compile(app)` isn't magic. It's fold, all the way down.

---

**Next:** [Conversations ->](22-stateful-codecs.md)
