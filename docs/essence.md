# The Essence of emergent

## One Operator

emergent is one function:

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

`items` — frozen dataclasses carrying `compile_*` methods.
`initial` — frozen accumulator (compilation state).
`protocol` — a `@runtime_checkable Protocol` with one `compile_*` method.
`method` — the method name, auto-derived from the protocol.
`handlers` — optional per-type overrides.
`trace` — optional trace collector (explanation for free, zero cost when off).

Everything in emergent — compilation, verification, explanation, LLM verification, query execution, derivation, semantic macros — is this one function applied to different data.

## The Encoding

A capability is a frozen dataclass that knows how to compile itself:

```python
@dataclass(frozen=True, slots=True)
class MaxLen(UniversalCapability):
    value: int

    def compile_pydantic(self, ctx: PydanticContext) -> PydanticContext:
        return replace(ctx, max_length=self.value)

    def compile_openapi(self, ctx: OpenAPIContext) -> OpenAPIContext:
        return replace(ctx, maxLength=self.value)

    def compile_sqlalchemy(self, ctx: SQLAlchemyContext) -> SQLAlchemyContext:
        return replace(ctx, column_type=f"VARCHAR({self.value})")
```

Capabilities attach to fields via `Annotated`:

```python
@dataclass
class User:
    email: Annotated[str, MaxLen(255), Unique, sql.Index()]
```

Compilation = fold capabilities through a target context:

```
fold([MaxLen(255), Unique, sql.Index()], PydanticContext(), PydanticCompilable, "compile_pydantic")
  → MaxLen transforms ctx (max_length=255)
  → Unique transforms ctx (unique=True)
  → sql.Index() skipped (not PydanticCompilable)
  → done: PydanticContext(max_length=255, unique=True)
```

Same list, different protocol — different target:

```
fold([MaxLen(255), Unique, sql.Index()], OpenAPIContext(), OpenAPICompilable, "compile_openapi")
  → MaxLen transforms ctx (maxLength=255)
  → Unique skipped (not OpenAPICompilable)
  → sql.Index() skipped (not OpenAPICompilable)
  → done: OpenAPIContext(maxLength=255)
```

One declaration. N targets. Each target sees only what implements its protocol. The `isinstance` check is what makes it open-world — new capabilities participate without registration.

## The Same Fold Everywhere

### Queries

Query operations are frozen dataclasses with `compile_*` methods — capabilities by another name:

```python
q = users.filter(lambda u: u.balance > 100).order_by(lambda u: u.balance.desc()).limit(50)

for op in q.ops:
    print(op)
# Filter(expr=Gt(Field('balance'), Const(100)))
# OrderBy(specs=(OrderSpec(field='balance', ascending=False),))
# Limit(count=50)
```

Same fold, different backends:

```
fold(q.ops, MemoryQueryContext(data=all_users), MemoryQueryCompilable, "compile_memory_query")
  → Filter removes non-matching → OrderBy sorts → Limit slices → done

fold(q.ops, SAQueryContext(query=select(User)), SAQueryCompilable, "compile_sa_query")
  → Filter adds WHERE → OrderBy adds ORDER BY → Limit adds LIMIT → done
```

One query. N backends. Write it once, fold it anywhere.

### Entity-Level: `@schema_meta`

Fields carry capabilities in `Annotated`. Entities carry capabilities in `@schema_meta`:

```python
@schema_meta(SoftDelete("deleted_at"), Timestamps("created_at", "updated_at"))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
```

`SoftDelete` and `Timestamps` are frozen dataclasses with `compile_*` methods — folded by `EntityFold`, structurally identical to `CompilationPhase`. When a target compiles an entity, it runs two folds: field-level (from `Annotated`) and entity-level (from `@schema_meta`). Same operator twice.

## Verification Is a Compilation Target

This is the insight that makes the architecture click.

`Min(100)` + `Max(50)` compiles fine — fold doesn't check logic, it accumulates context. The contradiction only surfaces at runtime. Unless you fold through a verification context:

```python
NUMERIC_VERIFY_PHASE = CompilationPhase(
    NumericVerifyCtx, NumericVerifyCompilable,
    lambda n, t: NumericVerifyCtx(field_name=n, field_type=t),
)
```

Same `CompilationPhase`. Same fold. But the context accumulates constraint facts instead of schema properties. After the fold, `ctx.check()` resolves contradictions:

```python
issues = verify(User)
# [Issue("balance", ERROR, "Min(100) > Max(50)")]
```

Three built-in phases: numeric ranges, string lengths, semantic contradictions (`ReadOnly` + `WriteOnly`). But the mechanism is open — build your own:

```python
@dataclass(frozen=True, slots=True)
class SecurityVerifyCtx:
    is_sensitive: bool = False
    is_encrypted: bool = False

    def check(self) -> tuple[Issue, ...]:
        if self.is_sensitive and not self.is_encrypted:
            return (Issue(..., "Sensitive field must be encrypted"),)
        return ()

SECURITY_VERIFY_PHASE = CompilationPhase(
    SecurityVerifyCtx, SecurityVerifyCompilable,
    lambda n, t: SecurityVerifyCtx(),
)
```

Any capability that implements `compile_verify_security` now participates. No registration. No modification of existing code. Just another fold target.

The query axis verifies too. `Limit` without `OrderBy` — non-deterministic results. `Having` without `GroupBy` — invalid query. Same fold, same `isinstance` dispatch, different items:

```python
QUERY_VERIFY = QueryPhase(
    protocol=QueryVerifyCompilable,
    method="compile_verify_query",
    handlers={
        Limit: lambda op, ctx: replace(ctx, has_limit=True),
        OrderBy: lambda op, ctx: replace(ctx, has_order=True),
    },
)

ctx = QUERY_VERIFY.fold(q.ops, QueryVerifyCtx())
issues = ctx.check()
```

Verification isn't bolted on. It's the same operator pointed at constraint checking.

## Explain Is Free

Pass `trace=TraceCollector()` to the fold. Every step gets recorded: which capabilities were applied, which were skipped, which changed the context. Zero overhead when off.

```python
axes = Axes.traced()
FASTAPI_SCHEMA.compile(User, axes)
print(explain(axes))  # full trace: every field, every phase, every step
```

Capabilities are data → `repr()` works. Contexts are data → diff works. The fold is transparent by construction. No special explain infrastructure needed — just record what the fold already does.

Schema explain, surface explain, query explain, compilation trace explain — five systems, all reading the same frozen data. Dict layer for agents. Human-readable layer for terminals.

## LLM Verification: The Fold Reaches Outside

llmify is a compilation target. `Contract` is a capability. It has `compile_llmify`:

```python
@dataclass(frozen=True, slots=True)
class Contract(SchemaAxisCapability):
    text: str

    def compile_llmify(self, ctx: LlmifyContext) -> LlmifyContext:
        return replace(ctx, messages=(*ctx.messages,
            system(text=f'Field "{ctx.field_name}" contract: "{self.text}"')
        ))
```

The fold collects all contracts and capabilities into LLM messages and tools. Then:

```python
program = contract_check(Sensor, domain="industrial monitoring")
# Returns: AI[ContractCheckResult] — frozen AST, not executed yet

result = await program.compile(provider)
# LLM checks: does Contract("Celsius, -40..125") match Min(-40), Max(125)?
# Returns: structured issues, invariant suggestions, test cases
```

`accumulate()` runs multiple passes. Each pass tells the LLM what was already found. LLM searches for new issues. Convergence when nothing new. Non-deterministic search, deterministic verification.

The fold collected the context. The LLM verified the meaning. Same operator, reaching outside the program.

## Derivation: The Fold Generates Programs

`@derive` attaches a pattern to an entity. A pattern compiles to a `Derivation` — a tuple of frozen dataclass steps:

```python
@derive(http_crud("/users", provider_node=Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
```

`http_crud` compiles to steps like `InspectEntity`, `BindProvider`, `BaseQuery`, and `DeriveOp` for each operation (List, Get, Create, Update, Delete). Each step is a frozen dataclass with `derive_*` methods for the axes it touches.

