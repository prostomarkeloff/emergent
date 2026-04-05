# 3. Modularity, Computations, and State

> Mεταβάλλον ἀναπαύεται
> (Even while it changes, it stands still.)
> — Heraclitus

> Plus ça change, plus c'est la même chose.
> — Alphonse Karr

---

## 3.1 Assignment and the Cost of State

We ordinarily view the world as populated by independent objects, each of which has a state that changes over time. A bank account has state in that the answer to "Can I withdraw $100?" depends upon the history of deposit and withdrawal transactions. A distributed agent has state in that its next action depends upon all events it has observed. A worker has state in that it knows which task it is currently processing.

The two preceding chapters avoided this problem entirely. Capabilities are frozen. Contexts are frozen. fold is pure. The same capabilities, fed through the same fold, always produce the same result. This is the source of emergent's power — and, the reader might suspect, its limitation. Eventually, we must confront systems that *change*.

SICP confronts this in its own Chapter 3 with an example so simple it devastates. We will begin with the same example, translated to Python.

### 3.1.1 Local State Variables

Consider a bank account with $100. We model withdrawal as a function:

```python
balance = 100

def withdraw(amount):
    global balance
    if balance >= amount:
        balance = balance - amount
        return balance
    return "Insufficient funds"
```

```
>>> withdraw(25)
75
>>> withdraw(25)
50
>>> withdraw(60)
'Insufficient funds'
>>> withdraw(15)
35
```

The expression `withdraw(25)`, evaluated twice, yields different values. This is a new kind of behavior. Until now, every function we have encountered was a mathematical function: same inputs, same output. Now a function has *memory*. It has *time*.

SICP motivates assignment honestly: it gives modularity. The bank account encapsulates its state. You can use `withdraw` without knowing its internals. You can model the account as a self-contained object. This is real power. But it comes at a price.

### 3.1.2 The Substitution Model Breaks

In Chapter 1, we introduced the fold model: capabilities fold into contexts via pure function application. The reader can trace any fold by hand — replace `ctx` with the result of each step, substituting values for names. This is the *substitution model*, and it always works because capabilities are frozen and `replace()` returns new objects.

Now consider what happens when we try to analyze `withdraw(25)` by substitution.

SICP provides a devastating demonstration. Consider a simplified withdrawal procedure:

```python
def make_simplified_withdraw(balance):
    def withdraw(amount):
        nonlocal balance
        balance = balance - amount
        return balance
    return withdraw

W = make_simplified_withdraw(25)
W(20)  # => 5
W(10)  # => -5
```

Compare with a pure decrementer:

```python
def make_decrementer(balance):
    def decrement(amount):
        return balance - amount
    return decrement

D = make_decrementer(25)
D(20)  # => 5
D(10)  # => 15
```

We can analyze `make_decrementer(25)(20)` by substitution: substitute 25 for `balance`, get `lambda amount: 25 - amount`. Apply to 20: `25 - 20 = 5`. Correct.

Now try `make_simplified_withdraw(25)(20)` by substitution. Substitute 25 for `balance` in the body. We get a function that sets `balance` to `25 - amount` and returns `balance`. Substitute 20 for `amount`: "set balance to 5, return balance." But which `balance`? The one before the assignment (25) or after (5)? Substitution cannot distinguish them. It predicts the result is 25. The actual result is 5. **The substitution model gives the wrong answer.**

SICP: "The trouble here is that substitution is based ultimately on the notion that the symbols in our language are essentially names for values. But as soon as we introduce `set!` and the idea that the value of a variable can change, a variable can no longer be simply a name. Now a variable somehow refers to a *place* where a value can be stored, and the value stored at this place can change."

Names become places. Values become time-dependent. The substitution model — the reader's mental tool for understanding evaluation — breaks.

SICP's response is the *environment model*: frames, bindings, enclosing environments. A new, more complex, less intuitive framework replaces substitution.

### 3.1.3 Sameness and Change

The damage goes deeper than the computational model. Assignment entangles identity with time.

```python
D1 = make_decrementer(25)
D2 = make_decrementer(25)
```

Are `D1` and `D2` the same? Yes. Each is a function that subtracts its input from 25. `D1` can substitute for `D2` anywhere without changing the result.

```python
W1 = make_simplified_withdraw(25)
W2 = make_simplified_withdraw(25)
```

Are `W1` and `W2` the same? No. `W1(20)` returns 5 and changes `W1`'s internal state. `W2(20)` also returns 5 but changes `W2`'s state independently. After the call, `W1(20)` returns -15, but `W2(20)` returns 5. They were created by the same expression. They have different futures.

SICP: "We cannot determine 'change' without some a priori notion of 'sameness,' and we cannot determine sameness without observing the effects of change."

This is circular. Assignment makes identity a philosophical problem. And the problem is not merely philosophical — it has engineering consequences. When Peter and Paul share a bank account:

```python
peter_acc = make_account(100)
paul_acc = peter_acc  # same object
```

Every withdrawal by Peter changes Paul's balance. If we search for all code that can change `paul_acc`, we must also search for all code that touches `peter_acc`. In a large system, this search is unbounded. Encapsulation does not help — it organizes the mutation but does not eliminate it.

A language that supports "equals can be substituted for equals" without changing the result is called *referentially transparent*. Assignment destroys referential transparency. And referential transparency is what made the fold model work in Chapters 1 and 2 — it is what allowed us to trace compilation by hand, to predict results, to reason about combinations.

### 3.1.4 The Concurrency Catastrophe

The single-threaded cost of assignment is bad enough. But the real disaster emerges when time becomes literal.

Peter and Paul withdraw from a joint account concurrently. Balance starts at 100. Peter withdraws 10, Paul withdraws 25.

```python
# Thread 1 (Peter)              # Thread 2 (Paul)
temp = balance        # 100
                                 temp = balance        # 100
balance = temp - 10   # 90
                                 balance = temp - 25   # 75
```

Final balance: 75. Expected: 65. Peter's withdrawal vanished. Money was created from nothing.

The problem: `balance = balance - amount` is three operations — read, compute, write — and another thread can interleave between any two. SICP calls this the *serialization* problem and proposes serializers: explicit locks that force operations to execute atomically.

But serializers introduce deadlock. Process A holds lock 1 and waits for lock 2. Process B holds lock 2 and waits for lock 1. Neither can proceed. The cure is a disease.

But what if Peter and Paul both *append* instead of modifying?

```python
# Peter:                           Paul:
await put(log, Withdrawal("joint", 10))
                                   await put(log, Withdrawal("joint", 25))
```

Both appends succeed. The Log now contains `[Deposit("joint", 100), Withdrawal("joint", 10), Withdrawal("joint", 25)]`. Balance = 100 - 10 - 25 = 65. Correct. The order of the two appends does not matter — addition is commutative. No interleaving corruption. No lock. We will develop this fully in 3.2, but note the structural difference: *append does not depend on current contents*.

SICP: "The central issue lurking beneath the complexity of state, sameness, and change is that by introducing assignment we are forced to admit *time* into our computational models."

### 3.1.5 The Frozen Advantage

Now consider emergent. For two chapters, every value has been frozen. `MaxLen(255) == MaxLen(255)` is True — always, everywhere, regardless of when you check. Two `PydanticContext` objects with the same fields are equal. There is no identity crisis: equality is structural, not temporal.

The fold model does not break because there is no assignment. `ctx = getattr(item, method)(ctx)` looks like assignment, but it is not. It is *rebinding*: `method(ctx)` returns a *new* frozen context. The old `ctx` is untouched. This is `let` in a functional language, not `set!` in an imperative one. The fold loop:

