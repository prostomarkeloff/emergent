# 1. Building Abstractions with Capabilities

> The acts of the mind, wherein it exerts its power over simple ideas, are chiefly these three: 1. Combining several simple ideas into one compound one, and thus all complex ideas are made. 2. The second is bringing two ideas, whether simple or complex, together, and setting them by one another so as to take a view of them at once, without uniting them into one, by which it gets all its ideas of relations. 3. The third is separating them from all other ideas that accompany them in their real existence: this is called abstraction, and thus all its general ideas are made.
>
> — John Locke, *An Essay Concerning Human Understanding* (1690)

We are about to study the idea of a *compilation process*. Compilation processes are abstract beings that inhabit programs. As they evolve, processes transform abstract things called *capabilities* into concrete things called *artifacts* — Pydantic models, OpenAPI schemas, SQL tables, HTTP endpoints, CLI parsers, Telegram commands. The evolution of a compilation process is directed by a pattern of rules called *fold*. People create capabilities to direct fold. In effect, we describe meaning and let fold produce the plumbing.

A compilation process is indeed much like a sorcerer's idea of a spirit. It cannot be seen or touched while it runs. However, it is very real. It can produce a working REST API from three lines of annotation. It can produce a distributed multi-agent system from a tuple of frozen dataclasses. It can verify at import time that your field constraints don't contradict each other. The capabilities we use to direct compilation processes are like a sorcerer's spells. They are carefully composed from frozen dataclasses in arcane and esoteric type annotations that prescribe the artifacts we want our compilation processes to produce.

A compilation process, when fed consistent capabilities, produces correct artifacts precisely and deterministically. The same capabilities, the same fold, the same result — always. Thus, like the sorcerer's apprentice, novice programmers must learn to understand and to anticipate the consequences of their capabilities. Even small contradictions (usually called *schema errors*) in capabilities can have complex and unanticipated consequences — a field that is simultaneously read-only and required, an endpoint that accepts data the database will reject, a query that returns non-deterministic results.

Fortunately, learning to compose capabilities is considerably less dangerous than learning to write compilers by hand, because the fold that consumes them is contained: it is six lines of Python, it always terminates, and when contradictions arise, the verification phases catch them before any server starts.

Master software engineers have the ability to organize capabilities so that they can be reasonably sure that the resulting compilation will produce the artifacts intended. They can visualize the behavior of their systems in advance — because capabilities are frozen data, printable and inspectable, and `explain()` produces a trace of every fold step. They know how to structure capabilities so that unanticipated problems do not lead to catastrophic consequences: orthogonal axes ensure that a bug in one dimension cannot propagate to another. Well-designed capability systems, like well-designed computational systems, are designed in a modular manner, so that the capabilities can be constructed, replaced, and debugged separately.

## Programming in emergent

We need an appropriate language for describing compilation processes, and we will use for this purpose the Python framework emergent. Just as our everyday thoughts are usually expressed in natural language, and descriptions of quantitative phenomena are expressed with mathematical notations, our compilational thoughts will be expressed in emergent.

emergent was begun in January 2026 as a formalism for reasoning about the use of certain kinds of frozen dataclasses, called *capabilities*, as a model for multi-target compilation. The framework is based on a paper by Meijer, Fokkinga, and Paterson (1991) — not cited in its design, but discovered to formalize what it was already doing — which showed that every inductive data type admits a unique structurally recursive consumer called a *catamorphism*. In emergent, capabilities are the data type and fold is the catamorphism.

Despite its inception as a compilation framework, emergent is a practical tool. An emergent interpreter — `fold` — is a function that carries out compilation processes described in emergent capabilities. The first emergent fold was six lines of Python. Emergent, whose name reflects the property that complex artifacts *emerge* from simple declarations, was designed to provide capability-manipulating facilities for attacking the problem of scattered meaning: the endemic situation in software where a single fact about a field must be manually transcribed into five files.

emergent was not the product of a concerted design effort. Instead, it evolved informally in response to the author's needs and to pragmatic implementation considerations. This evolution, together with the flexibility and elegance of the initial conception — frozen dataclasses with compile_* methods, dispatched by Protocol isinstance checks — has enabled emergent to continually adapt to encompass the most modern ideas about software construction: from web APIs to symbolic algebra to distributed multi-agent systems.

Because of its experimental character and its emphasis on capability manipulation, emergent was at first applicable only to web API generation. Over time, however, the same encoding — frozen dataclass + compile_* methods + fold — was found to apply to query compilation, schema verification, program derivation, runtime scheduling, and distributed computation. If emergent was not initially designed for these applications, why are we using it as the framework for our discussion of compilation thinking? Because the framework possesses unique features that make it an excellent medium for studying important compilation constructs and data structures and for relating them to the linguistic features that support them. The most significant of these features is the fact that emergent descriptions of compilation processes, called *capabilities*, can themselves be represented and manipulated as emergent data. The importance of this is that there are powerful program-design techniques that rely on the ability to blur the traditional distinction between "passive" data and "active" compilation processes. As we shall discover, emergent's flexibility in handling capabilities as data makes it one of the most convenient frameworks in existence for exploring these techniques. The ability to represent compilation processes as data also makes emergent an excellent framework for writing programs that must manipulate other programs as data, such as the derivation engine that generates REST endpoints from dataclass annotations, or the theworld runtime that generates a distributed agent system from a tuple of capabilities.

---

## 1.1 The Elements of Compilation

A powerful compilation framework is more than just a means for generating boilerplate. The framework also serves as a framework within which we organize our ideas about what software *means*. Thus, when we describe a compilation framework, we should pay particular attention to the means that the framework provides for combining simple ideas to form more complex ideas. Every powerful compilation framework has three mechanisms for accomplishing this:

- **primitive capabilities**, which represent the simplest facts the framework is concerned with,
- **means of combination**, by which compound capabilities are built from simpler ones, and
- **means of abstraction**, by which compound capabilities can be named and manipulated as units.

In compilation, we deal with two kinds of elements: capabilities and contexts. (Later we will discover that they are really not so distinct.) Informally, capabilities are the "meaning" that we want to compile, and contexts are the accumulation targets that carry the compilation state for each target. Thus, any powerful compilation framework should be able to describe primitive capabilities and primitive contexts and should have methods for combining and abstracting capabilities and contexts.

