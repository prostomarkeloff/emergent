# 1. Building Abstractions with Capabilities

> The acts of the mind, wherein it exerts its power over simple ideas, are chiefly these three: 1. Combining several simple ideas into one compound one, and thus all complex ideas are made. 2. The second is bringing two ideas, whether simple or complex, together, and setting them by one another so as to take a view of them at once, without uniting them into one, by which it gets all its ideas of relations. 3. The third is separating them from all other ideas that accompany them in their real existence: this is called abstraction, and thus all its general ideas are made.
>
> — John Locke, *An Essay Concerning Human Understanding* (1690)

There is a fact about your system that you must express five times: in the data model, the API schema, the database DDL, the validation layer, and the CLI help text. Each expression uses a different notation. None of them knows about the others. When the fact changes, you edit five files. When you forget one, the system develops a fracture — the kind that passes tests but corrupts data in production.

This is the *scattered meaning* problem: the same fact about a field must be manually transcribed into different formalisms that cannot share a source of truth. It is not a tooling problem. It is a *language* problem — the absence of a primitive that lets you state a fact once and have it interpreted by different evaluation regimes.

This chapter introduces that primitive. We call it a *capability*: a frozen dataclass that carries a fact and knows how to compile itself for each target. The mechanism that consumes capabilities is called *fold*: six lines of Python that iterate, dispatch by protocol, and accumulate a context. Together they form a complete system for building abstractions about software meaning — abstractions that scale from a single field constraint to a full REST API.

We will proceed from simple to complex. By the end of this chapter, you will be able to trace fold in your head, predict what a set of capabilities will produce, and understand why capabilities are not annotations on data but a primitive that generates *all* computation through fold.

---

## 1.1 The Elements of Compilation

Every powerful compilation framework provides three mechanisms:

- **primitive capabilities** — the simplest facts the framework is concerned with,
- **means of combination** — by which compound descriptions are built from simpler ones, and
- **means of abstraction** — by which compound descriptions can be named and manipulated as units.

In emergent, we deal with two kinds of elements: capabilities and contexts. Capabilities are the facts we want to express — "maximum length is 255," "this field is the primary key," "this field must be unique." Contexts are the accumulation targets that carry the compilation state for each target — PydanticContext, OpenAPIContext, SQLAlchemyContext. Each fold begins with an initial context and ends with a transformed one. The capability is the input. The context is the output. fold is the process that connects them.

### 1.1.1 Capabilities

Consider a field on a dataclass:

```python
email: Annotated[str, MaxLen(255)]
```

`MaxLen(255)` is a capability. It is a frozen dataclass:

```python
@dataclass(frozen=True, slots=True)
class MaxLen(UniversalCapability):
    value: int
```

One field. One fact: this string has a maximum length of 255. The capability is *data* — you can print it, compare it, put it in a set. `MaxLen(255) == MaxLen(255)` is True. `MaxLen(100) == MaxLen(255)` is False. There is no hidden state, no side effects, no identity apart from the value.

If you present fold with this capability and a Pydantic context, fold produces a new context with the constraint applied:

```python
ctx = PydanticContext(field_name="email", field_type=str, field_info=FieldInfo())
result = fold([MaxLen(255)], ctx, PydanticCompilable, "compile_pydantic")
# result.field_info now carries max_length=255
```

The call to fold takes four arguments: the items to fold over, the initial context, the protocol to dispatch on, and the method name to call. fold iterates the items, checks each against the protocol via `isinstance`, and calls the method if it matches. That is all fold does. We will examine its six-line implementation shortly.

Capabilities combine. Multiple capabilities on one field express multiple facts:

```python
email: Annotated[str, MaxLen(255), Unique]
```

fold processes them in sequence:

```python
result = fold([MaxLen(255), Unique()], ctx, PydanticCompilable, "compile_pydantic")
```

Before reading on, predict: what does the result contain? `MaxLen(255)` has a `compile_pydantic` method — it will participate. `Unique` has no `compile_pydantic` — fold will skip it (open-world). The result: a PydanticContext with `max_length=255` and nothing else. Unique is invisible to Pydantic.

Now predict what happens if we switch to SQLAlchemy:

```python
result = fold([MaxLen(255), Unique()], sa_ctx, SQLAlchemyCompilable, "compile_sqlalchemy")
```

Both participate. `MaxLen(255)` refines `Text` to `String(255)`. `Unique` sets `unique=True`. Same two capabilities, different fold — different result. This is the fundamental observation that the rest of the chapter will develop.

Each capability transforms the context left by the previous one. The result is the context after all capabilities have had their say.

Combination extends to entities. Capabilities can attach not just to fields but to entire classes:

```python
@schema_meta(SchemaName("users"), Timestamps())
@dataclass
class User:
    id: Annotated[int, Identity]
    email: Annotated[str, MaxLen(255), Unique]
```

Field-level capabilities (Identity, MaxLen, Unique) describe individual fields. Schema-level capabilities (SchemaName, Timestamps) describe the entity as a whole. Both are consumed by fold — field-level capabilities by `fold_field`, schema-level by `fold_schema`. The mechanism is identical.

### 1.1.2 Naming and the Context

A critical aspect of a compilation framework is the means it provides for naming compilation configurations. In emergent, we name fold configurations with `CompilationPhase`:

```python
PYDANTIC_PHASE = CompilationPhase(
    PydanticContext, PydanticCompilable, _pydantic_initial
)
```

This associates a context type, a protocol, and an initial factory into a single named object. Once this association exists, we refer to the entire fold configuration by name.

Further phases:

```python
OPENAPI_PHASE = CompilationPhase(OpenAPIContext, OpenAPICompilable, _openapi_initial)
ARGPARSE_PHASE = CompilationPhase(ArgparseContext, ArgparseCompilable, _argparse_initial)
CONSTRAINTS_PHASE = CompilationPhase(ConstraintsContext, ConstraintsCompilable, _constraints_initial)
```

`CompilationPhase` is the simplest means of abstraction in the framework. It lets us use a name where we would otherwise need a triple. Phases compose into `SchemaCompiler`:

```python
FASTAPI_SCHEMA = SchemaCompiler(phases=(PYDANTIC_PHASE, OPENAPI_PHASE))
CLI_SCHEMA = SchemaCompiler(phases=(ARGPARSE_PHASE,))
FULL = FASTAPI_SCHEMA + CLI_SCHEMA
```

