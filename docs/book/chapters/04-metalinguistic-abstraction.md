# 4. Metalinguistic Abstraction

> ... It's in words that the magic is -- Abracadabra, Open Sesame, and the rest -- but the magic words in one story aren't magical in the next. The real magic is to understand which words work, and when, and for what; the trick is to learn the trick.
>
> ... And those words are made from the letters of our alphabet: a couple-dozen squiggles we can draw with the pen. This is the key! And the treasure, too, if we can only get our hands on it! It's as if -- as if the key to the treasure *is* the treasure!
>
> -- John Barth, *Chimera*

You have used fold as a tool. You have traced it through Pydantic, through OpenAPI, through SQL, through query expressions, through the Log. You know the six lines. You know the dispatch: handler map, then isinstance, then skip. You know that capabilities are frozen data and that fold gives them meaning.

Now look at the tool itself.

`CompilationPhase` is a frozen dataclass. It carries `context_type`, `protocol`, `initial` -- data fields, like `MaxLen(255)` carries `value`. `SchemaCompiler` is a frozen dataclass containing a tuple of `CompilationPhase` instances. It has algebraic operations: `+`, `|`, `-`, `&`. It has a `compile` method that calls `compile_entity`, which calls `fold_field`, which calls `fold`.

The compiler IS data. The data IS the compiler.

The reader who senses something vertiginous here is sensing correctly. The fold that gives meaning to all capabilities is itself described by the same encoding as the capabilities it evaluates. This is *metalinguistic abstraction* -- not "embed a DSL in Python," but a system where the evaluator can be inspected, composed, transformed, and compiled by its own mechanisms.

SICP's Chapter 4 makes this the most fundamental idea in programming: *the evaluator, which determines the meaning of expressions in a programming language, is just another program.* In emergent: the fold that determines the meaning of capabilities in a compilation language is itself described by frozen dataclasses -- the same kind of data that fold consumes.

This chapter will make that precise.

---

## 4.1 The Evaluator Is Just Another Program

### 4.1.1 fold as Evaluator

Here is fold, from `emergent/wire/compile/_core.py`:

```python
def fold(items, initial, protocol, method, handlers=None, *, trace=None):
    if trace is not None:
        result, _ = traced_fold(items, initial, protocol, method, handlers, trace)
        return result
    ctx = initial
    for item in items:
        item_cls = item.__class__
        if handlers and item_cls in handlers:
            ctx = handlers[item_cls](item, ctx)
        elif isinstance(item, protocol):
            ctx = getattr(item, method)(ctx)
    return ctx
```

Strip the trace branch and you have eight lines. These eight lines give meaning to every capability in every compilation language in the system. When you write `MaxLen(255)` on a field and it produces Pydantic validation, OpenAPI documentation, SQL column constraints, and a verification check -- all four meanings come from fold dispatching `MaxLen(255)` through four different (protocol, method) pairs. When you write `http_crud("/users", Users)` and it produces a REST API -- that meaning comes from fold dispatching through `DeriveGeneratable`. When you write `Paginated(20)` and the List endpoint gains pagination -- fold dispatching through `DeriveModifiable`.

fold is the universal evaluator. Every compilation language in emergent is defined by a (protocol, context_type, initial) triple. fold evaluates programs written in that language. The programs are capability tuples. The meaning is determined by what the capabilities' `compile_*` methods do to the context.

SICP puts it bluntly:

> "It is no exaggeration to regard this as the most fundamental idea in programming: *The evaluator, which determines the meaning of expressions in a programming language, is just another program.*"

fold is eight lines. You can hold the entire evaluator in your head. Everything that emergent does -- schema compilation, query execution, verification, derivation, world construction -- is this function applied to different data.

### 4.1.2 CompilationPhase Is Data

Now examine what *describes* a compilation language. Here is `CompilationPhase`, from `emergent/wire/compile/_phase.py`:

```python
@dataclass(frozen=True, slots=True)
class CompilationPhase[Ctx]:
    context_type: type[Ctx]
    protocol: type
    initial: Callable[[str, type], Ctx]
    handlers: Mapping[type[Capability], CapabilityHandler[Ctx]] | None = None
    entity: EntityFold[Any] | None = None
```

A frozen dataclass. Five fields. It carries data: which context type to produce, which protocol to dispatch on, how to create the initial context, optional handler overrides, optional entity-level fold.

Compare with a capability:

```python
@dataclass(frozen=True, slots=True)
class MaxLen(UniversalCapability):
    value: int
```

A frozen dataclass. One field. It carries data.

The structural parallel is exact. Both are frozen. Both carry parameters. Both participate in composition. `MaxLen(255)` combines with other capabilities in a tuple. `CompilationPhase` combines with other phases in a `SchemaCompiler`. The encoding is the same.

**Stop and predict.** If CompilationPhase is structurally identical to a capability -- frozen dataclass, data fields, algebraic operations -- what happens when fold consumes a list of CompilationPhases?

### 4.1.3 SchemaCompiler Is a Fold Result

Here is `SchemaCompiler`:

```python
@dataclass(frozen=True, slots=True)
class SchemaCompiler:
    phases: tuple[CompilationPhase[Any], ...]

    def compile(self, cls: type, axes: Axes) -> EntityCompilation:
        return compile_entity(cls, axes, list(self.phases))

    def __add__(self, other):
        """Left-biased union. Idempotent: A + A == A."""
        if isinstance(other, CompilationPhase):
            other = SchemaCompiler(phases=(other,))
        seen = {p.context_type for p in self.phases}
        extra = tuple(p for p in other.phases if p.context_type not in seen)
        return SchemaCompiler(phases=(*self.phases, *extra))
```

A frozen dataclass containing a tuple of phases. Its `__add__` builds a new `SchemaCompiler` by combining phase tuples -- filtering duplicates by `context_type`, appending new phases. This is the same structural combination that fold performs: iterate items, accumulate result.

When you write:

```python
FASTAPI_SCHEMA = SchemaCompiler(phases=(PYDANTIC_PHASE, OPENAPI_PHASE))
```

you are constructing a compiler from two phases. When you write:

```python
FULLSTACK = FASTAPI_SCHEMA + SA_SCHEMA + TERRAFORM_PHASE
```

you are combining compilers with `+`. The result is a new `SchemaCompiler` with the union of all phases. This is fold in algebraic clothing: iterate the phases of the right operand, skip those whose `context_type` is already present, append the rest.

The compiler is not a black box. It is a value. You can inspect its phases: `len(FULLSTACK)` returns the number of phases. You can restrict it: `FULLSTACK - SA_SCHEMA` removes SA phases. You can intersect: `FULLSTACK & FASTAPI_SCHEMA` keeps only phases present in both. The algebra is:

| Operation | Meaning | Law |
|-----------|---------|-----|
| `A + B` | Left-biased union | `A + A == A` (idempotent) |
| `A \| B` | Right-biased merge | Override A's phases with B's |
| `A - B` | Restriction | Remove B's context_types from A |
| `A & B` | Intersection | Keep only shared context_types |

These laws hold because phases are keyed by `context_type` -- a natural identity. The algebra is a bounded semilattice over phase sets.

### 4.1.4 The Three-Layer Collapse

The reader's mental model so far has three layers:

