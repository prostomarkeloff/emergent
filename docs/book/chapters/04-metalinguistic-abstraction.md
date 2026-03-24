# 4. Metalinguistic Abstraction

> … It's in words that the magic is — Abracadabra, Open Sesame, and the rest — but the magic words in one story aren't magical in the next. The real magic is to understand which words work, and when, and for what; the trick is to learn the trick.
>
> … And those words are made from the letters of our alphabet: a couple-dozen squiggles we can draw with the pen. This is the key! And the treasure, too, if we can only get our hands on it! It's as if — as if the key to the treasure *is* the treasure!
>
> — John Barth, *Chimera*

In our study of compilation design, we have seen that expert programmers control the complexity of their compilations with the same general techniques used by designers of all complex systems. They combine primitive capabilities to form compound capabilities, they abstract compound capabilities to form higher-level building blocks, and they preserve modularity by adopting appropriate large-scale views of system structure — the four axes, the Log, the compilation algebra. In illustrating these techniques, we have used emergent as a framework for describing compilation processes and for constructing computational data objects and systems to model complex phenomena in the real world. However, as we confront increasingly complex problems, we will find that emergent, or indeed any fixed compilation framework, is not sufficient for our needs. We must constantly turn to new compilation languages in order to express our ideas more effectively. Establishing new compilation languages is a powerful strategy for controlling complexity in system design; we can often enhance our ability to deal with a complex problem by adopting a new compilation language that enables us to describe (and hence to think about) the problem in a different way, using primitives, means of combination, and means of abstraction that are particularly well suited to the problem at hand.

Compilation is endowed with a multitude of languages. There are schema languages — the field annotations of `Annotated[str, MaxLen(255)]`. There are query languages — the lambda-proxy expressions of `.filter(lambda u: u.balance > 100)`. There are derivation languages — the `@derive(http_crud(...), Paginated(20))` annotations that generate entire APIs. There are surface languages — the trigger-codec-capability triples that describe how endpoints are exposed. There are world languages — the computation-capability tuples that describe how agents behave and communicate through the Log.

*Metalinguistic abstraction* — establishing new compilation languages — plays an important role in all branches of compilation design. It is particularly important in emergent, because in emergent not only can we formulate new compilation languages but we can also implement these languages by constructing evaluators. An *evaluator* (or *fold*) for a compilation language is a function that, when applied to a capability of the language, performs the actions required to compile that capability.

It is no exaggeration to regard this as the most fundamental idea in compilation:

> **fold, which determines the meaning of capabilities in a compilation language, is just another program.**

To appreciate this point is to change our images of ourselves as programmers. We come to see ourselves as designers of compilation languages, rather than only users of compilation frameworks designed by others.

In fact, we can regard almost any compilation as the evaluator for some language. For instance, the query execution system of 2.4 embodies the rules of relational query processing and implements them in terms of operations on list-structured and SQL-structured data. If we augment this system with capabilities to build and simplify expressions, we have the core of a special-purpose language for dealing with problems in data access. The derivation engine of 1.2.3 and the verification system of 1.2.4 are legitimate languages in their own right, each with its own primitives, means of combination, and means of abstraction. Seen from this perspective, the technology for coping with large-scale compilation systems merges with the technology for building new compilation languages, and compilation science itself becomes no more (and no less) than the discipline of constructing appropriate fold configurations.

---

## 4.1 The Metacircular Fold

Our fold for emergent will be examined as an emergent compilation. It may seem circular to think about compiling emergent capabilities using a fold that is itself part of emergent. However, compilation is a process, so it is appropriate to describe the compilation process using emergent, which, after all, is our tool for describing compilation processes. A fold that compiles the same encoding it is written in is said to be *metacircular*.

The metacircular fold is essentially the six-line function we introduced in 1.1.3, now examined as an object of study rather than a tool.

```python
def fold(items, initial, protocol, method, handlers=None):
    ctx = initial
    for item in items:
        if handlers and item.__class__ in handlers:
            ctx = handlers[item.__class__](item, ctx)
        elif isinstance(item, protocol):
            ctx = getattr(item, method)(ctx)
    return ctx
```

Recall that fold has two basic parts:

1. **Dispatch:** For each item, determine how to handle it — handler map, protocol isinstance, or skip.
2. **Accumulate:** Apply the chosen handler or method to the current context, producing a new context.

These two parts describe the essence of compilation. Every compilation in emergent reduces to: iterate items, dispatch by protocol, accumulate context. The fold is the universal evaluator for capability languages.

### 4.1.1 The Core of the Fold

The dispatch mechanism has two branches:

**Handler dispatch** (`handlers` map): explicit per-type overrides. The handler receives the item AND the accumulated context. This is the analog of SICP's special forms — items that need treatment different from the default protocol dispatch. In query compilation, the handler map is used to dispatch emergent's cross-compilable ops (Filter, OrderBy, Limit) which implement protocols for multiple backends via their compile_* methods, but may need backend-specific override handling.

**Protocol dispatch** (`isinstance` check): the standard path. The item implements the protocol and carries its own compile_* method. fold calls the method. The item compiles itself — Reynolds' defunctionalization at work.

**Skip** (neither): the item is irrelevant to this target. No error. No warning. Open-world dispatch.

The accumulation is the catamorphism: `ctx = initial; for each item: ctx = transform(item, ctx); return ctx`. Meijer's banana bracket `(| initial, transform |)` applied to the item list.

### 4.1.2 How fold Represents Compilation Targets

The key insight of the metacircular fold is that a *compilation target* is nothing more than a choice of (protocol, context type, initial factory). The fold mechanism is identical for all targets. The meaning is determined by what the capabilities' compile_* methods do to the context.

Let us make this concrete. Consider one capability — `MaxLen(255)` — compiled through three different targets:

**Pydantic target.** Protocol: PydanticCompilable. Context: PydanticContext. Initial: `PydanticContext("email", str, FieldInfo())`. fold calls `MaxLen(255).compile_pydantic(ctx)`. The method adds `max_length=255` to the FieldInfo metadata. Result: a Pydantic field that rejects strings longer than 255 characters.

**OpenAPI target.** Protocol: OpenAPICompilable. Context: OpenAPIContext. Initial: `OpenAPIContext("email", str, schema={"type": "string"})`. fold calls `MaxLen(255).compile_openapi(ctx)`. The method merges `{"maxLength": 255}` into the JSON Schema. Result: an OpenAPI property with `maxLength: 255`.

**Verification target.** Protocol: LengthVerifyCompilable. Context: LengthVerifyCtx. Initial: `LengthVerifyCtx(field_name="email", field_type=str)`. fold calls `MaxLen(255).compile_verify_length(ctx)`. The method sets `max_length=255` on the verify context. Result: a context that, when `check()` is called, compares max_length with min_length to detect contradictions.

Three targets. Same capability. Same fold. Three completely different semantics. The Pydantic target produces runtime validation. The OpenAPI target produces documentation. The verification target produces a consistency check. MaxLen(255) doesn't know which target it's being compiled for — it implements all three methods, and fold calls whichever matches the protocol.

This is what it means for fold to be a "metacircular evaluator." In SICP, the Scheme evaluator applies procedures to arguments. In emergent, fold applies capabilities to contexts. The procedures/capabilities don't know how they'll be used — they define their behavior, and the evaluator/fold dispatches based on the expression type/protocol.

And just as SICP's metacircular evaluator "inherits the control structure of the underlying Lisp system" — its evaluation order matches Scheme's — fold inherits the iteration structure of Python's for-loop. The capabilities are processed left-to-right. But because they are commutative (each writes to independent context fields), the order doesn't matter. fold inherits Python's sequential iteration but emergent's semantics don't depend on it.

SICP makes a profound observation at this point: "It is no exaggeration to regard this as the most fundamental idea in programming: *The evaluator, which determines the meaning of expressions in a programming language, is just another program.*"

The emergent analog: *fold, which determines the meaning of capabilities in a compilation language, is just another six-line function.* It is not embedded in the framework's internals. It is not hidden behind abstractions. It is visible, readable, and finite. Six lines. You can hold the entire evaluator in your head. Everything that emergent does — schema compilation, query execution, verification, derivation, world construction — is this function applied to different data.

