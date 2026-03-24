# Philosophy

## One function

emergent is one function:

```python
def fold(items, initial, protocol, method):
    ctx = initial
    for item in items:
        if isinstance(item, protocol):
            ctx = getattr(item, method)(ctx)
    return ctx
```

`items` are frozen dataclasses that carry `compile_*` methods. `initial` is an immutable accumulator. `protocol` is a `@runtime_checkable Protocol`. `method` is auto-derived from the protocol.

Everything in emergent — compilation, verification, derivation, query execution, explanation — is this function applied to different data. There is no second mechanism.

## The encoding

A capability is a frozen dataclass that knows how to compile itself to multiple targets:

```python
@dataclass(frozen=True, slots=True)
class MaxLen(Capability):
    value: int

    def compile_pydantic(self, ctx):
        return replace(ctx, max_length=self.value)

    def compile_openapi(self, ctx):
        return replace(ctx, maxLength=self.value)

    def compile_argparse(self, ctx):
        return replace(ctx, validator=lambda s: len(s) <= self.value)
```

Capabilities attach to fields via `Annotated`:

```python
@dataclass
class User:
    id: Annotated[int, Identity]
    name: Annotated[str, MinLen(1), MaxLen(100)]
    email: Annotated[str, Unique, MaxLen(255)]
```

`fold` reads the capabilities and produces correct output for each target. One declaration, N outputs.

## Four properties

This encoding has four properties that no surveyed system (12 systems, 1991–2025) achieves simultaneously:

**Self-compiling.** Each capability carries its own compilation methods. No external visitor traverses the data — the data compiles itself.

**Multi-target.** The same `MaxLen(100)` produces Pydantic validation, OpenAPI schema, CLI argparse, and SQL column type. Not variants of one target — completely independent targets.

**Inspectable data.** Capabilities are frozen dataclasses — immutable, hashable, serializable, printable. Not opaque closures. You can `explain_schema(User)` and see every capability on every field.

**Open-world.** Add a new capability or a new target without modifying existing code. `isinstance(item, protocol)` dispatch means if your capability implements the protocol, fold picks it up. No registration.

## Why this matters

Traditional frameworks scatter meaning across files. A `User` lives in a model, a serializer, a view, a URL config, a migration. Each can be independently wrong. Each must be manually kept in sync.

emergent inverts this. Everything about a field is on the field:

```python
email: Annotated[str,
    Unique,              # database constraint
    MaxLen(255),         # validation + schema + column type
    Doc("User email"),   # documentation
]
```

One change propagates to all targets. Not by convention — by construction. `fold` over `Annotated` capabilities is a catamorphism. It's mathematically guaranteed to visit every capability exactly once and produce deterministic output.

## The algebra

Compilers compose algebraically:

```python
FASTAPI_SCHEMA = PYDANTIC_PHASE + OPENAPI_PHASE
CLI_SCHEMA = ARGPARSE_PHASE
FULL = FASTAPI_SCHEMA + CLI_SCHEMA + STORAGE_SCHEMA

# Algebraic laws hold:
# A + A == A                (idempotent)
# (A + B) + C == A + (B + C)  (associative)
# A + empty == A              (identity)
# A | B overrides A with B    (right-biased merge)
# A - B removes B from A      (restriction)
# A & B keeps only shared      (intersection)
```

This isn't an analogy. `SchemaCompiler` and `TargetCompiler` are algebraic structures with proven laws. Tests verify these laws with hypothesis on random compiler combinations.

## For humans and machines

emergent is designed for bounded observers — agents (human or AI) that can't hold the entire program in working memory.

For humans: locality. All concerns for a field live on that field. You never need to find a second file to understand what `MaxLen(100)` does.

For AI: determinism. The compilation is a pure function. Same input → same output. An LLM doesn't need to understand the whole codebase to make a correct change — it modifies one declaration and fold handles the rest. The entity declaration is ~50 tokens. The equivalent Django code is ~5,000 tokens.

For verification: `verify(User)` catches contradictions at import time. `Min(100), Max(50)` → error before your code runs. No runtime surprises.

## What emergent is not

emergent is not a web framework. It doesn't serve HTTP requests — FastAPI does. emergent doesn't talk to databases — SQLAlchemy does. emergent doesn't parse CLI args — argparse does.

emergent is a **compiler**. It takes your type declarations and compiles them to whatever target you need. The targets do the actual work. emergent makes them agree on what work to do.
