# Where Queries Run

You've built a beautiful query -- filtered, ordered, paginated, serializable. It sits there, a frozen tuple of operations, describing exactly what you want.

Now what? A description doesn't fetch rows. Something has to take that `RelationalQuerySet` and actually produce results. That something is a provider.

---

## The provider protocol

A provider is anything that implements a small set of async methods:

```python
@runtime_checkable
class RelationalProvider(Protocol[T]):
    async def fetch_one(self, query: RelationalQuerySet[T]) -> T | None: ...
    async def fetch_many(self, query: RelationalQuerySet[T]) -> list[T]: ...
    async def count(self, query: RelationalQuerySet[T]) -> int: ...
    async def exists(self, query: RelationalQuerySet[T]) -> bool: ...
    async def aggregate(self, query: RelationalQuerySet[T]) -> dict[str, Any]: ...
```

Five methods. That's the read side. If you need writes, there's `MutatingRelationalProvider`:

```python
class MutatingRelationalProvider(RelationalProvider[T], Protocol[T]):
    async def insert(self, entity: T) -> T: ...
    async def update(self, entity: T) -> T: ...
    async def delete(self, entity: T) -> None: ...
    async def delete_where(self, query: RelationalQuerySet[T]) -> int: ...
    async def insert_many(self, entities: Sequence[T]) -> list[T]: ...
    async def upsert(self, entity: T) -> T: ...
```

The protocol is deliberately minimal. You're not inheriting from a base class. You're not registering with a framework. If your object has the right methods with the right signatures, it's a provider. Duck typing at its finest.

## The memory provider

For prototyping and tests, you don't want a database. You want something that works immediately, holds data in a list, and behaves correctly.

```python
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
from emergent.wire.axis.query import relational

provider = MemoryRelationalProvider[User](
    key_fn=lambda u: u.id,
)

# Seed some data
await provider.insert(User(id=1, name="Alice", active=True, balance=250.0))
await provider.insert(User(id=2, name="Bob", active=True, balance=50.0))
await provider.insert(User(id=3, name="Carol", active=False, balance=300.0))

# Query it
users = relational(User)
q = users.filter(lambda u: u.active == True).order_by(lambda u: u.balance.desc())

results = await provider.fetch_many(q)
# [User(id=1, name='Alice', ...), User(id=2, name='Bob', ...)]
```

Under the hood, `MemoryRelationalProvider` does something elegant. It takes the query's `ops` tuple, creates a `MemoryQueryContext` wrapping a copy of its data list, and folds the ops through it. Each op's `compile_memory_query()` method transforms the context -- `Filter` removes non-matching items, `OrderBy` sorts, `Limit` slices. The fold produces the final filtered, sorted, paginated list.

No SQL parsing. No query planning. Just a Python list getting transformed by a sequence of data operations.

## Atomic transactions

The memory provider supports serialized access for concurrent scenarios:

```python
async with provider.atomic():
    balance = await provider.fetch_one(
        users.filter(lambda u: u.id == 1)
    )
    # ... compute new balance ...
    await provider.update(updated_user)
```

The `atomic()` context manager acquires an `asyncio.Lock`, ensuring that no other coroutine interleaves operations mid-transaction.

## Explaining queries before running them

Sometimes you want to know what a query *will do* before it touches any data. The explain system gives you structured introspection:

```python
from emergent.wire.axis.query._explain import format_ops, RELATIONAL_EXPLAIN

q = (
    users
    .filter(lambda u: u.active == True)
    .order_by(lambda u: u.name)
    .limit(10)
)

print(format_ops(q.ops, RELATIONAL_EXPLAIN))
#   1. Filter: expr=active == True, fields=active
#   2. OrderBy: specs=name ASC
#   3. Limit: count=10
```

Each op type has an explain handler that produces a structured dict. `format_ops` renders those dicts as human-readable text. The explain system is open-world -- add a handler for your custom op type and it folds in seamlessly.

For programmatic analysis, use `explain_ops()` directly to get the raw dicts instead of formatted text.

## ID generation

Providers often need to assign IDs to new entities. Instead of hardcoding auto-increment or UUIDs, identity generation is pluggable:

```python
from emergent.wire.axis.query import SequenceNextId, UuidNextId, PrefixedNextId

# Sequential integers: 1, 2, 3, ...
provider = MemoryRelationalProvider[User](next_id=SequenceNextId())

# UUIDs
provider = MemoryRelationalProvider[User](next_id=UuidNextId())

# Prefixed: "usr_1", "usr_2", ...
provider = MemoryRelationalProvider[User](
    next_id=PrefixedNextId("usr_", SequenceNextId()),
)

new_id = await provider.next_id()
user = User(id=new_id, name="Dave", active=True, balance=0.0)
await provider.insert(user)
```

`NextId` is a protocol. `SequenceNextId` implements it with a thread-safe counter. `UuidNextId` generates UUID4 strings. `PrefixedNextId` wraps any other `NextId` and prepends a string. Compose them freely.

## Capability markers

Not every provider can do everything. SQL can join tables; a memory list cannot. SQL can run window functions; an in-memory filter loop has no concept of `ROW_NUMBER()`. Rather than failing at runtime with cryptic errors, the type system expresses this:

```python
class JoinCapability(Protocol): ...
class AggregateCapability(Protocol): ...
class TransactionCapability(Protocol): ...
class WindowCapability(Protocol): ...
```

These are type-level markers. A SQLAlchemy provider implements `JoinCapability`; the memory provider does not. Static analysis tools can catch mismatches before your code runs. At the boundary between "what a query asks for" and "what a provider supports," these markers make the contract explicit.

## Building your own provider

The protocol is the contract. Implement the methods, and you have a working backend. A Redis provider, a REST API wrapper, an Elasticsearch adapter -- whatever your storage speaks, the query ops don't care. They compile themselves. Your provider just orchestrates the compilation context and returns results.

The memory provider is about 100 lines of actual logic. The fold does the work. The provider just sets up the context and calls fold. That's the architectural leverage: query ops carry their own compilation, so providers stay thin.

---

**Next:** [The Engine Room →](17-ops-and-runners.md)