```python
ctx = initial
for item in items:
    if isinstance(item, protocol):
        ctx = getattr(item, method)(ctx)
```

Each step is a pure function: `(item, ctx_old) -> ctx_new`. The loop is a catamorphism — guaranteed termination, referentially transparent, analyzable by substitution. The fold model from Chapter 1 survives unchanged.

SICP must abandon its substitution model at Chapter 3, replacing it with the more complex environment model. We do not. The fold model needs no revision. This is the architectural dividend of frozen data: the model that the reader learned in Chapter 1 remains valid through the rest of this book.

But the world still changes. Users sign up. Workers die. Markets move. If we cannot use assignment, how do we model change?

The key idea comes not from programming languages but from accounting.

---

## 3.2 The Log Model of Computation

Helland (2015), in "Immutability Changes Everything," makes an observation so simple it is easy to miss:

> "Accountants don't use erasers or they go to jail."

All entries in a ledger remain. Corrections are new entries. Observed facts — a debit, a credit — are recorded. Derived facts — the current balance — are calculated from observations.

> "The truth is the log. The database is a cache of a subset of the log."

Transaction logs record all changes made to a database. The database contents are a materialized view of the log — the latest value of each record. If the database is destroyed, it can be reconstructed from the log. The database is not the truth; the log is.

In theworld, we take this literally. The Log is the sole state primitive. It is append-only. Events, once written, cannot be modified or deleted. Computations do not have state variables — they have a *view* of the Log, obtained through a *Lens*.

### 3.2.1 A Bank Account Without Assignment

Let us rebuild the bank account using the Log model. Instead of a mutable `balance` variable, we record transactions as events:

```python
@dataclass(frozen=True, slots=True)
class Deposit:
    account: Annotated[str, Identity]
    amount: float

@dataclass(frozen=True, slots=True)
class Withdrawal:
    account: Annotated[str, Identity]
    amount: float
```

Events carry their own identity via the `Identity` annotation.

To operate the account:

```python
log = InMemoryLog()

await put(log, Deposit(account="alice", amount=100))
await put(log, Withdrawal(account="alice", amount=25))
await put(log, Withdrawal(account="alice", amount=25))
```

The balance is not stored. It is derived:

```python
deposits = await log.query(Lens().of_type(Deposit).of_identity("alice"))
withdrawals = await log.query(Lens().of_type(Withdrawal).of_identity("alice"))
balance = (
    sum(e.data.amount for e in deposits)
    - sum(e.data.amount for e in withdrawals)
)
# balance = 100 - 25 - 25 = 50
```

Now evaluate the same query twice:

```python
balance_1 = compute_balance(log, "alice")  # 50
balance_2 = compute_balance(log, "alice")  # 50
```

Same Log, same Lens, same result. The query is referentially transparent. The "state" of the account is not a mutable variable but the result of a pure function applied to immutable data.

What happened to `withdraw(25)` returning 75, then 50? In the Log model, the two withdrawals are two events — `Withdrawal(amount=25)` appended at two different positions. They do not overwrite each other. They coexist. The balance is derived from *all* events, not read from a variable. The expression `compute_balance(log, "alice")` returns the same result every time it is called with the same Log. If the Log grows — if a new `Withdrawal` is appended — the next call returns a different result. But the Log that was queried did not change. It grew.

This is the distinction that resolves SICP's bank-account problem. The balance does not change from 100 to 75. Rather, a `Withdrawal` event is appended, and the *derived* balance — the fold of all events — is now 75. The old events remain. The old balance is still derivable from the sub-log before the withdrawal. Nothing was overwritten. Nothing was lost.

### 3.2.2 Events as Facts

An event is a dataclass carrying type and identity:

```python
@dataclass(frozen=True, slots=True)
class MarketTick:
    symbol: Annotated[str, Identity]
    price: float
    volume: int

@dataclass(frozen=True, slots=True)
class OrderPlaced:
    id: Annotated[str, Identity]
    symbol: str
    quantity: int
    side: str  # "buy" | "sell"
```

Events carry their type — `MarketTick`, `OrderPlaced` — used by `isinstance` dispatch. Events carry their identity via `Identity`-annotated fields. The Log indexes events by type and by identity: `Lens().of_type(MarketTick)` is O(1) type lookup. `Lens().of_type(MarketTick).of_identity("BTC")` filters by identity within the type bucket.

### 3.2.3 Lens as Observation

A Lens is not a filter. It is a *point of view*.

```python
# The trader sees: market ticks for BTC
trader_lens = Lens().of_type(MarketTick).of_identity("BTC")

# The risk manager sees: all orders above 1000 units
risk_lens = Lens().where(OrderPlaced, lambda o: o.quantity > 1000)

# The billing observer sees: all events since the billing period started
billing_lens = Lens().after(billing_period_start)
```

Each Lens op narrows the view. `of_type` selects by event data type. `of_identity` selects by the Identity-annotated field's value. `where` applies a predicate. `after` selects events after a cursor position. Ops compose by concatenation — `Lens(ops=self.ops + (op,))` — which means they AND together: each successive op narrows further.

Different Lenses on the same Log produce different views. The Log does not change. The observation does.

**This is the key insight of this chapter: state is not a property of the system. State is a property of the observation.**

Consider three computations sharing one Log:

```python
log = InMemoryLog()

await put(log, MarketTick(symbol="BTC", price=42000, volume=100))
await put(log, MarketTick(symbol="ETH", price=2800, volume=50))
await put(log, OrderPlaced(id="o1", symbol="BTC", quantity=5, side="buy"))
await put(log, MarketTick(symbol="BTC", price=42100, volume=80))
await put(log, OrderPlaced(id="o2", symbol="ETH", quantity=10, side="sell"))
```

The trader's Lens `Lens().of_type(MarketTick).of_identity("BTC")` returns two events: `[MarketTick(BTC, 42000), MarketTick(BTC, 42100)]`. The trader does not see ETH ticks. It does not see orders.

The risk manager's Lens `Lens().of_type(OrderPlaced)` returns two events: `[OrderPlaced(o1, BTC, 5, buy), OrderPlaced(o2, ETH, 10, sell)]`. Different events from the trader.

The billing observer's Lens `Lens()` (everything) returns all five events.

Same Log. Three Lenses. Three different derived states. When a new `MarketTick` arrives, the trader's derived state changes. The risk manager's does not. The billing observer's does. Nobody mutated anything. The Log grew by one event.

In a mutable system, "the state of the trader" is a variable inside the trader object. Changing it requires assignment. Testing it requires knowing the current value. Reasoning about it requires tracking all possible values.

In the Log model, "the state of the trader" is a function — `log.query(trader_lens)` — applied to immutable data. The function is pure. The Log is append-only. The result is deterministic: given the same Log and the same Lens, the result is always the same. Testing is easy: construct a Log with known events, query it, check the result.

This is what Moseley and Marks (2006) mean by separating essential state from accidental state. The essential state is the events — the facts about what happened. The accidental state — current balances, cached positions, aggregated metrics — is derived. The essential state is written once (append). The accidental state is computed on demand (query).

### 3.2.4 Computation as Existence

In SICP, a computational object "has state" if its behavior depends on its history. In theworld, a Computation does not *have* state. A Computation *observes* history.

```python
agent = life("trader",
    select.self(),                    # observe own events
    select.type(MarketTick),          # observe market data
    KellyCriterion(max_bet=0.2),      # decision capability
    flow.every(1.0),                  # run every second
)
```