1. **Description** -- capabilities like `MaxLen(255)`, frozen data
2. **Compiler** -- `SchemaCompiler`, the tool that processes descriptions
3. **Output** -- `PydanticContext`, `OpenAPIContext`, the compiled result

Now the layers collapse.

The compiler (`SchemaCompiler`) IS a description -- it is a frozen dataclass, inspectable data. The compiler's phases (`CompilationPhase`) ARE descriptions -- frozen dataclasses with data fields. The compiler can be composed algebraically (`+`, `|`, `-`, `&`) just as capabilities compose in tuples. The compiler's `compile()` method calls `compile_entity`, which calls `fold_field`, which calls `fold` -- the same six-line function that processes `MaxLen(255)`.

There is no privileged level. The description of the evaluator uses the same encoding as the things the evaluator evaluates. In SICP terms: `eval` is written in Scheme, evaluating Scheme expressions. In emergent terms: fold is described by frozen dataclasses, processing frozen dataclasses.

This is what *metacircular* means. Not vicious circularity -- productive self-reference. The evaluator-as-data lets you inspect it, compose it, transform it, and -- as we will see -- compile it.

---

## 4.2 The Metacircular Fold

### 4.2.1 The Six-Fold Chain

The metacircular structure is not abstract. It is a concrete chain of folds, each consuming the output of the previous. Trace what happens from `@derive` to a running FastAPI server.

Starting point:

```python
@schema_meta(http_crud("/users", provider_node=Users), Paginated(20))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, Unique, MaxLen(255)]
```

**Fold 1: Generate.** `compile_derive` calls `fold_schema`:

```python
ctx = fold_schema(cls, ctx, DeriveGeneratable, "compile_derive_generate")
```

Inside fold: `http_crud(...)` is `isinstance(http_crud, DeriveGeneratable)` -- True. fold calls `http_crud.compile_derive_generate(ctx)`. This inspects `User`'s fields and produces five `OpSpec` instances: List, Get, Create, Update, Delete. Each OpSpec is a frozen dataclass containing: name, handler template, effects, input fields, request fields, capabilities.

`Paginated(20)` -- `isinstance(Paginated, DeriveGeneratable)` -- False. Skipped.

**Stop and predict.** Paginated(20) was skipped by DeriveGeneratable. When does it activate?

**Fold 2: Modify.** Same `compile_derive`, next line:

```python
ctx = fold_schema(cls, ctx, DeriveModifiable, "compile_derive_modify")
```

Now `http_crud(...)` -- not DeriveModifiable -- skipped. `Paginated(20)` IS DeriveModifiable. fold calls `Paginated.compile_derive_modify(ctx)`. It scans the OpSpecs for the `Pageable` effect, finds the List spec, replaces its handler with `PaginatedFetchMany(page_size=20)`, adds `page` and `page_size` fields. The List OpSpec is transformed. The other four are untouched.

**The self-reference.** The OpSpecs that Fold 1 produced contain `request_fields` like `{"email": Annotated[str, MaxLen(255)]}`. The `Annotated` types carry capabilities. These capabilities will be folded LATER by target compilers. fold produced data containing fold-consumable data.

