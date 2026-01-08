# Philosophy

`emergent` is the top layer of a functional stack for Python backends.

---

## The Core Insight

Traditional programs are **instructions**:

```python
profile = await get_profile(user_id)
loyalty = await get_loyalty(user_id)  # Waits for profile to finish
items = [await get_item(i) for i in cart.items]  # Sequential
```

`emergent` programs are **topologies**:

```python
@G.node
class ProfileNode:
    @classmethod
    async def __compose__(cls, cart: CartNode) -> ProfileNode: ...

@G.node
class LoyaltyNode:
    @classmethod
    async def __compose__(cls, cart: CartNode) -> LoyaltyNode: ...

@G.node
class CheckoutNode:
    @classmethod
    async def __compose__(
        cls,
        profile: ProfileNode,   # ┐
        loyalty: LoyaltyNode,   # ┘ Framework knows: no dependency → parallel
    ) -> CheckoutNode: ...
```

You declare **what depends on what**. The framework figures out **how to execute**.

---

## The Tower

```
Level 6: YOUR CODE      — business logic, domain invariants
Level 5: emergent       — domain patterns (saga, cache, graph)
Level 4: nodnod         — programs as dependency graphs
Level 3: combinators.py — resilience (retry, timeout, fallback)
Level 2: kungfu         — explicit errors (Result[T, E])
Level 1: Python 3.13    — type foundations
```

Each layer builds on the previous. Each can be used independently.

**Level 6 is YOUR code** — services, tasks, business rules. You compose nodes into workflows. You define invariants. You don't touch retry logic or compensators or parallelization. Those live below.

**nodnod** is the key layer. It transforms:
- Types → Graph nodes
- Signatures → Graph edges
- Resolution → Automatic parallelization

---

## Three Principles

### 1. Composition Over Configuration

```python
# Configuration (hidden in decorators, middleware, config files)
@retry(times=3)
@cache(ttl=300)
@trace("get_user")
async def get_user(user_id): ...

# Composition (explicit in node structure)
@G.node
class UserNode:
    @classmethod
    async def __compose__(cls, cart: CartNode, cache: UserCache) -> UserNode:
        # Cache: explicit
        result = await cache.get(cart.user_id)
        return cls(result.unwrap().value)
```

Decorators are fixed. Nodes compose infinitely.

### 2. Locality

Every piece of logic should be understandable by reading that piece alone.

**No globals. No singletons. No implicit context.**

```python
# Hidden dependencies (bad)
async def checkout():
    user = current_user.get()  # Where does this come from?
    db = get_db()              # Magic singleton?

# Explicit dependencies (good)
@G.node
class CheckoutNode:
    @classmethod
    async def __compose__(cls, user: UserNode, db: DatabaseNode) -> CheckoutNode:
        # Everything is in the signature
        ...
```

If you see a function, you know exactly what it needs.

### 3. Explicit Boundaries

System boundaries are where clean code meets chaos: databases, APIs, queues.

`emergent` patterns for boundaries:

| Boundary | Pattern | Module |
|----------|---------|--------|
| Multi-service transactions | Saga with compensation | `saga` |
| Latency vs freshness | Multi-tier caching | `cache` |
| Complex dependencies | Computation graphs | `graph` |

---

## The Graph Abstraction

Everything is a graph:

```
nodnod:     DI Graph         (nodes = components, edges = deps)
Flow:       Computation Graph (nodes = ops, edges = sequence)
Saga:       Transaction Graph (nodes = steps, edges = compensate)
Cache:      Tier Graph        (nodes = tiers, edges = fallback)
```

**Insight**: All complex systems are graphs. DSLs are ways to build and analyze graphs. Compilers execute graphs on specific runtimes.

---

## LLMs and Constrained Grammars

LLMs hallucinate when code hides failure modes. They guess—and guess wrong.

This stack constrains the grammar:

```python
# LLM sees explicit types
async def fetch_user(uid: int) -> Result[User, DBError | TimeoutError]: ...

# LLM generates correct handling
match await fetch_user(42):
    case Ok(user): return user
    case Error(DBError()): return fallback()
    case Error(TimeoutError()): retry()
```

The type system becomes a **constraint solver**. Pyright becomes a **fitness function**:

```
LLM generates → Pyright rejects → LLM fixes → Pyright accepts
```

Each iteration improves correctness. Patterns breed across the codebase.

---

## Juniors and LLMs

The paradox: declarative APIs look scary, then become liberating.

**Scary:**
```python
saga = S.step(reserve, release).then(lambda _: S.step(charge, refund))
```

**Liberating:**
```python
@G.node
class MyFeature:
    @classmethod
    async def __compose__(cls, user: UserNode, config: ConfigNode) -> MyFeature:
        # I just declare what I need
        return cls(...)
```

Why it works for juniors:
- **Locality**: read one function, understand it completely
- **No hidden state**: dependencies are in the signature
- **Type safety**: Pyright catches mistakes before runtime
- **Patterns**: same structure everywhere

Why it works for LLMs:
- **Constrained grammar**: fewer ways to be wrong
- **Type-driven**: signatures are specifications
- **Compositional**: add a node = add a parameter

**The stack separates concerns:**

| Role | Level | Does |
|------|-------|------|
| Platform engineers | 1-4 | Build foundations |
| Domain engineers | 5 | Build patterns (saga, cache) |
| App developers | 6 | Compose business logic |
| Juniors | 6 | Write nodes, compose services |
| LLMs | 5-6 | Generate patterns + logic |

Everyone works at their level. Nobody touches below.

---

## Why This Works

1. **Types as contracts**: Virtual nodes define WHAT, not HOW. Type system enforces correctness.

2. **Graphs as structure**: Dependencies = edges. Parallelism = topological analysis. Scheduling = graph traversal.

3. **Composition as mechanism**: Small graphs → big graphs. Same primitives at all scales.

4. **Deferred binding**: Virtual → Concrete at composition time. Same graph, different implementations.

---

## Summary

| Traditional | emergent |
|-------------|----------|
| Decorators, middleware | Nodes with `__compose__` |
| Globals, singletons | Explicit parameters |
| try/except, hope | saga, cache, graph |
| Hidden failures | Constrained grammar |
| Instructions | Topologies |

---

> "Constrain the grammar. Let correctness emerge."