To appreciate this is to understand why emergent has one mechanism. Not because its designers lacked imagination, but because one mechanism is *sufficient*. The variety comes not from the evaluator but from the capabilities — the frozen data that knows how to compile itself.

Consider verification. The "compilation target" is NumericVerifyCtx — a frozen dataclass with lower_bound, upper_bound, etc. The "capabilities" are the same MaxLen, Min, Max that compile to Pydantic and OpenAPI. But they also implement `compile_verify_numeric`. fold dispatches to this method. The verification target is just another (protocol, context, initial) triple — just another language.

The derivation engine is a different language entirely. DeriveCtx is the context. DeriveGeneratable, DeriveModifiable, DeriveAugmentable are the protocols. CRUD, Paginated, SoftDelete are the capabilities. Three folds — generate, modify, augment — form a three-pass compiler within the fold framework. Each pass is a fold. The derivation "language" is defined by the protocols and the capabilities that implement them.

theworld defines yet another language. WorldContext is the context. WorldCompilable is the protocol. Computations, Scripts, Supervised, HotReloadable are the capabilities. `World.run()` is the evaluation of this language — fold produces nodnod nodes, RuntimeAgent executes them.

Each of these is a full compilation language. Each has primitives (specific capabilities), means of combination (tuple concatenation), and means of abstraction (SchemaCompiler, scoped, CompilationPhase). And each is evaluated by the same fold.

### 4.1.3 Custom Compilation Languages

Because fold is so simple, creating a new compilation language requires only three things:

1. A context type (frozen dataclass with the compilation state).
2. A protocol (runtime_checkable Protocol with one compile_* method).
3. An initial factory (function that creates the initial context).

Let us build a complete example — not a sketch, but a working compilation language for infrastructure-as-code. We will compile the same emergent entity annotations to Terraform HCL, so that the same `User` dataclass that generates REST endpoints and SQL tables also generates the cloud infrastructure to host them.

**Step 1: The context.** What state does a Terraform compilation accumulate? At minimum: a list of resource blocks and a set of variable declarations.

```python
@dataclass(frozen=True, slots=True)
class TerraformContext:
    field_name: str
    field_type: type
    resource_type: str | None = None
    column_spec: dict[str, str | int | bool] = field(default_factory=dict)
```

This context accumulates per-field information: what kind of Terraform resource this field implies (a database column? an index? a search configuration?) and what properties it has.

**Step 2: The protocol.**

```python
@runtime_checkable
class TerraformCompilable(Protocol):
    def compile_terraform(self, ctx: TerraformContext) -> TerraformContext: ...
```

One method. One protocol. Any capability that implements it participates in Terraform compilation.

**Step 3: Handlers for existing capabilities.** The interesting question: how do existing capabilities — Identity, MaxLen, Unique — gain Terraform compilation powers? They don't implement TerraformCompilable. We don't want to modify their source code. And monkey-patching methods onto frozen dataclasses is a hack.

The answer is the `handlers` parameter of fold — the first branch of the three-way dispatch from Section 1.1.6. CompilationPhase accepts a handler map:

```python
terraform_handlers = {
    Identity: lambda cap, ctx: replace(ctx,
        column_spec={**ctx.column_spec, "primary_key": True}),
    MaxLen: lambda cap, ctx: replace(ctx,
        column_spec={**ctx.column_spec, "type": f"VARCHAR({cap.value})"}),
    Unique: lambda cap, ctx: replace(ctx,
        column_spec={**ctx.column_spec, "unique": True}),
}

TERRAFORM_PHASE = CompilationPhase(
    TerraformContext, TerraformCompilable,
    lambda n, t: TerraformContext(field_name=n, field_type=t),
    handlers=terraform_handlers,
)
```

When fold encounters Identity, it checks the handler map FIRST — finds the lambda — calls it. Identity doesn't need to know about Terraform. Terraform doesn't need to modify Identity. The handler map is the bridge.

This is the two-level dispatch at work: handler map (priority) > protocol isinstance (fallback) > skip. For NEW capabilities that are specifically designed for Terraform, the protocol path is natural — they implement compile_terraform. For EXISTING capabilities from other domains, the handler map extends them without modification.

New Terraform-specific capabilities can also participate via protocol:

```python
@dataclass(frozen=True, slots=True)
class TerraformTag(SchemaAxisCapability):
    key: str
    value: str

    def compile_terraform(self, ctx: TerraformContext) -> TerraformContext:
        return replace(ctx, tags={**ctx.tags, self.key: self.value})
```

TerraformTag implements TerraformCompilable directly. fold dispatches via isinstance. No handler needed. The two paths — handler map for cross-domain extension, protocol for native capabilities — coexist in the same fold.

**Step 4: The phase.**

```python
TERRAFORM_PHASE = CompilationPhase(
    TerraformContext, TerraformCompilable,
    lambda n, t: TerraformContext(field_name=n, field_type=t),
)
```

**Step 5: Composition with existing compilers.**

```python
FULLSTACK = FASTAPI_SCHEMA + SA_SCHEMA + TERRAFORM_PHASE

ec = FULLSTACK.compile(User, axes)
# ec now contains: PydanticContext, OpenAPIContext, SQLAlchemyContext, AND TerraformContext
# for every field of User
```

The `+` operation adds TERRAFORM_PHASE to the existing SchemaCompiler. compile() runs all phases — including Terraform — in one pass per field (banana split). The Terraform contexts sit alongside Pydantic and OpenAPI contexts in the same FieldCompilation dict.

**Step 6: Assembling the HCL.** A function reads the compiled TerraformContexts and produces HCL:

```python
def assemble_terraform(entity, ec):
    table_name = entity.__name__.lower()
    columns = []
    for fc in ec:
        tf = fc[TERRAFORM_PHASE]
        col = {"name": tf.field_name, **tf.column_spec}
        columns.append(col)

    return f'''
resource "aws_db_instance" "{table_name}_db" {{
  engine         = "postgres"
  instance_class = "db.t3.micro"
}}

resource "aws_rds_table" "{table_name}" {{
  db_instance = aws_db_instance.{table_name}_db.id
  {chr(10).join(f'  column "{c["name"]}" {{ type = "{c.get("type", "TEXT")}" }}' for c in columns)}
}}
'''
```

This is crude — production Terraform compilation would be richer. The point is not the HCL output. The point is: **we created a new compilation language in ~30 lines.** The language shares capabilities with Pydantic, OpenAPI, and SQL. It composes algebraically with existing compilers. It participates in banana-split optimization. And it was created without modifying a single line of existing emergent code.

SICP observes: "we can regard almost any program as the evaluator for some language." In emergent: we can regard any CompilationPhase as the definition of a compilation language, and fold as its evaluator. The Terraform example is not a toy — it demonstrates that the encoding truly is metalinguistic. A new compilation target IS a new language. Creating it requires defining the semantics (what does each capability mean in Terraform terms?) and registering the phase. fold provides the evaluator for free.

---

## 4.2 Variations on the Fold — Derivation

In SICP, Chapter 4.2 explores lazy evaluation: same evaluator, different evaluation strategy. In emergent, derivation is the major "variation" — same fold, but the fold generates *programs*.

### 4.2.1 Three-Phase Derivation as Staged Compilation

compile_derive is a three-phase fold:

```python
ctx = fold_schema(cls, ctx, DeriveGeneratable, "compile_derive_generate")  # Phase 1
ctx = fold_schema(cls, ctx, DeriveModifiable, "compile_derive_modify")      # Phase 2
ctx = fold_schema(cls, ctx, DeriveAugmentable, "compile_derive_augment")    # Phase 3
```

Phase 1 generates OpSpecs — descriptions of operations. These are not endpoints. They are the *intermediate representation* of a derivation. Phase 2 transforms OpSpecs. Phase 3 augments. Only then does materialize() produce actual types, handlers, and endpoints.

Let us trace derivation concretely. Consider:

```python
@derive(http_crud("/articles", Articles), Paginated(50), SoftDelete("deleted_at"))
@dataclass
class Article:
    id: Annotated[int, Identity]
    title: Annotated[str, MaxLen(200)]
    body: str
    deleted_at: datetime | None = None
```

Three capabilities in @schema_meta: `CRUD("/articles", Articles)`, `Paginated(50)`, `SoftDelete("deleted_at")`.