In this chapter we will deal only with simple schema capabilities so that we can focus on the rules for building compilation processes. In later chapters we will see that these same rules allow us to build compilation processes for queries, verification, derivation, and distributed computation as well.

### 1.1.1 Capabilities

One easy way to get started at compilation is to examine some typical interactions with fold for emergent capabilities. Imagine that you have a field on a dataclass. You annotate it with a capability:

```python
email: Annotated[str, MaxLen(255)]
```

MaxLen(255) is a *capability*. It is a frozen dataclass with a `value` field:

```python
@dataclass(frozen=True, slots=True)
class MaxLen(UniversalCapability):
    value: int
```

If you present fold with this capability and a Pydantic context, fold will respond by producing a new context with the max_length set:

```python
ctx = PydanticContext(field_name="email", field_type=str, field_info=FieldInfo())
result = fold([MaxLen(255)], ctx, PydanticCompilable, "compile_pydantic")
# result.field_info now has max_length=255
```

Capabilities can be combined with other capabilities to form compound annotations that represent the application of multiple constraints to a field. For example:

```python
email: Annotated[str, MaxLen(255), Unique]
```

```python
result = fold([MaxLen(255), Unique()], ctx, PydanticCompilable, "compile_pydantic")
```

Annotations such as these, formed by placing a list of capabilities within `Annotated`, are called *combinations*. The base type (`str`) is the carrier, and the capabilities are the elements. The result of compiling a combination is obtained by applying fold to the list of capabilities with an initial context — each capability transforms the context in turn.

A second advantage of capability combination is that it extends in a straightforward way to allow capabilities to be nested — that is, to have capabilities that attach not just to fields but to entire entities:

```python
@schema_meta(SchemaName("users"), Timestamps("created_at", "updated_at"))
@dataclass
class User:
    id: Annotated[int, Identity]
    email: Annotated[str, MaxLen(255), Unique]
```

There is no limit (in principle) to the number of capabilities on a field or on an entity. It is we humans who get confused by still relatively simple annotations. We can help ourselves by keeping the annotations short and using patterns — pre-composed capability bundles — for common cases.

Even with complex annotations, fold always operates in the same basic cycle: it iterates the capability list, checks isinstance against the protocol, calls the compile_* method, and accumulates the context. This mode of operation is often expressed by saying that fold performs a *catamorphism* over the capability list.

### 1.1.2 Naming and the Context

A critical aspect of a compilation framework is the means it provides for using names to refer to compilation objects. We say that a name identifies a *phase* whose *value* is a complete fold configuration.

In emergent, we name fold configurations with CompilationPhase:

```python
PYDANTIC_PHASE = CompilationPhase(
    PydanticContext, PydanticCompilable, _pydantic_initial,
)
```

causes the framework to associate the context type `PydanticContext`, the protocol `PydanticCompilable`, and the initial factory into a single named object. Once this association is made, we can refer to the entire fold configuration by name:

```python
OPENAPI_PHASE = CompilationPhase(
    OpenAPIContext, OpenAPICompilable, _openapi_initial,
)
```

Here are further examples:

```python
ARGPARSE_PHASE = CompilationPhase(ArgparseContext, ArgparseCompilable, _argparse_initial)
CONSTRAINTS_PHASE = CompilationPhase(ConstraintsContext, ConstraintsCompilable, _constraints_initial)
STORAGE_FIELD_PHASE = CompilationPhase(StorageFieldContext, StorageFieldCompilable, _storage_field_initial)
```

CompilationPhase is our framework's simplest means of abstraction, for it allows us to use simple names to refer to the results of compound fold configurations. In general, compilation objects may have very complex structures, and it would be extremely inconvenient to have to remember and repeat their protocol, context type, and initial factory each time we want to use them. Indeed, complex compilation systems are constructed by building, step by step, compilation objects of increasing complexity. The framework makes this step-by-step construction particularly convenient because phases can be composed incrementally into SchemaCompilers:

```python
FASTAPI_SCHEMA = SchemaCompiler(phases=(PYDANTIC_PHASE, OPENAPI_PHASE))
CLI_SCHEMA = SchemaCompiler(phases=(ARGPARSE_PHASE,))
FULL = FASTAPI_SCHEMA + CLI_SCHEMA + STORAGE_SCHEMA
```

This feature encourages the incremental development and testing of compilation systems and is largely responsible for the fact that an emergent compilation usually consists of a large number of relatively simple phases.

It should be clear that the possibility of associating fold configurations with names and later composing them means that the framework must maintain some sort of structure that keeps track of the phase identities. This structure is the SchemaCompiler — a keyed set of phases, identified by context type, with algebraic operations (+, -, &, |) that mirror set operations.

### 1.1.3 Evaluating Combinations

One of our goals in this chapter is to isolate issues about thinking compilationally. As a case in point, let us consider that, in compiling combinations, fold is itself following a procedure.

> To compile a combination, do the following:
>
> 1. Iterate the capabilities of the combination.
> 2. For each capability, check whether it implements the target protocol (isinstance).
> 3. If it does, call the compile_* method, passing the current context. Replace the context with the result.
> 4. If it does not, skip the capability.
> 5. Return the final context.

Even this simple rule illustrates some important points about compilation in general. First, observe that the rule is *flat* — it is a loop, not a recursion. Capabilities are a list, not a tree. The composition is sequential: each capability sees the context left by the previous one. But because capabilities are frozen and each writes to an independent part of the context, the order does not matter. This is the *commutativity* property, and it holds because capabilities form a *free monoid* — the algebra with the fewest identifications.

Second, observe that step 4 — skipping — is the *open-world* property. A capability that does not implement the target protocol is not an error. It is simply irrelevant to this target. `sql.Index()` is invisible to the Pydantic fold. `tg.CommandArg` is invisible to the SQL fold. Each target's fold contains only what is relevant to that target. Adding a new capability never breaks an existing target. Adding a new target never requires modifying existing capabilities.

Third, observe that the rule is *total* — it always terminates. The capability list is finite. The loop runs once per capability. There are no recursive calls, no infinite loops, no divergence. This is Meijer's catamorphism: the unique structurally recursive consumer of a finite data type. Termination is guaranteed by the structure of the data, not by the logic of the code.

### 1.1.4 Compound Capabilities

