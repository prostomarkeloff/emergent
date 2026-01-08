# Compositional Architecture

> Write nodes. Compose commands. Let the graph optimize.

---

## 1. Building Blocks

Nodes are atomic, pure, testable units:

```python
# _user.py — User data nodes
@G.node
class ProfileNode:
    async def __compose__(cls, cart: CartNode, repo: UserRepo) -> Self:
        return cls(await repo.get_profile(cart.user_id))

@G.node
class LoyaltyNode:
    async def __compose__(cls, cart: CartNode, repo: UserRepo) -> Self:
        return cls(await repo.get_loyalty(cart.user_id))

@G.node
class AddressNode:
    async def __compose__(cls, cart: CartNode, repo: UserRepo) -> Self:
        return cls(await repo.get_address(cart.user_id))
```

```python
# _items.py — Parallel item fetching
@G.node
class ItemsDataNode:
    async def __compose__(cls, cart: CartNode, catalog: CatalogRepo) -> Self:
        # combinators.traverse_par → parallel with fail-fast
        items = await C.traverse_par(cart.items, catalog.get_item_data)()
        return cls(items.unwrap())
```

```python
# _saga.py — Transactional operations
@G.node
class CheckoutSagaNode:
    async def __compose__(cls, ..., inventory: InventoryRepo, payment: PaymentGateway) -> Self:
        saga = (
            S.step(inventory.reserve(...), compensate=inventory.release)
            .then(S.step(payment.authorize(...), compensate=payment.void))
        )
        result = await S.run(saga)
        return cls(result.unwrap())  # Auto-rollback on failure
```

---

## 2. Compositions

Commands are compositions of building blocks:

```
┌─────────────────────────────────────────────────────────────────────────┐
│  COMMAND          COMPOSITION                                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  user 1           ProfileNode ─┬─▶ UserInfoNode                         │
│                   LoyaltyNode ─┤                                         │
│                   AddressNode ─┘                                         │
│                                                                          │
│  shipping 1 ...   AddressNode ─┬─▶ ShippingEstimateNode                 │
│                   ItemsNode   ─┘                                         │
│                                                                          │
│  preview 1 ...    ProfileNode ─┬─▶ SubtotalNode ─┬─▶ PreviewNode        │
│                   LoyaltyNode ─┤   TaxNode      ─┤                       │
│                   ItemsNode   ─┘   GrandTotal   ─┘                       │
│                                                                          │
│  checkout 1 ...   ProfileNode ─┬─▶ FraudCheck ─▶ SagaNode ─▶ OrderNode │
│                   LoyaltyNode ─┤                                         │
│                   ItemsNode   ─┤   (inventory + payment                  │
│                   TaxNode     ─┘    with rollback)                       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

In code:

```python
# _userinfo.py — Composes user nodes
@G.node
class UserInfoNode:
    async def __compose__(
        cls,
        profile: ProfileNode,   # ← Runs in parallel
        loyalty: LoyaltyNode,   # ← Runs in parallel
        address: AddressNode,   # ← Runs in parallel
    ) -> Self:
        return cls(UserInfo(profile.data, loyalty.data, address.data))
```

```python
# _order.py — Full checkout composition
@G.node
class CreateOrderNode:
    async def __compose__(
        cls,
        profile: ProfileNode,
        loyalty: LoyaltyNode,
        items: ItemsDataNode,
        tax: TaxNode,
        fraud: FraudCheckNode,
        saga: CheckoutSagaNode,  # ← Saga with rollback
    ) -> Self:
        return cls(Order(...))
    
    @classmethod
    async def execute(cls, cart: Cart) -> Result[Order, CheckoutError]:
        """Entry point — graph resolves everything."""
        return await G.run(cls, CartNode(cart))
```

---

## 3. Entry Points

All entry points call the same compositions:

```python
# routes/checkout.py — HTTP
@router.post("/checkout")
async def checkout(cart: CartRequest, repo: UserRepo, payment: PaymentGateway):
    return await CreateOrderNode.execute(cart.to_domain())