**Phase 1 — Generate.** fold_schema iterates with DeriveGeneratable protocol. Only CRUD implements it. Paginated and SoftDelete are skipped (they implement DeriveModifiable, not DeriveGeneratable).

CRUD.compile_derive_generate(ctx) inspects Article: fields are id (Identity), title (MaxLen(200)), body (str), deleted_at (datetime | None). It generates 7 OpSpecs:

```
OpSpec("List",    input={},                  output=list_response,    handler=FetchMany(),
       trigger=GET /articles,      effects=(Read(), Pageable(), Sortable()))

OpSpec("Get",     input={id: int},           output=entity_response,  handler=FetchOneById(),
       trigger=GET /articles/{id}, effects=(Read(), Idempotent(), Cacheable()))

OpSpec("Create",  input={title, body},       output=entity_response,  handler=InsertNew(),
       trigger=POST /articles,     effects=(Creates(),))

OpSpec("Update",  input={id, title, body, deleted_at}, output=entity_response, handler=UpdateExisting(),
       trigger=PUT /articles/{id}, effects=(Updates(), Idempotent()))

OpSpec("Patch",   input={id, ?title, ?body, ?deleted_at}, output=entity_response, handler=PatchExisting(),
       trigger=PATCH /articles/{id}, effects=(Updates(), Idempotent()))

OpSpec("Delete",  input={id},                output=ok_response,      handler=DeleteOne(),
       trigger=DELETE /articles/{id}, effects=(Deletes(), Idempotent()))

OpSpec("Upsert",  input={id, title, body, deleted_at}, output=entity_response, handler=UpsertExisting(),
       trigger=PUT /articles,      effects=(Creates(), Updates(), Idempotent()))
```

Each OpSpec is a frozen dataclass. It describes one operation completely: what fields it accepts, what it returns, how it handles data, what HTTP trigger activates it, and what effects it carries. But no types have been generated. No handlers have been built. No FastAPI routes exist. This is pure data — the intermediate representation.

**Phase 2 — Modify.** fold_schema iterates with DeriveModifiable protocol. CRUD does not implement it (skipped). Paginated(50) DOES:

Paginated.compile_derive_modify(ctx): scans specs for Pageable effect. Finds the List OpSpec. Replaces its handler: FetchMany() → PaginatedFetchMany(page_size=50). Adds `page: int = 1` and `page_size: int = 50` to the List op's input fields. The List response changes to include `items`, `total`, `page`, `page_size`.

SoftDelete("deleted_at").compile_derive_modify(ctx): three transformations:
1. Finds the Delete OpSpec (has Deletes effect). Replaces its handler: DeleteOne() → SoftDeleteMark("deleted_at"). Now "delete" sets `deleted_at = now()` instead of removing the row.
2. Adds a query filter to the base query: `lambda e: e.deleted_at.is_null()`. All Read ops now automatically exclude soft-deleted articles.
3. Removes `deleted_at` from Create input fields — users don't set deletion timestamp manually.

After Phase 2, the DeriveCtx has 7 OpSpecs, all transformed. The List op is paginated. The Delete op marks instead of removes. Read ops filter out soft-deleted articles. Create doesn't accept deleted_at.

**Phase 3 — Augment.** No capabilities implement DeriveAugmentable. Nothing happens.

**Materialization.** materialize(ctx) takes the 7 OpSpecs and produces an Endpoint:

For each OpSpec, `build_from_spec(spec, ctx)` dynamically creates:
- A frozen dataclass type for the request: `ArticleListOp(page: int = 1, page_size: int = 50, provider: MutatingRelationalProvider)`
- A frozen dataclass type for the response: appropriate Pydantic model
- An async handler function: PaginatedFetchMany.build(spec) returns a function that queries the provider with pagination
- An Exposure: `(HTTPRouteTrigger("GET", "/articles"), rrc(ArticleListOp, ArticleListResponse), error_caps)`

All 7 (OpType, handler) pairs register with an ops builder. `.compile()` → Runner. The Endpoint has 7 Exposures. fastapi.compile() turns them into 7 FastAPI routes.

