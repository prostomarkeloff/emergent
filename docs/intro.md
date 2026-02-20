# Introduction

So.. you're doing Python?

Emergent's here to solve lots of problems that bother you. If they still don't, be sure - they will.

Thanks to its well-thought architecture & design, emergent actually gives its users lots of tools. They're not plain helpers but building blocks, each dedicated to its own specific area of responsibility

Emergent's promise of design is simple: defunctionalization. Only through making implicit stuff - explicit one, we can make correct assumptions about our software and make tricky optimizations, that naturally come from data you're working on, but being hidden with mess of "architecture", "clean architecture" and "correct layering". Emergent respects them but makes an important statement: these principles are right, they sound nice on paper, but being actually the spoken word, not the code, they're, know they or not, only conventions whose intepretation is fully dependent on the reader. Their structure can be beatiful, everyone reading into DDD falls in love in first sight, but... the other day one wants to try it, he need to change over the path:

a) DDD is nice, yep, but... it's too __boilerplate-ish__... I'll adapt something into my project!
b) Ok, let's rewrite all from scratch...

The first option is the most common option, but being just yet another interpretation, I'd even say "yet another feeling" of DDD, implemented and lived through only partially, it can actually improve project's quality of code, but actually it just tends to tedious boilerplate, lots of unneccessary communication and smelly code solutions, arising from integration the "pure" architecture into messy legacy code. This integration is tricky, but not unsolvable. Typically, devs just do hacks. No blame on them, the environment they're acting in is stale, a nice hack in such can save lots of time.

The second is not so popular, but its outcomes is even worse on the number side. Doing DDD "right" is hard. It's always sold as "senior level of architecture" or any other nonsense you can see on media.

I talked lots about DDD but never gave its definition. I won't cite anything, here is mine: the domain driven development is an idea, that separation of concerns is useful and proven structural mechanism, DDD applies it to software; software, being just a lot of text, is fully dependent on the environment in which it was made and able to be running in. For example, my FastAPI application is a nice example to see these dependencies:

1) It's tied to Python
2) It's tied to FastAPI, HTTP, and server (such as uvicorn)

This setup, actually involing DB and maybe other sources-of-truth, is not simple. It requires a lot of stuff to be done right and even worse - to be wired together the right way. The DDD is not in software, it's not in code, it's only in the mind. Your project, to be DDD-compliant, and to be it continionusly, must be maintained well. Extremelly well. Syntax noise that DDD brings is easy to make mistake in, hard to understand at first glance, and totally onboarding-dependent; each DDD setup is unique, saying again: DDD is the convention, not actual framework or something.

Hope you happy to hear, emergent solves all these problems. To be specific, emergent makes your code DDD-compliant by design, and enabling those "tricky optimizations" not available in standard Python.

## Design

So, what's the tricky optimizations and what actually makes emergent DDD-compliant? The thing I didn't say in last paragraph: DDD is domain-centric, its main premise is to free your domain from your environment. Write once, run everywhere. Even better: done the right way, DDD also lets you compose these domains freely and construct wonderful apps. The reusable auth is always was a dream for me, uh, it's too much environment-specific..

Okay, I hope DDD sounds good for you, even better you read definitions of it somewhere else to make this concept more handy.

Emergent breaks all applications to one, library-defined structure, set of structures connected to each other. Their connection is purely structural and fully semantic. These structures are axes. They're 4, or to be specific 6, although defining all of them as full-blown axes can be tricky. To be even more correct, they're not really axes, in the sense of geometric orthoganality, but in the semantic one. All the computations can be expressed in emergent and using emergent, its model is complete and contains:
1) The `ops` axis; this is the thing actually running your stuff. Imagine having a REST API. The handler on a route is an operation, or point in the `ops` axis.
2) The `schema` axis; what is the data and how it looks. You define dataclasses, ORM models, openapi schemas, DTOs, uh... this thing is easy to break. Emergent disables this fragmentation and brings all the stuff to one place: the actual data definition.
3) The `storage` axis; where the data lives. PosgtreSQL, Redis, files, locks... anything that can hold concepts of data "living inthere". The storage axis lets you define the small "storage capabilities" (GetKV(key), PutKV(key, value)) and compose them to patterns: KV = (GetKv, PutKv); Lock = (acquire, release, status); relational = (... bunch of relational stuff, like joins, selects...)
4) The `query` axis; how to access the data. If schema lets us define the data, and storage to somehow access the place data lives in, we miss one particularly important instrument: queries. GetKV, PutKV are nice, but using them raw is just uncomfortable. Same for relational, locks, APIs... Query axis is a free algebra, being the same in structure as storage: you define dialect operations and compose them freely (using dialect's queryset): `relational(User).select(lambda u: u.name, lambda u: u.email)`. Then run using storage (after putting to provider, the query runner): `provider.fetch_many(query)`. This axis is special, it actually consists of schema and storage, making it explicitly not orthogonal in geometric sense, but proving the semantic one.
5) The `surface` axis; how the application can be run. This is where your domain meets the outside world. Surface takes care of WHERE and HOW your ops get exposed. Think about it: your operation doesn't care if it runs behind an HTTP endpoint, a CLI command, or a Telegram bot. It's the same `register(login, password) -> token`. The surface axis captures this: a trigger (WHERE: `HTTPRouteTrigger("POST", "/register")`, `CLITrigger("register")`, `TelegrindTrigger(Command("register"))`) paired with a codec (HOW: `rrc(Request, Response)` for request-response, `stateful(Flow)` for multi-turn conversations). You compose them freely:

```python
endpoint(auth_runner)
    .expose(HTTPRouteTrigger("POST", "/register"), rrc(RegisterRequest, TokenResponse))
    .expose(CLITrigger("register"), rrc(RegisterRequest, TokenResponse))
    .expose(TelegrindTrigger(Command("register")), rrc(RegisterRequest, TokenResponse))
```

One endpoint, three exposures. Same runner, same logic, three entry points. The surface axis doesn't own the behavior, it only describes the shape of the boundary.

6) The `capabilities` axis; this one is special. Unlike the first five, capabilities is a vertical axis — it doesn't sit alongside the others, it goes __through__ all of them. Every axis has its own compilation contexts (schema has PydanticContext, OpenAPIContext; surface has FastAPIRouteContext, CLICommandContext...), and a capability is anything that knows how to transform one or more of these contexts.

What does that mean? Let's say you write a constraint: `MaxLen(50)`. This is a capability. It implements `compile_pydantic()` to set `max_length=50` on the Pydantic field. It implements `compile_openapi()` to set `maxLength` in the JSON schema. It can implement `compile_argparse()` too, if it wants. Or it can skip some — a `cli.Help("Username")` only implements `compile_argparse`, it's invisible to Pydantic, invisible to OpenAPI. Each capability is a self-contained compiler plugin, carrying its own logic for every target it cares about.

The compiler doesn't read capabilities, doesn't interpret them, doesn't have a giant if-else chain. It __folds__ them. Given a list of capabilities on a field, the compiler initializes a context, and passes it through each capability one by one. Each capability either transforms the context (immutably, via `replace()`) or does nothing (if it doesn't implement the protocol). The result is the accumulated context — all constraints, all metadata, all configuration, ready for the target framework.

```
Annotated[str, MaxLen(50), cli.Help("Username")]
    ↓ fold through PydanticContext
        MaxLen → ctx with max_length=50
        cli.Help → skipped (no compile_pydantic)
    ↓ fold through ArgparseContext
        MaxLen → skipped (or adds validation)
        cli.Help → ctx with help="Username"
```

Same field, same annotations, but each target sees only what's relevant to it. This is structural dispatch via protocols, checked at runtime with `isinstance`. Not string matching, not dictionary lookups.

And capabilities are not just for field-level annotations. They work on schema-level (the whole model), route-level (the endpoint), application-level (the app itself). `FastAPICompilable`, `TelegrinderCompilable`, `CLICompilable` — each is a protocol. A surface capability like `Tag("admin")` can implement `compile_fastapi_route` to add OpenAPI tags. An application-level capability can implement `compile_fastapi_app` to add middleware. It's the same fold, the same mechanism, at every level.

This is why I call capabilities "vertical" — they cut through ops (handlers use capabilities for DI), schema (field annotations are capabilities), storage (providers are composed from capability-like protocols), query (dialect operations), surface (triggers carry capabilities). The whole system breathes through them.

## Compile and bridge

So you wrote your app using the five axes, sprinkled capabilities through all of them. You have an `Application` — emergent's intermediate representation. Cool. But FastAPI doesn't understand your `Application`. argparse doesn't know what a `Trigger` is. Telegrinder has its own Dispatch. How do you actually... run the thing?

Two operations. Symmetric. Together they close the loop.