The Computation is a tuple of capabilities — frozen data. Its identity is `"trader"`. Its behavior is determined by its capabilities, which fold into:
- A **Lens** (what it observes) — via `compile_perception()`
- An **action context** (what events it produces) — via `compile_action()`
- A **lifecycle context** (when it runs) — via `compile_lifecycle()`

The Computation itself does not change. The Log changes. The Computation's derived state — obtained by querying the Log through its Lens — changes as new events appear. But the Computation's *definition* — its capabilities — is immutable.

The Computation's cycle is a pure function:

```python
async def run(self, log):
    lens = self.compile_perception()           # fold capabilities → Lens
    perceived = await log.query(lens)          # read Log (no mutation)
    direct_events = self.compile_action(perceived)  # fold perceived → events
    return (*direct_events, *op_events)        # return, don't mutate
```

`compile_perception()` folds capabilities into a Lens:

```python
ctx = fold(self.capabilities, LensContext(lens=Lens(), identity=self.identity),
           LensCompilable, "compile_lens")
return ctx.lens
```

`compile_action()` folds perceived events into new events:

```python
ctx = fold(self.capabilities, ActionContext(identity=self.identity, perceived=perceived),
           ActionCompilable, "compile_action")
return ctx.pending_events
```

The Computation looks like an object — it has identity, its behavior depends on history, it interacts with other Computations. But it *is* a stream processor — it folds over immutable data and produces new immutable data.

**Exercise 3.1.** Build a Log-based bank account. Define `Deposit` and `Withdrawal` event types. Write `compute_balance(log, account_id)` as a fold over events. Then show: (a) two concurrent deposits to the same account always produce the correct total balance, and (b) the Log-based account does not suffer from the Peter/Paul interleaving problem described in 3.1.4. What does the Log model *cost* that the mutable model does not? (Hint: storage.)

**Exercise 3.2.** SICP's `make-decrementer` produces objects where `D1 == D2` (structurally identical, substitutable). SICP's `make-simplified-withdraw` produces objects where `W1 != W2` (different identities, different futures). In the Log model, two `Withdrawal` events with the same account and amount are structurally equal: `Withdrawal("alice", 25) == Withdrawal("alice", 25)`. But they occupy different positions in the Log and have different effects on the balance. Is this a problem? How does the Log model handle the distinction between "same event data" and "different event occurrence"?

---

## 3.3 Modeling with the Log

In a system composed of many computations, the computations communicate through the Log. There are no other channels. No RPC. No shared memory. No message-passing mailboxes. Only the Log.

### 3.3.1 Mortal Workers, Immortal Results

Three workers multiply a 1500x1500 matrix. Each worker lives 30 seconds, then crashes. Supervised restarts them. Four generations, twelve instances. Zero lost rows. Error = 0.00e+00 — mathematically exact.

This sounds impossible. In any conventional system — MapReduce, Spark, Celery — a coordinator tracks which tasks are assigned, which workers are alive, which tasks timed out. The coordinator is mutable state. The coordinator is a single point of failure. If the coordinator dies, you need a recovery protocol: distributed consensus (Raft, Paxos) or manual intervention.

There is no coordinator here. Workers decide for themselves.

**Setup:**

```python
world = World(log=log, computations=(
    scoped(
        Script(fn=lambda: mortal_worker(log, "w0", a, b_t)),
        Script(fn=lambda: mortal_worker(log, "w1", a, b_t)),
        Script(fn=lambda: mortal_worker(log, "w2", a, b_t)),
        Supervised(max_restarts=50, backoff=0.1),
    ),
    Script(fn=lambda: coordinator(log, n_chunks)),
))
```

`scoped(...)` creates a fold boundary: `Supervised` wraps only the workers inside the scope, not the coordinator outside it. This is the same isolation principle as lexical scoping in languages — modifiers see only what is in their scope.

**Step 1: World.run().**

```python
ctx = fold(self.computations, WorldContext(log=self.log),
           WorldCompilable, "compile_world")
```

`Scoped.compile_world` runs an inner fold: the three `Script` items each produce a node, `Supervised` wraps them with retry logic, the result merges back. The coordinator folds outside the scope, unwrapped. Result: four nodes — three supervised workers, one unsupervised coordinator.

**Step 2: The worker.**

```python
async def mortal_worker(log, name, a, b_t):
    deadline = time.monotonic() + 30  # mortal: dies after 30s
    while time.monotonic() < deadline:
        unclaimed = await _find_unclaimed(log)   # READ the Log
        if not unclaimed:
            break
        chunk = unclaimed[0]
        rows = compute_rows(chunk, a, b_t)       # PURE computation
        await put(log, RowResult(start=chunk.start, rows=rows))  # APPEND
    raise RuntimeError(f"{name} lifetime expired")  # DIE
```

`_find_unclaimed` queries the Log — nothing else:

```python
async def _find_unclaimed(log):
    done_starts = {r.data.start for r in await log.query(Lens().of_type(RowResult))}
    all_chunks = await log.query(Lens().of_type(RowChunk))
    return [c.data for c in all_chunks if c.data.start not in done_starts]
```

Two Lens queries. No mutable state. The worker's "knowledge" of what has been done comes entirely from the Log. The worker is a stateless function: query, compute, append.

Before reading on, predict: what happens when a worker dies?

**Step 3: Death and resurrection.**

Worker w0 raises `RuntimeError` after 30 seconds. `Supervised` catches it:

```python
async def supervised_compose(*args, **kwargs):
    restarts = 0
    while restarts < max_restarts:
        try:
            await original_compose(*args, **kwargs)
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            restarts += 1
            await asyncio.sleep(backoff * restarts)
```

A new instance of `mortal_worker` starts. It has no state from the previous generation — it is a fresh call to the same function. It calls `_find_unclaimed(log)` — queries the Log — sees which chunks are done — picks up unclaimed chunks. **The Log is the continuity.** The worker is disposable. The results are permanent.

**Step 4: The race that is not a race.**

Two workers take the same chunk simultaneously. Both compute the result. Both append `RowResult` to the Log. Two events for the same chunk exist in the Log.

Is this a problem? No. The computation is pure — same input, same output. Both results are identical. `_find_unclaimed` uses a set of done starts: `{r.data.start for r in ...}`. Duplicate `RowResult` for the same start = one entry in the set. The coordinator sees `len(done_starts) == 150` — all chunks done. The duplicate event is harmless redundancy. No serializer needed. No deadlock possible.

**Step 5: Mid-computation death.**

A worker begins computing a chunk but dies before emitting `RowResult`. The partial computation produces no event. The chunk stays unclaimed. The next generation picks it up. No partial results. No rollback. No cleanup protocol.

In Celery: task timeout, task marked as failed, retry policy, exponential backoff, configuration. In theworld: crash, Supervised restarts, query Log, continue. The Log is the retry mechanism.

**The result:**

```
4 generations. 12 worker instances. 0 lost rows. Error = 0.00e+00.
No coordination protocol. No locks. No serializers. No deadlock.
```

**Exercise 3.3.** The mortal workers handle duplicate computation by making it harmless (set dedup on read). Design a system where duplication is *not* harmless — a payment processing system where charging a customer twice is unacceptable. How would you prevent duplicate execution using only the Log? (Hint: before executing a payment, check the Log for an existing `PaymentExecuted` event with the same payment ID. What is the race window between the check and the append?)

**Exercise 3.4.** In the mortal workers, each generation is a fresh function call with no state from the previous generation. What if you wanted a worker to carry over *some* information — say, a count of how many chunks it has processed for performance reporting? Design this using the Log. The worker should not have mutable state; the count should be derived.

### 3.3.2 ViewSnapshot: Materialized Views in the Log

The coordinator observes progress by reading the Log:

```python
async def coordinator(log, n_chunks):
    state = ProgressState(done_starts=frozenset(), total=n_chunks)
    cursor = 0.0
    while len(state.done_starts) < n_chunks:
        events = await log.query(Lens().of_type(RowResult).after(cursor))
        for e in events:
            state = replace(state, done_starts=state.done_starts | {e.data.start})
        await put(log, ViewSnapshot(view_id="progress", state=state, cursor=cursor))
        cursor = log._clock
```

The coordinator folds new events into its state using `replace()` — frozen update, not mutation. It writes its state as a `ViewSnapshot` to the Log. The snapshot is an event, queryable through the same Lens mechanism as everything else.

If the coordinator crashes and restarts, it queries the last `ViewSnapshot`:

```python
snaps = await log.query(Lens().of_type(ViewSnapshot).of_identity("progress"))
if snaps:
    state = snaps[-1].data.state
    cursor = snaps[-1].data.cursor
```

O(delta) recovery, not O(all events). The dashboard — another computation or an external service — reads the same snapshot. It does not re-fold 150 `RowResult` events. It reads one event.

This pattern generalizes. Any derived state that is expensive to recompute can be written as a `ViewSnapshot` to the Log. The snapshot is persistent, typed, queryable, and compilable through emergent's wire.

### 3.3.3 Three Worlds, One Log

The cosmos.py example demonstrates the full scope. Three nested Worlds share one `InMemoryLog`:

```python
cosmos = World(log=log, computations=(
    Script(fn=lambda: run_swarm(log)),    # brute + heuristic workers
    Script(fn=lambda: run_api(log)),      # CRUD API via Log-HTTP
    Script(fn=lambda: oracle(log)),       # observer + Log-HTTP client
))
```

The swarm World runs two worker Computations: "brute" (brute-force SHA-256) and "heuristic" (hash-based shortcut). Both observe `Task` events, emit `Solution` events.

The API World compiles a `TaskItem` dataclass through emergent's `wire.derive` to produce CRUD endpoints. But the API does not bind a TCP port. It binds an *address* in the Log. HTTP requests are events. Responses are events. This is HTTP as a Log pattern.

The oracle queries everything. It reads Solutions through Lens, reads World lifecycle events, sends HTTP requests through the Log.

All three Worlds see the same Log. Each sees different events through different Lenses. The swarm sees Tasks. The API sees HTTP requests at its address. The oracle sees everything.

### 3.3.4 Tiered Storage

Not all events deserve the same storage backend. LLM responses must survive process restarts — they represent work done and money spent. Intermediate thinking steps are ephemeral — useful for debugging, expensive to persist.

`TieredLog` routes events to different backends by tier:

```python
from theworld import TieredLog, TierBinding, Durable, Ephemeral, InMemoryLog
from theworld.sqlite_log import open_multi_log

sqlite = await open_multi_log("agent.db")
memory = InMemoryLog()

log = TieredLog(
    TierBinding(Durable, sqlite),    # persists across restarts
    TierBinding(Ephemeral, memory),  # fast, volatile
)
```

Writing: `await put(log, response, tier=Durable)` routes to SQLite. `await put(log, thinking_step, tier=Ephemeral)` routes to memory. Reading: `Lens().tier(Durable)` queries the SQLite backend only. `Lens()` without a tier filter merges all backends.

`TieredLog` *is* a Log — same protocol (query, append). It compiles through the same Lens mechanism as `InMemoryLog`. The storage tier is a property of the write operation, not of the event. The Lens determines which tier to read from. Storage is infrastructure; the computation model does not change.

But here we must be honest about a trade-off. The Log grows without bound. SICP's `set!` mutates in constant space — the old value is destroyed, and the variable occupies the same memory regardless of how many times it is changed. The Log preserves every event. For the mortal workers, this means 150 `RowResult` events remain in the Log after the computation completes. For a payment system running for years, the Log would grow to billions of events.

Helland frames this clearly: "Append-only using more disk is an engineering choice. Losing history by overwriting is a semantic choice." The Log trades storage for history, replay, fault tolerance, and referential transparency. `TieredLog` manages the trade-off through tiering — hot events in memory, cold events in SQLite or Kafka, ancient events compacted or archived. But the fundamental choice — accumulate vs. overwrite — is a design decision with real costs.

**Exercise 3.5.** Design a `compact` operation on the Log that removes events older than a given cursor, replacing them with a `ViewSnapshot` that summarizes the removed events. What invariants must the snapshot preserve? Which computations would produce different results after compaction? Is there a class of computations for which compaction is guaranteed safe?

**Exercise 3.6.** Helland: "The truth is the log. The database is a cache of a subset of the log." Design a caching layer for theworld that maintains an in-memory index of the latest event per identity-type pair (like a key-value store). Show that the cache can be reconstructed from the Log at any time. What happens when the cache is stale? What is the relationship between this cache and `ViewSnapshot`?

### 3.3.5 Budget as Log Projection

A budget is not a counter to be incremented atomically. A budget is a *fold over resource usage events*.

Consider an API with a rate limit: 3 requests per minute. Multiple workers compete for slots. Mutable approaches (Redis INCR, semaphores, distributed mutexes) suffer the pathologies of 3.1. The Log approach requires no counter and no lock.

First, define the event type:

```python
@dataclass(frozen=True, slots=True)
class ResourceUsage:
    id: Annotated[int, Identity, Ordered(int)] = 0
    resource_name: str = ""
    claim_id: str = ""
    amount: float = 0.0
    date: str = ""  # ISO 8601
```

The algorithm:

1. Wait for the minimum interval between requests (a timing discipline, not a lock -- one Lens query, no race).
2. Write ONE claim to the Log with a unique `claim_id`. The Log assigns a monotonic ID via the `Ordered(int)` annotation.
3. Query all claims in the current window. Our claim has a *position* -- determined by its Log-assigned ID relative to other claims in the window.
4. If position <= limit: proceed. We are within budget.
5. If position > limit: wait for the (position - limit)th claim to expire from the window, then re-check.

No re-writing. Our single claim stays in the Log. We only re-check our position as the window slides.

Trace it with four concurrent workers, limit = 3, window = 60s:

```
Worker A claims at Log position 17 (limit=3, window=60s)
Worker B claims at Log position 18
Worker C claims at Log position 19
Worker D claims at Log position 20

Claims in window: A(17), B(18), C(19), D(20)
A: position in window = 1 → proceed
B: position in window = 2 → proceed
C: position in window = 3 → proceed
D: position in window = 4 > 3 → wait for A's claim to expire

[60 seconds pass, A's claim falls out of window]
D re-checks: claims in window = B(18), C(19), D(20)
D: position in window = 3 → proceed
```

No claim was rewritten. D's claim existed from the moment it was appended. Only its *position within the window* changed as older claims expired.

The budget check itself is a fold over Log events:

```python
async def check_budget(log, resource_name, window_seconds):
    cutoff_iso = datetime.fromtimestamp(
        time.time() - window_seconds, tz=timezone.utc
    ).isoformat()
    events = await log.query(
        Lens().of_type(ResourceUsage)
              .where(ResourceUsage, lambda e: e.resource_name == resource_name
                     and e.date >= cutoff_iso)
    )
    return sum(e.data.amount for e in events)
```

The cutoff is converted to ISO 8601 to match the event's `date` field — both sides of the comparison use the same format. This is a fold with a predicate: balance = fold over Deposit/Withdrawal events; budget consumed = fold over ResourceUsage events in a time window.

