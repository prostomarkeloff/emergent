# Documentation

## The Paradigm

Traditional programs are **instructions** (do this, then that).

`emergent` programs are **topologies** (this depends on that).

```python
# Instructions (imperative)
profile = await get_profile(user_id)
loyalty = await get_loyalty(user_id)  # Waits for profile
items = await get_items(cart)         # Waits for loyalty

# Topology (declarative)
@G.node
class ProfileNode:
    @classmethod
    async def __compose__(cls, cart: CartNode) -> ProfileNode: ...

@G.node
class LoyaltyNode:
    @classmethod
    async def __compose__(cls, cart: CartNode) -> LoyaltyNode: ...

# Framework sees: no dependency between Profile and Loyalty → parallel
```

---

## The Tower

```
Level 6: YOUR CODE      → business logic, invariants
Level 5: emergent       → saga, cache, graph
Level 4: nodnod         → programs as dependency graphs
Level 3: combinators.py → retry, timeout, fallback
Level 2: kungfu         → Result[T, E]
Level 1: Python 3.13    → type foundations
```

Levels 1-5 are libraries. Level 6 is your code. Juniors write Level 6. LLMs generate Levels 5-6.

---

## Documents

| Document | Purpose |
|----------|---------|
| [Philosophy](philosophy.md) | Why programs should be graphs |
| [Guide](guide.md) | Build a checkout system step by step |
| [Reference](reference.md) | API for code generation |

---

## Quick Reference

### graph (topology)

```python
@G.node
class MyNode:
    @classmethod
    async def __compose__(cls, dep: OtherNode) -> MyNode:
        return cls(...)

result = await G.compose(MyNode, input)
```

### saga (transactions)

```python
saga = S.step(action, compensate).then(lambda _: S.step(action2, compensate2))
result = await S.run_chain(saga)
```

### cache (latency)

```python
cache = C.cache(key_fn, fetch_fn).tier(C.LocalTier()).build()
result = await cache.get(key)
```

---

## Examples

```bash
uv run python -m examples.saga_example
uv run python -m examples.cache_example
uv run python -m examples.graph_example
uv run python -m examples.full_stack.main
```