**Fold 3: Materialize.** `materialize(ctx)` converts each OpSpec into an `Endpoint` with:
- A trigger (`HTTPRouteTrigger("GET", "/users")`)
- A codec (request/response types built from the OpSpec's field types)
- Capabilities (surface capabilities from the OpSpec)

The request type for List is a dynamically-created dataclass: `UserListOp(page: int = 1, page_size: int = 20, provider: ...)`. The request type for Create carries `Annotated[str, MaxLen(255)]` on its email field.

**Fold 4: Surface compilation.** For each Endpoint's Exposure:

```python
ctx = fold(capabilities, wrap_ctx, FastAPIPipelineCompilable, "compile_fastapi_pipeline")
```

Surface capabilities customize the pipeline -- timeout, retry, rate limiting, authentication. fold dispatches each by `FastAPIPipelineCompilable`.

**Fold 5: Field compilation.** To build the Pydantic validation model for each request type:

```python
ec = SchemaCompiler(phases=(PYDANTIC_PHASE,)).compile(request_type, axes)
```

This calls `fold_field` over the email field's capabilities `(MaxLen(255),)`:
- `MaxLen(255)` -- `isinstance(MaxLen, PydanticCompilable)` -- True -- `MaxLen.compile_pydantic(ctx)` adds `max_length=255` to the Pydantic FieldInfo.

**Fold 6: Assembly.** `assemble_pydantic` produces a `BaseModel`. FastAPI registers routes. The server runs.

The complete chain:

```
Fold 1: fold(schema caps, DeriveGeneratable) --> OpSpecs            [frozen data]
Fold 2: fold(schema caps, DeriveModifiable)  --> transformed OpSpecs [frozen data]
Fold 3: materialize                          --> Endpoints with caps  [frozen data]
Fold 4: fold(surface caps, PipelineCompilable) --> pipeline config   [frozen data]
Fold 5: fold(field caps, PydanticCompilable)   --> Pydantic contexts [frozen data]
Fold 6: assemble                               --> running server
```

Six folds. Each level's output is frozen data. Each level's input is frozen data. The encoding is the same at every level. The same eight-line function at every level.

This is the metacircular evaluator. Not because fold is written in the language it evaluates (that would be trivially true of any Python function). But because the DATA that describes how to fold -- `CompilationPhase`, `SchemaCompiler`, the protocols, the handler maps -- uses the SAME encoding as the data fold processes. Frozen dataclasses describing frozen dataclasses, fold consuming fold-consumable output, all the way down.

### 4.2.2 SICP's eval Compared

In SICP, the metacircular evaluator has a specific shape:

```scheme
(define (eval exp env)
  (cond ((self-evaluating? exp) exp)
        ((variable? exp) (lookup-variable-value exp env))
        ((quoted? exp) (text-of-quotation exp))
        ((assignment? exp) (eval-assignment exp env))
        ((definition? exp) (eval-definition exp env))
        ...
        ((application? exp)
         (apply (eval (operator exp) env)
                (list-of-values (operands exp) env)))
        (else (error "Unknown expression type" exp))))
```

`eval` dispatches on expression type. `apply` extends the environment and calls `eval`. The loop closes: eval calls apply calls eval.

fold has the same architecture:

| SICP metacircular evaluator | emergent metacircular fold |
|---|---|
| `eval` dispatches on expression type via `cond` | `fold` dispatches by `isinstance(item, protocol)` |
| `apply` extends environment, calls `eval` | `compile_*` transforms context, produces foldable data |
| Expression = list (data structure) | Capability = frozen dataclass (data structure) |
| `eval '(* 5 5)` -- data becomes computation | `fold([MaxLen(255)], ctx, PydanticCompilable, ...)` -- data becomes compilation |
| Evaluator defined by dispatch table in `eval` | Language defined by protocol + handler map |
| `(define (eval exp env) ...)` -- 50 lines | `def fold(items, initial, protocol, method, ...)` -- 8 lines |

The key structural parallel: in both systems, the evaluator's output can be fed back as input. In SICP, `(eval '(define (square x) (* x x)) env)` produces a procedure that `eval` can later apply. In emergent, fold over `DeriveGeneratable` produces OpSpecs containing capabilities that later folds consume.

But there is a difference worth noting honestly. SICP's metacircular evaluator is a single 200-line program that the reader can run in one file. emergent's metacircular fold is a pattern distributed across `fold` (8 lines), `CompilationPhase` (class), `SchemaCompiler` (class), `compile_derive` (function), and `materialize` (function). The self-reference is structural, not localized. The six-fold chain IS the metacircular evaluator, but you must trace it across modules to see it.

SICP's evaluator also needs an environment model -- frames, bindings, enclosing environments -- because Scheme has `set!` and closures. emergent does not need an environment model. All data is frozen. All contexts are passed explicitly. `replace()` is substitution, not mutation. The `Axes` dataclass (`Axes(schema=inspect_dataclass, trace=collector, scope_layer=layer)`) serves as the explicit configuration that flows through compilation -- not an environment, but a similar role: context that affects evaluation without being part of the expression.

### 4.2.3 Data as Programs, Programs as Data

SICP Section 4.1.5 delivers a result that changes how the reader thinks about programming:

> "A program is a description of an abstract machine. [...] The evaluator is a universal machine. It mimics other machines when these are described as Lisp programs."

`(define (factorial n) ...)` is a list -- data. Feed it to `eval` and it configures `eval` to behave as a factorial machine. The boundary between program and data, which the reader took for granted, dissolves.

In emergent, the same dissolution:

```python
@schema_meta(http_crud("/users", Users), Paginated(20), Readonly())
```

This capability tuple is a PROGRAM. It describes a machine: a read-only paginated REST API. `http_crud` is the "procedure definition" -- it defines five operations. `Paginated(20)` is a "transformation" -- it modifies the List operation. `Readonly()` is a "filter" -- it removes mutation operations.

`compile_derive` is the EVALUATOR -- it executes this program. The result (two endpoints: paginated List and Get) is the VALUE. The five-to-two reduction is not hard-coded anywhere. It emerges from three capabilities interacting through fold.

**Stop and predict.** If `Readonly()` removes all mutations, and `Paginated(20)` only touches the List spec (which has `Pageable` effect), what is the final set of OpSpecs? How many endpoints does `materialize` produce? What are their HTTP methods and paths?

The answer: two OpSpecs survive. List (GET /users) is paginated. Get (GET /users/{id}) is unchanged. Create, Update, Delete -- all have `Mutation` effects -- are rejected by `Readonly().compile_derive_modify(ctx)`, which calls `ctx.reject_by_effect(Mutation)`.

Now the deeper point. The SAME capability tuple, compiled by a different evaluator (`cli_compile` instead of `fastapi_compile`), produces a DIFFERENT machine -- a CLI tool instead of a REST API. Same program, different machine. The program is more fundamental than any single machine it describes.

And the program itself is data. `http_crud("/users", Users)` is a frozen dataclass. `Paginated(20)` is a frozen dataclass. `Readonly()` is a frozen dataclass. You can inspect them: `Paginated(20).page_size` returns `20`. You can compare them: `Paginated(20) == Paginated(20)` is True. You can put them in a set, serialize them, transmit them. Programs-as-data is not a metaphor. It is the encoding.

---

## 4.3 Variations on a Fold

SICP's Chapter 4 presents four evaluators: the standard metacircular evaluator, a lazy evaluator, a nondeterministic evaluator (`amb`), and a logic programming evaluator. Each shares the eval/apply core but changes evaluation strategy, producing a radically different language. The pedagogical point: the evaluator IS the semantics. Change the evaluator, change the language.

emergent's fold is the shared core. Different protocols give different semantics. The four SICP evaluators map onto four distinct modes of fold.

### 4.3.1 Standard Evaluation -- Immediate Compilation

The standard evaluator is what we have traced in Chapters 1-3. fold processes capabilities left-to-right, calling each `compile_*` method immediately, accumulating the context. Every capability is evaluated eagerly.

```python
ctx = fold(capabilities, initial, PydanticCompilable, "compile_pydantic")
```

`MaxLen(255)` is dispatched immediately. `Unique` is dispatched immediately. The context accumulates constraint after constraint. At the end, the PydanticContext contains all the information needed to build a Pydantic model field.

This corresponds to SICP's applicative-order evaluator: arguments are evaluated before the procedure is applied. In fold: capabilities are compiled before the result is assembled.

### 4.3.2 Lazy Evaluation -- Paginated as Thunk

SICP's lazy evaluator (Section 4.2) modifies `apply` to delay argument evaluation. Arguments become *thunks* -- promises that are forced only when their values are needed. The same expression `(try 1 (/ 1 0))` that errors under applicative order returns `1` under lazy order, because `(/ 1 0)` is never forced.

emergent's three-phase derivation has the same structure:

```python
ctx = fold_schema(cls, ctx, DeriveGeneratable, "compile_derive_generate")   # Phase 1
ctx = fold_schema(cls, ctx, DeriveModifiable, "compile_derive_modify")       # Phase 2
ctx = fold_schema(cls, ctx, DeriveAugmentable, "compile_derive_augment")     # Phase 3
```

`Paginated(20)` implements `DeriveModifiable`, not `DeriveGeneratable`. In Phase 1, fold encounters `Paginated(20)`, checks `isinstance(Paginated, DeriveGeneratable)` -- False -- skips it. Paginated is a *thunk*: present in the capability list but not yet evaluated. It sits dormant through the entire generate phase.

In Phase 2, fold encounters `Paginated(20)` again, checks `isinstance(Paginated, DeriveModifiable)` -- True -- *forces* it. `Paginated.compile_derive_modify(ctx)` runs, transforming the List OpSpec.

The parallel is precise:

| SICP lazy evaluator | emergent three-phase derive |
|---|---|
| Arguments become thunks | Phase 2 capabilities skip Phase 1 |
| Thunks are forced when needed | Phase 2 capabilities are compiled when DeriveModifiable fold runs |
| `(try 1 (/ 1 0))` -- unused arg never errors | `Paginated(20)` doesn't need to know how to generate OpSpecs |
| `force-it` / `delay-it` | Protocol dispatch: DeriveGeneratable vs DeriveModifiable |

The benefit is the same: separation of concerns through deferred evaluation. Generators do not need to anticipate how their output will be modified. Modifiers do not need to understand generation. The staging gap between Phase 1 and Phase 2 -- where OpSpecs exist as pure data, not yet materialized -- is where inspection, transformation, and verification all happen.

**Stop and predict.** `SoftDelete("deleted_at")` also implements `DeriveModifiable`, not `DeriveGeneratable`. In Phase 1, it is skipped. In Phase 2, it performs three transformations on the OpSpecs. What are they?

The answer, from `_transforms.py`:
1. Find the Delete OpSpec (has `Deletes` effect). Replace its handler: `DeleteOne()` becomes `SoftDeleteMark("deleted_at")`. Now "delete" sets `deleted_at = now()` instead of removing the row.
2. Add a query filter: `lambda e: e.deleted_at.is_null()`. All Read ops now exclude soft-deleted records.
3. Remove `deleted_at` from Create input fields -- users don't set deletion timestamps manually.

Three transformations, all operating on the frozen OpSpec data that Phase 1 produced. None of them require any knowledge of how `http_crud` generated the OpSpecs. The thunk was forced, and it transformed the world it found.

### 4.3.3 Nondeterministic Evaluation -- Generate and Prune

SICP's `amb` evaluator (Section 4.3) adds automatic search. Expressions can have multiple values. `(amb 1 2 3)` returns 1, 2, or 3 -- the evaluator explores alternatives. `(require (prime? (+ a b)))` prunes branches where the condition fails. The program describes WHAT it wants, not HOW to search.

emergent's three-phase derivation has the same generate-and-prune structure, but deterministic rather than backtracking:

**Generate (Phase 1):** `http_crud` generates five candidate OpSpecs: List, Get, Create, Update, Delete. These are the "branches" -- five possible operations that the entity might expose.

**Prune (Phase 2):** Transforms filter the candidates by their effects.

`Readonly()` is the `require` of emergent. Its implementation:

```python
@dataclass(frozen=True, slots=True)
class Readonly(SchemaCapability):
    def compile_derive_modify(self, ctx):
        return ctx.reject_by_effect(Mutation)