Why does this work without locks? Because the Log assigns monotonic IDs. Given N claims in a window, the first 3 (by Log ID) proceed. The 4th waits. The ordering is total and deterministic for any number of concurrent writers. Two workers writing claims at the same instant get different Log IDs. No ambiguity. No lost updates.

theworld provides this pattern through `BudgetPolicy` and `check_budget`:

```python
@runtime_checkable
class BudgetPolicy[D](Protocol):
    @property
    def total(self) -> float: ...
    @property
    def fork_at(self) -> float: ...
    def is_spend(self, event: Event[D]) -> float | None: ...
    def estimate_cost(self, work: D) -> float: ...

async def check_budget(log, policy):
    spent = await fold_log(
        log, 0.0,
        lambda s, e: s + (c if (c := policy.is_spend(e)) is not None else 0.0),
    )
    return BudgetState(total=policy.total, spent=spent, fork_at=policy.fork_at)
```

`BudgetState` has `remaining` and `should_fork` properties. The state is derived, never stored. The truth is the events; the budget is the fold.

`BudgetGuard` takes this further. When the budget approaches exhaustion (`remaining <= fork_at`), the guard triggers a `ForkStrategy` -- spawning a new World to continue the work. The guard itself is a `WorldCompilable` capability: it compiles to a nodnod node via `compile_world`, exactly like `Script` or `HotReloadable`. Budget enforcement is not a framework feature bolted on after the fact. It is a capability, participating in the same fold as every other World-level description.

```python
world = World(log=log, computations=(
    BudgetGuard(policy=CpuBudget(), strategy=SubprocessFork(cmd), work=run_work),
))
```

The insight: rate limiting, budget tracking, and resource accounting are not special mechanisms. They are Log projections -- folds over events in a time window. The Log provides the total ordering that makes the projection deterministic. The fold provides the accumulation that makes the projection pure. No new primitive is needed. The bank account (3.2.1), the mortal workers (3.3.1), and the budget (here) are the same pattern: derive state from the Log, act on the derived state, append new events.

**Exercise 3.6a.** Design a budget system with nested limits on the same resource: `Budget("rpm", window=60, limit=3)` AND `Budget("daily", window=86400, limit=1000)`. Each Budget is an independent fold over the same events with a different window. What is the position calculation when a claim falls within the rpm limit but exceeds the daily limit? How do you compose multiple budget checks without introducing a lock between them?

---

## 3.4 Concurrency: Time Is of the Essence

In 3.3, we modeled systems with multiple computations communicating through a shared Log. We did not explicitly address the issue of concurrent execution. In practice, computations run concurrently — multiple workers computing matrix rows simultaneously, the oracle querying while the swarm produces solutions.

### 3.4.1 The Nature of Time in Concurrent Systems

SICP 3.4 confronts the fundamental problem: "a computation might read a shared variable, compute a new value, and write it back — but another computation might have modified the variable in between." This is the read-modify-write race. It requires serializers. Serializers require ordering. Ordering between concurrent processes requires synchronization. Synchronization introduces deadlock.

### 3.4.2 Append-Only Eliminates the Race

Recall the bank account from 3.1.4. With mutable state, the interleaving of Peter's and Paul's withdrawals corrupted the balance — final balance 75 instead of 65. With the Log, both withdrawals are separate events. The balance is a commutative fold: 100 - 10 - 25 = 65 regardless of append order.

The general principle: append-only means the only write operation is *append*, and append does not depend on the current contents of the Log. Peter's `Withdrawal(10)` does not need to know Paul's `Withdrawal(25)` exists. Each event is self-contained. The aggregate is correct because it folds over *all* events. Concurrent appends do not interfere — the Log serializes them internally (an asyncio lock for `InMemoryLog`, a Kafka producer for distributed logs). No external serializer. No deadlock.

### 3.4.3 What Append-Only Does Not Solve

There is a gap. Consider a hotel booking system:

```python
@dataclass(frozen=True, slots=True)
class BookRoom:
    room: Annotated[str, Identity]
    guest: str

# Alice and Bob try to book Room 101 simultaneously
```

Alice queries the Log: "Is Room 101 booked?" No `BookRoom` event for Room 101. Alice appends `BookRoom(room="101", guest="Alice")`.

Bob queries the Log at the same time: "Is Room 101 booked?" No `BookRoom` event — Alice's append has not yet been processed. Bob appends `BookRoom(room="101", guest="Bob")`.

The Log now has two `BookRoom` events for Room 101. Both Alice and Bob think they have the room.

This is the **race window** between query and append. The Log eliminates read-modify-write races (because there is no modify). But it does not eliminate query-then-append races. The solution depends on the domain:

1. **Last writer wins**: the second booking overwrites the first (equivalent to mutable state).
2. **First writer wins**: a reconciliation process reads the Log, finds duplicate bookings, and cancels the later one. Requires a conflict resolution event.
3. **Optimistic concurrency**: before appending, re-query with `AwaitConsistent` to ensure you see all prior events. This narrows the race window but cannot eliminate it entirely on distributed logs.

The honest answer: the Log resolves the *concurrency* problem (no locks, no deadlock, no lost updates from interleaving) but does not resolve all *coordination* problems. When two actors compete for a scarce resource, some form of conflict resolution is still needed. But the resolution mechanism itself uses the Log — conflict resolution events are just more events — and the Log's total ordering provides the foundation for deterministic resolution.

**Exercise 3.7.** Implement the hotel booking system using the Log. Define event types for `BookRoom` and `CancelBooking`. Write a reconciliation computation that watches the Log and cancels duplicate bookings (keeping the first writer). What is the window during which both Alice and Bob believe they have the room? How does this compare to the window in a lock-based system?

**Exercise 3.8.** Lamport (1978) defines "happened before" as the transitive closure of (a) sequential ordering within a process and (b) send-before-receive for messages. In theworld, what constitutes "happened before"? Define it formally in terms of Log positions and Lens queries. Show that `Lens().after(cursor)` implements Lamport's "happened before" for single-log systems.

### 3.4.4 RuntimePolicy: Scheduling as Data

How computations execute concurrently is itself a capability:

```python
world = World(
    log=log,
    computations=(...),
    policy=RuntimePolicy(
        scheduling=WorkStealing(workers=4),
        errors=FailFast(),
        gil=AutoDowngrade(),
    ),
)
```

**Cooperative** (default): single asyncio event loop. All computations run as coroutines on one thread. No true parallelism, but no data races.

**WorkStealing**: N OS threads, each with its own event loop. Tasks pushed onto local deques (LIFO) and stolen from other workers' deques (FIFO) when idle. True parallelism on free-threaded Python (3.13t+).

**AutoDowngrade**: if WorkStealing is requested but GIL is enabled, silently fall back to Cooperative.

The scheduling policy is data — not code buried in a framework. Adding a custom scheduling policy means implementing `SchedulingCompilable`. The mortal workers example produces the same results under both policies. Cooperative: 1.5 chunks/s, 4 generations, 101 seconds. WorkStealing (3 threads): 3.3 chunks/s, 2 generations, 46 seconds. 2.2x speedup from one line of configuration. Same code, same Log, same Lens, same fold.

Nothing in the worker's logic knows about the scheduling policy. The worker writes `await asyncio.sleep(0.001)` to yield. Whether that yield dispatches to an asyncio loop (Cooperative) or an OS thread switch (WorkStealing) is decided by the policy. The computation does not know. The computation does not care.

---

## 3.5 The Resolution

SICP Chapter 3.5 introduces streams as an alternative to assignment for modeling state. A stream is a lazily evaluated, possibly infinite sequence. Instead of a bank account with a mutable balance, you have a stream of transaction events:

```scheme
(define (stream-withdraw balance amount-stream)
  (cons-stream
    balance
    (stream-withdraw
      (- balance (stream-car amount-stream))
      (stream-cdr amount-stream))))
```

No assignment. No local state. "Yet the system has state!" — the user perceives change, but the computation is a pure mathematical function.

### 3.5.1 The Merge Problem

Streams work beautifully for a single actor. But SICP 3.5.5 reveals the trap. When Peter and Paul share a joint account, the stream model requires *merging* their transaction streams:

> "The trouble with this formulation is in the notion of merge. It will not do to merge the two streams by simply taking alternately one request from Peter and one request from Paul... However such a merge is implemented, it must interleave the two transaction streams in some way that is constrained by 'real time' as perceived by Peter and Paul." (SICP 3.5.5)

The merge must respect real-time ordering. But real-time ordering is precisely what streams were meant to abstract away. SICP is explicit about the failure:

> "Thus, in an attempt to support the functional style, the need to merge inputs from different agents reintroduces the same problems that the functional style was meant to eliminate." (SICP 3.5.5)

And the chapter ends with an admission:

> "We can model the world as a collection of separate, time-bound, interacting objects with state, or we can model the world as a single, timeless, stateless unity. Each view has powerful advantages, but neither view alone is completely satisfactory. A grand unification has yet to emerge."

Objects with state: modularity, identity, natural concurrency model — but no referential transparency, no substitution, synchronization nightmares.

Streams without state: referential transparency, mathematical purity, clean reasoning — but the merge problem reintroduces time, and interactive concurrent systems resist the model.

The reader of SICP is left genuinely stuck. Neither model is sufficient.

### 3.5.2 The Log Dissolves the Merge

The merge problem arises because two independent streams must be combined into one, and the combination requires knowing the real-time relationship between their elements.

The Log has no merge problem. Peter and Paul do not have separate streams to merge — they both append to the same Log. The ordering question that paralyzed SICP's streams is meaningless here. The Log does not merge streams. It accumulates events. The events are facts, and the balance is a commutative fold over those facts — the order of arrival is irrelevant.

### 3.5.3 Lens Is the Stream

The structural mapping between SICP's streams and theworld's Lens is precise:

| SICP stream operation | theworld equivalent | Role |
|---|---|---|
| `cons-stream` (produce element) | `await put(log, event)` (append to Log) | Produce new data |
| `stream-car` (access current) | `await log.query(lens)` (query current state) | Access current data |
| `stream-cdr` (promise of rest) | `Lens().after(cursor)` (events after cursor) | Access future data |
| `stream-map f s` | `Computation.compile_action` (fold perceived into new events) | Transform elements |
| `stream-filter pred s` | `Lens().of_type(T).where(pred)` | Select elements |
| `merge` (THE PROBLEM) | Shared Log (multiple writers, no merge) | Combine streams |

The critical row is the last one. SICP's merge requires interleaving two independent streams in real-time order. theworld's Log *is* the merge point. Multiple computations write to it independently. The Log imposes a total order. Readers see a consistent sequence. No merge procedure exists because no merge is needed.

The Lens goes beyond SICP's streams in three ways:

**Cross-compilable.** The same Lens, different backends. `Lens().of_type(MarketTick).of_identity("BTC")` compiles to a memory filter on `InMemoryLog`, a Kafka consumer filter on `KafkaLog`, a SQL WHERE clause on `ClickHouseLog`. SICP's streams are tied to one evaluation strategy.

**Queryable history.** SICP's streams are ephemeral — once consumed, elements are gone. The Log remembers. You can query events from the past: `Lens().of_type(MarketTick).after(yesterday)`. The stream that never forgets.

**Consistency as observation.** `AwaitConsistent` makes a Lens wait for specific computations to catch up before returning results. On InMemoryLog, this is a no-op. On KafkaLog, it waits for consumer group offsets. Consistency is a property of your Lens, not of the Log.

### 3.5.4 SICP Needed a New Language Feature; We Do Not

SICP 3.5.1 builds elaborate machinery for lazy evaluation: `delay`, `force`, memoization, special forms for `cons-stream`. Streams require language-level support for delayed evaluation — you cannot implement them as ordinary procedures.

Python's `async for` provides lazy evaluation natively. An async generator yields elements one at a time. `log.subscribe(lens)` returns an async generator that yields events as they arrive — an infinite, lazy stream:

```python
async for event in log.subscribe(Lens().of_type(MarketTick)):
    # each event = next element of the stream
    balance = fold_events(all_events_so_far)
```

No `delay`. No `force`. No special forms. The mechanism is unremarkable. The semantics — an infinite stream of events, consumed lazily, driving a pure fold — is what matters.

### 3.5.5 The Object-Stream Duality Resolved

We can now state the resolution precisely.

SICP's tension: objects have modularity (identity, encapsulation, interaction) but lose referential transparency. Streams have referential transparency but lose modularity when agents must interact (the merge problem).

The Log provides both:

**The Computation looks like an object:**
- It has identity: `life("trader", ...)`
- Its behavior depends on history: the trader's next action depends on all market ticks it has observed
- It interacts with other Computations: the trader emits `OrderPlaced` events that the risk manager observes

**The Computation is a stream processor:**
- It has no mutable state: its capabilities are frozen, its definition is immutable
- It folds over immutable data: `Lens().of_type(MarketTick)` produces a view of the Log
- Its "state" is derived: the result of a pure function applied to immutable data
- It produces new data by appending: `await put(log, OrderPlaced(...))` — no mutation, only growth

The duality is resolved because the Log provides what objects need — shared state, communication, identity — through what streams are — immutable, append-only, referentially transparent. There is no compromise. The object view and the stream view are two perspectives on the same architecture.

**Change is not mutation. Change is accumulation.**

The balance does not change from 100 to 75. A `Withdrawal` event is appended, and the derived balance — the fold of all events — is now 75. The old balance is still derivable. The events that produced it still exist. Nothing was overwritten. Nothing was lost.

Heraclitus: "Even while it changes, it stands still." The Log stands still — events never change, never move, never disappear. But the view through the Lens changes — new events arrive, the derived state evolves, the Computation's behavior adapts. The river flows. The water is new. The river is the same.

And the fold model survives. Every phase — perception, action, lifecycle, plan, world — is a fold over capabilities. No mutation, no environment model, no `set!`. The promise made in Chapter 1 — that the fold model is permanently valid — is kept here, in the chapter where SICP's equivalent promise (the substitution model) dies.

This is the divergence point. SICP: "the substitution model breaks at Chapter 3, replaced by the environment model." emergent: "the fold model survives Chapter 3, because state is accumulation, not mutation."

### 3.5.6 The Practical Consequence: Concurrency Becomes Trivial

SICP's unresolved tension is not merely philosophical — it has engineering consequences. In a mutable-state world, two threads writing to the same balance require locks, semaphores, transactions, or software transactional memory. Each mechanism introduces its own complexity: locks require ordering disciplines, semaphores require correct initialization, transactions require retry logic, STM requires conflict detection.

In the Log world, two computations appending events require nothing. Append is the only write operation, and it is atomic by construction. There are no data races because there is no shared mutable data. There are no deadlocks because there are no locks. There are no lost updates because updates are appends, and appends are never lost.

The mortal workers are the proof. Three workers, dying every 30 seconds, coordinating without a protocol, without a coordinator, without a lock. They coordinate through the Log — the thing that is simultaneously their shared state and their communication channel. The Log does not know it is being used for coordination. It is just an append-only sequence of facts. The coordination emerges from the facts and the workers' queries over them.