@router.post("/user/{user_id}")
async def get_user(user_id: int, repo: UserRepo):
    return await UserInfoNode.execute(UserId(user_id))
```

```python
# worker/main.py — Background jobs
async def process(task: Task) -> None:
    match task.task_type:
        case "refund":
            await RefundSagaNode.execute(task.payload)  # Same nodes!
```

```python
# cli.py — Interactive
match cmd:
    case "user":     await UserInfoNode.execute(...)
    case "checkout": await CreateOrderNode.execute(...)
```

**Same nodes. Same graphs. Different entry points.**

---

## 4. Emergent Properties

Properties that arise from composition:

### Parallelization

```python
# Graph sees:
#   ProfileNode ─┐
#   LoyaltyNode ─┼─▶ UserInfoNode
#   AddressNode ─┘
#
# Automatically runs all 3 in parallel.
```

### Caching

```python
profile_cache = C.cache(key=lambda u: f"user:{u}", fetch=repo.get_profile)
    .tier(C.LocalTier(ttl=300))
    .build()

# ProfileNode uses cache → shared across all compositions
# "user 1" caches → "checkout 1" gets cache hit
```

### Saga Rollback

```python
# If payment fails after inventory reserved:
#
#   reserve(LAPTOP) ✓
#   reserve(CABLE)  ✓
#   authorize()     ✗ DECLINED
#   → release(CABLE)  ← automatic
#   → release(LAPTOP) ← automatic
```

---

## 5. Production Stack

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   FastAPI    │────▶│   Postgres   │◀────│   Worker     │
└──────────────┘     └──────────────┘     └──────────────┘
        │                   │                    │
        └───────── Same emergent.graph ──────────┘
```

### Queue (SQLAlchemy)

```python
import sqlalchemy as sa

task_queue = sa.Table("task_queue", metadata,
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("task_type", sa.String),
    sa.Column("payload", sa.JSON),
    sa.Column("status", sa.String, default="pending"),
)

class TaskQueue:
    async def claim_next(self) -> Task | None:
        subq = sa.select(task_queue.c.id).where(...).with_for_update(skip_locked=True)
        return await self.conn.execute(sa.update(task_queue).where(...).returning(...))
```

### Enqueue as Node

```python
@G.node
class EnqueueEmailNode:
    async def __compose__(cls, order: CreateOrderNode, queue: TaskQueue) -> Self:
        task_id = await queue.enqueue("email", {"order_id": order.id})
        return cls(task_id)
```

---

## 6. File Structure

```
nodes/
├── _user.py        ProfileNode, LoyaltyNode, AddressNode
├── _items.py       ItemsDataNode (parallel)
├── _totals.py      SubtotalNode, TaxNode, GrandTotalNode
├── _fraud.py       FraudCheckNode
├── _saga.py        CheckoutSagaNode (inventory + payment)
├── _order.py       CreateOrderNode
│
└── COMPOSED VIEWS
    ├── _userinfo.py    UserInfoNode = Profile + Loyalty + Address
    ├── _preview.py     PreviewNode = Totals without saga
    └── _shipping.py    ShippingEstimateNode = Address + Items
```

---

## 7. The Point

| Imperative | Compositional |
|------------|---------------|
| Copy-paste logic | Compose nodes |
| Manual parallelization | Automatic from graph |
| try/except rollback | Saga pattern |
| Cache scattered | Cache in nodes |
| Test the monolith | Test each node |

```
┌──────────────────────────────────────────────────────┐
│                                                       │
│   Nodes are LEGO blocks.                             │
│   Commands are assembled models.                     │
│   Graph is the instruction manual.                   │
│                                                       │
│   Build once. Compose infinitely.                    │
│                                                       │
└──────────────────────────────────────────────────────┘
```

---

## Running

```bash
cd emergent && uv run python -m examples.full_stack.main
```
