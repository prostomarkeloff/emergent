# Custom capabilities

You've used `Min(0)`, `MaxLen(100)`, `OneOf("a", "b")`. Now write your own.

## The pattern

A capability is a frozen dataclass with `compile_*` methods:

```python
from dataclasses import dataclass, replace
from emergent.wire.axis._capability import Capability, OpenAPIContext, ConstraintsContext, openapi_schema

@dataclass(frozen=True, slots=True)
class Currency(Capability):
    """Annotates a monetary field with its currency code."""
    code: str

    def compile_openapi(self, ctx: OpenAPIContext) -> OpenAPIContext:
        return openapi_schema(ctx, **{"x-currency": self.code})

    def compile_constraints(self, ctx: ConstraintsContext) -> ConstraintsContext:
        return replace(ctx, choices=(self.code,))
```

Use it:

```python
@dataclass
class Invoice:
    id: Annotated[int, Identity]
    amount: Annotated[float, Min(0), Currency("USD")]
```

That's it. No registration. No plugin system. fold picks it up via `isinstance(Currency(...), OpenAPICompilable)` — structural subtyping.

## How dispatch works

fold checks: does this item implement the protocol?

```python
@runtime_checkable
class OpenAPICompilable(Protocol):
    def compile_openapi(self, ctx: OpenAPIContext) -> OpenAPIContext: ...
```

Your `Currency` has `compile_openapi` → `isinstance(Currency("USD"), OpenAPICompilable)` is `True` → fold calls it. Your `Currency` doesn't have `compile_pydantic` → `isinstance(Currency("USD"), PydanticCompilable)` is `False` → fold skips it. No crash.

This is why it's open-world. You add a capability, existing compilers that understand your protocol pick it up. Compilers that don't, skip it.

## Multi-target capability

A single capability can compile to many targets:

```python
@dataclass(frozen=True, slots=True)
class Encrypted(Capability):
    """Field value is encrypted at rest."""
    algorithm: str = "AES-256"

    def compile_openapi(self, ctx: OpenAPIContext) -> OpenAPIContext:
        return openapi_schema(ctx, **{"x-encrypted": True, "x-algorithm": self.algorithm})

    def compile_storage_field(self, ctx: StorageFieldContext) -> StorageFieldContext:
        return replace(ctx, to_storage=encrypt_fn, from_storage=decrypt_fn)

    def compile_constraints(self, ctx: ConstraintsContext) -> ConstraintsContext:
        return ctx  # no constraint effect, but participates in fold
```

Now `Annotated[str, Encrypted()]` means:
- OpenAPI documents it as encrypted
- Storage axis encrypts before write, decrypts after read
- Constraints pass through (no validation needed)

Three targets, one annotation. Each target gets exactly what it needs.

## Capability with verify

Your capability can participate in verification:

```python
@dataclass(frozen=True, slots=True)
class MaxPrecision(Capability):
    """Float field must not exceed N decimal places."""
    places: int

    def compile_verify_numeric(self, ctx: NumericVerifyCtx) -> NumericVerifyCtx:
        return replace(ctx, max_precision=self.places)

    def compile_openapi(self, ctx: OpenAPIContext) -> OpenAPIContext:
        return openapi_schema(ctx, **{"x-max-precision": self.places})
```

Now `verify(Invoice)` checks that `MaxPrecision(2)` doesn't contradict other numeric constraints.

## Compose capabilities

Capabilities compose via tuple concatenation (free monoid):

```python
amount: Annotated[float, Min(0), Max(1_000_000), Currency("USD"), MaxPrecision(2), Encrypted()]
```

Five capabilities on one field. fold processes each independently, in order. The result is the composition of all their effects. No interference between capabilities — each transforms its own context.

## When NOT to write a capability

Don't write a capability for logic that runs at request time. Capabilities are compile-time metadata. They describe what a field IS, not what to DO with it at runtime.

- ✅ `Encrypted()` — describes the field's storage behavior
- ✅ `Currency("USD")` — describes the field's semantics
- ❌ `ValidateAsync(check_db)` — this is a runtime enricher, not a capability

For runtime behavior, use enrichers (Timeout, Retry, Auth) or handler templates.

---

← [fold.md](fold.md) | → [encoding.md](encoding.md)
