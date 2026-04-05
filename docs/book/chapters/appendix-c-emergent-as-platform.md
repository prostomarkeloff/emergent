# Appendix C: emergent as Platform

---

## C.1 The Distinction

emergent is not a web framework. It is not an ORM. It is not a CRUD generator. It is a platform for building compilation languages from frozen data and fold.

The distinction matters because frameworks prescribe structure. Rails prescribes MVC. Django prescribes models-views-templates. Spring prescribes beans and dependency injection. You write code *inside* the framework. The framework calls you.

A platform provides primitives. UNIX provides processes, pipes, and files. BEAM provides processes, messages, and supervision trees. You build *on* the platform. You call the primitives.

emergent provides fold, CompilationPhase, SchemaCompiler, TargetCompiler, and Axes. Everything else -- every axis, every compilation target, every derive pattern, every theworld capability -- is a library built on those primitives. The platform does not know about Pydantic. It does not know about FastAPI. It does not know about the Log. Libraries know about the platform. The platform knows about nothing.

## C.2 The Platform Layer

The platform provides five things:

**fold(items, initial, protocol, method, handlers)** -- the universal primitive. Iterate items, call `method` on each that isinstance-matches `protocol`, accumulate context. Custom handlers override by item type. Unknown items skipped. Six lines of dispatch logic. Zero overhead when tracing is off.

```python
def fold(items, initial, protocol, method, handlers=None, *, trace=None):
    ctx = initial
    for item in items:
        if handlers and item.__class__ in handlers:
            ctx = handlers[item.__class__](item, ctx)
        elif isinstance(item, protocol):
            ctx = getattr(item, method)(ctx)
    return ctx
```

**CompilationPhase[Ctx]** -- a reified fold configuration. Binds a context type, a protocol, and an initial-context factory into one frozen value. The method name is auto-derived from the protocol's `compile_*` method. Phases are identified by context_type -- no strings.

```python
PYDANTIC_PHASE = CompilationPhase(
    PydanticContext, PydanticCompilable, _pydantic_initial,
    entity=PYDANTIC_MODEL_FOLD,
)
```

**SchemaCompiler** -- a composable set of phases with algebra. `+` is left-biased union. `|` is right-biased merge. `-` is restriction. `&` is intersection. Laws: `A + A == A` (idempotent), `(A + B) + C == A + (B + C)` (associative), `A + empty == A` (identity). A SchemaCompiler compiles a dataclass through all its phases in one pass.

```python
FULLSTACK = FASTAPI_SCHEMA + SA_SCHEMA + CONSTRAINTS_SCHEMA
ec = FULLSTACK.compile(User, axes)
```

**TargetCompiler[Trigger]** -- the surface-level analog of SchemaCompiler. Binds codec types to `from_codec` initializers, pipeline fold configuration, and an assembler. Same algebraic operations as SchemaCompiler, keyed by codec_type.

**Axes** -- compilation configuration carrier. Holds the schema inspector, optional trace collector, and optional scope layer. Passed explicitly to all compiler functions. No global state.

That is the platform. Everything else is library.

## C.3 The Library Layer

| Layer | What it provides | Built on |
|-------|-----------------|----------|
| **Platform** | fold + CompilationPhase + SchemaCompiler + TargetCompiler + Axes | emergent core (`wire/compile/`) |
| **Axis libraries** | Schema (Pydantic, OpenAPI, SQL, argparse, Telegrinder), Surface (triggers, codecs, enrichers), Storage (KV, Queue, Lock), Query (Expr, RelationalQuerySet, providers) | emergent (`wire/axis/`) |
| **Derive library** | DeriveGeneratable / Modifiable / Augmentable + OpSpec + materialize + CRUD + Methods + transforms | emergent (`wire/derive/`) |
| **Bridge library** | Framework-to-Application extraction (FastAPI, CLI, Telegrinder) | emergent (`wire/bridge/`) |
| **Verify library** | Numeric, length, semantic verification -- each a CompilationPhase | emergent (`wire/verify/`) |
| **OS kernel** | Log, Lens, Computation, World, Supervision, HotReload, Migration, Budget, Channels | theworld (separate package) |
| **Your system** | Custom compilers, custom capabilities, custom Worlds | production code |

All layers use the same `fold()`. All use frozen dataclasses. All use isinstance dispatch. The platform does not know about any library. Libraries do not know about each other unless they choose to. They compose because the algebra composes.

Consider: theworld's `HotReloadable` is a `WorldCompilable` capability. It calls `fold(caps, WorldContext(log=log), WorldCompilable, "compile_world")` -- the same fold that compiles Pydantic models, that compiles OpenAPI schemas, that compiles SQLAlchemy tables. HotReloadable does not import Pydantic. Pydantic does not import theworld. Both import fold.

Or consider: emergent's `wire.verify` defines three verification phases (numeric, length, semantic). Each is a `CompilationPhase` with its own protocol and context. They compose with schema phases via `SchemaCompiler` algebra: `FULLSTACK + VERIFY_NUMERIC + VERIFY_LENGTH`. The verification library does not know what FULLSTACK contains. It does not need to.