`SchemaCompiler` is a keyed set of phases, identified by context type, with algebraic operations (`+`, `-`, `&`, `|`) that mirror set operations. `+` is left-biased union. `FULL.compile(User, axes)` runs all three phases in one pass.

### 1.1.3 Evaluating Combinations

When fold compiles a combination, it follows a simple rule:

> 1. Iterate the capabilities.
> 2. For each capability, check whether it implements the target protocol (`isinstance`).
> 3. If it does, call the `compile_*` method, passing the current context. Replace the context with the result.
> 4. If it does not, skip the capability.
> 5. Return the final context.

Here is fold — the entire implementation:

```python
def fold(items, initial, protocol, method, handlers=None, *, trace=None):
    ctx = initial
    for item in items:
        item_cls = item.__class__
        if handlers and item_cls in handlers:
            ctx = handlers[item_cls](item, ctx)
        elif isinstance(item, protocol):
            ctx = getattr(item, method)(ctx)
    return ctx
```

Six lines of logic (the trace branch delegates to a separate function; the hot path is untouched). This is the universal primitive. Every compilation in emergent — Pydantic models, OpenAPI schemas, SQL tables, argparse specs, Telegram renderers, verification checks, CRUD endpoint generation — passes through these six lines.

Three properties follow from this rule:

**Flat.** The rule is a loop, not a recursion. Capabilities are a list, not a tree. Each capability sees the context left by the previous one.

**Open-world.** A capability that does not implement the target protocol is not an error — it is simply irrelevant to this target. `Unique` has no `compile_pydantic` method; when fold compiles for Pydantic, Unique is skipped. But `Unique` *does* have `compile_sqlalchemy`; when fold compiles for SQLAlchemy, it participates. Adding a new capability never breaks an existing target. Adding a new target never requires modifying existing capabilities.

**Total.** The capability list is finite. The loop runs once per capability. No recursive calls, no infinite loops, no divergence. This is what Meijer, Fokkinga, and Paterson (1991) call a *catamorphism* — the unique structurally recursive consumer of a finite data type. Termination is guaranteed by the structure of the data, not by the logic of the code.

### 1.1.4 Compound Capabilities

We have identified the elements of compilation:

- MaxLen, Identity, Unique — primitive capabilities
- `Annotated[T, cap1, cap2, ...]` — means of combination
- `CompilationPhase` — a limited means of abstraction

Now we introduce *compound capabilities*: a powerful abstraction technique by which a compound compilation operation can be given a name and used as a unit.

To create a CRUD API, we say:

```python
http_crud("/users", provider_node=Users)
```

This is a compound capability. It is a frozen dataclass — `CRUD` — that implements `DeriveGeneratable`, meaning fold will call its `compile_derive_generate` method during Phase 1 of derivation. Inside that method, it inspects the entity's fields, generates operation specifications for List, Get, Create, Update, Patch, and Delete, and accumulates them into the `DeriveCtx`.

We use it with the `@derive` decorator:

```python
@derive(http_crud("/users", provider_node=Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, MaxLen(255), Unique]
```

Compound capabilities compose with other capabilities:

```python
@derive(http_crud("/users", provider_node=Users), Paginated(20), SoftDelete("deleted_at"))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, MaxLen(255), Unique]
    deleted_at: datetime | None = None
```

`Paginated(20)` and `SoftDelete("deleted_at")` are also compound capabilities — they implement `DeriveModifiable`, meaning fold will call them during Phase 2 (Modify) after the CRUD operations have been generated. fold does not distinguish between primitive and compound capabilities. It dispatches on `isinstance`. Any capability that implements the protocol participates.

### 1.1.5 The Fold Model: A Worked Trace

We now trace a complete compilation step by step — the emergent equivalent of SICP's substitution model applied to `(f 5)`. The reader should be able to reproduce this trace by hand for any combination of capabilities.

**The entity:**

```python
@derive(http_crud("/users", provider_node=Users), Paginated(20))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, MaxLen(255), Unique]
```

**Phase 1 — Field-level compilation (Pydantic).**

`compile_fields` iterates each field and runs `fold_field` through `PYDANTIC_PHASE`. Before reading the trace below, predict: for each field, which capabilities will participate and which will be skipped? What will the PydanticContext contain after each field's fold completes? Try to answer before reading on.

*Field: id*
- Capabilities: `(Identity,)`
- Initial context: `PydanticContext(field_name="id", field_type=int, field_info=FieldInfo())`
- Step 1: `Identity` — `isinstance(Identity, PydanticCompilable)`? Identity has no `compile_pydantic`. **Skipped.**
- Final context: unchanged. PydanticContext for `id` has no constraints.

*Field: name*
- Capabilities: `()` (no capabilities)
- fold iterates zero items. Context unchanged.

*Field: email*
- Capabilities: `(MaxLen(255), Unique)`
- Initial context: `PydanticContext(field_name="email", field_type=str, field_info=FieldInfo())`
- Step 1: `MaxLen(255)` — `isinstance(MaxLen, PydanticCompilable)`? Yes. Calls `MaxLen.compile_pydantic(ctx)`. Inside: imports `MaxLen` from `annotated_types`, adds it to `ctx.field_info.metadata`. Context now carries `max_length=255`.
- Step 2: `Unique` — `isinstance(Unique, PydanticCompilable)`? No `compile_pydantic` on Unique. **Skipped.**
- Final context: PydanticContext with max_length=255.

`assemble_pydantic` takes these three FieldCompilations and builds a Pydantic model with `email: Annotated[str, MaxLen(max_length=255)]`.

**Phase 1 — Field-level compilation (SQLAlchemy) — same fields, different fold:**

Now predict again: the same three fields, but the fold protocol is `SQLAlchemyCompilable` instead of `PydanticCompilable`. Which capabilities participate this time? The answer will be different — and that difference is the subject of Section 1.2.

*Field: id*
- Step 1: `Identity` — `isinstance(Identity, SQLAlchemyCompilable)`? Yes. Calls `Identity.compile_sqlalchemy(ctx)`. Sets `primary_key=True`.
- Final context: SQLAlchemyContext with primary_key=True.

*Field: email*
- Step 1: `MaxLen(255)` — Yes. Calls `MaxLen.compile_sqlalchemy(ctx)`. Since `field_type is str`, replaces `column_type` with `String(255)`.
- Step 2: `Unique` — Yes. Calls `Unique.compile_sqlalchemy(ctx)`. Sets `unique=True`.
- Final context: SQLAlchemyContext with `String(255), unique=True`.

