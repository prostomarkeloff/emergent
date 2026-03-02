# The Shape of the Whole Thing

Twenty-three chapters of building things. Time to stop building and look at what we built.

Not the applications --- the framework underneath them. The recurring patterns. The reason things compose the way they do, why adding a feature doesn't break existing ones, why a Telegram compiler and a FastAPI compiler can coexist without knowing about each other. None of this is accidental. There's a shape to it, and that shape has a name.

---

## Everything is data

Pick any construct in emergent and try to call `explain()` on it. It works. Pick a query expression, a derivation step, a surface capability, an endpoint --- they're all inspectable, serializable, printable. No hidden state in closures. No behavior buried in lambda captures. No "you had to be there when it was constructed."

This is defunctionalization. Instead of representing behavior as functions, emergent represents it as frozen dataclasses. A filter isn't a function that checks a predicate --- it's a `Filter(Gt(Field("balance"), Const(100)))` data structure that describes the check. You can print it. You can serialize it to JSON. You can send it to a different backend that compiles it to SQL. You can feed it to an explain system that produces a human-readable description of what it does.

Functions are opaque. Data is transparent. Emergent chose transparency everywhere, and everything else follows from that choice.

## One way to consume

You produce capabilities --- annotations, steps, expressions --- by concatenation. Tuple append. The free monoid. You annotate a field with `Annotated[str, MaxLen(50), Index(), Doc("name")]` and each annotation is an independent generator. You build a derivation as `tuple[Step, ...]` and each step is independent. You stack exposures with `.expose()` and each exposure is independent.

You consume them with fold. Every compilation target, every query backend, every explain system walks the tuple, checks each element with `isinstance`, and processes the ones it understands. This isn't a design choice that could have gone another way. If your algebra is free (no equations between generators), then fold (the catamorphism) is the universal way to consume it. Any other consumer can be expressed as a fold. So emergent uses fold directly and skips the indirection.

One production mechanism (concatenation). One consumption mechanism (fold). Uniform from top to bottom.

## Build-time and runtime are different things

When you write `@derive(http_crud("/users"))`, nothing happens at runtime yet. The decorator produces a wire Application --- an intermediate representation. A data structure describing what endpoints exist, what triggers they respond to, what codecs they use, what capabilities they carry. It's a blueprint, not a building.

The compilation step --- `fastapi.compile(app)` --- reads that blueprint and produces a real FastAPI application. A different compilation step --- `cli.compile(app)` --- reads the same blueprint and produces a real argparse parser. The blueprint is the pivot point. It exists so you can inspect it before compiling, transform it between declaration and compilation, explain it without executing it, compile it to targets that didn't exist when you wrote the code.

This is staging. A program that produces a program. The first program runs at build-time (import-time, in Python). The second program runs at request-time. The gap between them is where all the power lives --- transforms rewrite the IR, explain reads it, multi-target compilation projects it.

If you went straight from decorators to FastAPI routes, you'd have a web framework. By going from decorators to IR to target, you have a compiler. And a compiler can target anything.

## Axes don't interfere

Schema, Query, Storage, Surface. Four axes, four compilation phases, four independent concerns. A `MaxLen(50)` on a field is a schema capability. A `Timeout(5.0)` on an endpoint is a surface enricher. They live in different phases of the fold, processed by different compilers, and they cannot interfere with each other by construction.

This isn't just "separation of concerns" in the hand-wavy software engineering sense. It's algebraic orthogonality. The schema fold produces a `SchemaCtx`. The surface fold produces a `SurfaceCtx`. They share no mutable state. A bug in your schema annotations cannot cause a bug in your surface layer, because they're folded independently into independent contexts. The type system enforces this --- a `SchemaDerivable` step has no access to `SurfaceCtx`, and vice versa.

The practical payoff: when something goes wrong with your HTTP routing, you don't need to check your field validators. When a query is slow, you don't need to audit your CLI argument parsing. Each axis is a closed world.

## Order doesn't matter

