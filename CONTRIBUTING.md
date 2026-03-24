# Contributing to emergent

## Setup

```bash
git clone https://github.com/prostomarkeloff/emergent.git
cd emergent
uv sync --dev
```

This installs all dependencies including optional targets (FastAPI, SQLAlchemy, Telegrinder).

## Running tests

```bash
uv run python tests/run.py light     # ~1min  — pre-commit
uv run python tests/run.py medium    # ~3min  — CI
uv run python tests/run.py tough     # ~15min — nightly
```

All modes run the same tests. The difference is fuzzing intensity (hypothesis examples, schemathesis requests, mutation testing).

## Type checking

```bash
uv run pyright emergent/    # must be 0 errors
```

emergent uses pyright strict mode. No `type: ignore`, no `object` as type annotation. Use generics, protocols, and isinstance narrowing.

## Architecture

emergent is one function:

```python
def fold(items, initial, protocol, method):
    ctx = initial
    for item in items:
        if isinstance(item, protocol):
            ctx = getattr(item, method)(ctx)
    return ctx
```

Everything else — compilation, verification, derivation, query execution — is this function applied to different data.

### Key invariants

- `fold` signature does not change
- `CompilationPhase + SchemaCompiler + TargetCompiler` algebra laws hold (idempotent, associative, identity)
- Capabilities are frozen dataclasses with `compile_*` methods
- Protocol dispatch via `isinstance` — open-world, no registration
- All contexts are immutable (`@dataclass(frozen=True, slots=True)`)

### Adding a capability

```python
@dataclass(frozen=True, slots=True)
class MyCapability(Capability):
    value: int

    def compile_constraints(self, ctx: ConstraintsContext) -> ConstraintsContext:
        return replace(ctx, my_field=self.value)

    def compile_openapi(self, ctx: OpenAPIContext) -> OpenAPIContext:
        return openapi_schema(ctx, **{"x-my-field": self.value})
```

No registration needed. `fold` picks it up via `isinstance(cap, ConstraintsCompilable)`.

### Adding a compilation target

Follow the pattern in `emergent/wire/compile/targets/testing.py`:

1. Define `WrapContext` (frozen dataclass)
2. Define `from_codec` functions for each codec type
3. Define `assemble` function
4. Create `TargetCompiler` instance
5. Write `compile` function that calls `scan_and_wrap`

## PR requirements

- All tests pass: `uv run python tests/run.py light`
- pyright clean: `uv run pyright emergent/`
- No `type: ignore` in emergent/ (tests may use it sparingly)
- New capabilities must have at least one property test