Pause and observe. The same two capabilities — `MaxLen(255)` and `Unique` — produced different results under different folds:

| | Pydantic fold | SQLAlchemy fold |
|---|---|---|
| MaxLen(255) | max_length metadata | String(255) column type |
| Unique | skipped | unique=True |

MaxLen participated in both but produced different artifacts. Unique participated only in SQLAlchemy. The capability did not change. The fold changed — specifically, the protocol and method name changed.

**Phase 2 — Derivation (three-phase fold over schema_meta).**

`compile_derive` retrieves the schema_meta capabilities: `(CRUD(...), Paginated(20))`.

*Phase 2a — Generate:* fold iterates with protocol `DeriveGeneratable`.
- `CRUD(...)` — implements `DeriveGeneratable`. Calls `CRUD.compile_derive_generate(ctx)`. Inside: inspects User's fields, finds `id` (Identity) and two other fields. Generates six OpSpecs: List, Get, Create, Update, Patch, Delete. Each carries a handler template, trigger (`HTTPRouteTrigger`), input/output fields, and effects.
- `Paginated(20)` — does not implement `DeriveGeneratable`. **Skipped.**
- DeriveCtx after Phase 2a: `specs = (List, Get, Create, Update, Patch, Delete)`.

*Phase 2b — Modify:* fold iterates with protocol `DeriveModifiable`.
- `CRUD(...)` — does not implement `DeriveModifiable`. **Skipped.**
- `Paginated(20)` — implements `DeriveModifiable`. Calls `Paginated.compile_derive_modify(ctx)`. Inside: iterates `ctx.specs`, finds the List spec (which has the `Pageable` effect), replaces its handler with `PaginatedFetchMany(page_size=20)`, adds `page` and `page_size` fields to the request type.
- DeriveCtx after Phase 2b: `specs` still has 6 operations, but List now has pagination.

*Phase 2c — Augment:* fold iterates with protocol `DeriveAugmentable`.
- Neither implements it. Both **skipped.**

Final DeriveCtx: six OpSpecs, one modified with pagination. `materialize()` builds the types and handlers. `targets.fastapi.compile()` produces a FastAPI app with routes.

The purpose of the fold model is to help us think about capability compilation, not to describe how emergent really works in every implementation detail. In practice, the compilation is accomplished by the six-line fold function with isinstance dispatch. Over the course of this book, we will present increasingly elaborate models of what compilation processes produce — from data structures to programs to distributed systems to the compiler that compiles itself.

One property of this model is worth noting now. Because capabilities are frozen and contexts are replaced (via `dataclasses.replace`) rather than mutated, the fold model is *permanently valid*. SICP introduces the substitution model in Chapter 1, then abandons it in Chapter 3 when assignment enters — the model breaks because substitution cannot account for mutable state. The fold model has no such limitation. Capabilities cannot be assigned to. Contexts are never modified in place. `replace()` returns a new frozen object. The model we have just introduced will remain correct through all five chapters of this book. This is a direct consequence of the frozen-dataclass design, and it is why there is no "environment model" chapter in this book — we never need one.

**Exercise 1.1.** Trace fold for each annotation through PydanticCompilable. For each capability, state whether it participates or is skipped, and what the final context contains:

```python
a) Annotated[str, MaxLen(100)]
b) Annotated[int, Min(0), Max(1000)]
c) Annotated[str, MaxLen(255), Unique]
d) Annotated[float, Min(-40), Max(125)]
```

Now trace the same annotations through SQLAlchemyCompilable. Which produce different results? Which capabilities participate in one target but not the other?

**Exercise 1.2.** The open-world property means unknown capabilities are silently skipped. What would break if fold raised an error instead? Consider: (a) adding a new target, (b) adding a new capability, (c) composing capabilities from independent libraries.

### 1.1.6 Protocol Dispatch

When fold encounters a capability, it must determine how to dispatch. The code is:

```python
if handlers and item.__class__ in handlers:
    ctx = handlers[item.__class__](item, ctx)
elif isinstance(item, protocol):
    ctx = getattr(item, method)(ctx)
# else: skip
```

Three branches:

1. **Handler map** — custom per-type overrides take priority. The handler is keyed by exact class, not by isinstance. This means a handler for `MaxLen` matches only `MaxLen`, not subclasses.
2. **Protocol dispatch** — `isinstance` checks whether the capability implements the target protocol. This is the standard path.
3. **Skip** — neither applies. The capability is irrelevant to this target.

The handler map exists for cases where the standard compile_* method is insufficient. A deployment might want strict mode (reject unknown capabilities), logging (trace every dispatch), or custom behavior for specific capability-target pairs:

```python
def _require_sql(item, ctx):
    raise TypeError(f"{type(item).__name__} requires SQL backend")

memory_handlers = {SomeCapability: _require_sql}
fold(caps, ctx, MemoryCompilable, "compile_memory", handlers=memory_handlers)
```

A capability can also enforce its own requirements by implementing the protocol with a raise:

```python
def compile_memory_query(self, ctx):
    raise NotImplementedError("Requires SQL backend with full-text indexing")
```

Three options, one mechanism. The fold site controls the behavior: permissive (default skip), strict (handler that raises), or custom (handler that transforms). The framework does not decide; you do.

**Exercise 1.3.** Design a scenario where handler dispatch is essential — where protocol dispatch alone would produce an incorrect result. Then design the handler that corrects it. Why is the handler keyed by exact type (`item.__class__`) rather than by isinstance?

### 1.1.7 Capabilities as Black-Box Abstractions

We have established that compound capabilities like `http_crud` and `Paginated` are used in exactly the same way as primitive capabilities. A user of `Paginated(20)` need not know its implementation — only that it modifies list operations to add pagination. The details of which specs it modifies, how it replaces handler templates, what request fields it adds — all suppressed behind the protocol interface.

This is the principle of black-box abstraction: a capability should be usable without knowledge of its implementation. The `scoped()` combinator supports this by isolating capabilities within a boundary:

```python
@derive(
    scoped(
        http_crud("/users", provider_node=Users),
        Readonly(),
        ProjectResponse(exclude=("secret",)),
    ),
    scoped(
        http_crud("/admin/users", provider_node=Users),
        Authenticated(BearerExtract(), TokenValidate(AuthUser, lookup)),
    ),
)
```