```

One line. `reject_by_effect(Mutation)` removes every OpSpec whose effects include `Mutation`. Create, Update, Delete -- pruned. List and Get -- kept. The program says "I want only reads." The evaluator prunes the branches.

`MutationsOnly()` is the complement:

```python
def compile_derive_modify(self, ctx):
    return ctx.select_by_effect(Mutation)
```

Keep only the mutation branches. Discard reads.

`WithoutDelete()`:

```python
def compile_derive_modify(self, ctx):
    return ctx.reject_by_effect(Deletes)
```

Keep everything except the delete branch.

The parallel to `amb`:

| SICP amb evaluator | emergent Phase 1 + Phase 2 |
|---|---|
| `(amb 1 2 3)` generates alternatives | `http_crud` generates 5 OpSpecs |
| `(require ...)` prunes | `Readonly()` calls `reject_by_effect(Mutation)` |
| Backtracking explores all valid paths | Sequential filter keeps surviving specs |
| `(if (require ...) v1 v2)` -- conditional | `has_effect(s.effects, Pageable)` -- effect-based dispatch |

The difference: SICP's `amb` backtracks -- it explores alternatives through chronological backtracking with success/failure continuations. emergent's derive is deterministic -- all candidates are generated, then filtered in one pass. This is simpler and always terminates, but it cannot express search problems where the generation itself depends on which branches survived. For compilation, deterministic generate-and-prune is the right model: you want ALL operations first, then you refine.

### 4.3.4 Logic Evaluation -- Verification as Relational Checking

SICP's logic programming evaluator (Section 4.4) expresses knowledge as relations, not computations. `append` is not a procedure that computes a result -- it is a rule that relates three lists. Given any two, the system finds the third. The evaluator uses pattern matching and unification instead of procedure application.

emergent's verification system occupies the same structural position: instead of PRODUCING output, it checks RELATIONS between capabilities.

Here is `verify`, from `emergent/wire/verify/_verify.py`:

```python
def verify(*entities, axes=None, phases=VERIFY_PHASES):
    _axes = axes or Axes.default()
    compiler = SchemaCompiler(phases=phases)
    issues = []
    for entity in entities:
        ec = compiler.compile(entity, _axes)
        for fc in ec:
            for phase in phases:
                ctx = fc[phase]
                issues.extend(ctx.check())
    return tuple(issues)
```

This uses `SchemaCompiler.compile` -- the SAME infrastructure as Pydantic and OpenAPI compilation. The SAME `compile_entity`. The SAME `fold_field`. The only difference: the phases are verification phases whose contexts have `check()` methods:

```python
VERIFY_PHASES = (NUMERIC_VERIFY_PHASE, LENGTH_VERIFY_PHASE, SEMANTICS_VERIFY_PHASE)
```

And here is `NumericVerifyCtx`, from `emergent/wire/verify/_numeric.py`:

```python
@dataclass(frozen=True, slots=True)
class NumericVerifyCtx:
    field_name: str
    field_type: type
    lower_bound: float | None = None
    upper_bound: float | None = None
    exclusive_lower: float | None = None
    exclusive_upper: float | None = None

    def check(self):
        issues = []
        if self.lower_bound is not None and self.upper_bound is not None:
            if self.lower_bound > self.upper_bound:
                issues.append(Issue(
                    self.field_name, Severity.ERROR,
                    f"Min({self.lower_bound}) > Max({self.upper_bound})",
                ))
        # ... more consistency checks
        return tuple(issues)