We have identified in emergent some of the elements that must appear in any powerful compilation framework:

- MaxLen, Identity, Unique and other annotations are primitive capabilities.
- Annotated provides a means of combining capabilities on a field.
- CompilationPhase provides a limited means of abstraction.

Now we will learn about *compound capabilities*, a much more powerful abstraction technique by which a compound compilation operation can be given a name and then referred to as a unit.

We begin by examining how to express the idea of "CRUD for users." We might say, "To create a CRUD API, inspect the entity schema, generate OpSpecs for each operation (list, get, create, update, delete), and attach HTTP triggers." This is expressed in emergent as:

```python
http_crud("/users", provider_node=Users)
```

We have here a *compound capability*, which has been given the name `http_crud`. The capability represents the operation of generating CRUD endpoints from an entity schema. The path and the data provider are given as arguments. Compiling the combination:

```python
@derive(http_crud("/users", provider_node=Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, MaxLen(255), Unique]
```

creates this compound capability and attaches it to the entity class via @schema_meta. The general form of a compound capability is a frozen dataclass that implements one or more of the derivation protocols (DeriveGeneratable, DeriveModifiable, DeriveAugmentable).

http_crud is a SchemaCapability. It implements `compile_derive_generate` — the method that fold calls during Phase 1 of derivation. Inside that method, it reads the entity's fields, generates OpSpecs for LIST, GET, CREATE, UPDATE, PATCH, DELETE, attaches HTTPRouteTriggers, and accumulates them into the DeriveCtx.

Having defined http_crud, we can now use it:

```python
app = build_application_from_decorated(User)
fastapi_app = targets.fastapi.compile(app)
# 7 REST endpoints — list, get, create, update, patch, delete, upsert
```

We can also use http_crud as a building block in defining other compilation operations. For example, we might want to add pagination and soft delete:

```python
@derive(http_crud("/users", provider_node=Users), Paginated(20), SoftDelete("deleted_at"))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, MaxLen(255), Unique]
    deleted_at: datetime | None = None
```

Now we can use this as a building block for constructing further compilations:

```python
@derive(
    http_crud("/users", provider_node=Users),
    cli_crud("user", provider_node=Users),
    Paginated(20),
    SoftDelete("deleted_at"),
    Authenticated(BearerExtract(), TokenValidate(AuthUser, lookup)),
)
```

Compound capabilities are used in exactly the same way as primitive capabilities. Indeed, one could not tell by looking at the `@derive` decorator whether `Paginated` was built into emergent, like `MaxLen`, or defined as a compound capability. The compilation process does not distinguish — fold dispatches on isinstance, and all capabilities that implement the protocol participate equally.

### 1.1.5 The Fold Model for Capability Compilation

To compile a combination whose capabilities include compound capabilities, fold follows much the same process as for combinations whose capabilities are primitive. That is, fold iterates the capabilities and calls the compile_* method on each that implements the target protocol.

We can assume that the mechanism for compiling primitive capabilities is built into the capability itself — each has its compile_* methods. For compound capabilities, the compilation process is as follows:

> To compile a compound capability, fold calls its compile_derive_generate (or compile_derive_modify, or compile_derive_augment) method, passing the current DeriveCtx. The compound capability examines the entity schema, generates or transforms OpSpecs, and returns a new DeriveCtx.

To illustrate this process, let us trace the compilation of:

```python
@derive(http_crud("/users", Users), Paginated(20))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
```

compile_derive retrieves the @schema_meta capabilities: `(CRUD(...), Paginated(20))`. It performs three fold passes:

**Phase 1 (Generate):** fold iterates capabilities with protocol DeriveGeneratable. CRUD implements it. CRUD.compile_derive_generate inspects User's fields, finds id (Identity) and name (str), generates OpSpecs: List, Get, Create, Update, Patch, Delete. Each OpSpec carries a handler template, input/output field specs, trigger (HTTPRouteTrigger), and effects (Read, Creates, Deletes, etc.). Paginated(20) does not implement DeriveGeneratable — skipped.

**Phase 2 (Modify):** fold iterates with protocol DeriveModifiable. CRUD does not implement it — skipped. Paginated(20) implements it. Paginated.compile_derive_modify finds the OpSpec with Pageable effect (the List op), replaces its handler template with PaginatedFetchMany(page_size=20), adds page and page_size fields to the request type.

**Phase 3 (Augment):** fold iterates with protocol DeriveAugmentable. Neither capability implements it — both skipped.

Result: DeriveCtx with six OpSpecs, one of them modified with pagination. materialize() builds the types, handlers, and exposures. build_application_from_decorated() produces the wire Application. fastapi.compile() turns it into a FastAPI app with routes.

The purpose of the fold model is to help us think about capability compilation, not to provide a description of how emergent really works in every detail. In practice, the compilation is accomplished by the six-line fold function with isinstance dispatch. Over the course of this book, we will present increasingly elaborate models of what compilation processes produce, culminating with a distributed multi-agent system in theworld. The fold model is only the first of these — a way to get started thinking formally about the compilation process.

### 1.1.6 Protocol Dispatch and the Open World

The expressive power of the class of compilations that we can define at this point is notable, because we have a way to make tests — isinstance — and to perform different compilations depending on the result of a test.

Consider: when fold encounters a capability, it must determine how to dispatch. The rule is:

```python
if handlers and item.__class__ in handlers:
    ctx = handlers[item.__class__](item, ctx)
elif isinstance(item, protocol):
    ctx = getattr(item, method)(ctx)
# else: skip
```

This is a case analysis with three branches. First, the handler map is checked — custom per-type overrides take priority. Second, isinstance checks whether the capability implements the target protocol — the standard path. Third, if neither applies, the capability is skipped.

The third branch — skipping — is the *open-world* property. By default, it is not an error for a capability to lack a protocol. It means the capability is irrelevant to this target. `sql.Index()` has no `compile_pydantic` method; it is not PydanticCompilable; fold skips it when compiling for Pydantic. But it IS SQLAlchemyCompilable, and when fold compiles for SQLAlchemy, it participates.

But "by default" is important. The open-world skip is a *choice*, not a fate. If you want a capability that REFUSES to be skipped — that raises an error when compiled for an unsupported target — you can do so. The handler map is the mechanism:

```python
def _require_memory(item, ctx):
    raise TypeError(f"{type(item).__name__} does not support in-memory execution. "
                    f"Use a SQL or HTTP backend.")

# Register as handler for the memory backend
memory_handlers = {
    FullTextSearch: _require_memory,
}

# fold will call the handler instead of skipping
fold(query.ops, MemoryQueryContext(data), MemoryQueryCompilable, "compile_memory_query",
     handlers=memory_handlers)
```

The handler has priority over both protocol dispatch and skip. When fold encounters FullTextSearch in the handler map, it calls `_require_memory` — which raises TypeError. The user gets an explicit, descriptive error: "FullTextSearch does not support in-memory execution. Use a SQL or HTTP backend."

This is the key distinction: fold's DEFAULT is open-world (skip unknown capabilities). But the programmer CONTROLS the behavior at the fold site via the handler map. Some deployments want strict mode — every capability must be handled. Others want permissive mode — unknown capabilities are tolerated. The handler map gives you both. The framework doesn't decide; you do.

A capability can also enforce its own requirements by implementing the protocol with an explicit error:

```python
@dataclass(frozen=True, slots=True)
class FullTextSearch:
    query: str
    fields: tuple[str, ...]

    def compile_sa_query(self, ctx):
        # Full implementation for SQL
        return replace(ctx, stmt=ctx.stmt.where(func.to_tsvector(...)))

    def compile_http_api(self, ctx):
        ctx.params["q"] = self.query
        return ctx

    def compile_memory_query(self, ctx):
        raise NotImplementedError(
            f"FullTextSearch requires a backend with full-text indexing. "
            f"In-memory backend does not support this. "
            f"Use SQLAlchemy with tsvector or an HTTP API with search support."
        )
```

Here the capability DOES implement the protocol — isinstance returns True — but the implementation raises. fold calls the method, the method raises, the user gets a clear error. This is not the open-world skip. This is the capability *choosing* to reject a target.

The three options:
1. **Don't implement the protocol** → fold skips (open-world default). Good for capabilities that are simply irrelevant to a target (sql.Index is irrelevant to Pydantic).
2. **Implement the protocol with a raise** → fold calls it, it raises. Good for capabilities that COULD be relevant but the backend lacks a feature (FullTextSearch on memory).
3. **Register a handler** → fold calls the handler. Good for deployment-specific policies (strict mode, logging, fallback behavior).

This three-way dispatch — handlers, protocol, skip — may be compared with the conditional expressions `cond` and `if` in Scheme. But where Scheme's conditionals test values for truth or falsity, fold's dispatch tests capabilities for *protocol conformance*. The question is not "is this true?" but "does this capability know how to compile itself for this target?" And the answer is not binary — it is one of three: "yes, and here's how" (protocol), "yes, but it's an error" (protocol + raise), or "this question is irrelevant to me" (skip).

In addition to primitive protocol dispatch, there are logical composition operations which enable us to construct compound protocol tests. The most frequently used are these:

- `isinstance(item, PydanticCompilable)` — does it compile to Pydantic?
- `isinstance(item, DeriveGeneratable)` — does it generate OpSpecs?
- `isinstance(effect, Mutation)` — is this effect a mutation? (hierarchy: Creates, Updates, Deletes are all Mutations)

The hierarchy of effects enables dispatch at multiple levels of specificity:

```python
has_effect(spec.effects, Mutation)   # matches Creates, Updates, Deletes
has_effect(spec.effects, Deletes)    # matches only Deletes
isinstance(effect, Pageable)         # matches Pageable with its data (default_size, etc.)
```

### 1.1.7 Example: Mortal Workers by Append-Only Coordination

Capabilities, as introduced above, are much like ordinary database annotations — they specify a constraint that is determined by one or more parameters. But there is an important difference between database annotations and emergent capabilities. Capabilities must be *active* — they carry their own compilation methods. And this difference changes what is possible.

As a case in point, consider the problem of multiplying two 1500×1500 matrices. This is a simple computation — 2.25 million dot products — but we will perform it under a constraint that makes it interesting: the workers that compute the rows *die* every 30 seconds.

Not "might fail occasionally." Die. Deterministically. Every worker has a 30-second lifetime. When the lifetime expires, the worker raises RuntimeError and is gone. Supervised restarts it. A new worker — a new generation — takes over. The old worker's in-memory state is lost.

The question is: can the computation complete correctly? Can mortal workers produce immortal results?

**Declarative description.** We define two event types — facts about the computation:

```python
@dataclass(frozen=True, slots=True)
class RowChunk:
    start: int = 0
    end: int = 0

@dataclass(frozen=True, slots=True)
class RowResult:
    start: int = 0
    data: tuple[tuple[float, ...], ...] = ()
```

RowChunk means "rows start through end need computing." RowResult means "rows start through end have been computed, and here is the data." These are the only two facts in the system. They are frozen dataclasses. They live in the Log — append-only, never modified, never deleted.

**Imperative description — the conventional approach.** In a conventional distributed system (MapReduce, Spark, Celery, Dask), a *coordinator* manages the computation:

1. The coordinator maintains a mutable assignment table: which chunks are assigned to which workers.
2. Workers lease chunks from the coordinator. The coordinator tracks timeouts.
3. When a worker dies, the coordinator detects the timeout and re-assigns the chunk.
4. The coordinator must handle its own failure — which requires consensus (Raft, Paxos) or manual intervention.

The coordinator is mutable state. The assignment table is mutable state. The timeout tracking is mutable state. Every piece of mutable state is a source of bugs, a complication for testing, and a failure mode for the system.

**Declarative description — the emergent approach.** There is no coordinator. There is no assignment table. There is no timeout tracking. There is only the Log and a stateless function:

```python
async def _find_unclaimed(log):
    done_starts = {r.data.start for r in await log.query(Lens().of_type(RowResult))}
    all_chunks = await log.query(Lens().of_type(RowChunk))
    return [c.data for c in all_chunks if c.data.start not in done_starts]
```

"What needs doing?" — all RowChunk events. "What has been done?" — all RowResult events. "What's left?" — the difference. This is a pure function over the Log. No state. No mutation. No side effects (besides the query itself). Any worker, at any time, calling this function, gets the correct answer — the set of unclaimed chunks as of that moment.

The worker itself:

```python
async def mortal_worker(log, name, a, b_t):
    deadline = time.monotonic() + LIFETIME  # 30 seconds
    computed = 0
    while time.monotonic() < deadline:
        unclaimed = await _find_unclaimed(log)
        if not unclaimed:
            break
        chunk = unclaimed[0]
        rows = compute_rows(chunk, a, b_t, deadline)
        if rows is None:
            break  # died mid-chunk — chunk stays unclaimed
        await put(log, RowResult(start=chunk.start, data=rows))
        computed += 1
    raise RuntimeError(f"{name} lifetime expired ({computed} chunks)")
```

The `computed` counter is local — for tracing only. Remove it and the worker is a pure function: query → compute → emit. No state that persists between calls. No state that must be migrated between generations. The worker's "memory" is the Log.

**What happens when a worker dies.** The worker has been computing for 28 seconds. It has emitted three RowResults. At second 30, it raises RuntimeError. Supervised catches it. A new worker starts — same function, same arguments, fresh deadline.

The new worker calls `_find_unclaimed(log)`. The Log has the three RowResults from the previous generation. The unclaimed set is smaller by three. The new worker picks the next unclaimed chunk and continues.

No handoff protocol. No state transfer. No recovery procedure. The new worker simply *asks the Log what has been done* and *does what hasn't*.

**What happens when two workers grab the same chunk.** Worker A and worker B both call `_find_unclaimed` at the same moment. Both see chunk 7 as unclaimed. Both compute it. Both emit RowResult(start=7, data=...).

The Log now has two RowResult events for start=7. The coordinator (which is just an observer, not a controller) queries `done_starts = {r.data.start for r in ...}`. It's a set. Two entries for start=7 produce one element in the set. No conflict. No duplicate detection logic. No distributed lock. Append-only makes duplication safe by construction — because both results are identical (pure computation, same inputs, deterministic).

**What happens when a worker dies mid-chunk.** Worker A starts computing chunk 7. At row 3 of 10, the deadline expires. `compute_rows` returns None (it checks the deadline after each row). The worker breaks out of the loop without emitting. Chunk 7 has no RowResult in the Log. Next generation sees it as unclaimed. Picks it up. Computes all 10 rows. Emits.

No partial results in the Log. No cleanup. No rollback. The only side effect of a mid-chunk death is wasted computation — the 3 rows computed but never emitted. The correctness of the system does not depend on every computation completing. It depends on the Log — which only contains complete, correct results.

**The result.**

```
  [   2.4s]  3/150  ( 2.0%)  1.3/s  1 gen
  [  14.5s]  21/150  (14.0%)  1.4/s  1 gen
  [  29.3s]  43/150  (28.7%)  1.5/s  1 gen
  ☠ w1.gen1 died (14 chunks)
  ☠ w0.gen1 died (15 chunks)
  ☠ w2.gen1 died (14 chunks)
  [  34.2s]  49/150  (32.7%)  1.4/s  2 gen
  ...
  ☠ w0.gen2 died (15 chunks)
  ☠ w1.gen2 died (16 chunks)
  ☠ w2.gen2 died (16 chunks)
  [  63.9s]  97/150  (64.7%)  1.5/s  3 gen
  ...
  [ 101.3s]  150/150  (100.0%)  1.5/s  4 gen

  ✓ 1500/1500 rows computed, max error: 0.00e+00
  ✓ 5 snapshots, 150 result events
  ✓ 12 worker generations
```

Four generations. Twelve worker instances (3 workers × 4 generations). 150 chunks. Zero lost rows. Error: 0.00e+00 — mathematically exact. Not one line of coordination code.

**The declarative-imperative distinction.** The contrast between the declarative approach (Log + query) and the imperative approach (coordinator + assignment table + timeout) is a reflection of the general distinction between describing *properties of things* and describing *how to do things*. In the declarative approach, RowChunk means "this needs computing" and RowResult means "this is done." The coordination — which chunk to pick, how to handle failure, how to avoid duplication — *emerges* from these facts and the append-only property of the Log. In the imperative approach, the coordination is explicit: assignment tables, leases, heartbeats, re-assignment logic, consensus.

The declarative approach is not merely more concise. It is *safer*. The imperative coordinator can be in an inconsistent state (assigned a chunk to a dead worker, lease expired but not yet detected, re-assignment race with a slow worker). The declarative approach has no state that can be inconsistent — the Log is append-only, and `_find_unclaimed` is a pure function.

The `mortal_worker` program also illustrates that the simple capability framework we have introduced so far is sufficient for writing distributed, fault-tolerant computational systems. This might seem surprising, since we have not included any coordination primitives — no locks, no leases, no consensus protocols. `mortal_worker`, on the other hand, demonstrates how coordination can be accomplished using no special construct other than the ordinary ability to query an append-only log and emit frozen events.

### 1.1.8 Capabilities as Black-Box Abstractions

The mortal worker example is our first example of a system defined by a set of interacting capabilities and computations. Notice that the pattern — query Log, compute, emit — is *compositional*: each worker is a self-contained unit that can be understood without reference to other workers. The entire system can be viewed as a cluster of computations that mirrors the decomposition of the problem into subproblems.

The importance of this decomposition strategy is not simply that one is dividing the program into parts. Rather, it is crucial that each capability accomplishes an identifiable task that can be used as a module in defining other compilations. For example, when we define `Supervised(max_restarts=5)` in terms of restart logic, we are able to regard the supervision capability as a "black box." We are not at that moment concerned with how it restarts crashed computations, only with the fact that it provides fault tolerance. The details of how supervision is implemented can be suppressed, to be considered at a later time. Indeed, as far as the World is concerned, `Supervised` is not quite a capability but rather an abstraction of a capability — a so-called *capability abstraction*. At this level of abstraction, any supervision strategy with the same interface is equally good.

Thus, considering only the WorldContext they produce, the following two supervision capabilities should be indistinguishable:

```python
Supervised(max_restarts=5, backoff=1.0)

AdaptiveSupervision(initial_strategy="one_for_one", max_restarts=5)
```

So a capability definition should be able to suppress detail. The users of the capability may not have written the capability themselves, but may have obtained it from another programmer or from an earlier version of the system. A user should not need to know how the capability is implemented in order to use it.