Each `scoped()` creates a self-contained derivation: the generator runs, then the modifiers apply — only to the specs produced by that generator. `Readonly()` affects `/users` but not `/admin/users`. `Authenticated` affects `/admin/users` but not `/users`. This is the emergent analog of block structure: definitions local to a scope do not leak to the enclosing environment.

The mechanism is simple. `Scoped` implements `DeriveGeneratable`. Its `compile_derive_generate` delegates to the inner generator, then folds the local modifiers through the result:

```python
class Scoped(SchemaCapability):
    generator: SchemaCapability
    caps: tuple[SchemaCapability, ...]

    def compile_derive_generate(self, ctx):
        ctx = self.generator.compile_derive_generate(ctx)
        ctx = fold(list(self.caps), ctx, DeriveModifiable, "compile_derive_modify")
        ctx = fold(list(self.caps), ctx, DeriveAugmentable, "compile_derive_augment")
        return ctx
```

fold inside fold. The outer fold (compile_derive) encounters Scoped and calls its generate method. Inside, Scoped runs its own folds over its local capabilities. The outer fold does not know this happened — it sees only the transformed context that Scoped returns. Black-box abstraction, accomplished by the same six-line primitive.

**Exercise 1.4.** The three-mechanism framework (primitives, combination, abstraction) applies at every level of emergent. Identify the three mechanisms for the derivation language: what are the primitives, the means of combination, and the means of abstraction?

---

## 1.2 Capabilities and the Compilations They Generate

We have now considered the elements of compilation: primitive capabilities, combinations, compound capabilities, the fold rule, and protocol dispatch. But this is not enough to say we know how to compile. We are like someone who has learned how the pieces move in chess but knows nothing of openings, tactics, or strategy.

The ability to visualize the consequences of a capability combination is crucial to becoming an expert compilation designer. To become experts, we must learn to see the compilations generated by various types of capabilities. Only after we develop this skill can we reliably construct capability systems that produce the intended artifacts.

A capability is a pattern for the *local transformation* of a compilation context. It specifies how one step of compilation is built upon the previous step. We want to make statements about the *global* behavior of a compilation whose local transformations have been specified by capabilities. This is straightforward because fold is a catamorphism — its global behavior is determined by the local behavior of the capabilities and the algebraic laws that govern their composition.

### 1.2.1 The Compilation That a Capability Generates

Consider a User with three fields:

```python
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, MaxLen(255), Unique]
```

We compile this through two phases — Pydantic and SQLAlchemy — using `SchemaCompiler`:

```python
FULLSTACK = PYDANTIC_PHASE + OPENAPI_PHASE
ec = FULLSTACK.compile(User, axes)
```

`compile_fields` inside `SchemaCompiler.compile()` iterates each field. For each field, it iterates each phase. For each phase, it calls `fold_field`. The result is a `FieldCompilation` per field — a dict of contexts keyed by phase.

Let us trace every step. For each field, predict which capabilities participate in each phase before reading the table.

**Field: id. Capabilities: (Identity,)**

| Phase | Capability | isinstance? | Action | Context change |
|-------|-----------|-------------|--------|----------------|
| Pydantic | Identity | No compile_pydantic | Skip | none |
| OpenAPI | Identity | No compile_openapi | Skip | none |

Identity has no Pydantic or OpenAPI methods. It is a storage-layer capability. It is invisible here — open-world.

**Field: name. Capabilities: ()**

No capabilities. Both phases produce default contexts. `name` will appear as a plain `str` in the Pydantic model and a default string entry in the OpenAPI schema.

**Field: email. Capabilities: (MaxLen(255), Unique)**

| Phase | Capability | isinstance? | Action | Context change |
|-------|-----------|-------------|--------|----------------|
| Pydantic | MaxLen(255) | Yes | compile_pydantic | metadata += MaxLen(max_length=255) |
| Pydantic | Unique | No compile_pydantic | Skip | none |
| OpenAPI | MaxLen(255) | Yes | compile_openapi | schema["maxLength"] = 255 |
| OpenAPI | Unique | No compile_openapi | Skip | none |

Unique has no Pydantic or OpenAPI methods. It is purely a storage/constraint capability.

Now add the SQLAlchemy phase:

**Field: id. Capabilities: (Identity,)**

| Phase | Capability | isinstance? | Action | Context change |
|-------|-----------|-------------|--------|----------------|
| SQLAlchemy | Identity | Yes | compile_sqlalchemy | primary_key=True |

Identity *does* have `compile_sqlalchemy`. It sets the column as the primary key. The same capability that was invisible to Pydantic is now active.

**Field: email. Capabilities: (MaxLen(255), Unique)**

| Phase | Capability | isinstance? | Action | Context change |
|-------|-----------|-------------|--------|----------------|
| SQLAlchemy | MaxLen(255) | Yes | compile_sqlalchemy | column_type: Text -> String(255) |
| SQLAlchemy | Unique | Yes | compile_sqlalchemy | unique=True |

Both participate. The result: `Column(String(255), unique=True)`.

**Summary across all three phases:**

| Capability | Pydantic | OpenAPI | SQLAlchemy |
|-----------|----------|---------|------------|
| Identity | skip | skip | primary_key=True |
| MaxLen(255) | max_length metadata | maxLength: 255 | String(255) |
| Unique | skip | skip | unique=True |

Three capabilities. Three folds. Nine dispatch decisions. The same frozen data, interpreted differently by each evaluation regime.

### 1.2.2 The Crisis: One Fact, Four Evaluators

We are now in a position to confront the central insight of this chapter.

Look again at `MaxLen(255)`. It is a frozen dataclass with one field: `value: int`. How many compile methods does it carry? Before reading on, look at the summary table above and count the targets where MaxLen participated. Now consider: what if there are targets beyond Pydantic, OpenAPI, and SQLAlchemy?

MaxLen carries *five* compile methods:

```python
class MaxLen(UniversalCapability):
    value: int

    def compile_pydantic(self, ctx):       # → Pydantic metadata: max_length=255
    def compile_openapi(self, ctx):        # → OpenAPI schema: {"maxLength": 255}
    def compile_sqlalchemy(self, ctx):     # → Column type: String(255)
    def compile_constraints(self, ctx):    # → Constraint: max_length=255
    def compile_verify_length(self, ctx):  # → Verification: max_length=255
```