Write `Annotated[str, MaxLen(50), Index()]` or `Annotated[str, Index(), MaxLen(50)]`. Same result. Always. The fold over capabilities within an axis is commutative --- the output doesn't depend on the order of inputs. This means no ordering bugs. You never have to remember "put the validator before the serializer" or "the auth middleware must come after the CORS middleware." Within an axis, capabilities form a multiset, not a sequence.

This is a hard property to maintain, and emergent maintains it deliberately. Capabilities contribute independently to the compilation context. `MaxLen(50)` adds a constraint to the field. `Index()` marks it for indexing. Neither reads the other's output. They're parallel contributions, not sequential steps.

The enricher chain on the surface axis is the one place where ordering could matter --- enrichers wrap the handler, so the outermost enricher runs first. But even there, the capability declaration order doesn't determine execution order. The compiler sorts enrichers by their declared priority, not by their position in the annotation list.

## New things can't break old things

A colleague adds `GraphQLType("String!")` to a field. Your FastAPI compiler has never heard of GraphQL. What happens? Nothing. The compiler encounters the annotation, checks `isinstance(cap, ...)` against the types it knows, finds no match, skips it. Your application compiles and runs exactly as before.

This is open-world dispatch. The set of possible capabilities is open --- anyone can define new ones. Compilers only process what they recognize. An unknown capability is not an error --- it's a no-op. This means you can evolve your annotation vocabulary freely. Add capabilities for a new target before the compiler for that target exists. Ship annotations that only matter in staging. Attach metadata for documentation generators that haven't been written yet.

Closed-world systems (registries, enums, switch statements) break when you add a new case. Open-world systems (isinstance checks, protocol dispatch) ignore what they don't understand. Emergent is open-world everywhere.

## The sheaf

Put it all together and a geometric structure appears.

Your wire Application is a global section --- a single, coherent description of your entire system. It contains endpoints with multiple exposures, fields with multiple annotations, operations with multiple projections. Everything about a thing is on the thing.

Each compilation target is a fiber. The FastAPI compiler projects the global section onto the HTTP fiber and produces a FastAPI app. The CLI compiler projects onto the CLI fiber and produces an argparse parser. The Telegram compiler projects onto the Telegram fiber and produces a dispatcher. Each fiber is complete and self-consistent.

The sheaf condition holds: where fibers overlap (shared domain types, shared validation rules, shared operation semantics), they agree. They agree because they derive from the same source. The `PlaceBet` operation validates the same bet format whether you're hitting it via curl, typing it into a terminal, or sending it as a Telegram command. Not because someone remembered to copy the validation logic three times, but because all three fibers fold through the same handler.

One source. Multiple projections. Agreement on overlaps guaranteed by construction. That's a sheaf. Not a metaphor --- the actual mathematical object.

## What this buys you

Local reasoning. Everything about a field is on the field. Everything about an endpoint is on the endpoint. You don't need to trace through middleware registries, global configuration files, or framework magic to understand what a piece of code does. An LLM can read one annotated dataclass and understand the complete behavior of that entity across all targets. A human can too.

Zero-cost multi-target. Adding a new compilation target doesn't touch existing code. Write a new compiler that recognizes a new trigger type. Existing compilers ignore the new triggers. The new compiler ignores the old triggers. No refactoring. No adapter layers. No "extract interface" to make things testable across targets.

Mathematical composition guarantees. Capabilities compose by concatenation (a free monoid operation). Fold preserves the monoid structure (it's a homomorphism). Axis orthogonality prevents cross-axis interference. Commutativity prevents ordering bugs. Open-world dispatch prevents breakage from extension. These aren't aspirational properties --- they're algebraic invariants enforced by the type system and the fold architecture.

And self-description for free. Because everything is data, everything can be explained. `explain()` doesn't need special hooks or documentation annotations. It just reads the IR --- the same IR that the compilers read. The documentation and the behavior can't disagree, because they're derived from the same source.

---

**Next:** [Verify and Explain →](25-verify-and-explain.md)