**Scope and the scoped combinator.** One detail of a capability's compilation that should not matter to users outside its scope is which other capabilities it affects. Thus, `scoped()` provides a fold boundary:

```python
world = World(log=log, computations=(
    scoped(
        life("worker-0", ...), life("worker-1", ...), life("worker-2", ...),
        Supervised(max_restarts=50),
    ),
    Script(fn=coordinator),  # NOT supervised
))
```

`Supervised` inside `scoped()` wraps only the workers. The coordinator, outside the scope, is not affected. This is the emergent analog of block structure in Scheme: definitions that are local to a scope do not leak to the enclosing environment.

The `scoped()` combinator is basically the right solution to the simplest capability-packaging problem. But there is a better idea lurking here. In addition to isolating capabilities within a scope, we can simplify them. Since the Log is bound in the definition of World, the computations that are defined internally have access to it — it is injected into their scope automatically. Thus, it is not necessary to pass the Log explicitly to each computation. Instead, the Log is available as a free variable in the computation's scope, getting its value from the World that created it. This discipline — automatic injection of shared values through scope hierarchy — is what emergent calls *nodnod scope resolution*, and it is analogous to lexical scoping in Scheme.

---

## 1.2 Capabilities and the Compilations They Generate

We have now considered the elements of compilation: We have used primitive capabilities, we have combined these capabilities into annotations, and we have abstracted these composite capabilities by defining them as compound capabilities like http_crud. But that is not enough to enable us to say that we know how to compile. Our situation is analogous to that of someone who has learned the rules for how the pieces move in chess but knows nothing of typical openings, tactics, or strategy. Like the novice chess player, we don't yet know the common patterns of compilation in the domain. We lack the knowledge of which capabilities are worth composing (which compilation phases are worth defining). We lack the experience to predict the consequences of composing a capability (executing a fold).

The ability to visualize the consequences of the capabilities under consideration is crucial to becoming an expert compiler designer, just as it is in any synthetic, creative activity. In becoming an expert photographer, one must learn how to look at a scene and know how it will appear on a print for each choice of exposure. So it is with compilation, where we are planning the compilation to be performed by fold and where we control fold by means of capabilities. To become experts, we must learn to visualize the compilations generated by various types of capabilities. Only after we have developed such a skill can we learn to reliably construct capability systems that exhibit the desired behavior.

A capability is a pattern for the *local transformation* of a compilation context. It specifies how one step of the compilation is built upon the previous step. We would like to be able to make statements about the overall, or *global*, behavior of a compilation whose local transformations have been specified by capabilities. This is straightforward to do, because fold is a catamorphism — its global behavior is determined by the local behavior of the capabilities and the algebraic laws (fusion, banana split, universality) that govern their composition.

In this section we will examine some common "shapes" for compilations generated by capabilities. We will also investigate the resources these compilations consume, and the artifacts they produce. The capabilities we will consider are simple. Their role is like that played by test patterns in photography: as prototypical patterns, rather than practical examples in their own right.

### 1.2.1 Single-Phase Compilation

We begin by considering the simplest compilation: one phase, one field, several capabilities. Consider a field:

```python
email: Annotated[str, MaxLen(255), Unique, sql.Index()]
```

and the Pydantic compilation phase. fold iterates three capabilities:

```
Step 1: MaxLen(255)  — isinstance(PydanticCompilable) → True
        compile_pydantic(ctx) → ctx' with max_length=255
Step 2: Unique()     — isinstance(PydanticCompilable) → False → skip
Step 3: sql.Index()  — isinstance(PydanticCompilable) → False → skip
Result: PydanticContext with max_length=255
```

The compilation is *linear* — fold processes each capability once, in order. The total work is proportional to the number of capabilities. But the result is independent of the order. If we permute the capabilities:

```python
email: Annotated[str, sql.Index(), MaxLen(255), Unique]
```

the result is identical. This is because each capability writes to an independent part of the context. MaxLen writes to max_length. Unique writes to unique. sql.Index writes to index. They do not interfere. This *commutativity* is a consequence of the free monoid structure — the algebra with no equations between generators.

Now consider the same field compiled through the SQLAlchemy phase:

```
Step 1: MaxLen(255)  — isinstance(SQLAlchemyCompilable) → True
        compile_sqlalchemy(ctx) → ctx' with column_type=String(255)
Step 2: Unique()     — isinstance(SQLAlchemyCompilable) → True
        compile_sqlalchemy(ctx') → ctx'' with unique=True
Step 3: sql.Index()  — isinstance(SQLAlchemyCompilable) → True
        compile_sqlalchemy(ctx'') → ctx''' with index=True
Result: SQLAlchemyContext with String(255), unique=True, index=True
```

Same capabilities. Different protocol. Different number of capabilities participating (all three vs one). Different result. The open-world dispatch determines which capabilities participate — and the same capability can participate in multiple targets.

### 1.2.2 Multi-Phase Compilation (Banana Split)

When we compile one field through multiple phases — say, Pydantic AND OpenAPI — we could run fold twice:

```python
pydantic_ctx = fold(caps, pydantic_initial, PydanticCompilable, "compile_pydantic")
openapi_ctx  = fold(caps, openapi_initial, OpenAPICompilable, "compile_openapi")
```

Two traversals of the same capability list. But Meijer's *banana split* theorem tells us these can be combined into one traversal producing a pair:

```python
# compile_fields does this internally
for phase in phases:
    ctx = phase.initial(name, field_type)
    ctx = fold_field(info, ctx, phase.protocol, phase.method)
    contexts[phase.context_type] = ctx
```

The result is a FieldCompilation — a dict of contexts keyed by phase. One traversal per field (iterating phases inside), not one traversal per phase. This is why adding a new compilation phase does not add a new traversal of the capability list — it adds one more entry to the inner loop.

The SchemaCompiler algebra makes this explicit:

```python
FASTAPI_SCHEMA = PYDANTIC_PHASE + OPENAPI_PHASE
```

`+` is left-biased union of phase sets. `FASTAPI_SCHEMA.compile(User, axes)` runs both phases in one pass. Adding `+ ARGPARSE_PHASE` adds one more inner-loop iteration, not one more outer-loop traversal.

### 1.2.3 Derivation: Fold Generating Programs