Each method takes a different context type and produces a different artifact from the same fact.

The reader who has been following along has likely been thinking of capabilities as "smart annotations" — metadata that attaches to fields and gets read by different backends. Annotations with methods. This understanding is incomplete.

Consider: `MaxLen(255)` compiled through Pydantic produces a runtime validation constraint. Through OpenAPI, it produces a documentation artifact. Through SQLAlchemy, it produces a DDL instruction that physically constrains the column width. Through Constraints, it produces a checkable proposition. Through verification, it produces an assertion about consistency.

These are not different "output formats." They are different *processes*. Pydantic validation runs at request time, rejecting strings longer than 255. OpenAPI documentation is consumed by API clients at design time. SQLAlchemy DDL runs at migration time, altering the physical storage. Verification runs at import time, before any server starts.

**This is not four different features. This is ONE fact — maximum length is 255 — interpreted by four different evaluation regimes. The capability is the meaning. The fold is the evaluator. The protocol determines the semantics.**

In 1972, John Reynolds showed that a lambda closure and a record carrying the closure's free variables are interchangeable representations — a transformation he called *defunctionalization*. The lambda `(lambda (s) (if (> (string-length s) 255) (error "too long") s))` and the record `MaxLen(value=255)` are two representations of the same decision: "this string cannot exceed 255 characters." The lambda carries the decision as *code*. The record carries it as *data*.

Reynolds proved the transformation is reversible. Neither representation is more fundamental. But there is a profound practical difference: the record can be *inspected*. You can ask `MaxLen(255)` what its value is. You can put it in a set, serialize it, compare it. You cannot do any of these things with a lambda. And — crucially — the record can be consumed by *multiple* evaluators. A lambda is bound to one evaluation: the one that applies it. A record can be consumed by any fold that speaks the right protocol.

`MaxLen(255)` is Reynolds' defunctionalized closure. `value=255` is the free variable. The `compile_*` methods are the lambda bodies. fold is Reynolds' `apply` function — but with a critical inversion. In Reynolds, `apply` dispatches on the record type and contains all the logic. In emergent, each record carries its own methods. fold dispatches via isinstance and calls whatever it finds. The knowledge lives *in the capability*, not in the fold.

This is the crisis of Chapter 1. Capabilities are not annotations. They are *defunctionalized decisions* — data representations of facts that generate different processes through different folds. The frozen dataclass IS a program. The compile methods are its instruction set. fold is the evaluator. And just as different interpreters give different semantics to the same program text, different folds give different semantics to the same capability.

**Exercise 1.5.** `Unique` has `compile_sqlalchemy` (sets unique=True on the column) and `compile_constraints` (sets is_unique=True in the constraint context) but no `compile_pydantic`. Should it? What would Pydantic-level uniqueness mean? Why is it fundamentally different from database-level uniqueness? (Hint: uniqueness is a property of a *collection*, not of a single value.)