```

`Min(100)` on a field: `compile_verify_numeric(ctx)` records `lower_bound=100`. `Max(50)` on the same field: `compile_verify_numeric(ctx)` records `upper_bound=50`. `ctx.check()`: `lower_bound > upper_bound` -- `Issue(ERROR, "Min(100) > Max(50)")`.

**Stop and predict.** `verify` uses `SchemaCompiler(phases=VERIFY_PHASES)`. This is the same type as `FASTAPI_SCHEMA = SchemaCompiler(phases=(PYDANTIC_PHASE, OPENAPI_PHASE))`. What happens if you write `FASTAPI_SCHEMA + VERIFY_SCHEMA`?

The answer: a `SchemaCompiler` with five phases -- Pydantic, OpenAPI, NumericVerify, LengthVerify, SemanticsVerify. One `compile()` call runs all five folds per field. You get both compiled output AND consistency checks from the same compilation pass. Verification is not a separate system. It is another set of phases in the same compiler.

The SICP parallel: verification checks relations between capabilities, like the logic evaluator checks relations between terms. `Min(100)` and `Max(50)` RELATE to each other -- min must be <= max. The verification fold doesn't produce output; it accumulates constraints and checks consistency. This is relational, not functional.

The parallel is honest but limited. SICP's logic evaluator has unification -- a powerful bidirectional pattern-matching operation. emergent's verification is unidirectional: it accumulates and checks, but it does not SOLVE for satisfying assignments. A "capability inference" system that, given partial capabilities, inferred the rest would be the full analog. emergent does not have this. The structural parallel (same dispatch core, relational semantics) holds. The depth does not.

### 4.3.5 The Handler Map as Language Definition

SICP's evaluator is defined by its dispatch table -- the `cond` in `eval` that maps expression types to handlers. Add a new clause, define a new construct. The dispatch table IS the language definition.

fold's handler map plays the same role:

```python
terraform_handlers = {
    Identity: lambda cap, ctx: replace(ctx,
        column_spec={**ctx.column_spec, "primary_key": True}),
    MaxLen: lambda cap, ctx: replace(ctx,
        column_spec={**ctx.column_spec, "type": f"VARCHAR({cap.value})"}),
    Unique: lambda cap, ctx: replace(ctx,
        column_spec={**ctx.column_spec, "unique": True}),
}
```

This handler map defines what `Identity`, `MaxLen`, and `Unique` mean in the Terraform language. The capabilities don't implement `TerraformCompilable` -- they don't need to. The handler map provides the translations. This is ADDING A CLAUSE TO EVAL -- defining what each expression type means in a new language.

And the `compile_*` methods on each capability are the distributed language definition. `MaxLen.compile_pydantic` says "in the Pydantic language, MaxLen(255) means `Field(max_length=255)`." `MaxLen.compile_openapi` says "in the OpenAPI language, MaxLen(255) means `{maxLength: 255}`." Each protocol defines a language. Each capability defines its own translation into every language it supports. The open-world skip means new capabilities can be added without modifying existing languages, and new languages can be added without modifying existing capabilities.

Creating a new compilation language requires three things:

1. A context type (frozen dataclass with compilation state)
2. A protocol (`runtime_checkable Protocol` with one `compile_*` method)
3. An initial factory (function creating the initial context)

Bundle them into a `CompilationPhase` and you have a language definition:

```python
TERRAFORM_PHASE = CompilationPhase(
    TerraformContext, TerraformCompilable,
    lambda n, t: TerraformContext(field_name=n, field_type=t),
    handlers=terraform_handlers,
)
```

Add it to an existing compiler with `+`:

```python
FULLSTACK = FASTAPI_SCHEMA + SA_SCHEMA + TERRAFORM_PHASE
ec = FULLSTACK.compile(User, axes)
```

One pass. All phases -- Pydantic, OpenAPI, SQLAlchemy, Terraform -- run simultaneously over each field. The banana-split theorem (Meijer et al. 1991) guarantees this is equivalent to running them separately: any pair of folds over the same list combines into one fold generating a pair. `compile_fields` implements banana-split -- it iterates fields once, running all phases per field.

The language was created in ~15 lines: a context, a protocol, a handler map, a phase. No modifications to fold. No modifications to existing capabilities. No framework extension points. The handler map bridges existing capabilities to the new language. New Terraform-specific capabilities implement `TerraformCompilable` directly. Both paths coexist in the same fold.

---

## 4.4 Semantic Macros

### 4.4.1 Beyond Syntax

A C preprocessor macro operates on tokens. A Lisp macro operates on syntax trees. Template Haskell operates on typed syntax trees. Idris reflection operates on elaborated terms. All four transform PROGRAMS -- they rewrite code before the evaluator sees it.

emergent's transforms -- Paginated, SoftDelete, Readonly, Authenticated -- transform OPERATIONS. They do not rewrite code. They rewrite frozen data that describes behavior: OpSpecs with effects, handler templates, input fields, output projections. The dispatch mechanism is not syntactic pattern matching but effect-based isinstance: `has_effect(s.effects, Mutation)`.

This is a different kind of macro system. Let us formalize what makes it different.

### 4.4.2 Effects as Semantic Dispatch

Each OpSpec carries a tuple of effects:

```python
OpSpec("Delete", ..., effects=(Deletes(), Idempotent()))
OpSpec("List",   ..., effects=(Read(), Pageable(), Sortable()))
OpSpec("Create", ..., effects=(Creates(),))
```

Effects form a hierarchy: `Creates` is a subtype of `Mutation`. `Deletes` is a subtype of `Mutation`. `Read` is distinct from `Mutation`.

Transforms dispatch on effects via isinstance:

```python
# Readonly: reject all mutations
ctx.reject_by_effect(Mutation)  # checks has_effect(s.effects, Mutation)

# Paginated: modify Pageable ops
for s in ctx.specs:
    if has_effect(s.effects, Pageable):
        s = replace(s, handler_template=PaginatedFetchMany(page_size=20), ...)
```

The dispatch is semantic, not syntactic. `Readonly()` does not look for operations named "Create" or "Delete." It looks for operations that have the Mutation effect -- operations whose MEANING includes modification. An operation called "Archive" with a `Deletes` effect would be caught by `reject_by_effect(Deletes)` even though its name says nothing about deletion.

Compare with a syntactic macro that rewrites `delete_user()` calls. If someone renames the function to `archive_user()`, the macro misses it. A syntactic macro is fragile to renaming. A semantic macro is robust to renaming -- it dispatches on meaning, not name.

### 4.4.3 Transforms as Endomorphisms

A transform is a function `DeriveCtx -> DeriveCtx`. The set of all such functions forms a monoid under composition: the identity transform returns `ctx` unchanged, and any two transforms compose.

Concretely, the Phase 2 fold IS monoid composition:

```python
ctx = fold_schema(cls, ctx, DeriveModifiable, "compile_derive_modify")
```

fold iterates the capabilities. Each `DeriveModifiable` capability applies its `compile_derive_modify` to `ctx`. The result is the sequential composition of all transforms: `ctx' = t_n(t_{n-1}(...t_1(ctx)))`.

This means transforms compose. `Paginated(20)` followed by `Readonly()` is well-defined: first paginate the List spec, then remove mutations. `Readonly()` followed by `Paginated(20)` is also well-defined: first remove mutations, then paginate. In the second order, Paginated still finds the List spec (it has `Pageable`, not `Mutation`) and paginates it.

**Stop and predict.** Are these two orderings equivalent? Does `Paginated(20) >> Readonly()` produce the same result as `Readonly() >> Paginated(20)`?

The answer: yes, because their effects are independent. `Paginated` targets `Pageable` specs. `Readonly` targets `Mutation` specs. No spec has both `Pageable` and `Mutation` (List has `Pageable` and `Read`; Create/Update/Delete have `Mutation` but not `Pageable`). The transforms operate on disjoint subsets of specs. They commute.

This is not always the case. `SoftDelete("deleted_at")` modifies the Delete spec (replacing its handler) and adds a query filter to Read specs. If a transform also modified Read specs' query filters, they would not commute -- the order would matter. The endomorphism monoid does not guarantee commutativity. It guarantees closure (composition of transforms is a transform) and associativity.

### 4.4.4 Staged Compilation

The three-phase structure gives transforms a crucial property: they operate on intermediate representations, not on source code or final output.

Between `@derive` and the FastAPI routes, the OpSpecs existed as pure data. During that staging gap:

- `Paginated` read the `Pageable` effect and replaced the handler
- `SoftDelete` read the `Deletes` effect, replaced the handler, added a query filter, removed a field from Create
- `explain_derive(ctx)` could print every OpSpec in human-readable form
- `verify()` could check that no OpSpec has contradictory effects
- A second generator (`cli_crud`) could fork the derivation context

If compilation went straight from `@derive` to FastAPI routes -- no OpSpec IR, no staging -- none of this would be possible. The staging IS the metalinguistic abstraction: OpSpecs are the "programs" that the derivation "language" produces, and `materialize()` is the "evaluator" that runs them.

This maps to SICP Section 4.1.7's insight: separate what can be determined from the expression alone (analysis time) from what depends on the environment (execution time). `analyze` processes the expression ONCE, producing an execution procedure that can be called MANY times with different environments.

emergent has the same split:

1. **Definition time:** `CompilationPhase(PydanticContext, PydanticCompilable, _pydantic_initial)` -- the phase is defined once. Protocol, method, initial factory are fixed. This is `analyze`.
2. **Compilation time:** `compile_fields(User, axes, [PYDANTIC_PHASE])` -- the phase is applied to a specific entity. This is the execution procedure called with an environment.
3. **Assembly time:** `assemble_pydantic(User, ec)` -- compiled result becomes a concrete artifact. A stage SICP does not have, because SICP's output is a value while emergent's output is a type.

The three-phase derivation (`compile_derive`) is an even deeper staging: Phase 1 produces intermediate data (OpSpecs), Phase 2 transforms it, Phase 3 augments it, then `materialize` converts it to endpoints. Four stages of deferred evaluation, each operating on the previous stage's frozen output.