**The staging gap.** Between @derive and the FastAPI routes, the OpSpecs existed as pure data. During that gap:
- Paginated read the Pageable effect and replaced the handler
- SoftDelete read the Deletes effect and replaced the handler, added a query filter, removed a field from Create
- explain_derive(ctx) could have printed every OpSpec
- verify() could have checked that no OpSpec has contradictory effects
- A second generator (cli_crud) could have forked the derivation context

If compilation went straight from @derive to FastAPI routes — no OpSpec IR, no staging — none of this would be possible. The staging IS the metalinguistic abstraction: OpSpecs are the "programs" that the derivation "language" produces, and materialize() is the "evaluator" that runs them.

### 4.2.2 Semantic Macros

The transforms of Phase 2 — Paginated, SoftDelete, Readonly, Authenticated — are *semantic macros*. They dispatch on the *meaning* of operations (effects like Read, Mutation, Deletes, Pageable) rather than on their syntax (function names, route paths, variable names).

In the macro taxonomy (Nicolajsen 2025), this is Level 4 — beyond lexical (C preprocessor), syntactic (Lisp macros), type-aware (Template Haskell), and elaboration (Idris reflection). No existing macro system in the literature combines domain semantics awareness, compositional algebra, defunctionalized data, and open-world dispatch. Simonyi's Intentional Programming (1995) had the closest vision — but no formalism, no algebra, and it died unrealized at Microsoft.

The formalism is straightforward. Effects are frozen dataclasses in a hierarchy: `Creates < Mutation`, `Deletes < Mutation`. Transforms are endomorphisms on DeriveCtx dispatching via isinstance. Composition is `.chain()` — function composition in the endomorphism monoid.

---

## 4.3 Variations on the Fold — Verification

SICP Chapter 4.3 explores nondeterministic computing — same evaluator, `amb` choices. In emergent, verification is the variation: same fold, but producing *failures* instead of artifacts.

Verification is a compilation target whose context accumulates constraints rather than schema properties. After the fold, `ctx.check()` resolves contradictions:

```python
# Same Min(100) capability that compiles to Pydantic and OpenAPI
# ALSO compiles to NumericVerifyCtx:
def compile_verify_numeric(self, ctx):
    return replace(ctx, lower_bound=float(self.value))
```

The capability doesn't know it's being verified. It implements compile_verify_numeric because it has something to say about numeric constraints. fold dispatches to it. The verification context accumulates. check() detects `lower_bound > upper_bound`.

This is the Curry-Howard connection (Wadler 2015). Capabilities are propositions: "the maximum length is 255." "The minimum value is 100." Fold is proof construction: from propositions and axioms (initial context), derive a conclusion (compiled context). verify() is consistency checking: do the propositions contradict?

The dissolved tradeoff: initial encoding (frozen data) gives inspectability. Custom domain verifiers give guarantees that host-language type checkers cannot express. `Min(100) > Max(50)` is invisible to any type system. verify() catches it at import time, with a domain-specific error message. Both at once: inspectable AND verified.

---

## 4.4 Variations on the Fold — World Compilation

SICP Chapter 4.4 explores logic programming — same evaluator, pattern-matching rules. In emergent, world compilation is the most dramatic variation: fold that produces an *operating system*.

```python
ctx = fold(self.computations, WorldContext(log=self.log), WorldCompilable, "compile_world")
```

The capabilities are Computations, Scripts, Supervised, HotReloadable. The context accumulates nodnod nodes. After fold, RuntimeAgent executes the graph.

Each Computation carries its own capabilities — a nested layer. Computation.compile_world builds a nodnod node type from the Computation's capabilities by folding through LensCompilable (what to observe), ActionCompilable (what to emit), LifecycleCompilable (when to run), PlanCompilable (what ops to execute).

This is fold inside fold. The outer fold builds the World's node set from Computations. Each Computation's compile_world runs inner folds to build its behavior from its capabilities. The same mechanism at each level.

Supervised wraps all nodes in the current scope with retry logic. scoped() creates a fold boundary — inner Supervised doesn't affect outer Computations. HotReloadable watches the Log for Reload events and dynamically spawns/despawns nodes. Migration ships Computation capabilities (frozen data) through the Log to another World.

