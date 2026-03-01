# How It Works

Seven chapters of "look what it can do." Time to open the hood.

You don't need this chapter to *use* emergent. But if you've been thinking "okay, but what's *actually happening* when I write `@derive(http_crud(...))`?" — this is where we answer that.

---

## The four axes

Every piece of your application lives on one of four axes:

| Axis | Question it answers | Lives in |
|------|-------------------|----------|
| **Schema** | What does the data look like? | `Annotated[int, Identity]`, field types |
| **Query** | How do we access the data? | `relational(Bug).filter(...)`, provider binding |
| **Storage** | Where does the data live? | `memory_node()`, SQLAlchemy backend |
| **Surface** | How is the app exposed? | `HTTPRouteTrigger("GET", "/bugs")`, CLI triggers |

They're orthogonal. A schema capability (`Identity`, `Unique`, `MaxLen`) doesn't interfere with a surface capability (`Tag`, `CORS`). Each compiler reads the axis it cares about and ignores the rest. That's why `http_crud` and `cli_crud` compose without conflict — they operate on different regions of the surface axis with different trigger types.

## The two-pass fold

When `build_application_from_decorated(Bug)` runs, it calls `fold_derive` — a two-pass fold over the derivation tuple.

**Pass 1 — Schema:** Inspect the entity. Populate `SchemaCtx` with field names, types, identity fields. This runs first because everyone else needs it.

**Pass 2 — Query, Storage, Surface:** Run sequentially, each reading from `SchemaCtx`:
- `QueryCtx` gets the provider node and base query
- `StorageCtx` gets the backend (if any)
- `SurfaceCtx` accumulates `OpSpec`s — one per endpoint

The fold is a catamorphism. Each step in the derivation tuple is a frozen dataclass implementing one or more axis protocols (`SchemaDerivable`, `QueryDerivable`, `SurfaceDerivable`). The fold checks `isinstance`, calls the matching `derive_*` method, and passes the context through. Steps that don't match an axis are silently skipped.

## Walk-through: `@derive(http_crud("/users", Users))`

Let's trace every step.

**Step 1 — `http_crud()` creates a Dialect.**

```python
http_crud("/users", provider_node=Users)
```

This calls `dialect()` which bundles:
- **Preamble:** `(inspect_entity(), require_identity(), bind_provider(Users), base_query())`
- **Ops:** `(LIST, GET, CREATE, UPDATE, PATCH, DELETE)` — each an `Op` with a name, input projection, response spec, handler template, and effects
- **Triggers:** `HTTPTriggers("/users")` — maps op names to HTTP method + path

**Step 2 — `Dialect.compile(User)` assembles the derivation.**

The preamble steps + one `DeriveOp` per op get concatenated into a `Derivation` tuple. Each `DeriveOp` wraps an `Op` with its trigger (e.g., `HTTPRouteTrigger("GET", "/users")` for List).

**Step 3 — `fold_derive(steps, User)` runs.**

Pass 1:
- `inspect_entity()` → populates `SchemaCtx` with `{"id": FieldInfo(int, [Identity]), "name": FieldInfo(str, []), "email": FieldInfo(str, [Unique])}`
- `require_identity()` → validates that at least one field has `Identity`. If not, error.

Pass 2:
- `bind_provider(Users)` → sets `QueryCtx.provider_node = Users`
- `base_query()` → sets `QueryCtx.base_query = relational(User)`
- Each `DeriveOp` runs `derive_surface()`:
  - Reads field projections from `SchemaCtx` (e.g., for CREATE: non-identity fields → `name`, `email`)
  - Builds an `OpSpec` with the projected fields, response spec, handler template, and trigger
  - Appends the `OpSpec` to `SurfaceCtx.specs`

**Step 4 — `materialize(ctx)` generates concrete artifacts.**

For each `OpSpec`:
1. **Request type** — a new dataclass. `CreateUserRequest(name: str, email: str, provider: MutatingRelationalProvider[User])`
2. **Response type** — a new dataclass. `CreateUserResponse(id: int, name: str, email: str)` with a `from_domain()` classmethod
3. **Handler** — built from the handler template. `InsertNew.build(spec)` returns a function that constructs the entity from request fields and inserts it via the provider
4. **Exposure** — `(HTTPRouteTrigger("POST", "/users"), rrc(CreateUserRequest, CreateUserResponse), capabilities)`

**Step 5 — Assembly.**

All exposures go into one wire `Endpoint` with a shared `Runner`. The endpoint goes into an `Application`.

**Step 6 — Compilation.**

`targets.fastapi.compile(app)` scans the application for `HTTPRouteTrigger` exposures. For each one: creates a FastAPI route function that unwraps the RRC codec, registers it at the trigger's path and method. Pydantic models are generated from the request/response types (via a fold through `PydanticContext` — yet another catamorphism).

---

## The key insight

Everything between steps 1 and 4 is *data*. `Op`, `DeriveOp`, `OpSpec` — all frozen dataclasses. Inspectable. Transformable. Serializable. When you `.chain(paginated())`, you're rewriting that data between steps 2 and 4. When you `explain_entity(User)`, you're reading it. The actual code generation only happens at step 4 (materialize) and step 6 (compile).

This is staging — a compile-time data phase followed by a runtime code phase. It's why transforms work, why explain works, why multi-target works. The program is data first, code second.

---

**Next:** [Custom Handler Templates →](09-custom-handlers.md)