**Compile: Application → Framework.** You have a wire app, you want a FastAPI server. `fastapi.compile(app, axes)` scans the application for `HTTPRouteTrigger` exposures, wraps each handler into a FastAPI route function, generates Pydantic models from your schema annotations (folding capabilities through `PydanticContext`, `OpenAPIContext`), and registers everything on a FastAPI instance. Pure function: in goes `Application`, out comes `FastAPI`.

```python
from emergent.wire.compile.targets import fastapi, cli, telegrinder

app_fastapi = fastapi.compile(wire_app, axes)    # → FastAPI
app_cli = cli.compile(wire_app, axes)            # → argparse
telegrinder.compile(wire_app, axes)              # → telegrinder Dispatch
```

Same `Application`, three outputs. No rewriting, no adapters, no glue code. Each compiler is a target-specific fold: it grabs the triggers it understands, ignores the rest. The FastAPI compiler only sees `HTTPRouteTrigger`. CLI only sees `CLITrigger`. Open-world: add your own trigger type, write a `TargetCompiler` for it, done.

**Bridge: Framework → Application.** The reverse. You have a legacy FastAPI app, you want a wire `Application`. `fastapi.extract()` scans routes, extracts handlers, infers triggers and codecs, and builds wire endpoints. But it also lets you transform the extraction on the fly — through bridge capabilities:

```python
from emergent.wire.bridge import WrapAsDelegate, IsolateGlobal, AddTrigger
from emergent.wire.bridge.bridgers import fastapi

wire_app = fastapi.extract(
    legacy_fastapi_app,
    capabilities=(
        WrapAsDelegate(),                    # preserve handler signatures
        IsolateGlobal(                       # rewrite globals with wire storage
            module_path="myapp.legacy",
            attr_name="_notes",
            factory=create_notes,
        ),
        AddTrigger(                          # add CLI triggers for cross-compilation
            trigger_type=CLITrigger,
            builder=build_cli_trigger,
        ),
    ),
)
cli_parser = cli.compile(wire_app, prog="notes-cli")
```

Your legacy REST API just got a CLI for free. No rewriting, no adapters. Bridge extracts the structure — `WrapAsDelegate` preserves the original handler signatures, `IsolateGlobal` rewrites module-level state with wire storage (so your CLI calls persist to disk instead of dying with the process), `AddTrigger` maps each extracted route to a CLI command. Then compile emits a different target. The wire `Application` is the universal intermediate representation. Anything in, anything out.

And the extracted `Application` is just a regular wire app — you can `.mount()` more endpoints on it, mix bridged routes with native wire endpoints:

```python
wire_app = wire_app.mount(
    endpoint(empty_runner()).expose(
        CLITrigger("state", "Show storage state"),
        immediate_factory(lambda: StateResponse(data=get_state())),
    ),
)
```

Compile and bridge are not axes. They're operations __on__ the IR. They're the entry and exit ramps of the highway that is wire's `Application`.

## Wait. This is still boilerplate.

Read back through this introduction. We talked about freeing your domain from environment, about DDD-by-design, about "tricky optimizations" that emergent unlocks. And then we showed... what exactly? You define ops, schema, storage, query, surface, capabilities, compile. That's a lot of concepts, a lot of wiring, and frankly — a lot of typing.

Look at the roulette example: you define the op as a dataclass, write the handler, build a runner, compose the endpoints, attach triggers, attach codecs, compile to three targets. It's precise, it's correct, it's fully explicit. But it doesn't feel like less boilerplate than the thing we criticized. You moved the boilerplate from "three separate apps" to "one app with three compile targets." Sure, it's structurally better — but line-for-line?

So: if emergent wants to reduce boilerplate, why is it so boilerplate-ish?

Here's the thing. The six axes and compile/bridge — that's the __foundation__. The explicit wiring, the manual endpoint construction, the hand-crafted triggers — that's Level 4, the escape hatch, the "I know exactly what I want" mode. You need this layer to exist, because without it there's no honest base to build on. But you're not supposed to live here.

Remember the promise from the very beginning? "Tricky optimizations, that naturally come from data you're working on, but being hidden with mess of architecture." We said emergent makes them available. We didn't say emergent makes you do them by hand.

## derivelib: the tricky optimizations

Emergent ships with `derivelib` by default — check `pyproject.toml`, it's right there, not an optional extra. derivelib is emergent's meta-layer: it operates on emergent's own primitives (ops, schema, storage, query, surface, capabilities) and generates them from the shape of your data. It's not code generation in the template sense. It's algebraic derivation over the sheaf.

The syntax is one decorator: `@derive(pattern)`.

```python
@derive(http_crud("/api/users", provider_node=Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: str
```