### 4.4.5 What Makes This Novel

Traditional macro systems and emergent's transforms compared:

| Property | C preprocessor | Lisp macros | Template Haskell | emergent transforms |
|----------|---------------|-------------|------------------|---------------------|
| Dispatch | Textual match | Syntax pattern | Type-aware pattern | Effect isinstance |
| Target | Token stream | S-expression | Typed AST | Frozen OpSpec data |
| Composability | None | Manual | Manual | Monoid (automatic) |
| Open-world | No | No | No | Yes (new effects, new transforms) |
| When | Before parse | Before compile | Before compile | Between generate and materialize |
| Level | Lexical | Syntactic | Type-aware | Semantic |

The combination -- semantic dispatch on effects, composition via monoid, open-world extensibility, operation on frozen IR -- does not appear in existing macro systems. Each property exists separately: Intentional Programming (Simonyi 1995) had semantic dispatch but no algebra and no formalization. Racket macros have composability but syntactic dispatch. emergent's contribution is the combination, made possible by the frozen-data encoding: because OpSpecs are values, transforms are pure functions, and effects form a hierarchy, the pieces compose mechanically.

---

## 4.5 Capabilities as Propositions

### 4.5.1 The Correspondence

Each capability on a field is a proposition about that field:

- `MaxLen(255)` asserts: "the maximum length of this field is 255"
- `Min(0)` asserts: "the minimum value of this field is 0"
- `Unique` asserts: "this field's values are unique"
- `Identity` asserts: "this field identifies the entity"

fold over capabilities constructs a compilation context. Each `compile_*` call is one step: from the current context and a new proposition, derive an extended context. `MaxLen(255).compile_pydantic(ctx)` takes the context (what we know so far) and the proposition (max length is 255), and produces a new context incorporating the constraint.

