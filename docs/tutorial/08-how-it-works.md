# How It Works

Seven chapters of "look what it can do." Time to open the hood.

You don't need this chapter to *use* emergent. But if you've been thinking "okay, but what's *actually happening* when I write `@schema_meta(http_crud(...))`?" — this is where we answer that.

---

## The four axes

Every piece of your application lives on one of four axes:

| Axis | Question it answers | Lives in |
|------|-------------------|----------|
| **Schema** | What does the data look like? | `Annotated[int, Identity]`, field types |
| **Query** | How do we access the data? | `relational(Bug).filter(...)`, provider binding |
| **Storage** | Where does the data live? | `MemoryRelationalProvider`, SQLAlchemy backend |
| **Surface** | How is the app exposed? | `HTTPRouteTrigger("GET", "/bugs")`, CLI triggers |

They're orthogonal. A schema capability (`Identity`, `Unique`, `MaxLen`) doesn't interfere with a surface capability (`Tag`, `CORS`). Each compiler reads the axis it cares about and ignores the rest. That's why `http_crud` and `cli_crud` compose without conflict — they operate on different regions of the surface axis with different trigger types.

## The three-phase fold

When `compile_derive(Bug)` runs, it performs three phases of protocol-based fold:

**Phase 1 — Generate (`DeriveGeneratable`):** Each generator capability (like `CRUD`) reads the entity schema and produces `OpSpec` descriptions — one per endpoint. The `DeriveCtx` is populated with entity fields, identity fields, query strategy, and specs.

**Phase 2 — Modify (`DeriveModifiable`):** Transform capabilities (like `Paginated`, `Readonly`, `SoftDelete`) read the specs from Phase 1 and rewrite them. `Paginated` replaces the List handler, `Readonly` removes mutation specs, etc.

**Phase 3 — Augment (`DeriveAugmentable`):** Post-modification augmentation (like `NestedCRUD` backlinks).

The fold is a catamorphism. Each capability in `@schema_meta(...)` is a frozen dataclass implementing one or more phase protocols. The fold checks `isinstance`, calls the matching `compile_derive_*` method, and passes the context through. Capabilities that don't match a phase are silently skipped.

## Walk-through: `@schema_meta(http_crud("/users", Users))`

Let's trace every step.

**Step 1 — `http_crud()` creates a `CRUD` capability.**

```python
http_crud("/users", Users)
```

This creates `CRUD(triggers=HTTPTriggers("/users"), provider_node=Users)` — a `SchemaCapability` implementing `DeriveGeneratable`.

**Step 2 — `compile_derive(User)` runs three phases.**

Phase 1 (`compile_derive_generate`):
- `CRUD` reads entity fields → discovers `id`, `name`, `email`
- Validates identity field exists → `id` has `Identity`
- Sets up `RelationalStrategy` with the provider node
- Calls `generate_specs()` → one `OpSpec` per CRUD operation (List, Get, Create, Update, Patch, Delete)
- Each `OpSpec` carries: name, input fields, response spec, handler template, trigger, effects

Phase 2 (`compile_derive_modify`):
- No modifiers in this example, so specs pass through unchanged

Phase 3 (`compile_derive_augment`):
- No augmenters, pass through

**Step 3 — `materialize(ctx)` generates concrete artifacts.**

For each `OpSpec`:
1. **Request type** — a new dataclass. `CreateUserRequest(name: str, email: str, provider: MutatingRelationalProvider[User])`
2. **Response type** — a new dataclass. `CreateUserResponse(id: int, name: str, email: str)` with a `from_domain()` classmethod
3. **Handler** — built from the handler template. `InsertNew.build(spec)` returns a function that constructs the entity from request fields and inserts it via the provider
4. **Exposure** — `(HTTPRouteTrigger("POST", "/users"), rrc(CreateUserRequest, CreateUserResponse), capabilities)`

All exposures go into one wire `Endpoint` with a shared ops `Runner`.

**Step 4 — `application().mount(endpoint)` + Compilation.**

`targets.fastapi.compile(app)` scans the application for `HTTPRouteTrigger` exposures. For each one: creates a FastAPI route function, registers it at the trigger's path and method. Pydantic models are generated from the request/response types (via a fold through `PydanticContext` — yet another catamorphism).

---

## The key insight

Everything between steps 1 and 3 is *data*. `Op`, `OpSpec`, `DeriveCtx` — all frozen dataclasses. Inspectable. Transformable. Serializable. When you add `Paginated(20)` to `@schema_meta`, you're rewriting that data in Phase 2. When you `explain_entity(User)`, you're reading it. The actual code generation only happens at step 3 (materialize) and step 4 (compile).

This is staging — a compile-time data phase followed by a runtime code phase. It's why transforms work, why explain works, why multi-target works. The program is data first, code second.

---

**Next:** [Custom Handler Templates →](09-custom-handlers.md)