The most interesting compilation shape is *derivation* — a compilation that produces not data structures but *programs*. compile_derive takes a class with @schema_meta capabilities and produces OpSpecs — descriptions of operations that, when materialized, become endpoints with handlers, request types, and response types.

This is a fold that generates programs which generate programs. The DeriveCtx accumulator starts empty and fills with OpSpecs. Each OpSpec describes one endpoint: name, fields, handler template, trigger, effects. materialize() turns OpSpecs into actual Python types (frozen dataclasses for request/response) and async handler functions.

The derivation process has three phases, each a separate fold over the same capability list:

```
Phase 1 (Generate):  http_crud produces 6 OpSpecs
Phase 2 (Modify):    Paginated transforms the List OpSpec
Phase 3 (Augment):   (unused in this example)
```

The shape of this compilation is unlike single-phase or multi-phase — it is *staged*. Phase 1 creates an intermediate representation (OpSpecs). Phase 2 transforms it. Phase 3 augments it. Only then does materialization produce the final artifacts. The gap between declaration and materialization is where the power lives — transforms can rewrite OpSpecs, explain can inspect them, multi-target can fork them.

### 1.2.4 Verification: Fold as Constraint Checker

Another compilation shape is *verification* — a fold that accumulates constraints and checks them for consistency. Consider:

```python
balance: Annotated[float, Min(100), Max(50)]
```

The verification fold accumulates: `lower_bound=100, upper_bound=50`. After the fold, `ctx.check()` discovers `lower_bound > upper_bound` and emits an Issue. This is the same fold — same six lines — but the context is a constraint accumulator instead of a schema builder.

The verification shape is notable because it produces *failures*, not artifacts. A successful verification produces an empty tuple of Issues. A failed verification produces a non-empty tuple. verify_raising() raises VerificationError at import time — before any server starts, before any request is processed.

This is the dissolved tradeoff between inspectability and type safety. Initial encoding (frozen data) + domain verification (fold over constraint contexts) provides guarantees that no host-language type checker can express: Min(100) > Max(50) is invisible to Haskell's type system, but visible to emergent's verify().

---

## 1.3 Formulating Abstractions with Higher-Order Capabilities

We have seen that capabilities are, in effect, abstractions that describe compound compilation operations on contexts. We have also seen how compound capabilities like http_crud, Paginated, and SoftDelete act as building blocks for defining further compilation operations.

One of the things we should demand from a powerful compilation framework is the ability to build abstractions by assigning names to common patterns and then to work in terms of the abstractions directly. Capabilities provide this ability. This is why all but the most primitive compilation frameworks include mechanisms for defining capabilities.

Yet even in defining capabilities, we are limited to a certain kind of abstraction. We observe that there is a common pattern in many capabilities:

```python
@dataclass(frozen=True, slots=True)
class Readonly(SchemaCapability):
    def compile_derive_modify(self, ctx):
        return ctx.reject_by_effect(Mutation)

@dataclass(frozen=True, slots=True)
class MutationsOnly(SchemaCapability):
    def compile_derive_modify(self, ctx):
        return ctx.select_by_effect(Mutation)

@dataclass(frozen=True, slots=True)
class WithoutDelete(SchemaCapability):
    def compile_derive_modify(self, ctx):
        return ctx.reject_by_effect(Deletes)
```

These three capabilities differ only in the effect they select and the method they call (reject vs select). The pattern is: "filter OpSpecs by effect." We could abstract this pattern:

```python
def effect_filter(effect_type, method="reject"):
    @dataclass(frozen=True, slots=True)
    class _Filter(SchemaCapability):
        def compile_derive_modify(self, ctx):
            return getattr(ctx, f"{method}_by_effect")(effect_type)
    return _Filter()
```

Readonly = `effect_filter(Mutation, "reject")`. MutationsOnly = `effect_filter(Mutation, "select")`. WithoutDelete = `effect_filter(Deletes, "reject")`.

This is a *higher-order capability* — a function that takes a pattern parameter and produces a capability. The capability itself is still a frozen dataclass with a compile_* method. But the function that creates it abstracts over the pattern.

### 1.3.1 Capabilities as Arguments

The `scoped()` combinator is our first example of a capability that accepts other capabilities as arguments:

```python
scoped(
    http_crud("/users", Users),      # generator capability
    Readonly(),                       # modifier capability
    ProjectResponse(exclude=("secret",)),  # another modifier
)
```

scoped takes a generator and zero or more modifiers. It implements DeriveGeneratable — Phase 1 of derivation. Its compile_derive_generate delegates to the inner generator, then folds the modifiers through the result. The modifiers are *arguments* to scoped — capabilities passed as data to another capability.

The Authenticated capability similarly accepts capabilities as arguments:

```python
Authenticated(
    BearerExtract(),           # enricher capability
    TokenValidate(AuthUser, lookup),  # enricher capability
    effect=Mutation,           # restrict to mutations
)
```

BearerExtract and TokenValidate are ScopeEnricher capabilities. Authenticated is a SchemaCapability that, during Phase 2 (Modify), attaches these enrichers to the appropriate OpSpecs. It receives capabilities as data, stores them in its frozen fields, and deploys them during compilation.

### 1.3.2 Constructing Capabilities with Factories

Consider the `memory_node()` function:

```python
Users = memory_node()
```

This returns a nodnod node type that provides an in-memory relational provider. It is a *capability factory* — a function that constructs a reusable compilation component.

```python
def memory_node(key_field="id", auto_id=True):
    store = MemoryRelationalProvider(key_fn=lambda x: getattr(x, key_field), next_id=SequenceNextId())
    @scalar_node
    class _Node:
        @classmethod
        def __compose__(cls):
            return store
    return _Node
```

The factory closes over the store. Each call to memory_node() creates a fresh provider and a fresh node type. The node type is a value — it can be stored in a variable, passed to http_crud, and used in multiple @derive decorators.

### 1.3.3 Capabilities as General Methods

The SchemaCompiler algebra is our most powerful example of capabilities used as general methods. Consider:

```python
FULLSTACK = FASTAPI_SCHEMA + SA_SCHEMA + CONSTRAINTS_SCHEMA
issues = verify(User, phases=FULLSTACK.phases)
ec = FULLSTACK.compile(User, axes)
```

FULLSTACK is a SchemaCompiler — a set of phases. `+` composes phase sets. `.compile()` runs all phases. `verify()` runs verification phases. The same algebra that composes compilation targets also composes verification — because verification is just another compilation target.

