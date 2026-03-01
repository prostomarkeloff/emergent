# Talking to Data

Your handler needs to find all active users with a balance over 100, sorted by balance descending, page 2 of 50. You could loop through a list with Python's `filter()` and `sorted()`. You could write raw SQL. You could reach for an ORM.

But then your handler is married to a backend. Switch from Postgres to an in-memory store for tests? Rewrite the query. Expose the same filter over a REST API? Rewrite again. Log what the query *does* for debugging? Parse the SQL string, I guess.

There's a different way. What if the query itself were data?

---

## Building a query

```python
from dataclasses import dataclass
from emergent.wire.axis.query import relational

@dataclass(frozen=True, slots=True)
class User:
    id: int
    name: str
    active: bool
    balance: float

users = relational(User)
```

`relational(User)` creates a `RelationalQuerySet[User]` -- a lazy, composable query builder. It holds no data. It knows nothing about databases. It's a description of *what you want*, not *how to get it*.

Chain operations to build up the query:

```python
q = (
    users
    .filter(lambda u: u.active == True)
    .filter(lambda u: u.balance > 100)
    .order_by(lambda u: u.balance.desc())
    .limit(50)
)
```

Each call returns a new immutable `RelationalQuerySet`. Nothing executes. Nothing touches a database. You're assembling a pipeline of operations.

## The proxy trick

That `lambda u: u.balance > 100` looks like it should return a boolean. It doesn't. Here's what actually happens:

1. The lambda receives an `EntityProxy[User]`, not a real `User`
2. `u.balance` creates a `FieldProxy("balance")` via `__getattr__`
3. `FieldProxy.__gt__(100)` builds `Gt(Field("balance"), Const(100))`

The lambda never runs against real data. It's a tiny DSL that constructs an expression AST. Python's operator overloading does the heavy lifting -- you write what looks like a predicate, and the proxy system captures it as a data structure.

This means the query system validates field names at build time. Write `u.balnce > 100` and you'll get an `AttributeError` immediately -- not a silent wrong result at query time.

## Queries are data

The key insight: every operation in the chain becomes a frozen dataclass in the `ops` tuple.

```python
for op in q.ops:
    print(op)
# Filter(expr=Eq(Field('active'), Const(True)))
# Filter(expr=Gt(Field('balance'), Const(100)))
# OrderBy(specs=(OrderSpec(field='balance', ascending=False),))
# Limit(count=50)
```

Because operations are data, you can serialize them, inspect them, store them, transmit them:

```python
from emergent.wire.axis.query._serialize import expr_to_dict, expr_repr

# Human-readable
for f in q.filters:
    print(expr_repr(f))
# active == True
# balance > 100

# JSON-serializable
for f in q.filters:
    print(expr_to_dict(f))
# {'op': 'eq', 'left': {'op': 'field', 'name': 'active'}, 'right': {'op': 'const', 'value': True}}
# {'op': 'gt', 'left': {'op': 'field', 'name': 'balance'}, 'right': {'op': 'const', 'value': 100}}
```

You can analyze queries before running them -- `expr_fields()` extracts all referenced field names, `expr_complexity()` counts AST nodes, `expr_depth()` measures nesting. Useful for query cost estimation, caching keys, or audit logs.

## Executing queries

A query without a provider is just a description. To get results, hand it to a provider:

```python
results = await provider.fetch_many(q)
count = await provider.count(q)
exists = await provider.exists(q)
first = await provider.fetch_one(q)
```

Where does `provider` come from? That's the next chapter. The point here is separation: the query describes *what*, the provider handles *where* and *how*.

## Beyond filtering

The relational query language covers more than `filter`. Pagination with `.limit()` and `.offset()`, or the convenience `.paginate(page=2, per_page=50)`. Projection with `.select(lambda u: u.name, lambda u: u.email)`. Deduplication with `.distinct()`. Joins, grouping, aggregation -- the full relational vocabulary, all as composable data.

## KV queries: a different space

Not everything is relational. Sometimes you have keys and values -- sessions, caches, feature flags. The KV query space has its own vocabulary:

```python
from emergent.wire.axis.query import kv

sessions = kv(Session, key=lambda s: s.session_id)

# Point lookups
q = sessions.get("abc-123")
q = sessions.exists("abc-123")

# Mutations
q = sessions.set("abc-123", session)
q = sessions.delete("abc-123")

# Pattern scanning
q = sessions.scan("user:*")
```

Same principle -- queries are data, providers execute them -- but a completely different operation set. Relational queries filter rows. KV queries look up keys. Each query space speaks its own language, matched to its domain.

## The defunctionalization payoff

This is the emergent pattern showing through. Queries are *defunctionalized* -- behavior encoded as data, not as opaque function closures. The same `Filter(Gt(Field("balance"), Const(100)))` operation knows how to compile itself to multiple backends:

- `compile_memory_query()` filters a Python list
- `compile_sa_query()` emits a SQLAlchemy `WHERE` clause
- `compile_http_api()` adds query parameters to a URL

One query, many backends. No adapter layer, no translation code. The operation carries its own compilation logic as methods on a frozen dataclass. Write the query once. Run it anywhere.

---

**Next:** [Where Queries Run →](16-providers.md)