This has the shape of proof construction. From premises (initial context) and inference steps (capabilities), derive a conclusion (compiled context). Each step preserves consistency: if the input context was valid, the output context is valid (assuming the capability's assertion is consistent with what came before).

`verify()` is the consistency check. It asks: do these propositions contradict?

```python
@dataclass
class Bad:
    value: Annotated[int, Min(100), Max(50)]
```

`Min(100)` records `lower_bound=100`. `Max(50)` records `upper_bound=50`. `check()` detects: `lower_bound > upper_bound`. No value satisfies both. The propositions are inconsistent.

In logical terms: the conjunction `Min(100) AND Max(50)` has no model. No assignment to `value` makes both propositions true. `verify()` is a satisfiability checker for the specific constraint languages implemented (numeric ranges, length ranges, semantic consistency).

### 4.5.2 The Subformula Principle

Gentzen proved that in a normalized proof, only subformulas of the conclusion appear. A proof of `A AND B` uses only things relevant to `A` and `B`.

In emergent: fold's open-world skip implements the subformula principle. `Unique` has no `compile_pydantic` method. When fold encounters `Unique` during Pydantic compilation, it checks `isinstance(Unique, PydanticCompilable)` -- False -- skips it. `Unique` is not relevant to the Pydantic proof. It is not an error. It is irrelevance.

`Unique` IS relevant to the SQL proof. `isinstance(Unique, SQLAlchemyCompilable)` -- True -- fold dispatches. `Unique` IS relevant to the verification proof. `isinstance(Unique, SemanticsVerifyCompilable)` -- True.

Each compilation target defines a proof system. Each protocol defines which propositions (capabilities) are subformulas of that system. The open-world skip is the subformula principle made operational: irrelevant propositions are silently excluded.

### 4.5.3 Verification IS Compilation

The deepest consequence: verification is not a separate system. It is another compilation target. `VERIFY_PHASES` are `CompilationPhase` instances, just like `PYDANTIC_PHASE`. They use the same `fold_field`. The same `compile_fields`. The same `SchemaCompiler`.

```python
VERIFY_SCHEMA = SchemaCompiler(phases=VERIFY_PHASES)
issues = verify(User)

# Equivalent to:
compiler = SchemaCompiler(phases=VERIFY_PHASES)
ec = compiler.compile(User, axes)
issues = []
for fc in ec:
    for phase in VERIFY_PHASES:
        issues.extend(fc[phase].check())
```

And you can combine them:

```python
FULL_CHECK = FASTAPI_SCHEMA + VERIFY_SCHEMA
ec = FULL_CHECK.compile(User, axes)
# ec contains both Pydantic contexts AND verify contexts
# One pass, both compilation and consistency checking
```

The Curry-Howard lens explains why this works. Compilation and verification are both morphisms from the initial algebra (capability list) to different target algebras. Hutton's universal property guarantees that both are folds. Since both are folds over the same list, banana-split combines them into a single pass. Compilation and verification are not separate concerns that happen to use similar infrastructure. They are two instances of the same thing: fold from propositions to a target algebra.

This should be called Curry-Howard-*inspired*, not a formal Curry-Howard correspondence. True Curry-Howard maps types to propositions and programs to proofs with precise structural rules. Here, capabilities are runtime values (not types), fold is iteration (not a proof term), and verification checks value-level consistency (not type-level consistency). The analogy is structurally suggestive and practically useful -- it explains WHY verification composes with compilation -- but it is not a formal isomorphism.

---

## 4.6 The Fractal

### 4.6.1 Level 0: Expressions as Data

In `examples/fractal.py`, the polynomial `x^2 + 2x + 1` is represented as:

```python
@dataclass(frozen=True, slots=True)
class Poly(Capability):
    coefficients: tuple[float, ...]

    def compile_eval(self, ctx: EvalCtx) -> EvalCtx:
        coeffs = self.coefficients
        def evaluate(x):
            result = 0.0
            for c in coeffs:
                result = result * x + c
            return result
        return replace(ctx, evaluate=evaluate)

    def compile_latex(self, ctx: LatexCtx) -> LatexCtx:
        # ... renders to LaTeX string
        return replace(ctx, latex=latex_string)

    def compile_python(self, ctx: PythonCtx) -> PythonCtx:
        # ... renders to Python source
        return replace(ctx, code=python_string)

    def compile_derivative(self, ctx: DerivativeCtx) -> DerivativeCtx:
        degree = len(self.coefficients) - 1
        d_coeffs = tuple(
            self.coefficients[i] * (degree - i)
            for i in range(len(self.coefficients) - 1)
        )
        return replace(ctx, coefficients=d_coeffs)
```

`Poly(1, 2, 1)` is a frozen dataclass. It is x^2 + 2x + 1. It is data. And it knows how to compile itself into four different languages: evaluation (a callable), LaTeX (a string), Python (source code), and symbolic differentiation (derivative coefficients).

Four compilation phases exist:

```python
EVAL_PHASE = CompilationPhase(EvalCtx, EvalCompilable, lambda n, t: EvalCtx(n, t))
LATEX_PHASE = CompilationPhase(LatexCtx, LatexCompilable, lambda n, t: LatexCtx(n, t))
PYTHON_PHASE = CompilationPhase(PythonCtx, PythonCompilable, lambda n, t: PythonCtx(n, t))
DERIVATIVE_PHASE = CompilationPhase(DerivativeCtx, DerivativeCompilable, lambda n, t: DerivativeCtx(n, t))
```

Four languages. Same algebra. Same fold.

### 4.6.2 Level 1: Compiling Entities

An entity whose fields are formulas:

```python
@dataclass
class Physics:
    position: Annotated[float, Poly(0.5, 0, 0), Scale(9.81)]    # 0.5 * 9.81 * t^2
    velocity: Annotated[float, Poly(1, 0), Scale(9.81)]          # 9.81 * t
    energy: Annotated[float, Poly(0.5, 0, 0), Scale(9.81), Scale(1)]
```

Compile it with the algebra:

```python
FULL_ALGEBRA = EVAL_SCHEMA + LATEX_SCHEMA + PYTHON_SCHEMA + DERIVATIVE_SCHEMA
ec = FULL_ALGEBRA.compile(Physics, axes)
```

One pass. Four languages. For the `position` field: fold processes `Poly(0.5, 0, 0)` then `Scale(9.81)` through each of four phases. The EvalCtx accumulates a callable. The LatexCtx accumulates `"9.81 \cdot (0.5x^{2})"`. The PythonCtx accumulates `"9.81 * (0.5*x**2)"`. The DerivativeCtx accumulates coefficient `(1.0, 0)` (derivative of 0.5x^2 is x).

This is Level 1 of the fractal: fold compiling an entity's fields through multiple languages.

### 4.6.3 Level 2: Fold Producing Capabilities

`derive_derivatives(Physics)` inspects the entity, compiles each field through `DERIVATIVE_PHASE` to get derivative coefficients, and creates a NEW entity type whose fields carry `Poly` capabilities with those coefficients:

```python
def derive_derivatives(entity):
    fields = inspect_dataclass(entity)
    new_annotations = {}
    for name, info in fields.items():
        d_ctx = DerivativeCtx(field_name=name, field_type=float)
        for cap in info.capabilities:
            if isinstance(cap, DerivativeCompilable):
                d_ctx = cap.compile_derivative(d_ctx)
        if d_ctx.coefficients:
            new_annotations[f"d_{name}"] = Annotated[float, Poly(*d_ctx.coefficients)]
    return dataclass(type(f"{entity.__name__}Derivative", (), {"__annotations__": new_annotations}))
```

fold (via `compile_derivative`) produced coefficients. Those coefficients became `Poly` capabilities on a new entity. The new entity can be compiled by the same `FULL_ALGEBRA`. fold's output became fold's input.

This is Level 2: fold producing capabilities that are themselves fold-consumable.

### 4.6.4 Level 3: Compiling the Compiler

Now the metacircular capstone. A "compiler configuration" entity:

```python
@dataclass
class FullReport:
    formulas: Annotated[str, IncludePhase(LATEX_PHASE), IncludePhase(PYTHON_PHASE), OutputFormat("text")]
    values: Annotated[str, IncludePhase(EVAL_PHASE), OutputFormat("dict")]
    derivatives: Annotated[str, IncludePhase(DERIVATIVE_PHASE), OutputFormat("text")]
```

`IncludePhase` is a capability that, when compiled, adds a `CompilationPhase` to the output context:

```python
@dataclass(frozen=True, slots=True)
class IncludePhase(Capability):
    phase: CompilationPhase[Any]

    def compile_output(self, ctx: OutputCtx) -> OutputCtx:
        return replace(ctx, phases=(*ctx.phases, self.phase))
```

A capability that carries a `CompilationPhase` as data. When fold calls `IncludePhase.compile_output(ctx)`, it ADDS A PHASE TO THE COMPILER CONFIGURATION. fold is producing a compiler configuration. The compiler is being configured by the same mechanism it uses to configure output.

Compile the configuration:

```python
config = compile_compiler_config(FullReport)  # fold over IncludePhase caps
# config = {
#   "formulas": ((LATEX_PHASE, PYTHON_PHASE), "text"),
#   "values":   ((EVAL_PHASE,), "dict"),
#   "derivatives": ((DERIVATIVE_PHASE,), "text"),
# }
```

Use the compiled configuration to build a compiler, and compile an entity:

```python
for name, (phases, fmt) in config.items():
    compiler = SchemaCompiler(phases=phases)    # config becomes compiler
    ec = compiler.compile(Physics, axes)        # compiler compiles entity
```

**Three levels of fold:**

```
Level 3: fold(IncludePhase caps)  --> compiler config  [frozen data]
Level 2: fold(derivative caps)    --> new entity        [frozen data with Poly caps]
Level 1: fold(Poly caps)          --> LaTeX/Python/eval [compiled output]
Level 0: Poly(1, 2, 1)           --> data              [the expression itself]
```

Each level uses the same fold. Each level's data is frozen dataclasses. Each level's output can be the next level's input. The fractal: the compiler compiles the compiler configuration, which compiles the entity, whose fields are compiled through the phases specified by the compiled configuration.

This is `examples/fractal.py`, and it runs. It is not a thought experiment. `uv run python examples/fractal.py` produces output at every level.

**Stop and predict.** What would Level 4 look like? A capability that, when compiled, produces an `IncludePhase` capability? fold producing capabilities that produce compiler configurations that produce compilers? Where does it end?

It ends wherever you stop composing. fold always terminates (finite iteration over a finite tuple). Each level is well-defined. The fractal is conceptually infinite but practically finite -- you compose as many levels as your problem demands. Most real programs use one or two levels. The six-fold chain of `compile_derive` to FastAPI uses six. `fractal.py` uses three plus one. The mechanism places no upper limit.

---

## 4.7 What Doesn't Map Cleanly

Honesty about the SICP parallel requires noting where it breaks.

**No environment model.** SICP's metacircular evaluator implements frames, bindings, and enclosing environments because Scheme has `set!` and closures with free variables. emergent doesn't need environments. All data is frozen. All contexts are passed explicitly. `replace()` is substitution. This makes the model simpler -- no equivalent of SICP's Chapter 3 environment model complications -- but it means there is no deep analog to SICP's sections on variable lookup and scope.

**No halting problem.** SICP Section 4.1.5 Exercise 4.15 presents the halting problem -- the universal machine has fundamental limits. emergent's fold always terminates: finite iteration over a finite tuple. But the question "does this set of capabilities produce a consistent compilation?" is undecidable in the general case (it reduces to satisfiability). The verification phases check specific decidable fragments. fold always terminates; the question of what it means to verify arbitrary capability combinations does not always have a decidable answer.

**No continuations.** SICP's amb evaluator uses success/failure continuations -- the internal machinery that makes backtracking work. emergent's three-phase derive achieves generate-and-prune through sequential folds, not backtracking. This is deterministic and simpler, but it means emergent cannot express the full power of nondeterministic computation. Compilation is a total function: you compile ALL capabilities, you don't search for a satisfying subset.

**No unification.** SICP's query language uses unification -- bidirectional pattern matching. emergent's query axis uses expressions and filters, which are unidirectional. Verification checks consistency but does not solve for satisfying assignments. The structural parallel (same dispatch core, relational semantics) holds. The algorithmic power does not.

**Distributed, not localized.** SICP's metacircular evaluator is one file, 200 lines. emergent's metacircular fold is a pattern across modules: `fold` in `_core.py`, `CompilationPhase` in `_phase.py`, `SchemaCompiler` in `_phase.py`, `compile_derive` in `_compile.py`, `materialize` in the derive package. The `fractal.py` example is the closest to a self-contained metacircular artifact.

These gaps are real. The emergent model is simpler than SICP's in some dimensions (no mutation, no environments, always terminates) and shallower in others (no unification, no backtracking). The power comes from a different place: not from the evaluator's internal complexity, but from the encoding's composability -- the fact that compilers, phases, and capabilities all share one representation, and fold processes all of them.

---

## 4.8 The Evaluator as Program -- Reprise

SICP closes Chapter 4 with:

> "We come to see ourselves as designers of languages, rather than only users of languages designed by others."

In emergent: every `CompilationPhase` defines a compilation language. Every set of capabilities that implement the phase's protocol constitute the programs of that language. fold evaluates them.

When you write a new `CompilationPhase`:

```python
TERRAFORM_PHASE = CompilationPhase(
    TerraformContext, TerraformCompilable,
    lambda n, t: TerraformContext(field_name=n, field_type=t),
    handlers=terraform_handlers,
)
```

you are not "adding a feature to emergent." You are *designing a compilation language*. The `TerraformContext` is the language's value domain. `TerraformCompilable` is the set of well-formed expressions. The handler map extends the language to cover existing capabilities. `compile_*` methods on new capabilities extend the language further.

When you write `FASTAPI_SCHEMA + TERRAFORM_PHASE`, you are evaluating two programs simultaneously -- one in the Pydantic language, one in the Terraform language -- from the same source text. The capability tuple is the shared program. Each phase is a different evaluator. Each evaluator gives the program a different meaning.

And because fold is eight lines, the evaluator is transparent. There is no hidden complexity. No metaclass machinery. No framework magic. Eight lines that iterate a list, check isinstance, and call a method. The magic is not in the evaluator. The magic is in the capabilities -- the frozen data that knows how to compile itself.

In Chapter 5, we will descend from the metalinguistic heights to the machine. How does fold actually execute? What are the physical mechanisms -- asyncio, threads, nodnod graphs -- that carry out the computation? How does RuntimeAgent map nodnod nodes to OS threads? The abstraction we have built in Chapters 1-4 will bottom out at the metal.

---

## Exercises

**Exercise 4.1.** Trace the full six-fold chain for this entity:

```python
@schema_meta(http_crud("/products", Store), Paginated(10), SoftDelete("removed_at"))
@dataclass
class Product:
    id: Annotated[int, Identity]
    name: Annotated[str, MaxLen(100)]
    price: Annotated[float, Min(0)]
    removed_at: datetime | None = None
```

For each fold, state: (a) what protocol dispatches, (b) which capabilities match, (c) what frozen data is produced. How many OpSpecs survive after Phase 2? What HTTP endpoints does the final server expose?

**Exercise 4.2.** The `SchemaCompiler` algebra has four operations: `+`, `|`, `-`, `&`. Prove or disprove each law:

- `A + A == A` (idempotent)
- `(A + B) + C == A + (B + C)` (associative)
- `A + empty == A` (identity)
- `A + B == B + A` (commutative)

For the law that fails: construct a concrete counterexample using `PYDANTIC_PHASE` and `OPENAPI_PHASE`.

**Exercise 4.3.** Write a complete compilation language for generating JSON Schema from emergent dataclass annotations. Define `JsonSchemaContext`, `JsonSchemaCompilable`, handler mappings for `MaxLen`, `Min`, `Max`, `Unique`, and `JSONSCHEMA_PHASE`. Show that `FASTAPI_SCHEMA + JSONSCHEMA_PHASE` compiles a User entity to both Pydantic models and JSON Schema in one pass.

**Exercise 4.4.** `Readonly()` and `MutationsOnly()` are dual: one keeps reads, the other keeps mutations. What is `Readonly() >> MutationsOnly()` (apply both in sequence)? What is `MutationsOnly() >> Readonly()`? Do they commute? Is the result the same as `OnlyOps(())`?

**Exercise 4.5.** Design a "nondeterministic fold" where `OneOf("red", "blue", "green")` produces three compilation results -- one per color. What does fold return? (Hint: the context must be a collection, not a single value.) How does this relate to SICP's `amb`?

**Exercise 4.6.** What would change if `isinstance` in fold were replaced with exact type match (`item.__class__ is protocol`)? Which capabilities would stop working? What property would be lost? (Hint: consider capability inheritance hierarchies.)

**Exercise 4.7.** `IncludePhase(LATEX_PHASE)` is a capability that produces a compiler configuration. Design `ExcludePhase(PYDANTIC_PHASE)` -- a capability that REMOVES a phase from the compiler configuration. Implement `compile_output`. What does the compiler configuration look like after folding `[IncludePhase(LATEX_PHASE), IncludePhase(PYTHON_PHASE), ExcludePhase(LATEX_PHASE)]`?

**Exercise 4.8.** The verification system uses the same `SchemaCompiler` as compilation. Design a new verification phase: `EFFECT_VERIFY_PHASE` that checks whether a derivation's OpSpecs have contradictory effects (e.g., an operation marked both `Read` and `Creates`). What is the context type? What does `check()` look for?

**Exercise 4.9.** In the Curry-Howard analogy, the open-world skip corresponds to the subformula principle: irrelevant propositions are excluded from the proof. Write a capability `NonEmpty` that means "this field must have at least one element." Implement `compile_pydantic`, `compile_openapi`, and `compile_verify_length`. What proposition does `NonEmpty` assert? In which proof systems is it relevant?

**Exercise 4.10.** `fractal.py` has three levels. Design Level 4: a capability `MetaReport` that, when compiled, produces a `FullReport`-like configuration entity. fold produces an entity, that entity is compiled to produce a compiler configuration, that configuration compiles another entity. Four levels of fold. Sketch the types and trace one path through all four levels.

**Exercise 4.11.** Map Simonyi's Intentional Programming concepts (intentions, enzymes, projection) to emergent concepts (capabilities, compile_* methods, assemble_*). What did IP lack that emergent has? What did IP have that emergent lacks?

**Exercise 4.12.** The six-fold chain from `@derive` to running server is emergent's metacircular evaluator. SICP's metacircular evaluator is 200 lines. Count the total lines of code involved in emergent's six-fold chain (from `fold` through `compile_derive` through `materialize` through `fastapi_compile` through `assemble_pydantic`). Is emergent's metacircular fold more or less complex than SICP's?

**Exercise 4.13.** `verify(User)` combines with `FASTAPI_SCHEMA` via `+`. Design a compilation phase `DOCUMENTATION_PHASE` whose context accumulates human-readable documentation for each field, drawing from all capabilities' descriptions. Show that `FASTAPI_SCHEMA + VERIFY_SCHEMA + DOCUMENTATION_PHASE` produces compiled output, consistency checks, AND documentation in one pass.

**Exercise 4.14 (research).** emergent's verification checks specific decidable fragments (numeric ranges, length ranges, semantic consistency). The general problem -- "does there exist a value satisfying ALL capabilities on this field?" -- is undecidable (reduces to satisfiability). Identify one realistic combination of capabilities where the general problem is undecidable but emergent's specific checks miss the inconsistency. What would be needed to catch it?