The algebraic laws — `A + A = A` (idempotent), `(A + B) + C = A + (B + C)` (associative), `A + empty = A` (identity) — are not design choices. They follow from the structure: phases are keyed by context type, and the operations are set operations on those keys.

This observation — that compilation and verification share the same algebra — is the key to the power of the framework. It means that any new compilation target (GraphQL, Protobuf, Terraform) automatically participates in the same composition algebra, and any new verification phase (security, accessibility, domain consistency) composes identically with existing targets. There is no second mechanism.

---

## Exercises

**Exercise 1.1.** Below is a sequence of capability annotations. For each, determine what the result of folding through PydanticCompilable would be (which capabilities participate, which are skipped, what the final context contains):

```python
a) Annotated[str, MaxLen(100)]
b) Annotated[int, Min(0), Max(1000)]
c) Annotated[str, MaxLen(255), Unique, sql.Index()]
d) Annotated[float, Min(-40), Max(125), Doc("Temperature in Celsius")]
e) Annotated[str, Pattern(r"^[a-z]+$"), OneOf("red", "blue", "green")]
```

Now determine the same for SQLAlchemyCompilable. Which annotations produce different results for the two targets? Which capabilities participate in one target but not the other?

**Exercise 1.2.** The open-world property means that unknown capabilities are silently skipped. What would happen if fold raised an error for unknown capabilities instead? Consider: (a) what would break if you added a new target; (b) what would break if you added a new capability; (c) whether it would be possible to compose capabilities from independent libraries.

**Exercise 1.3.** The commutativity of capabilities within an axis depends on each capability writing to an independent part of the context. Construct a hypothetical capability whose compile_pydantic method reads a field that another capability writes. Show that order would matter for this pair. Then explain why emergent's actual capabilities avoid this — what property of the context design prevents it?

**Exercise 1.4.** Define a capability `DefaultValue` that, when compiled to Pydantic, sets a default value on the FieldInfo. Then define a capability `Required` that marks the field as required (no default). What happens when both appear on the same field? Design a verification phase that detects this contradiction at import time.

**Exercise 1.5.** In Section 1.1.7, the mortal workers query unclaimed chunks by computing `done_starts = {r.data.start for r in await log.query(Lens().of_type(RowResult))}`. This query is O(N) where N is the number of RowResult events. Design a ViewSnapshot-based optimization that makes the query O(1) by maintaining a materialized view of done starts. How does this interact with the mortal worker pattern — can a worker safely use a slightly stale snapshot?

**Exercise 1.6.** The SchemaCompiler algebra satisfies `A + A = A` (idempotent), `(A + B) + C = A + (B + C)` (associative), and `A + empty = A` (identity). Does it satisfy commutativity (`A + B = B + A`)? If not, construct an example where `A + B ≠ B + A`. What does this mean for the semantics of compiler composition?

**Exercise 1.7.** Hutton (1999) proves that `foldl` can be expressed as a `foldr` that generates a function. In emergent, fold is always a left fold (iterate sequentially, accumulate context). Could fold be implemented as a right fold? What would this mean for the compilation process? Would the results differ? (Hint: consider commutativity.)

**Exercise 1.8.** The `handlers` parameter of fold provides priority override dispatch. Design a scenario where handler dispatch is essential — where protocol dispatch alone would produce an incorrect result. Then design the handler that corrects it. Consider: why is the handler keyed by exact type (`item.__class__`) rather than by isinstance?

**Exercise 1.9.** The three-mechanism framework (primitives, combination, abstraction) applies at every level of emergent. Identify the three mechanisms for: (a) the query expression language, (b) the derivation language, (c) theworld computation language. For each, name the primitives, the means of combination, and the means of abstraction.

**Exercise 1.10.** Moseley and Marks (2006) distinguish essential complexity (inherent in the problem) from accidental complexity (artifacts of the implementation). For a system with Users who have emails with max length 255 and uniqueness constraints, enumerate: (a) the essential complexity; (b) the accidental complexity in a Django implementation; (c) the accidental complexity in an emergent implementation. Is the emergent implementation's accidental complexity zero? If not, what remains?

**Exercise 1.11.** Reynolds (1972) showed that defunctionalization is reversible — given a set of records with dispatch, you can reconstruct the original closures (refunctionalization). Apply this to emergent: given `MaxLen(255)` (the record) and `fold` (the dispatch), reconstruct the "closure" that MaxLen defunctionalizes. What function does MaxLen(255) represent? What are its "free variables" (Reynolds' environment)? What is the "lambda body"?

**Exercise 1.12.** Meijer's banana split theorem says that two folds over the same list combine into one fold producing a pair. compile_fields uses this to run all phases in one pass. But what if two phases have a dependency — phase B needs the result of phase A? Can they still be banana-split? Design a two-phase compilation where the second phase reads the first phase's output. How would compile_fields need to change to support this? What algebraic law would break?

**Exercise 1.13.** The algebra example (examples/algebra.py) uses fold for symbolic differentiation. The product rule is:

```python
Mul.compile_deriv = lambda self, ctx: replace(ctx, result=(
    ctx.compile_expr(self.left) * self.right + self.left * ctx.compile_expr(self.right)
))
```

Implement the chain rule for `Fn("log", arg)`: `d/dx log(u) = u'/u`. Then implement the quotient rule for `Div(f, g)`: `d/dx (f/g) = (f'g - fg') / g²`. Verify your implementations by computing `compile_deriv(log(x**2))` and `compile_deriv(x / sin(x))` and simplifying the results.

**Exercise 1.14.** The capability `Unique` compiles to SQLAlchemy's `unique=True` column kwarg. But Unique has no compile_pydantic method. Should it? What would Pydantic-level uniqueness mean — and why is it fundamentally different from database-level uniqueness? What would a verification phase that checks cross-field uniqueness constraints look like?

**Exercise 1.15.** SICP Exercise 1.5 tests whether an interpreter uses applicative-order or normal-order evaluation. Design an analogous test for emergent: a pair of capabilities where the result differs depending on whether fold uses eager dispatch (the current behavior) or lazy dispatch (only call compile_* when the context field is actually read). Could emergent benefit from lazy compilation? What would it cost?