`fold_derive` runs four sequential folds — one per axis:

```python
schema_ctx  = SCHEMA_PHASE.fold(steps, SchemaCtx.from_entity(entity))
query_ctx   = QUERY_PHASE.fold(steps, QueryCtx(schema=schema_ctx))
storage_ctx = STORAGE_PHASE.fold(steps, StorageCtx(schema=schema_ctx))
surface_ctx = SURFACE_PHASE.fold(steps, SurfaceCtx(schema=schema_ctx, query=query_ctx, ...))
```

Each phase uses the same `fold()` underneath. Each step implements only the protocols it cares about. `InspectEntity` implements `SchemaDerivable`. `DeriveOp` implements `SurfaceDerivable`. The others are skipped — open-world, same as field compilation.

The output: a complete `Application` with endpoints, handlers, exposures, ready for `fastapi.compile()` or `cli.compile()` or any target.

## Semantic Dispatch: Transforms on Meaning

Each `DeriveOp` carries effects — frozen dataclasses describing what the operation *means*:

```python
DeriveOp("List", ..., effects=(Read(), Pageable(default_size=20)))
DeriveOp("Create", ..., effects=(Mutation(),))
DeriveOp("Delete", ..., effects=(Mutation(), Deletes()))
```

`DerivationT` transforms dispatch on these effects:

```python
def readonly() -> DerivationT:
    return reject_by_effect(Mutation)  # drops Create, Update, Delete

def paginated(size: int) -> DerivationT:
    # finds ops with Pageable effect, replaces their handler
    return map_by_effect({Pageable: lambda eff, op: replace(op, handler=PaginatedFetchMany(size))})
```

The transform doesn't parse code. It asks: *is this operation pageable?* via `isinstance(eff, Pageable)`. It reads `Pageable.default_size`. It replaces the handler. That's semantic dispatch — operating on domain meaning, not syntax.

Compose them:

```python
@derive(
    http_crud("/articles", provider_node=Articles)
        .chain(paginated(20))
        .chain(sorted_list())
        .chain(readonly())
)
```

`.chain()` applies `DerivationT` transforms sequentially: `tuple → tuple → tuple`. Pure functions on frozen data. Each transform is independently testable, composable, explainable.

## Why Only Python

The fold requires three language primitives simultaneously:

| Primitive | What it does | Python PEP | Year |
|-----------|-------------|------------|------|
| `@dataclass(frozen=True)` | Immutable data that carries methods | 557 | 2018 |
| `Protocol` + `isinstance` | Structural dispatch at runtime | 544 | 2019 |
| `Annotated[T, ...]` | Attach frozen objects to type annotations | 593 | 2020 |

Remove any one:

- **Without frozen dataclass**: capabilities are mutable → can't hash, can't compare, can't serialize, can't reason about.
- **Without Protocol + isinstance**: dispatch requires inheritance or registration → closed world, no open extension.
- **Without Annotated**: nowhere to put capabilities per-field at the type level.

The conjunction arrived in Python 3.9 (2020). The fold was mathematically possible since Reynolds (1972) and Meijer (1991). But no language gave you all three primitives — immutable data carrying methods, structural dispatch checking at runtime, and type-level metadata attachment — until Python did.

Other languages get close but lose something. TypeScript erases types at runtime — no `isinstance`. Rust proc macros generate invisible code — no inspectability. Kotlin annotations aren't typed objects — no methods. Go struct tags are strings — no dispatch. Each loses a property the fold requires.

## The Inversion

The Dragon Book (1977): IR is passive data, compilers traverse it externally.

emergent: IR carries its own compilation methods. There are no external visitors, no passes, no separate traversal infrastructure. The data compiles itself through fold.

This is why everything in emergent is the same pattern. Compilation, verification, explanation, LLM verification, query execution, derivation, semantic macros — each is a new (context, protocol) pair fed to the same fold. The operator doesn't change. The data does.

One fold. Three language primitives. The rest is consequences.