The World "language" has: primitives (life, Script), means of combination (tuple concatenation of Computations), means of abstraction (scoped, Supervised, HotReloadable). It is a full compilation language evaluated by fold. The "programs" it produces are distributed agent systems.

---

## 4.5 The Evaluator as Program

SICP closes Chapter 4 with a meditation on what it means that the evaluator is a program:

> "We come to see ourselves as designers of languages, rather than only users of languages designed by others."

In emergent, the corresponding realization is:

**fold is not a utility function. It is the evaluator for an open-ended family of compilation languages.** Each CompilationPhase defines a new language. Each set of capabilities that implement the phase's protocol constitute the programs of that language. fold evaluates them.

When you write:

```python
@dataclass(frozen=True, slots=True)
class GraphQLField:
    graphql_type: str = "String"

    def compile_graphql(self, ctx: GraphQLContext) -> GraphQLContext:
        return replace(ctx, graphql_type=self.graphql_type)
```

you are not "adding a feature to emergent." You are *designing a compilation language* — the GraphQL schema language — and defining its primitives. When you write:

```python
GRAPHQL_PHASE = CompilationPhase(GraphQLContext, GraphQLCompilable, _graphql_initial)
```

you are defining the evaluator for this language. When fold processes `Annotated[str, MaxLen(255), GraphQLField("String!")]`, it evaluates two programs simultaneously — one in the Pydantic language, one in the GraphQL language — from the same source text.

This is metalinguistic abstraction in the strongest sense. Not "embed a DSL in Python" — that is syntactic sugar. But: define a compilation target with its own semantics, compose it with other targets algebraically, and evaluate all targets simultaneously through a single fold pass. The target IS the language. fold IS the evaluator. The capability IS the program.

And because fold is six lines, the evaluator is transparent. There is no hidden complexity. No metaclass machinery. No framework magic. Six lines that iterate a list, check isinstance, and call a method. The magic is not in the evaluator. The magic is in the capabilities — the frozen data that knows how to compile itself.

In Chapter 5, we will descend from the metalinguistic heights to the machine. How does fold actually execute? What are the physical mechanisms — asyncio, threads, nodnod graphs — that carry out the computation? How does theworld's RuntimeAgent map nodnod nodes to OS threads? The abstraction we have built in Chapters 1-4 will bottom out at the metal.

---

## Exercises

**Exercise 4.1.** Implement a complete compilation language for generating Terraform HCL from emergent dataclass annotations. Define TerraformContext, TerraformCompilable, at least three capabilities, and TERRAFORM_PHASE. Show that your language composes with existing SchemaCompilers via `+`.

**Exercise 4.2.** Write a metacircular fold — a fold that, given a list of capabilities describing a fold configuration, produces a fold function. Is this useful? Is it circular?

**Exercise 4.3.** Design a "lazy fold" that defers compile_* method calls until context fields are accessed. What changes? Would existing capabilities work unchanged?

**Exercise 4.4.** Design an "nondeterministic fold" where `OneOf("red", "blue", "green")` produces three compilation results. What does fold return?

**Exercise 4.5.** Nicolajsen (2025) defines five macro system levels. Give examples from real languages for each level. Show that emergent's transforms operate at Level 4 by constructing an example where a syntactic macro breaks but an emergent transform works.

**Exercise 4.6.** What would change if isinstance in fold were replaced with exact type match? Which capabilities would stop working? What property would be lost?

**Exercise 4.7.** Design a Bridge "decompiler": given a FastAPI app, reconstruct the capability annotations. Is perfect decompilation possible? What information is lost?

**Exercise 4.8.** How many distinct compilation languages are currently defined in emergent? Count them. Is the number bounded? What determines the set of possible languages?

**Exercise 4.9.** Map Simonyi's Intentional Programming concepts (intentions, enzymes) to emergent concepts. What did IP lack that emergent has?

**Exercise 4.10.** The query axis has two-level fold: capabilities → Lens → backend. Design a THREE-level fold: capabilities → Lens → optimizer → backend. The optimizer rewrites Lens ops before backend execution (e.g., merging adjacent Filters, pushing Limits down). What frozen dataclass represents the optimizer? How does it compose with existing Lens ops?