**Exercise 1.6.** Reynolds (1972) showed that defunctionalization is reversible — given a set of records with dispatch, you can reconstruct the original closures (*refunctionalization*). Apply this to emergent: given `MaxLen(255)` (the record) and `fold` (the dispatch), what function does `MaxLen(255)` defunctionalize? What are its "free variables" (Reynolds' environment)? What is the "lambda body"?

### 1.2.3 Multi-Phase Compilation and the Banana Split

When we compile one field through multiple phases — say, Pydantic AND OpenAPI — we *could* traverse the capability list twice:

```python
pydantic_ctx = fold(caps, pydantic_initial, PydanticCompilable, "compile_pydantic")
openapi_ctx  = fold(caps, openapi_initial, OpenAPICompilable, "compile_openapi")
```

But Meijer's *banana split* theorem tells us: two folds over the same list combine into one fold producing a pair. `compile_fields` exploits this:

```python
for phase in phases:
    ctx = phase.initial(name, field_type)
    ctx = fold_field(info, ctx, phase.protocol, phase.method)
    contexts[phase.context_type] = ctx
```

One traversal per field (iterating phases in the inner loop), not one traversal per phase. The result is a `FieldCompilation` — a dict of contexts keyed by phase. Adding a new phase adds one inner-loop iteration, not a new outer-loop traversal.

The SchemaCompiler algebra makes this explicit:

```python
FASTAPI_SCHEMA = PYDANTIC_PHASE + OPENAPI_PHASE     # 2 phases
FULL = FASTAPI_SCHEMA + ARGPARSE_PHASE               # 3 phases
ec = FULL.compile(User, axes)                         # one pass
```

The algebraic laws hold: `A + A == A` (idempotent — adding the same phase twice has no effect), `(A + B) + C == A + (B + C)` (associative), `A + empty == A` (identity). These are not design choices. They follow from the structure: phases are keyed by context type, and the operations are set operations on those keys.

### 1.2.4 Derivation: Fold Generating Programs

The most interesting compilation shape is *derivation* — a compilation that produces not data structures but *programs*. `compile_derive` takes a class with `@schema_meta` capabilities and produces `OpSpec`s — descriptions of operations that, when materialized, become HTTP endpoints with handlers, request types, and response types.

This is a fold that generates programs which generate programs. The `DeriveCtx` accumulator starts empty and fills with `OpSpec`s. Each `OpSpec` describes one endpoint: name, fields, handler template, trigger, effects. `materialize()` turns `OpSpec`s into actual Python types and async handler functions.

The derivation has three phases, each a separate fold over the same capability list:

```python
# Phase 1: CRUD generates OpSpecs
ctx = fold_schema(cls, ctx, DeriveGeneratable, "compile_derive_generate")

# Phase 2: Paginated/SoftDelete transform the OpSpecs
ctx = fold_schema(cls, ctx, DeriveModifiable, "compile_derive_modify")

# Phase 3: Augmenters post-process
ctx = fold_schema(cls, ctx, DeriveAugmentable, "compile_derive_augment")
```

Three folds. Same capability list. Different protocols each time. Consider the declaration `@derive(http_crud("/users", Users), Paginated(20), Readonly())`. Before reading on, predict: in Phase 1, which capabilities participate? In Phase 2, which participate? How many OpSpecs survive Phase 2?

The answer: Phase 1 — only `http_crud` (it implements `DeriveGeneratable`), producing 6 OpSpecs. Phase 2 — `Paginated(20)` modifies the List spec, then `Readonly()` removes all specs with the Mutation effect (Create, Update, Patch, Delete). Two OpSpecs survive: List (paginated) and Get. `http_crud` is skipped in Phase 2 because it doesn't implement `DeriveModifiable`.

The capabilities that fold skips in Phase 1 (because they don't implement `DeriveGeneratable`) become active in Phase 2 (because they implement `DeriveModifiable`). The capability list is a program. Each fold is a different *evaluation* of that program.

The shape of derivation is *staged*. Phase 1 creates an intermediate representation (OpSpecs). Phase 2 transforms it. Phase 3 augments it. Only then does materialization produce the final artifacts. The gap between declaration and materialization is where the power lives — transforms can rewrite OpSpecs, `explain` can inspect them, multiple targets can fork them.

### 1.2.5 Verification: Fold as Constraint Checker

Another compilation shape is verification — a fold that accumulates constraints and checks them for consistency:

```python
balance: Annotated[float, Min(100), Max(50)]
```

The verification fold accumulates `lower_bound=100, upper_bound=50`. After the fold, a consistency check discovers `lower_bound > upper_bound` and emits an Issue. This is the same fold — same six lines — but the context is a constraint accumulator instead of a schema builder.

Verification produces *failures*, not artifacts. A successful verification returns an empty tuple. A failed one returns issues. `verify_raising()` raises at import time — before any server starts.

This is the dissolved tradeoff between inspectability and type safety. `Min(100) > Max(50)` is invisible to any type checker. It is visible to emergent's verify, because verify is just another fold target.

**Exercise 1.7.** The capability `MaxLen(255)` participates in five protocols: PydanticCompilable, OpenAPICompilable, SQLAlchemyCompilable, ConstraintsCompilable, and LengthVerifyCompilable. Trace fold for the field `email: Annotated[str, MaxLen(255), Unique]` through all five. For each, state which capabilities participate, which are skipped, and what the final context contains. Then answer: is there a protocol where *both* MaxLen and Unique participate?

**Exercise 1.8.** Meijer's banana split theorem says that two folds over the same list combine into one fold producing a pair. But what if Phase B needs the result of Phase A? Can they still be banana-split? Design a two-phase compilation where the second phase reads the first phase's output. What algebraic law would break?

---

## 1.3 Formulating Abstractions with Higher-Order Capabilities

We have seen that capabilities describe compilation operations on contexts. We have combined them, named them, and traced the compilations they generate. But we have not yet exploited one of the most powerful features of capabilities: that they are *values*. A capability is a frozen dataclass. It can be stored in a variable, passed as an argument, returned from a function, and placed inside another capability. Capabilities are first-class.

This section explores the consequences of first-class capabilities — the emergent equivalent of SICP's Section 1.3 on higher-order procedures. We build toward a crescendo: capabilities as arguments, capabilities that produce capabilities, capabilities as a general method, and the glimpse of something deeper — the fold that folds over fold-described data.

### 1.3.1 Capabilities as Arguments

The `scoped()` combinator accepts capabilities as arguments:

```python
scoped(
    http_crud("/users", Users),       # generator capability
    Readonly(),                        # modifier capability
    ProjectResponse(exclude=("secret",)),  # another modifier
)
```

`scoped` takes a generator and zero or more modifiers. It stores them in its frozen fields and deploys them during compilation. The modifiers are *data* — capabilities passed to another capability. During Phase 1, Scoped delegates to the inner generator, then folds the modifiers through the result.

This is not special syntax. It is the natural consequence of capabilities being values. Any capability can accept other capabilities as constructor arguments:

```python
# From examples/roulette/wiring.py — a real capability that takes another as argument
@dataclass(frozen=True, slots=True)
class Auth(SurfaceCapability, ScopeEnricher):
    """Auth enricher — extracts auth op from request via HasAuth protocol."""
    request_type: type

    def compile_enricher(self, ctx):
        return ctx.add_enricher(self)
```

This is a real example from the emergent codebase (not a hypothetical). `Auth` takes a request type as an argument — a capability parameterized by another type. During compilation, it registers itself as a scope enricher that will extract authentication from requests.

`BearerExtract()` and `TokenValidate(AuthUser, lookup)` are capabilities passed as data to `Authenticated`, which deploys them during the modify phase. Capabilities taking capabilities as arguments — the same pattern as SICP's `sum` taking `term` and `next` as arguments.

### 1.3.2 Capabilities That Produce Capabilities

Consider the `memory_node()` factory:

```python
Users = memory_node()
Posts = memory_node()
Comments = memory_node()
```

Each call creates a fresh in-memory relational provider wrapped in a nodnod node type. The implementation:

```python
def memory_node(key_field="id", auto_id=True):
    next_id = SequenceNextId() if auto_id else None
    store = MemoryRelationalProvider(
        key_fn=lambda x: getattr(x, key_field),
        next_id=next_id,
    )

    @scalar_node
    class _Node:
        @classmethod
        def __compose__(cls):
            return store

    return _Node
```

`memory_node` is a function that returns a *value* (a node type) that will be used as a capability argument to `http_crud`. It is a capability factory — a function that constructs reusable compilation components. Each call closes over a fresh store, producing an independent provider.

The factory pattern generalizes. Here is the pattern underlying `Readonly`, `MutationsOnly`, and `WithoutDelete`:

```python
class Readonly(SchemaCapability):
    def compile_derive_modify(self, ctx):
        return ctx.reject_by_effect(Mutation)

class MutationsOnly(SchemaCapability):
    def compile_derive_modify(self, ctx):
        return ctx.select_by_effect(Mutation)

class WithoutDelete(SchemaCapability):
    def compile_derive_modify(self, ctx):
        return ctx.reject_by_effect(Deletes)
```

Three capabilities. Same structure. Differ only in the effect and the method (reject vs select). The abstraction is obvious — but emergent deliberately keeps each as a separate class. Why? Because a capability is not just its behavior. It is its *identity*. `Readonly()` appears in traces, in `explain()` output, in error messages. An anonymous `_Filter` generated by a factory would be opaque.

This is an important design point: higher-order capability factories are powerful but should be used for *internal* machinery, not for the *vocabulary* that users read and write. The user-facing capabilities — `Readonly`, `Paginated`, `SoftDelete` — are named, documented, and independently traceable.

### 1.3.3 Capabilities That Transform Other Capabilities' Output

`Paginated` and `Readonly` do not generate anything themselves. They *transform* what other capabilities generated. In Phase 1, `http_crud` generates six OpSpecs. In Phase 2, `Paginated` modifies one of them and `Readonly` removes three.

This is the higher-order pattern: capabilities operating on the *output* of other capabilities. SICP's `average-damp` takes a function and returns a transformed function. emergent's `Readonly()` takes a set of specs and returns a filtered set.

The pattern is explicit in `SoftDelete`:

```python
class SoftDelete(SchemaCapability):
    deleted_field: str = "deleted_at"

    def compile_derive_modify(self, ctx):
        # Replace the hard-delete handler with a soft-delete handler
        ctx = ctx.replace_handler(Deletes, SoftDeleteMark(self.deleted_field))
        # Add a query filter: only return non-deleted items
        ctx = ctx.filter_query(lambda e: getattr(e, self.deleted_field).is_null())
        # Exclude the deleted_at field from create requests
        ctx = ctx.exclude_fields(Creates, frozenset({self.deleted_field}))
        return ctx
```

Three transformations in one capability. It replaces a handler template (modifying the *program* that another capability generated), adds a query filter (modifying the *data access* that another capability configured), and excludes a field (modifying the *schema* that another capability produced). One capability reaching into the output of another and reshaping it.

This is where the staged architecture of derivation pays off. Phase 1 generates a representation (OpSpecs). Phase 2 transforms that representation. The separation means transforms can be *composed* independently:

```python
@derive(
    http_crud("/users", provider_node=Users),
    Paginated(20),
    SoftDelete("deleted_at"),
    Readonly(),
)
```

Each modifier sees the specs left by the previous one. `Paginated` adds pagination to the List spec. `SoftDelete` replaces the Delete handler and adds a query filter. `Readonly` removes all mutation specs — including the soft-delete spec that `SoftDelete` just created. The composition is declarative and the order among Phase 2 capabilities doesn't matter for most combinations (they operate on independent parts of the DeriveCtx).

### 1.3.4 The SchemaCompiler Algebra: Capabilities as General Method

The SchemaCompiler provides the most powerful example of capabilities used as a general method. Recall:

```python
FASTAPI_SCHEMA = SchemaCompiler(phases=(PYDANTIC_PHASE, OPENAPI_PHASE))
CLI_SCHEMA = SchemaCompiler(phases=(ARGPARSE_PHASE,))
SA_SCHEMA = SchemaCompiler(phases=(STORAGE_FIELD_PHASE,))
CONSTRAINTS_SCHEMA = SchemaCompiler(phases=(CONSTRAINTS_PHASE,))

FULLSTACK = FASTAPI_SCHEMA + CLI_SCHEMA + SA_SCHEMA + CONSTRAINTS_SCHEMA
```

`FULLSTACK` compiles a User entity through *all* targets in one pass. The same `compile_fields` kernel handles Pydantic, OpenAPI, argparse, storage, and constraints — because they are all just phases, and phases are just `(context_type, protocol, initial)` triples.

The algebra supports restriction:

```python
JUST_API = FULLSTACK - CLI_SCHEMA - SA_SCHEMA    # Pydantic + OpenAPI + Constraints
JUST_SQL = FULLSTACK & SA_SCHEMA                   # Storage only
```

And override:

```python
CUSTOM = FULLSTACK | SchemaCompiler(phases=(MY_CUSTOM_PYDANTIC_PHASE,))
```

`|` is right-biased merge: `MY_CUSTOM_PYDANTIC_PHASE` replaces `PYDANTIC_PHASE` by context type.

This observation — that compilation, verification, and custom targets share the same algebra — is central. Any new compilation target (GraphQL, Protobuf, Terraform) automatically participates in the same composition algebra. Any new verification phase composes identically with existing targets. There is no second mechanism.

### 1.3.5 The Fractal: Fold Consuming Fold-Described Data

We conclude with a glimpse of what comes in later chapters. Consider `examples/fractal.py`:

```python
@dataclass(frozen=True, slots=True)
class Poly(Capability):
    coefficients: tuple[float, ...]

    def compile_eval(self, ctx: EvalCtx) -> EvalCtx:
        coeffs = self.coefficients
        def evaluate(x: float) -> float:
            result = 0.0
            for c in coeffs:
                result = result * x + c
            return result
        return replace(ctx, evaluate=evaluate)

    def compile_latex(self, ctx: LatexCtx) -> LatexCtx:
        # ... generates LaTeX: "x^{2} + 2x + 1"

    def compile_derivative(self, ctx: DerivativeCtx) -> DerivativeCtx:
        # ... generates derivative coefficients: (2, 2)
```

`Poly(1, 2, 1)` represents x^2 + 2x + 1. It is data. But fold it with `compile_eval` and it generates a *Python function*. Fold it with `compile_latex` and it generates a LaTeX string. Fold it with `compile_derivative` and it generates `(2, 2)` — the coefficients of the derivative — which are *themselves* valid input to another Poly, which is itself a valid input to another fold.

This is Hutton's result (1999) that fold can generate *functions* as output. `foldl` is a `foldr` that produces a function and then applies it. The capability is data. The fold produces functions, strings, new data, even new capabilities. The fractal: fold consuming fold-described data, producing data that is itself fold-describable.

The fractal example has four levels:

- **Level 0:** Expressions as capabilities (`Poly`, `Scale`, `Shift`)
- **Level 1:** Compile entity to multiple targets (EvalCtx, LatexCtx, PythonCtx, DerivativeCtx)
- **Level 2:** Derive new entities from compiled data (generate derivative entity whose fields are themselves capabilities)
- **Level 3:** Compile *compiler configurations* — a meta-capability `IncludePhase(LATEX_PHASE)` that, when folded, tells the compiler *which phases to run*

At Level 3, capabilities describe the compiler itself. fold over capabilities produces a compiler configuration, which is used to fold over more capabilities. The fold folds over fold-described data.

We are not yet in a position to fully develop this idea — it requires the data abstractions of Chapter 2 and the metalinguistic framework of Chapter 4. But the fact that it is expressible at all — that the same six-line fold, the same frozen dataclasses, the same isinstance dispatch can bootstrap a compiler that compiles itself — should give the reader pause.

Later we will discover that this is not a clever trick. It is a consequence of Hutton's universal property: fold is the *unique morphism* from the initial algebra (the list of capabilities) to any target algebra. If the target algebra is "compiler configurations," fold produces compiler configurations. If the target algebra is "functions," fold produces functions. If the target algebra is "new capabilities," fold produces new capabilities. The universal property says: any structural processing of capabilities *is* a fold. This is not a design choice. It is a mathematical necessity.

The reader who senses that fold is not just a loop but an *evaluation model* — that capabilities are not just data but a *language* that fold interprets — is sensing correctly. Chapter 4 will make this precise.

**Exercise 1.9.** In `examples/fractal.py`, `Poly(1,2,1).compile_eval(ctx)` produces a *function* as output. Can you write a capability whose `compile_*` method returns a context containing *another capability*? What would this mean for compilation?

**Exercise 1.10.** Define a new `CompilationPhase` for GraphQL:

```python
@dataclass(frozen=True, slots=True)
class GraphQLContext:
    field_name: str
    field_type: type
    graphql_type: str | None = None
    nullable: bool = False

class GraphQLCompilable(Protocol):
    def compile_graphql(self, ctx: GraphQLContext) -> GraphQLContext: ...

GRAPHQL_PHASE = CompilationPhase(GraphQLContext, GraphQLCompilable, lambda n, t: GraphQLContext(n, t))
```

Now add `compile_graphql` methods to `MaxLen` and `Identity`. Compile a User entity through `GRAPHQL_PHASE` and produce a GraphQL schema fragment. How many lines of fold code did you need to change? (Answer: zero.)

---

## 1.4 Summary and Forward References

We have established the primitives of compilation thinking:

**Capabilities** are frozen dataclasses that carry facts and know how to compile themselves for each target. They are Reynolds' defunctionalized closures: data representations of decisions that were once implicit in scattered code.

**fold** is the six-line universal primitive that iterates capabilities, dispatches by protocol, and accumulates context. It is Meijer's catamorphism — the unique structurally recursive consumer of a finite list. It always terminates. It is total.

**CompilationPhase** and **SchemaCompiler** name and compose fold configurations. They form an algebra — `+`, `-`, `&`, `|` — that mirrors set operations.

**Derivation** is staged compilation: generate, modify, augment. Three folds over the same capability list, each with a different protocol. The capability list is a program. Each fold is a different evaluation.

**Higher-order capabilities** take capabilities as arguments, produce capabilities as output, and transform other capabilities' compilations. They make the framework *composable* — not merely sequential.

The crisis of this chapter: capabilities are not annotations. They are not metadata. They are the primitive that generates ALL computation through fold. The same `MaxLen(255)`, consumed by different folds, produces validation logic, documentation, DDL, constraints, and verification results. The capability is the meaning. fold is the evaluator. The protocol determines the semantics.

Three questions remain open:

*How do we build compound data from capabilities?* We have seen capabilities on fields and on entities. But how do we compose schemas — entities that reference other entities, nested structures, the closure property that makes composition *compositional*? This is Chapter 2.

*What happens when capabilities describe state and change?* Everything so far is pure and frozen. But real systems change over time — entries are created, updated, deleted. How do we model change without losing the properties that make fold tractable? This is Chapter 3.

*The fold that compiles capabilities... is itself described by capabilities.* We glimpsed this in the fractal example. The compiler that compiles your code can itself be compiled by the same mechanism. This metacircular property — fold consuming fold-described data — will be the subject of Chapter 4.

*What machine executes this fold?* We have treated fold as an abstraction — six lines that "just work." But those six lines run on real hardware, in real time, with real concurrency constraints. The abstract fold becomes a concrete nodnod DAG, then a RuntimePolicy, then actual OS threads or asyncio coroutines. Chapter 5 opens the machine.

---

## Exercises

**Exercise 1.11.** Below is a sequence of `@derive` declarations. For each, determine: (a) how many OpSpecs are generated after Phase 1, (b) how many remain after Phase 2, (c) what the final endpoint count is.

```python
a) @derive(http_crud("/users", Users))
b) @derive(http_crud("/users", Users), Readonly())
c) @derive(http_crud("/users", Users), Paginated(20), Readonly())
d) @derive(http_crud("/users", Users), WithoutDelete())
e) @derive(http_crud("/users", Users), SoftDelete("deleted_at"))
```

**Exercise 1.12.** The commutativity of capabilities within a fold depends on each capability writing to an independent part of the context. Construct a hypothetical capability whose `compile_pydantic` method reads a field that another capability writes. Show that order would matter for this pair. Then explain why emergent's actual capabilities avoid this — what property of the context design prevents it?

**Exercise 1.13.** The SchemaCompiler algebra satisfies `A + A = A` (idempotent), `(A + B) + C = A + (B + C)` (associative), and `A + empty = A` (identity). Does it satisfy commutativity (`A + B = B + A`)? If not, construct an example where `A + B != B + A`. What does this mean for the semantics of compiler composition?

**Exercise 1.14.** Hutton (1999) proves that `foldl` can be expressed as a `foldr` that generates a function. In emergent, fold is always a left fold (iterate sequentially, accumulate context). Could fold be implemented as a right fold? Would the results differ? (Hint: consider commutativity.)

**Exercise 1.15.** Moseley and Marks (2006) distinguish essential complexity (inherent in the problem) from accidental complexity (artifacts of the implementation). For a system with Users who have emails with max length 255 and uniqueness constraints, enumerate: (a) the essential complexity, (b) the accidental complexity in a Django implementation, (c) the accidental complexity in an emergent implementation. Is emergent's accidental complexity zero? If not, what remains?

**Exercise 1.16.** SICP Exercise 1.5 tests whether an interpreter uses applicative-order or normal-order evaluation. Design an analogous test for emergent: a pair of capabilities where the result differs depending on whether fold uses eager dispatch (the current behavior) or lazy dispatch (only call compile_* when the context field is actually read). Could emergent benefit from lazy compilation? What would it cost?

**Exercise 1.17.** The `examples/01_quickstart.py` file produces 15+ endpoints from 3 dataclasses. Read the file. Trace the compilation for the `User` entity: (a) what capabilities does `@derive(http_crud("/users", provider_node=Users))` attach? (b) What are the three phases of `compile_derive`? (c) How does `build_application_from_decorated` collect the results? (d) How does `targets.fastapi.compile` produce the final FastAPI app?
