# The Engine Room

You've been calling `runner.run(SomeOp(...))` for chapters now, and it just works. Operations go in, results come out. But something strange happened in the last project: you had two independent data fetches -- a price lookup and a stock check -- and even though you wrote them sequentially, your logs showed them running at the same time. Nobody called `asyncio.gather()`. Nobody wrote any concurrency code at all.

Time to open the hatch and climb down into the engine room.

---

## Ops are frozen data

An Op is not a function. It's a frozen dataclass that *describes* what you want to happen and what you expect back. The type parameters tell the story: `Op[T, E]` means "this operation produces a `T` on success or an `E` on failure."

```python
from dataclasses import dataclass
from emergent.ops import Op
from kungfu import Result, Ok

@dataclass(frozen=True, slots=True)
class GetPrice(Op[float, str]):
    product_id: int

@dataclass(frozen=True, slots=True)
class GetStock(Op[int, str]):
    product_id: int
```

`GetPrice` doesn't *do* anything. It doesn't know about databases or HTTP clients or caches. It's a piece of data that says: "I want the price for product 42, and I expect a `float` back or a `str` error." That's it. Behavior lives elsewhere.

## Handlers bring behavior

A handler is an async function that takes an Op and returns a `Result`. You register handlers with the builder:

```python
from emergent.ops import ops

async def get_price(req: GetPrice) -> Result[float, str]:
    # Imagine a database call here
    return Ok(29.99)

async def get_stock(req: GetStock) -> Result[int, str]:
    return Ok(42)

runner = ops().on(GetPrice, get_price).on(GetStock, get_stock).compile()
```

`ops()` creates a builder. `.on(OpType, handler)` registers a handler. `.compile()` seals the deal and returns a `Runner` -- the thing that actually executes operations.

The separation matters. The Op is the *what*. The handler is the *how*. The runner is the *when and where*. Three distinct concerns, three distinct objects.

## Dependencies -- where the magic lives

Here's where it gets interesting. What if one operation depends on the results of others?

```python
@dataclass(frozen=True, slots=True)
class BuildSummary(Op[str, str]):
    product_id: int
    price: GetPrice    # dependency
    stock: GetStock    # dependency
```

`BuildSummary` declares its dependencies right in the dataclass fields. It doesn't call `GetPrice` or `GetStock`. It doesn't await them. It just *mentions* them. The runner reads those fields, sees that `price` and `stock` are Op types, and draws the graph.

The handler receives the dependencies as parameters, already resolved:

```python
from kungfu import Error

async def build_summary(
    req: BuildSummary,
    price: GetPrice,    # nodnod resolves this -- cached Result
    stock: GetStock,    # nodnod resolves this -- cached Result
) -> Result[str, str]:
    p = await price  # instant -- already computed in parallel
    s = await stock  # instant -- already computed in parallel
    match (p, s):
        case (Ok(p_val), Ok(s_val)):
            return Ok(f"${p_val}, {s_val} in stock")
        case _:
            return Error("failed to build summary")
```

When you `await price` inside `build_summary`, it returns instantly. The result was already computed. nodnod -- the dependency graph engine underneath -- saw that `GetPrice` and `GetStock` are independent of each other, ran them concurrently, cached the results, and only then invoked `build_summary` with the cached values.

No `asyncio.gather()`. No manual task management. The parallelism comes from the *shape of the data*.

## Wiring it up

```python
runner = (
    ops()
    .on(GetPrice, get_price)
    .on(GetStock, get_stock)
    .on(BuildSummary, build_summary)
    .compile()
)

result = await runner.run(
    BuildSummary(
        product_id=1,
        price=GetPrice(product_id=1),
        stock=GetStock(product_id=1),
    )
)
```

When `runner.run()` fires, it walks the fields of `BuildSummary`, discovers the `GetPrice` and `GetStock` dependencies, collects their transitive dependencies (if any), builds a nodnod agent with all the required nodes, and executes. Independent nodes run in parallel. Dependent nodes wait for their inputs. The graph is implicit in the data; the execution is automatic.

## Result algebra

Every handler returns `Result[T, E]`. No exceptions for domain errors. If `GetPrice` fails, the caller sees an `Error(...)` value -- not a stack trace, not a 500 response, not a swallowed exception.

```python
match result:
    case Ok(summary):
        print(summary)  # "$29.99, 42 in stock"
    case Error(e):
        print(f"Failed: {e}")
```

Pattern matching on results is exhaustive. The type checker knows every branch. The happy path and the sad path have equal standing.

## Injecting shared dependencies

Handlers often need shared resources -- a database connection, a config object. The runner supports typed injection:

```python
runner = (
    ops()
    .on(GetPrice, get_price)
    .on(GetStock, get_stock)
    .on(BuildSummary, build_summary)
    .compile()
    .inject(Database, db)
)
```

Now any handler whose signature includes `db: Database` will receive it automatically. The injection is type-safe: the key is the type itself, not a string name.

## Why this design?

Ops are defunctionalized. Behavior is data. The runner doesn't need to understand your domain to parallelize it -- it just reads the dependency graph from the type structure. Add a new dependency field to an Op, and the parallelization adjusts. Remove one, and it adjusts again. No rewiring, no configuration, no "worker pool" tuning.

This is the engine room. Frozen dataclasses go in. Dependency graphs come out. Results flow back. Everything between is automatic.

---

**Next:** [Who Gets What, When ->](18-scope-and-di.md)