## C.4 The Runtime Layer

emergent has two primitives, not one.

**fold** reads capabilities, produces compiled descriptions. This is compile-time.

**nodnod** reads type signatures, produces parallel execution plans. This is run-time.

The nodnod graph is orthogonal to fold. A nodnod Node declares dependencies in its `__compose__` signature. nodnod resolves dependencies, parallelizes independent nodes, and executes the graph. Scope provides typed storage with parent chains. Either provides fallback (Sequential or Concurrent). ResultNode provides typed error handling.

RuntimePolicy bridges the two primitives. A scheduling policy IS a compiler: `WorkStealing` uses fold to read per-node capabilities and produces an executor. The executor uses nodnod to run the DAG.

World.run() is the junction point:

```python
async def run(self) -> None:
    # fold (compile-time): capabilities → nodes
    ctx = fold(self.computations, WorldContext(log=self.log),
               WorldCompilable, "compile_world")

    # nodnod (run-time): nodes → parallel execution
    agent = RuntimeAgent.with_policy(self.policy).build(set(ctx.nodes))
    await agent.run(local_scope=scope.inner, mapped_scopes={})
```

fold produces the *what*. nodnod executes the *how*. Neither knows about the other. They meet at the type level: fold produces `frozenset[type]` (node types), nodnod consumes `set[type[Node]]` (node types). The handoff is a set of types.

## C.5 What This Means

When you write `CompilationPhase(MyCtx, MyProtocol, my_initial)`, you are not configuring emergent. You are defining a language. The context is the value domain. The protocol is the set of well-formed programs. fold is the evaluator. Capabilities are the programs.

When you write `fold(items, ctx, protocol, method)`, you are not calling a library function. You are running a compiler. Your compiler. For your language. On your data.

The platform is 6 lines of fold + approximately 200 lines of infrastructure (CompilationPhase, SchemaCompiler, TargetCompiler, Axes). Everything else -- every axis, every target, every derive pattern, every theworld capability -- is a library built on those 200 lines.

The pre-built phases in emergent's codebase (PYDANTIC_PHASE, OPENAPI_PHASE, ARGPARSE_PHASE, TG_INPUT_PHASE, TG_RENDER_PHASE, CONSTRAINTS_PHASE, QUERY_SCHEMA_PHASE, STORAGE_FIELD_PHASE, REQUEST_BUILD_PHASE) are not special. They are CompilationPhase values, identical in kind to any phase you define. The codebase ships them for convenience. You could delete them all and fold would still work.

The pre-built SchemaCompilers (FASTAPI_SCHEMA, CLI_SCHEMA, TG_SCHEMA) are tuples of those phases. They are not frameworks. They are algebra. `FASTAPI_SCHEMA - OPENAPI_PHASE` removes OpenAPI generation. `FASTAPI_SCHEMA + YOUR_PHASE` adds your compilation target. The algebra does not care where the phases came from.

theworld is the strongest proof. It is a separate package, written by the same author, that consumes the platform exactly as any external user would. theworld imports `fold` from `emergent.wire.compile._core`. It imports `CompilationPhase` from nowhere -- it defines its own protocols (WorldCompilable, LensCompilable, ActionCompilable, LifecycleCompilable, PlanCompilable) and calls fold directly. The platform did not anticipate theworld. theworld does not require the platform to change.

## C.6 Exercises

**Exercise C.1.** Count the CompilationPhases in emergent's codebase. The pre-built constants are: PYDANTIC_PHASE, OPENAPI_PHASE, ARGPARSE_PHASE, REQUEST_BUILD_PHASE, TG_INPUT_PHASE, TG_RENDER_PHASE, CONSTRAINTS_PHASE, QUERY_SCHEMA_PHASE, STORAGE_FIELD_PHASE. That is nine. theworld adds at least five fold axes (LensCompilable, ActionCompilable, LifecycleCompilable, PlanCompilable, WorldCompilable) that are not CompilationPhase values but use fold identically. How many of these fourteen folds could you remove without changing fold itself? What does this tell you about the platform-library boundary?

**Exercise C.2.** theworld's `Computation.compile_perception()` folds through `LensCompilable`. theworld's `Computation.compile_action()` folds through `ActionCompilable`. Neither protocol exists in emergent's codebase. Where do they live? What does this prove about the platform's knowledge of its consumers?

**Exercise C.3.** Define a new compilation target: `GraphQLCompilable` with a `compile_graphql` method and a `GraphQLContext` accumulator. Write a `GraphQLPhase = CompilationPhase(GraphQLContext, GraphQLCompilable, ...)`. Write a `MaxLen` capability that implements both `PydanticCompilable` and `GraphQLCompilable`. Compile a dataclass through `FASTAPI_SCHEMA + GraphQLPhase`. What changed in emergent's source code? (Answer: nothing.)