That's it. Six endpoints (List, Get, Create, Update, Patch, Delete), request types with validation, response types, OpenAPI schema, error handling (404, 409, 422 as RFC 7807 ProblemDetail), triggers, codecs, handlers. All derived from the shape of `User` and the pattern you chose.

How? The derivation pipeline works on the same axes you already know:

1. `http_crud` creates a `Dialect` — a bundle of `Op` descriptors + a `TriggerGen` (maps ops to HTTP routes) + a provider node.
2. `@derive` stores this pattern on the class. Nothing runs yet.
3. When you build the application, `fold_derive(steps, User)` folds the steps through two passes:
   - Pass 1: Schema — inspect entity fields, discover `Identity`, validate constraints
   - Pass 2: Query → Storage → Surface — bind provider, set base query, generate operations
4. Each step is a frozen dataclass implementing `derive_schema`, `derive_query`, `derive_storage`, or `derive_surface` (or any subset). The fold checks `isinstance` and skips non-matching phases.
5. The surface pass accumulates `OpSpec`s — pure data descriptions of operations. An OpSpec knows its name, input projection, response shape, handler template, trigger, capabilities, effects.
6. `materialize(ctx)` takes the specs and builds concrete artifacts: op types, request types (with `to_domain()` baked in), response types (with `from_domain()` baked in), handlers, exposures.
7. The result is a wire `Endpoint`, which gets mounted into an `Application`, which gets compiled to FastAPI or CLI or whatever.

The beauty: steps are just frozen dataclasses. Composable, inspectable, transformable. You don't like the default Delete? `swap_handler("Delete", SoftDeleteMark())`. Pagination on List? `.chain(paginated(20))`. Auth on mutations only? `.chain(add_capability(AuthCap(), Mutation))`. These are transforms on the derivation tuple — code, not configuration.

But `http_crud` is just one pattern. derivelib is not a CRUD generator. CRUD is one dialect built from generic primitives. The step algebra is generic, axis-agnostic, transport-agnostic. You can build your own dialect for anything: a task queue, an event-sourced system, a game API, a stateful conversation flow. The primitives are low-level enough that any derivation pattern can be expressed:

```python
# CRUD is one dialect
@derive(http_crud("/api/users", provider_node=Users))
@dataclass
class User: ...

# Methods is another
@derive(methods)
@dataclass
class OrderService:
    @classmethod
    @post("/api/orders")
    async def create(cls, customer: str, total: float) -> Result[int, DomainError]:
        return Ok(new_id)

# Mix them
@derive(
    http_crud("/bounties", provider_node=BountyBoard, ops=(LIST, GET, CREATE)),
    methods,
)
@dataclass
class Bounty:
    id: Annotated[int, Identity]
    title: str
    reward: int

    @classmethod
    @post("/bounties/{bounty_id}/claim")
    async def claim(cls, db: ..., bounty_id: int, hunter: str) -> Result[Bounty, DomainError]:
        ...

# Or build your own dialect from scratch
@derive(game_api(runner, expose(GetBalance, BalanceResponse, "/balance")))
class GameAPI: ...
```

Four levels of the same system: Level 1 (pure algebra, one decorator, full API), Level 2 (CRUD + hand-written methods), Level 3 (methods only, you write async methods, derivelib wires them), Level 4 (pure wire, full manual control). Pick the level you need. Mix them in the same app. The escape hatch is always there.

This is what "tricky optimizations" means. The data you already have — your dataclass fields, your type annotations, your capabilities — carries enough structural information to derive the entire API surface. derivelib reads that structure and writes the boilerplate you'd otherwise type by hand. Not by convention, not by guessing, not by magic strings. By algebraic derivation over the same axes your whole app is built on.

Emergent's promise, delivered: write the domain, derive the rest. The framework is just the projection.

## What's next

You now know the shape of emergent. Five axes, one vertical capability system, compile/bridge symmetry, and derivelib — the meta-layer that turns explicit structure into derived applications.

If you want to build a CRUD API in 5 minutes, jump to the derivelib quickstart. `@derive(http_crud(...))` and go.

If you want to understand the wire primitives, read the wire reference. Endpoints, triggers, codecs, capabilities — all there.

If you want to build a multi-target app from scratch (HTTP + CLI + Telegram sharing logic), look at the roulette example. It's pure Level 4 wire, every piece visible.

If you want to build your own derivation dialect — a task queue, a state machine, an event-sourced CQRS system — read the derivelib reference. The algebra is small: Step, Derivation, DerivationT, Pattern. Everything else is built from these four.
