# Who Gets What, When

Your app has a database pool. It was created once at startup and should live forever. Your app also has a "current user" -- extracted from a JWT token on every request, thrown away when the response is sent. Both values need to reach your handlers. Both have completely different lifetimes.

Most DI frameworks solve this with string labels: `@inject("singleton")`, `@inject("request")`. You write the label, hope you spelled it right, hope someone doesn't change the label upstream without telling you. emergent solves it with types and computation graphs.

---

## TypedScope -- the runtime value bag

A `TypedScope` is a typed dictionary. You put values in, you get values out. The key is the type itself.

```python
from emergent import graph as G

scope = G.TypedScope(detail="request")
scope.inject(Database, db)
scope.inject(CurrentUser, user)

db = scope.get(Database)       # -> Database instance
user = scope.get(CurrentUser)  # -> CurrentUser instance
```

No string keys. No `container.resolve("database")`. The type *is* the key. If you ask for `Database` and nobody injected one, you get a `KeyError` immediately -- not a `None` that explodes three layers deeper.

`TypedScope` wraps nodnod's `Scope` with a typed interface. Under the hood, it pushes `Value(type, instance)` pairs into the scope. But you never touch that layer directly.

## Nodes -- the computation graph

A node is a class with a `__compose__` classmethod. nodnod reads the parameter types and builds a dependency graph automatically.

```python
from emergent import graph as G

@G.node
class FetchUser:
    def __init__(self, user: User):
        self.user = user

    @classmethod
    async def __compose__(cls, order: Order, db: Database) -> "FetchUser":
        raw = await db.get_user(order.user_id)
        return cls(User(raw["id"], raw["name"]))
```

`FetchUser` depends on `Order` and `Database`. nodnod knows this because it reads the `__compose__` signature. If `Order` itself depends on something else, nodnod follows the chain. If two dependencies are independent, nodnod runs them in parallel. Sound familiar? It's the same engine from the Ops chapter -- Ops are built on top of this.

## run() -- the fluent bridge

The `run()` function connects the value bag to the computation graph:

```python
result = await (
    G.run(FetchUser)
    .inject(order_data)
    .inject(db)
)
```

What happens here: `run(FetchUser)` creates a `Run[FetchUser]` builder. Each `.inject(value)` adds a value to the scope, with its type inferred from `type(value)`. When you `await` the builder, it creates a `TypedScope`, pushes all injections into it, auto-discovers every node that `FetchUser` depends on, and executes the graph.

Need to inject with an explicit type (because you're injecting a subclass as a base)?

```python
result = await (
    G.run(FetchUser)
    .inject_as(Database, postgres_db)  # inject PostgresDB as Database
    .inject(order)
)
```

Or if brevity is your thing:

```python
result = await G.run(FetchUser).given(order, db, email_service)
```

`.given()` takes multiple values at once, inferring types from each.

## compose() -- one-shot

When you don't need the fluent builder, `compose()` does it in one call:

```python
user = await G.compose(FetchUser, order, db)
```

Same machinery. Less ceremony. Auto-discovers the graph, injects the values, runs everything, returns the result.

## Compiled graphs -- pay once, run many

`run()` and `compose()` discover the dependency graph on every call. For a hot path, you want to pay that cost once. That's what `graph()` does:

```python
pipeline = G.graph(FetchUser)

# Later, at request time (many times):
user1 = await pipeline(order1, db)
user2 = await pipeline(order2, db)
```

`graph(FetchUser)` returns a `Compiled[FetchUser]` -- a pre-compiled graph that remembers the agent configuration. Each call to `pipeline(...)` reuses the compiled structure and only creates a fresh scope for the new inputs.

The fluent API works here too:

```python
user = await pipeline.run().inject(order).inject(db)
```

## ScopeFamily -- the lifetime algebra

Back to the original problem: database pool lives forever, current user lives per-request. `ScopeFamily` maps types to lifetime tiers:

```python
from emergent.graph import ScopeFamily

family = (
    ScopeFamily()
    .bind("app", Database, Config, FeatureFlags)
    .bind("request", CurrentUser, RequestId, Locale)
)
```

Each `.bind(tier, *types)` says: "these types belong to this lifetime." The tier key can be a string, an enum, whatever you want. The family is frozen data -- no side effects, no scope creation.

Query it:

```python
family.types_for("app")       # -> frozenset({Database, Config, FeatureFlags})
family.tier_of(CurrentUser)   # -> "request"
```

Compose families with `|`:

```python
auth_family = ScopeFamily().bind("request", CurrentUser, AuthToken)
infra_family = ScopeFamily().bind("app", Database, Cache)

combined = infra_family | auth_family  # right side wins on conflict
```

When it's time to run, `materialize()` interprets the family into nodnod's `mapped_scopes`:

```python
from nodnod import Scope

app_scope = Scope(detail="app")
request_scope = Scope(detail="request")

# Push values into their scopes...
mapped = family.materialize({"app": app_scope, "request": request_scope})
# -> {Database: app_scope, Config: app_scope, CurrentUser: request_scope, ...}
```

nodnod uses this mapping to resolve each dependency from the correct scope. `Database` comes from the app scope (created once). `CurrentUser` comes from the request scope (created per-request). The resolution is automatic. The lifetimes are explicit. No ambient state, no thread-locals, no magic.

## The three layers

Think of it as three distinct layers:

**TypedScope** is the runtime value bag. It holds concrete instances. It's created, filled, used, and discarded.

**Nodes and `run()`/`compose()`/`graph()`** are the computation graph. They describe what depends on what. nodnod parallelizes the independent parts.

**ScopeFamily** is the lifetime algebra. It describes which values live how long. Pure data, composable with `|`, interpreted into scope mappings at the boundary.

DI in emergent is not a container with registration callbacks and lifecycle hooks. It's a computation graph that reads its own shape from the types you wrote, resolves in parallel where it can, and respects the lifetimes you declared. The types *are* the configuration.

---

**Next:** [Wrapping the Handler ->](19-enrichers.md)