**Exercise 3.9.** SICP 3.5 implements `stream-withdraw` — a stream version of the bank account. Implement the equivalent using the Log: an async generator that yields successive balances as `Withdrawal` events arrive. Compare: (a) what happens when the stream is consumed by two readers simultaneously (SICP's merge problem), and (b) what happens when the Log is queried by two readers simultaneously (no merge problem).

**Exercise 3.10.** SICP 3.5.5's merge problem arises because two independent streams must be combined in real-time order. Construct a scenario with three theworld Computations — a producer, a transformer, and a consumer — where the producer emits events, the transformer folds them into new events, and the consumer reads the transformed events. Show that no merge is needed. What plays the role of SICP's merge? How does the Log's total ordering replace it?

**Exercise 3.11.** The chapter claims "the fold model survives Chapter 3." Verify this: write a Computation with three capabilities — `select.type(MarketTick)`, a custom `Threshold(price=42000)` capability that filters perceived events, and `flow.every(1.0)`. Trace `compile_perception()` step by step, showing each fold step as the substitution model: `ctx_0 → select.type compiles → ctx_1 → Threshold compiles → ctx_2`. Does the trace require knowing the Log's contents? Does it require knowing the time? Does it require an "environment model"?

---

## 3.6 Capability Evolution: The Frozen That Changes

Throughout this chapter we have relied on a powerful invariant: capabilities are frozen. A `Supervised(max_restarts=50)` is the same value forever. A `Computation("trader", caps)` never changes its capabilities tuple. This invariant is what preserves the fold model -- the same capabilities, the same fold, the same result.

But production systems must change. A trader's risk parameters need adjustment at 3 AM without a redeploy. A worker pool needs to scale from 3 to 8 nodes under load. A model version needs to be swapped while the system is serving traffic.

How do you change what is frozen?

You do not change it. You *replace* it. And the channel for replacement is the same channel for everything else: the Log.

### 3.6.1 HotReloadable

`HotReloadable` is a `WorldCompilable` capability. When included in a World's computations, it compiles to a watcher node that subscribes to `Reload` events in the Log:

```python
world = World(log=log, computations=(
    Script(fn=worker_a),
    HotReloadable(),
))

# Later, from anywhere -- another coroutine, an HTTP endpoint, another World:
await put(log, Reload(life="world", capabilities=(
    Script(fn=new_worker),
    HotReloadable(),
)))
```

`Reload` is a frozen dataclass:

```python
@dataclass(frozen=True, slots=True)
class Reload:
    id: Annotated[int, Identity, Ordered(int)] = 0
    life: str = "world"
    capabilities: tuple[WorldCompilable, ...] = ()
    mode: str = "add"  # "add" | "remove" | "replace"
```

The watcher's logic, stripped to its essence:

```python
async def _reload_watcher(spawnable: Spawnable) -> None:
    epoch = 0
    async for event in log.subscribe(Lens().of_type(Reload)):
        new_nodes = _fold_to_nodes(event.data.capabilities)
        old_nodes = spawnable.living_nodes

        if mode == "add":
            to_add = new_nodes - old_nodes
        elif mode == "remove":
            to_remove = new_nodes & old_nodes
        else:  # replace
            to_remove = old_nodes - new_nodes - {watcher_node}
            to_add = new_nodes - old_nodes

        spawnable.despawn(to_remove)
        spawnable.spawn(to_add)
        epoch += 1
        await put(log, ReloadApplied(life="world", epoch=epoch,
                                      added=len(to_add), removed=len(to_remove)))
```

Trace a concrete reload. The World starts with two workers:

```
Initial World: living_nodes = {worker_a_node, worker_b_node}

Event appended: Reload(capabilities=(Script(fn=worker_c),), mode="add")

Watcher receives event:
  _fold_to_nodes((Script(fn=worker_c),)) → {worker_c_node}
  old_nodes = {worker_a_node, worker_b_node}
  mode = "add"
  to_add = {worker_c_node} - {worker_a_node, worker_b_node} = {worker_c_node}

  spawnable.spawn({worker_c_node})
  put(log, ReloadApplied(added=1, removed=0, epoch=1))

Living nodes: {worker_a_node, worker_b_node, worker_c_node}
```

No existing node was touched. The watcher appended one node to the living set. The `ReloadApplied` event is itself in the Log — any computation can confirm the reload happened.

Inside `_fold_to_nodes`:

```python
def _fold_to_nodes(caps):
    new_ctx = fold(caps, WorldContext(log=log), WorldCompilable, "compile_world")
    return new_ctx.nodes
```

The same fold that `World.run()` uses. The result is a `frozenset[type]` of nodnod node types. The watcher diffs this set against `spawnable.living_nodes`, despawns the removed, spawns the added.

`Spawnable` — implemented by both `CallbackAgent` (Cooperative) and `_WorkStealingAgent` — provides `spawn`, `despawn`, and `living_nodes`. `World.run()` injects it into the nodnod Scope; the watcher node declares `spawnable: Spawnable` in its signature and nodnod resolves it. Dependency injection through types, not globals.

The confirmation — `ReloadApplied` — is itself an event in the Log. The reload is auditable. You can query "what capabilities was the system running at epoch 3?" by reading the Reload events.

### 3.6.2 Why This Does Not Break the Fold Model

The fold model says: same capabilities, same fold, same result.

HotReload does not violate this. It *replaces* the capabilities. The old capabilities, if folded again, still produce the same node set they always did. The new capabilities produce a different node set. The change happened at the specification level -- a new `Reload` event was appended to the Log -- not at the execution level. No existing frozen value was mutated. A new frozen value (the Reload event) was created, and the watcher responded by swapping the running nodes.

This is the chapter's thesis applied to the system's own configuration: **change is accumulation, not mutation.** The old Reload events are not overwritten. A new Reload event is appended. The watcher reads the latest specification from the Log. The Log grows. The specification evolves. Nothing is erased.

### 3.6.3 Migration: Capabilities Cross World Boundaries

If capabilities are frozen data -- serializable, transmittable -- then they can cross machine boundaries. (With one caveat: capabilities that close over Python callables — `Script(fn=my_func)` — require the function to be importable on the receiving machine, or serialized via cloudpickle. Pure-data capabilities like `Supervised(max_restarts=5)` serialize trivially.) `MigrationWatcher` implements exactly this:

```python
@dataclass(frozen=True, slots=True)
class NodeFork:
    life: Annotated[str, Identity] = ""
    capabilities: tuple[object, ...] = ()
    reason: str = ""

@dataclass(frozen=True, slots=True)
class MigrationWatcher:
    world_id: str = ""
    accept_filter: str = "*"

    def compile_world(self, ctx: WorldContext) -> WorldContext:
        # ... compiles to a watcher node, same pattern as HotReloadable
```

World A detects overload and forks a computation's capabilities to the Log:

```python
await put(log, NodeFork(
    life="worker-7",
    capabilities=(Script(fn=restored_worker),),
    reason="no resources",
))
```

World B's `MigrationWatcher` subscribes to `NodeFork` events:

```python
async for event in log.subscribe(Lens().of_type(NodeFork)):
    new_ctx = fold(
        event.data.capabilities,
        WorldContext(log=log),
        WorldCompilable,
        "compile_world",
    )
    spawnable.spawn(set(new_ctx.nodes))
    await put(log, NodeRestored(life=event.data.life, world_id=self.world_id))
```

The capabilities travel as frozen data through the Log. World B folds them -- the same fold, producing the same nodes -- and spawns the result. The computation *migrates* without any IPC protocol, without shared memory, without a migration framework. The Log is the migration medium. fold is the recompiler. Capabilities are the portable specification.

The `accept_filter` field narrows which forks a watcher accepts. `MigrationWatcher(world_id="pool-b", accept_filter="team-a")` only restores computations whose `life` contains "team-a". Selective migration through data, not configuration files.

### 3.6.4 The Living Specification

HotReload and Migration together reveal a pattern: the system's specification is not a static configuration file. It is a *living document in the Log*.

At any moment, the system's current specification is the fold of all Reload and NodeFork events, filtered by World identity. The specification has a history (all events). It has a current value (the latest fold). It is auditable (query the Log). It is reproducible (replay the events on a fresh World). It is distributed (the Log can be shared across machines).

This is the Log model applied to the system itself. The bank account's balance is a fold over transaction events. The system's configuration is a fold over Reload events. The fold of all events on the same Log always produces the same result.

**Exercise 3.11a.** Design a verification step for hot reload: before spawning new nodes, fold the new capabilities through `VerifyCompilable` and reject the reload if contradictions are found (emit `ReloadRejected` instead of `ReloadApplied`). Write the pseudocode. Why is this important for production systems? What happens if a Reload event specifies capabilities that conflict -- for example, two `Supervised` with different `max_restarts` in the same scope?

**Exercise 3.11b.** HotReload replaces capabilities at the World level. Design a finer-grained mechanism: capability replacement at the *Computation* level. A `ReloadComputation(identity="trader", capabilities=(...))` event should replace only the trader's capabilities, leaving all other computations unchanged. What changes in the watcher? What changes in the fold? (Hint: you need to track per-identity capability sets, not just a flat node set.)

---

## 3.7 The Complete Architecture

### 3.7.1 World as Operating System

The full architecture:

```python
world = World(
    log=log,
    computations=(
        scoped(
            life("worker-0", select.type(Task), TaskExecutor(), flow.continuous()),
            life("worker-1", select.type(Task), TaskExecutor(), flow.continuous()),
            Supervised(max_restarts=10, backoff=1.0),
        ),
        life("observer", select.all(), ProgressTracker(), flow.every(5.0)),
    ),
    policy=RuntimePolicy(scheduling=Cooperative()),
)
await world.run()
```

`World.run()` folds `computations` through `WorldCompilable`:

1. `Scoped.compile_world` — inner fold:
   - `life("worker-0", ...).compile_world(ctx)` → registers a nodnod node for worker-0
   - `life("worker-1", ...).compile_world(ctx)` → registers a nodnod node for worker-1
   - `Supervised(...).compile_world(ctx)` → wraps both nodes with retry logic
   - Merges back: two supervised nodes join the outer context
2. `life("observer", ...).compile_world(ctx)` → registers an unsupervised node
3. Result: `WorldContext(nodes={supervised_worker_0, supervised_worker_1, observer})`
4. Nodes are assembled into a nodnod DAG, and `RuntimeAgent` executes them according to the policy.

Computations fold into a World. The mechanism does not change. The domain does.

### 3.7.2 The Perceive-Act-Emit Cycle

Each Computation's lifecycle is an infinite loop:

```python
async def live(self, log):
    lc = self.compile_lifecycle()
    cycles = 0
    while lc.max_cycles is None or cycles < lc.max_cycles:
        events = await self.run(log)
        if events:
            await log.append(events)
        cycles += 1
        await asyncio.sleep(lc.delay)
```

`self.run(log)` is the pure core:

1. **Perceive**: `self.compile_perception()` — fold capabilities into a Lens. Query the Log.
2. **Act**: `self.compile_action(perceived)` — fold perceived events into new events.
3. **Return**: the new events (not yet in the Log).

`live()` appends the returned events to the Log. The next cycle's `compile_perception()` will see them (and all other events appended since the last cycle).

This is a metamorphism in the sense of Gibbons (2007): the output of one cycle feeds the input of the next. `run()` is a hylomorphism — an unfold (query the Log) composed with a fold (compile events). `live()` wraps it in a feedback loop: output events enter the Log, which is the input of the next unfold. Streaming. Self-referential. The recursion scheme that describes ongoing existence.

### 3.7.3 Forward References

In Chapter 4, we will turn from how systems are organized to how the compilation framework itself is organized. We will see that fold is not merely a useful utility. It is an evaluator, and like SICP's metacircular evaluator, it determines the meaning of capabilities. The fold that compiles your program *is itself compiled by fold*. To appreciate this is to change our image of ourselves as programmers: we come to see ourselves as designers of compilation languages.

In Chapter 5, we will see the exact machine that executes fold. The abstract `RuntimePolicy` that we used in 3.4.4 — Cooperative, WorkStealing — will be opened up. The nodnod DAG, the Scope registry, the Node lifecycle, the thread pool, the work-stealing deques — the mechanics that turn the abstract fold into concrete execution on real hardware.

---

## Exercises

**Exercise 3.12.** SICP's digital circuit simulator (3.3.4) models wires with signals, gates that propagate changes, and an agenda that schedules future events. The simulator is an event-driven system built on mutable state. Design a simplified circuit simulator using the Log: `SetSignal` events on wires, gate computations that read input wires and emit output signal events. No wire has mutable state — the current signal on a wire is the latest `SetSignal` event for that wire. Compare: what is simpler? What is harder?

**Exercise 3.13.** SICP's random-number generator (3.1.2) encapsulates state to provide modularity: you call `(rand)` and get a number without knowing the internal seed. In the Log model, random-number generation would emit `RandomSeed` events. This seems to destroy the modularity — anyone can query the seeds. Is this a genuine loss? Design a Log-based random number generator and discuss whether the Log model is appropriate for *all* kinds of state, or whether some state is best kept local.

**Exercise 3.14.** theworld's `scoped()` creates a fold boundary for `Supervised` and other modifiers. Design a `scoped()` variant that creates a *Log boundary* — a sub-Log visible only within the scope. Events written to the sub-Log are not visible to the parent World. Events from the parent are visible to the sub-scope. What would this enable? What invariants does it preserve or break?

**Exercise 3.15.** Moseley and Marks (2006) classify state as essential (user-facing) or accidental (implementation artifact). For the mortal workers example, enumerate: (a) essential state — what events does the user observe? (b) essential logic — what invariants must hold? (c) accidental state — what derived data exists for performance? Redesign the example so that *only* essential state appears in the Log.

---

## Summary

This chapter confronted the problem of modeling change — the same problem SICP confronts in its Chapter 3. The paths diverge at the critical moment.

SICP introduces assignment (`set!`), gains modularity, and pays the price: the substitution model breaks, referential transparency dies, identity becomes circular, concurrency requires serializers, serializers cause deadlock. Streams offer an escape — model state as infinite lazy sequences — but the merge problem reintroduces time when multiple agents interact. SICP ends with the tension unresolved: "A grand unification has yet to emerge."

emergent refuses assignment. The Log replaces `set!`: events accumulate rather than overwrite. The Lens replaces the environment model: state is derived by querying immutable data, not by looking up mutable bindings. The fold model survives. No environment model is needed because there is no assignment.

The Log dissolves the merge problem. There is no merge — there is one Log with multiple writers. The balance is a commutative fold over events. The order of appends does not matter. Concurrency requires no locks, no serializers, no deadlock prevention.

The mortal workers are the proof: twelve instances across four generations, zero data loss, zero coordination protocol. The Log is the memory. The worker is disposable. The result is permanent.

The cost is storage: the Log grows. The benefit is everything else: referential transparency, fault tolerance, concurrency safety, deterministic replay, and a computational model that does not break when change enters the picture.

**Change is not mutation. Change is accumulation.** The Log stands still. The view through the Lens evolves. The river flows, the water is new, the river is the same.
