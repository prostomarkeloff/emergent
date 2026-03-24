# 3. Modularity, Computations, and State

> Μεταβάλλον ἀναπαύεται
> (Even while it changes, it stands still.)
> — Heraclitus
>
> Plus ça change, plus c'est la même chose.
> — Alphonse Karr

The preceding chapters introduced the basic elements from which compilations are made. We saw how primitive capabilities and primitive data are combined to construct compound entities, and we learned that abstraction is vital in helping us to cope with the complexity of large systems. But these tools are not sufficient for designing systems that change over time. Effective system synthesis also requires organizational principles that can guide us in formulating the overall design of a system. In particular, we need strategies to help us structure large systems so that they will be *modular* — that is, so that they can be divided "naturally" into coherent parts that can be separately developed and maintained.

One powerful design strategy, which is particularly appropriate to the construction of programs for modeling physical systems, is to base the structure of our programs on the structure of the system being modeled. For each entity in the system, we construct a corresponding computational object. For each system action, we define a symbolic operation in our computational model. Our hope in using this strategy is that extending the model to accommodate new entities or new actions will require no strategic changes to the program, only the addition of the new symbolic analogs of those entities or actions.

To a large extent, then, the way we organize a large program is dictated by our perception of the system to be modeled. In this chapter we will investigate two prominent organizational strategies arising from two rather different "world views" of the structure of systems. The first organizational strategy concentrates on *objects*, viewing a large system as a collection of distinct objects whose behaviors may change over time. An alternative organizational strategy concentrates on the *streams of events* that flow in the system, much as an electrical engineer views a signal-processing system.

Both the object-based approach and the event-stream approach raise significant issues in system design. With objects, we must be concerned with how a computational object can change and yet maintain its identity. This forces us to grapple with mutable state — and as Moseley and Marks (2006) argue in "Out of the Tar Pit," mutable state is the single largest source of accidental complexity in contemporary software. The difficulties of dealing with objects, change, and identity are a fundamental consequence of the need to grapple with *time* in our computational models. These difficulties become even greater when we allow the possibility of concurrent execution — as Lamport (1978) showed, "happened before" is only a partial ordering in a distributed system.

The event-stream approach can be most fully exploited when we decouple simulated time in our model from the order of events in the computer. We will accomplish this using a technique that is both old and radical: the *append-only log*.

---

## 3.1 The Cost of State

We ordinarily view the world as populated by independent objects, each of which has a state that changes over time. A bank account has state in that the answer to "Can I withdraw $100?" depends upon the history of deposit and withdrawal transactions. A web application has state in that the response to "GET /users/1" depends upon all prior POST, PUT, PATCH, and DELETE operations. A distributed agent has state in that its next action depends upon all events it has observed.

We can characterize an object's state by one or more *state variables*, which among them maintain enough information about history to determine the object's current behavior. In a simple banking system, we could characterize the state of an account by a current balance rather than by remembering the entire history of account transactions.

This is the conventional approach — and Moseley and Marks dissect its costs.

### 3.1.1 State Destroys Testing

A test on a system in one state tells you nothing about its behavior in another state. If the system has N bits of state, there are 2^N possible states, and a test covers one of them. The common approach — start in a "clean" state, run the test — is "sweeping the problem under the carpet." If some sequence of inputs can put the system in a "bad state" (one different from the test's starting state), things go wrong.

The hypothetical support-desk scenario: "try it again," "restart the program," "reinstall." Each is an attempt to force the system back into a "good internal state." The system's internal state is hidden, vast, and — after six months of production — unknowable.

### 3.1.2 State Destroys Reasoning

Informal reasoning about stateful systems proceeds by case-by-case mental simulation: "if this variable is in this state, then this will happen — which is correct — otherwise that will happen — which is also correct." As the number of states grows, this approach buckles. Every additional bit of state doubles the number of scenarios.

Worse: *contamination*. A procedure that is itself stateless, but calls a stateful procedure — even indirectly — becomes effectively stateful. All reasoning about it must account for the hidden state. "When you let the nose of the camel into the tent, the rest of him tends to follow."

### 3.1.3 State Destroys Modularity — Or Does It?

It is sometimes argued that state permits a particular kind of modularity. Working within a stateful framework, one can add state to any component without adjusting the components that invoke it. Working within a functional framework, the same effect requires threading an additional parameter through every caller.

But the trade-off is severe: in a functional program, you can always tell what controls the outcome of a function by looking at its arguments. In a stateful program, you can never tell — potentially every piece of code in the entire system can influence the outcome through hidden mutable variables.

Moseley and Marks: "The trade-off is between complexity (with the ability to take a shortcut when making some specific types of change) and simplicity (with huge improvements in both testing and reasoning)."

### 3.1.4 The Conventional Escape: Encapsulation

The object-oriented response to the problem of state is *encapsulation*: bundle state with the procedures that access it, and restrict access to those procedures. This is the essence of objects — a bank account object has a balance and methods deposit! and withdraw! that are the only way to modify it.

Encapsulation provides a discipline of state management. But it does not eliminate state — it organizes it. The balance is still mutable. The test problem remains: testing the account in one state tells you nothing about its behavior in another. The contamination problem remains: any procedure that calls deposit! becomes, from the standpoint of reasoning, a stateful procedure.

In emergent, we have so far avoided this problem entirely. Capabilities are frozen. Contexts are frozen. Fold is pure. Compilation is deterministic. The same capabilities produce the same artifacts — always. This is the source of emergent's power — and its limitation.

Consider: what does `MaxLen(255).compile_pydantic(ctx)` return when called twice with the same ctx? The same result. Always. This is referential transparency — the property that made substitution-model reasoning in Chapter 1 possible, that made banana-splitting in Chapter 2 valid, that made verification-as-compilation-target work. If we lose referential transparency, we lose all of that.

But the world changes. Users sign up. Orders are placed. Workers die. Markets move. A query `Lens().of_type(User)` returns different results at different times — not because the query changed, but because the Log grew. The answer to "how many users exist?" depends on *when you ask*. This is state. We cannot avoid it forever.

SICP confronts this moment with assignment: `(set! balance (- balance amount))`. The substitution model breaks. "Sameness and change" become philosophical problems. Two bank accounts with the same balance are not the same account — they have different identities, different futures. The environment model replaces substitution. Referential transparency is lost.

emergent confronts the same moment — but refuses the same solution. We will NOT introduce assignment. We will NOT introduce mutable state variables. We will NOT lose referential transparency. Instead, we will find a way to model a changing world using only immutable data and pure functions.

The key idea comes not from programming languages but from databases.

---

## 3.2 The Log Model of Computation

Helland (2015), in "Immutability Changes Everything," makes an observation so simple it is easy to miss: "The truth is the log. The database is a cache of a subset of the log."

Helland (2015), in "Immutability Changes Everything," observes: "The truth is the log. The database is a cache of a subset of the log." Transaction logs record all changes made to a database. The database contents are a materialized view of the log — the latest value of each record. If the database is destroyed, it can be reconstructed from the log. The database is not the truth; the log is.

Accountants don't use erasers, or they go to jail. All entries in a ledger remain. Corrections are new entries. Observed facts (a debit, a credit) are recorded. Derived facts (the current balance) are calculated from observations.

In theworld, we take this literally. The Log is the sole state primitive. It is append-only. Events, once written, cannot be modified or deleted. Computations do not have state variables. They have a *view* of the Log, obtained through a *Lens*.

```python
log = InMemoryLog()

# Write an event — append, never modify
await put(log, UserCreated(name="Alice", email="alice@example.com"))

# Read events — query, never mutate
users = await log.query(Lens().of_type(UserCreated))
```

The Log grows. Events accumulate. The "current state" — what users exist, what their balances are, which workers are alive — is not stored anywhere. It is *derived* by folding over the relevant events. A computation's "state" is the result of a fold over its view of the Log. Different computations, same Log, different views, different derived state.

### 3.2.1 Events as Facts

An event is a frozen dataclass:

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

Events carry their own identity — via emergent's `Identity` annotation on fields, the same annotation used for database primary keys in Chapter 1. Events carry their type — `MarketTick`, `OrderPlaced` — which is the same Python type used by isinstance dispatch, the same dispatch used by fold.

The Log indexes events by type and by identity. Querying `Lens().of_type(MarketTick)` returns all market tick events. Querying `Lens().of_type(MarketTick).of_identity("BTC")` returns all BTC ticks. The queries are O(1) for type (index lookup) and O(bucket) for identity (filter within type bucket). Compare with Erlang's mailbox, where selective receive scans the entire mailbox: O(N).

### 3.2.2 Lens as Observation

A Lens is not a filter. It is a *point of view*.

```python
# The trader sees: market ticks for BTC
trader_lens = Lens().of_type(MarketTick).of_identity("BTC")

# The risk manager sees: all orders above 1000 units
risk_lens = Lens().where(OrderPlaced, lambda o: o.quantity > 1000)

# The billing observer sees: all events since the billing period started
billing_lens = Lens().after(billing_period_start)
```

Each Lens op narrows the view. `of_type` selects by event data type. `of_identity` selects by the Identity-annotated field's value. `where` applies a predicate. `after` selects events after a cursor position. Ops compose by concatenation — `Lens(ops=self.ops + other.ops)` — which means they AND together: each successive op narrows further.

Different Lenses on the same Log produce different views. The Log does not change. The observation does.

This is the key insight of this chapter, and it is worth dwelling on: *state is not a property of the system. State is a property of the observation.*

Consider a concrete example. Three computations share one Log:

```python
log = InMemoryLog()

# A market data feed emits ticks
await put(log, MarketTick(symbol="BTC", price=42000, volume=100))
await put(log, MarketTick(symbol="ETH", price=2800, volume=50))
await put(log, OrderPlaced(id="o1", symbol="BTC", quantity=5, side="buy"))
await put(log, MarketTick(symbol="BTC", price=42100, volume=80))
await put(log, OrderPlaced(id="o2", symbol="ETH", quantity=10, side="sell"))
```

The trader's Lens: `Lens().of_type(MarketTick).of_identity("BTC")`. The trader sees: `[MarketTick(BTC, 42000), MarketTick(BTC, 42100)]`. Two events. The trader's "state" — its view of the world — is these two ticks. It does not see ETH ticks. It does not see orders.

The risk manager's Lens: `Lens().of_type(OrderPlaced)`. The risk manager sees: `[OrderPlaced(o1, BTC, 5, buy), OrderPlaced(o2, ETH, 10, sell)]`. Two events. Different events from what the trader sees. The risk manager's "state" is these two orders.

The billing observer's Lens: `Lens()` (everything). The billing observer sees all five events. Its "state" is the entire log.

Same Log. Three Lenses. Three different "states." The Log itself has no state in the mutable sense — it only grows. But each observer derives a different view, and that view IS the observer's state. When a new MarketTick arrives, the trader's state changes (its Lens query returns more results). The risk manager's state does not change (no new orders). The billing observer's state changes (one more event).

This is fundamentally different from mutable state. In a mutable system, "the state of the trader" is a mutable variable inside the trader object. Changing it requires assignment. Testing it requires knowing the current value. Reasoning about it requires tracking all possible values.

In the Log model, "the state of the trader" is a FUNCTION — `trader_lens.query(log)` — applied to the immutable Log. The function is pure. The Log is append-only. The result is deterministic: given the same Log and the same Lens, the result is always the same. Testing is easy: construct a Log with known events, query it, check the result. Reasoning is tractable: the Lens ops are frozen data, inspectable and composable.

This is what Moseley and Marks (2006) mean by "essential state" vs "accidental state." The essential state is the events — the facts about what happened. The accidental state — current balances, cached positions, aggregated metrics — is derived. In emergent, the essential state is the Log. The accidental state is whatever each Computation's Lens produces. The essential state is written once (append). The accidental state is computed on demand (query).

Lenses compose as a monoid. `Lens().of_type(A).of_identity("x").after(t)` is the concatenation of three Lens ops. Lens ops are frozen dataclasses — the same encoding as capabilities in Chapter 1 and query ops in Chapter 2. They compile through a two-level fold:

**Level 1:** `fold(computation.capabilities, LensContext(identity), LensCompilable, "compile_lens")` → builds a Lens from capabilities. "This computation observes MarketTick events for its own identity."

**Level 2:** `fold(lens.ops, backend_ctx, BackendCompilable, "compile_backend")` → executes the Lens ops on a concrete backend (InMemoryLog, KafkaLog, ClickHouseLog).

Two folds. The same six-line function at each level. The same isinstance dispatch. The same open-world: new Lens ops don't break existing backends. New backends don't break existing Lens ops.

### 3.2.3 Computation as Existence

In SICP, a computational object "has state" if its behavior depends on its history. In theworld, a Computation does not *have* state. A Computation *observes* history.

```python
agent = life("trader",
    select.self(),                    # observe own events
    select.type(MarketTick),          # observe market data
    KellyCriterion(max_bet=0.2),      # decision capability
    flow.every(1.0),                  # run every second
)
```

The Computation is a tuple of capabilities — frozen data. Its identity is "trader." Its behavior is determined by its capabilities, which fold into:
- A Lens (what it observes)
- An action context (what events it produces)
- A lifecycle context (when it runs)
- A node (how it joins the World's nodnod DAG)

The Computation itself does not change. The Log changes. The Computation's derived state — obtained by folding its Lens over the Log — changes as new events appear. But the Computation's *definition* — its capabilities — is immutable.

This is the resolution of SICP's Chapter 3 tension. SICP presents two world views: objects with state (mutable, identity-preserving, concurrency-challenging) and streams (functional, history-preserving, lazily evaluated). The Log is the stream that never forgets. Computations are the observers that derive their "state" by folding over it. The object view and the stream view are reconciled: the Computation looks like an object (it has identity, it has behavior that depends on history) but is implemented as a stream processor (it folds over an immutable log, it produces new events, it has no mutable state).

---

## 3.3 Modeling with the Log

In a system composed of many computations, the computations communicate through the Log. There are no other channels. No RPC. No shared memory. No message-passing mailboxes. Only the Log.

### 3.3.1 Mortal Workers, Immortal Results

We return to the matrix multiplication example from 1.1.7, now understanding *why* it works.

Three workers multiply a 1500×1500 matrix. Each worker dies after 30 seconds. Supervised restarts them. Four generations, twelve instances. Zero lost rows.

The workers are Computations. Their capability `select.type(RowChunk)` builds a Lens that observes RowChunk events. Their action capability computes matrix rows and emits RowResult events. Their lifecycle capability `flow.continuous()` keeps them running until they die.

When a worker dies, Supervised restarts it. The new worker is a fresh Computation — same capabilities, same Lens. It queries the Log: which RowChunks exist? Which RowResults have been emitted? The difference = unclaimed chunks. The new worker picks one and computes.

No coordination protocol. No assignment table. No leader election. The Log IS the coordination:

- "What needs doing?" → `Lens().of_type(RowChunk)` → all chunks
- "What has been done?" → `Lens().of_type(RowResult)` → done starts
- "What's left?" → set difference

Two workers grab the same chunk simultaneously. Both compute. Both emit. The Log has two RowResult events for the same start. The coordinator's `done_starts` is a set: duplicate entry = same element. No conflict. Append-only makes duplication safe by construction.

A worker dies mid-computation. It has not emitted a RowResult. The chunk stays unclaimed. Next generation picks it up. No partial results. No rollback. No cleanup.

### 3.3.2 Three Worlds, One Log

cosmos.py demonstrates the full scope. Three nested Worlds share one InMemoryLog:

```python
cosmos = World(log=log, computations=(
    Script(fn=lambda: run_swarm(log)),    # brute + heuristic workers
    Script(fn=lambda: run_api(log)),      # CRUD API via Log-HTTP
    Script(fn=lambda: oracle(log)),       # observer + Log-HTTP client
))
```

The swarm World runs two worker Computations: "brute" (brute-force SHA-256) and "heuristic" (hash-based shortcut). Both observe Task events, emit Solution events. Supervised with max_restarts=3.

The API World compiles TaskItem — a three-field dataclass — through emergent's wire.derive to produce CRUD endpoints. But the API does not bind a TCP port. It binds an *address* in the Log. HTTP requests are events. Responses are events. `serve()` watches for request events at address "tasks:7777" and routes them through the FastAPI app.

The oracle queries everything. It reads Solutions through Lens, reads WorldBorn/WorldDied events, sends HTTP requests to the API through the Log — `call(log, "tasks:7777", "POST", "/api/tasks", body=...)` — and prints whispers: "the fold remembers what the function forgets."

All three Worlds see the same Log. Each sees different events through different Lenses. The swarm sees Tasks. The API sees HTTP requests at its address. The oracle sees everything.

### 3.3.3 A Token Billing System

SICP 3.3.4 builds a digital circuit simulator — a concrete system that uses mutable state (wires with signals) and event propagation (agenda). The simulator demonstrates the object-based approach to modeling in all its complexity: mutable wire objects, shared state between gates, an agenda that schedules future events.

We will build the analogous system using the Log: a token billing system for an LLM agent platform. The system has three computations: an agent that processes user queries (emitting LLMResponse events with token counts), a billing observer that tracks token usage per model per session, and a dashboard that reads billing summaries.

The crucial difference from SICP's circuit simulator: nothing is mutable. The agent emits events. The billing observer folds them. The dashboard reads snapshots. All communication through the append-only Log.

**Event types:**

```python
@dataclass(frozen=True, slots=True)
class LLMResponse:
    session: Annotated[str, Identity]
    model: str
    tokens_in: int
    tokens_out: int
    content: str

@dataclass(frozen=True, slots=True)
class BillingSnapshot:
    view_id: Annotated[str, Identity]
    by_model: tuple[tuple[str, int], ...]   # (model_name, total_tokens)
    by_session: tuple[tuple[str, int], ...]  # (session_id, total_tokens)
    grand_total: int
    cursor: float   # Log position of last processed event
```

Both are frozen dataclasses with Identity annotations — the same encoding as User in Chapter 1. BillingSnapshot is a ViewSnapshot — a materialized view checkpoint that lives in the Log itself.

**The billing observer.** This is a Computation with a specific pattern: it watches for LLMResponse events and maintains a running tally. The tally is not a mutable variable — it is a frozen state that gets replaced each cycle:

```python
@dataclass(frozen=True, slots=True)
class BillingState:
    by_model: dict[str, int] = field(default_factory=dict)
    by_session: dict[str, int] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class TokenUsageView:
    def compile_view(self, ctx):
        match ctx.evt:
            case LLMResponse(model=m, session=s, tokens_in=ti, tokens_out=to):
                total = ti + to
                ctx.state.by_model[m] = ctx.state.by_model.get(m, 0) + total
                ctx.state.by_session[s] = ctx.state.by_session.get(s, 0) + total
        return ctx
```

The `observe()` function drives the loop:

```python
async for cycle in observe(
    lambda c: log.query(Lens(ops=(After(c),))),
    (TokenUsageView(),),
    state=BillingState(),
    cursor_of=lambda e: float(e.id),
    interval=10.0,
):
    if cycle.delta > 0:
        grand_total = sum(cycle.report.state.by_model.values())
        await put(log, BillingSnapshot(
            view_id="billing",
            by_model=tuple(cycle.report.state.by_model.items()),
            by_session=tuple(cycle.report.state.by_session.items()),
            grand_total=grand_total,
            cursor=cycle.cursor,
        ))
```

Every 10 seconds, the observer queries the Log for new LLMResponse events since its last cursor. It folds them through TokenUsageView (a capability — frozen dataclass with compile_view). The resulting state is used to emit a BillingSnapshot event.

**The dashboard.** Another computation — or an external service — reads BillingSnapshot:

```python
snapshots = await log.query(Lens().of_type(BillingSnapshot).of_identity("billing"))
if snapshots:
    latest = snapshots[-1].data
    print(f"Total tokens: {latest.grand_total}")
    for model, count in latest.by_model:
        print(f"  {model}: {count}")
```

The dashboard does not re-fold all LLMResponse events. It reads ONE snapshot — O(1). The snapshot IS an event in the Log — queryable through the same Lens mechanism as everything else.

**Recovery.** If the billing observer dies and restarts:

```python
snapshots = await log.query(Lens().of_type(BillingSnapshot).of_identity("billing"))
if snapshots:
    last = snapshots[-1].data
    state = BillingState(by_model=dict(last.by_model), by_session=dict(last.by_session))
    start_cursor = last.cursor
else:
    state = BillingState()
    start_cursor = 0.0
```

It resumes from the last snapshot's cursor. Only processes events since then. O(Δ) recovery, not O(all events).

**Comparison with SICP's circuit simulator.** SICP's simulator maintains mutable wires with signal values, gates that read and write wires, and an agenda that schedules future signal changes. The state is distributed across mutable objects. Testing requires setting up initial wire states. Concurrency would require locks on shared wires.

The billing system maintains NO mutable state that persists between observer cycles. BillingState is a mutable accumulator WITHIN one cycle — created, filled, used to emit a snapshot, discarded. Between cycles, all state is in the Log (BillingSnapshot events). Testing requires constructing a Log with known events — `put(log, LLMResponse(...))` — and checking the resulting snapshot. Concurrency is free: the observer appends snapshots, the dashboard reads them, no shared mutable data.

The circuit simulator teaches: objects with mutable state can model propagation networks. The billing system teaches: the Log with fold can model the same propagation without mutable state. The events propagate through the Log. The derived state propagates through fold. The snapshots propagate through Lens queries. Nothing is mutated. Everything is appended.

### 3.3.4 Tables and Queues as Log Patterns

Traditional databases maintain tables — mutable collections of rows. Traditional message queues maintain queues — FIFO buffers that consume messages.

In theworld, both are patterns over the Log:

**Table (materialized view):** The billing system above IS a table. BillingSnapshot is the "current row." Each new snapshot supersedes the previous. The dashboard reads the latest snapshot — like reading a row from a table. The table is not mutable; it grows by appending new versions.

**Queue (work distribution):** The mortal workers pattern IS a queue. RowChunk events are "enqueued" (appended to Log). Workers "dequeue" by querying unclaimed chunks. But unlike a traditional queue, the events are never consumed — they remain in the Log. "Dequeue" is a derived operation: unclaimed = all chunks minus completed chunks. New workers see the same queue — they don't need to re-enqueue anything.

Both patterns arise naturally from the Log. No new primitives needed. Events, Lens, fold — the same three things that underlie everything else.

```python
async for cycle in observe(
    lambda c: log.query(Lens(ops=(After(c),))),
    (TokenUsageView(),),
    state=TokenState(),
    cursor_of=lambda e: float(e.id),
    interval=10.0,
):
    await put(log, ViewSnapshot(view_id="tokens", state=cycle.report.state))
```

The ViewSnapshot IS an event in the Log. Other computations read it through Lens. O(1) to read the latest snapshot, O(Δ) to update from snapshot — not O(all events).

**Queue (work distribution):** Workers observe unclaimed work items through Lens queries. No FIFO buffer. No message consumption. The "queue" is the difference between "what was emitted" and "what was processed," computed dynamically from the Log.

### 3.3.5 Tiered Storage

Not all events deserve the same storage backend. LLM responses must survive process restarts — they represent work done and money spent. Intermediate thinking steps are ephemeral — useful for debugging, expensive to persist.

TieredLog routes events to different backends by tier:

```python
from theworld import TieredLog, TierBinding, Durable, Ephemeral, InMemoryLog
from theworld.sqlite_log import open_multi_log

sqlite = await open_multi_log("agent.db",
    compile_sa(LLMResponse, "responses"),
    compile_sa(BillingSnapshot, "billing"))
memory = InMemoryLog()

log = TieredLog(
    TierBinding(Durable, sqlite),    # persists across restarts
    TierBinding(Ephemeral, memory),  # fast, volatile
)
```

Writing: `await put(log, response, tier=Durable)` → SQLite. `await put(log, thinking_step, tier=Ephemeral)` → memory. Reading: `Lens().tier(Durable)` routes query to the sqlite backend only. `Lens()` without tier filter merges all backends.

TieredLog IS a Log — same protocol (query, append). Nesting works: a Durable TieredLog can contain a Local SQLite and a Network PostgreSQL sub-log. Three tiers, two levels, one protocol.

The sqlite backend uses emergent's wire compilation: `compile_sa(LLMResponse, "responses")` generates a SQLAlchemy model from the frozen dataclass event type. Same compilation that generates REST endpoints in Chapter 1 and Pydantic models in Chapter 2. The event type IS the schema. The schema compiles to a SQL table. One encoding, all the way down.

Helland (2015): "The truth is the log." But the log has layers. Some truths are forever (Durable). Some truths are transient (Ephemeral). TieredLog expresses this without changing the computation model — computations see one Log through one Lens. The tier is a property of storage, not of observation.

---

## 3.4 Concurrency: Time Is of the Essence

In 3.3, we modeled systems with multiple computations communicating through a shared Log. We did not, however, explicitly address the issue of concurrent execution. In practice, computations run concurrently — multiple workers computing matrix rows simultaneously, the oracle querying while the swarm produces solutions, the API serving requests while computations emit events.

### 3.4.1 The Nature of Time in Distributed Systems

Lamport (1978) showed that in a distributed system, the "happened before" relation is only a partial ordering. Two events at different processes are concurrent unless one causally precedes the other. There is no global clock. There is no total ordering given by physics.

The Log provides a total ordering. Events are appended sequentially — each has a position in the log. This position IS the time. "Event A happened before event B" means A's position in the Log is less than B's. No wall clock needed. No distributed consensus. The Log's append order is the time.

On InMemoryLog (single event loop), this ordering is trivially consistent — the asyncio event loop serializes all appends. On KafkaLog (distributed), the ordering is per-partition — Kafka guarantees ordering within a topic partition. On ClickHouseLog (analytical), the ordering is by insert time — eventual consistency with explicit flush.

The Lens op `After(cursor)` means "events with position > cursor." The Lens op `AwaitConsistent(subscribers)` means "block until named computations have processed up to the caller's cursor." Consistency is a property of the observation, not of the Log.

### 3.4.2 Mechanisms for Controlling Concurrency

RuntimePolicy determines how computations execute concurrently:

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

**Cooperative** (default): single asyncio event loop. All computations run as coroutines on one thread. No true parallelism, but no data races. Sufficient when computations are I/O-bound.

**WorkStealing**: N OS worker threads, each with its own event loop. Tasks are pushed onto local deques (LIFO) and stolen from other workers' deques (FIFO) when idle. True parallelism on free-threaded Python (3.13t+). The work-stealing scheduler is itself a compiler — `WorkStealing.build_agent` folds schema_meta from nodes via WorkStealingCompilable to collect per-node traits (priority, etc.).

**AutoDowngrade**: if WorkStealing is requested but GIL is enabled, silently fall back to Cooperative. Safety net for running the same code on standard and free-threaded Python.

The scheduling policy is a frozen dataclass. It is a capability in the same sense as MaxLen or Paginated — it carries compile methods and is consumed by fold. Adding a custom scheduling policy requires implementing SchedulingCompilable — same Protocol pattern as everywhere else.

### 3.4.3 Concurrency Without Shared Mutable State

The critical property of theworld's concurrency model is that computations share NO mutable state. The Log is append-only — concurrent appends are the only write operation, and they are serialized by the Log's internal mechanism (asyncio lock for InMemoryLog, Kafka producer for KafkaLog). Scopes are hierarchical — each computation has its own scope; parent-child scope access is read-only upward.

SICP identifies the fundamental problem of concurrent state: "a computation might read a shared variable, compute a new value, and write it back — but another computation might have modified the variable in between." In theworld, there is no "write back." There is only "append to Log." Two computations that observe the same events and produce the same results produce duplicate events — which are harmless (sets deduplicate naturally).

This is why mortal workers produce immortal results. Not because of a clever coordination protocol, but because the architecture makes coordination unnecessary. Append-only + read-through-Lens = coordination-free.

---

## 3.5 The Log as Stream

We've gained a good understanding of the Log as a tool for modeling state, as well as an appreciation of the problems that mutable state raises and the Log avoids. Let us step back and ask: what IS the Log, mathematically?

### 3.5.1 The Log Is the Stream That Never Forgets

In SICP, Chapter 3.5 introduces streams as an alternative to assignment for modeling state. A stream is a (possibly infinite) sequence, lazily evaluated. Instead of a bank account with a mutable balance, you have a stream of transaction events: `(deposit 100) (withdraw 50) (deposit 200) ...`. The current balance is the fold of this stream.

SICP's streams are ephemeral — once consumed, the elements are gone. They model time without mutation, but they do not model *history*. If you want the balance at time t, you must replay the stream from the beginning.

The Log is a stream that remembers. Events, once appended, remain queryable. The Log is both a stream (new events arrive) and an archive (old events are accessible). This is Helland's insight: "the truth is the log."

In SICP's terms: the Log is `cons-stream` where the elements are never garbage collected. In functional programming terms: the Log is a persistent data structure that grows monotonically.

### 3.5.2 Two-Level Fold

The query pattern in theworld uses two levels of fold:

**Level 1: Capabilities → Lens.** A Computation's capabilities fold into a Lens — a description of what events to observe. `select.self()` adds `OfIdentity(computation.identity)`. `select.type(MarketTick)` adds `OfType(MarketTick)`. The result is a Lens with a tuple of LensOps.

**Level 2: LensOps × Backend → Events.** The Lens ops fold through a backend context. For InMemoryLog: `OfType(MarketTick)` does O(1) type-index lookup. `OfIdentity("BTC")` filters by identity. `After(cursor)` filters by position. For KafkaLog: `OfType` maps to topic. `OfIdentity` maps to key. `After` maps to offset.

This is the Left Kan Extension pattern (Milewski 2018): Level 1 builds the free structure (Lens), Level 2 interprets it in a concrete backend. Adding a new backend = adding a new Level 2 fold. Capabilities and Lenses don't change.

### 3.5.3 Infinite Streams and Continuous Computation

theworld Computations with `flow.continuous()` run indefinitely — they continuously observe the Log and react to new events. This is the emergent analog of SICP's infinite streams: `ones`, `integers`, `fibs` — streams that never end.

```python
agent = life("listener",
    select.type(MarketTick),
    ReactToTicks(),
    flow.continuous(),
)
```

The `subscribe()` method on the Log returns an async iterator — new events as they arrive. The Computation processes each event through its capabilities. The "stream" is the Log; the "consumer" is the fold of Lens ops; the "processing" is the fold of action capabilities.

SICP asks whether we could model change without mutation. theworld answers: yes. The Log grows. Events accumulate. Computations observe. Derived state changes — but nothing is mutated. The Log is append-only. The Computations are frozen capabilities. The fold is pure. The illusion of change arises from the accumulation of immutable facts.

### 3.5.4 The Tension Revisited

SICP Chapter 3 leaves the tension between objects and streams unresolved. The final paragraphs acknowledge that both approaches have merits: objects provide natural modularity for systems where components have distinct identities, while streams provide referential transparency and avoid the problems of assignment. "The question of which modeling technique leads to more modular and more easily maintained systems remains open."

SICP is honest about why the tension persists. The problem is fundamental: if we model the world as objects with state, we must confront identity ("is this the same account?"), change ("the balance was 100, now it's 50"), and concurrency ("two threads modifying the same balance"). If we model the world as streams, we avoid these problems but struggle with the practical reality that systems have interacting components — a bank account that responds to withdrawals, a worker that reads tasks and produces solutions.

theworld does not compromise between these positions. It dissolves the tension by identifying a structure that is simultaneously object-like and stream-like: the **Computation observing the Log**.

A Computation LOOKS like an object:
- It has identity: `life("trader", ...)` — the trader is a named entity.
- It has behavior that depends on history: the trader's next action depends on all market ticks and orders it has observed.
- It interacts with other computations: the trader emits OrderPlaced events that the risk manager observes.

A Computation IS a stream processor:
- It has no mutable state: its capabilities are frozen, its definition is immutable.
- It folds over an immutable log: `Lens().of_type(MarketTick)` produces a view of the log.
- Its "state" is a derived value: `fold(lens.query(log))` — the result of a pure function applied to immutable data.
- It produces new data by appending to the log: `put(log, OrderPlaced(...))` — no mutation, only growth.

The resolution is this: the Log is BOTH the shared state (all computations see it) AND the communication channel (all computations write to it). It replaces mutable variables (the balance is the fold of deposit/withdrawal events), message queues (events are the messages), shared databases (the Log IS the database), and coordination protocols (workers coordinate by querying the Log for unclaimed work).

There is no compromise. The object view and the stream view are not in tension — they are two perspectives on the same thing. The Computation-observing-the-Log is an object (has identity, has behavior, interacts). It is also a stream processor (pure fold over immutable data). The duality is resolved because the Log provides what objects need (shared state, communication) through what streams are (immutable, append-only, referentially transparent).

This is not merely an engineering trade-off. It is a philosophical position: **change is not mutation. Change is accumulation.** The balance does not change from 100 to 50. Rather, a Withdrawal event is appended to the Log, and the derived balance — the fold of all events — is now 50. The old balance (100) is not overwritten. It is still there, derivable from the sub-log before the withdrawal. The Log is the complete history. The "current state" is a function of the complete history, computed on demand.

SICP's Heraclitus: "Even while it changes, it stands still." The Log stands still — events never change, never move, never disappear. But the view through the Lens changes — new events arrive, the derived state evolves, the computation's behavior adapts. The river flows. The water is new. The river is the same.

This resolution has a practical consequence that SICP's unresolved tension does not: **concurrency becomes trivial.** In a mutable-state world, two threads writing to the same balance require locks, semaphores, transactions, or software transactional memory. In the Log world, two computations appending events require nothing — append is the only write operation, and it is atomic by construction (the Log serializes appends internally). There are no data races because there is no shared mutable data. There are no deadlocks because there are no locks. There are no lost updates because updates are appends, and appends are never lost.

The mortal workers of Section 1.1.7 are the proof. Three workers, dying every 30 seconds, coordinating without a protocol, without a coordinator, without a lock. They coordinate through the Log — the thing that is simultaneously their shared state and their communication channel. The Log does not know it is being used for coordination. It is just an append-only sequence of facts. The coordination emerges from the facts and the workers' pure-function queries over them.

In Chapter 4, we will turn from how systems are organized to how the compilation framework itself is organized. We will see that fold — the six-line function that has been our constant companion — is not merely a useful utility. It is an evaluator, and like SICP's metacircular evaluator, it determines the meaning of capabilities. To appreciate this is to change our image of ourselves as programmers: we come to see ourselves as designers of compilation languages, rather than only users of compilation frameworks designed by others.

---

## Exercises

**Exercise 3.1.** SICP 3.1 opens with a bank account that has mutable state. Design a bank account using the Log model: `Deposit` and `Withdrawal` events, balance derived by fold. Show that two concurrent deposits cannot produce an incorrect balance (compare with SICP's serialization problem). What is the trade-off — what does the Log model cost that the mutable model doesn't?

**Exercise 3.2.** In the mortal workers example, two workers may grab the same chunk simultaneously. Both compute. Both emit RowResult. The coordinator uses a set to deduplicate. Design a more complex scenario where duplication IS harmful — say, a payment system where charging a customer twice is unacceptable. How would you prevent duplicate execution using only the Log? (Hint: consider the IdempotencyKey pattern — checking for existence before executing.)

**Exercise 3.3.** Lamport (1978) defines "happened before" as the transitive closure of (a) sequential ordering within a process and (b) send-before-receive for messages. In theworld, what constitutes "happened before"? Define it formally in terms of Log positions and Lens queries. Show that `After(cursor)` implements Lamport's "happened before" for single-log systems.

**Exercise 3.4.** The AwaitConsistent Lens op blocks until named computations have processed up to the caller's cursor. On InMemoryLog, this is a no-op (single event loop = already consistent). Implement AwaitConsistent for a hypothetical two-node system where each node has its own InMemoryLog and events are replicated asynchronously. What guarantees can you provide? What can you NOT guarantee?

**Exercise 3.5.** SICP 3.5 implements streams as delayed lists — `cons-stream` with lazy evaluation. theworld's Log is a stream that never forgets. Design a `forget` operation on the Log that removes events older than a given cursor. What invariants break? Which computations would produce different results? Is there a safe way to compact the Log? (Hint: ViewSnapshot.)

**Exercise 3.6.** Helland (2015): "The truth is the log. The database is a cache of a subset of the log." Design a caching layer for theworld that maintains an in-memory index of the latest event per identity-type pair (like a key-value store). This cache IS Helland's "database." Show that the cache can be reconstructed from the Log at any time. What happens when the cache is stale?

**Exercise 3.7.** The cosmos.py example has HTTP-over-Log: requests and responses travel through the Log as events at an address. Design a WebSocket-over-Log protocol: bidirectional, persistent, multiplexed. What event types do you need? How does the server route messages to the correct client? How do you handle client disconnect? Is this more or less complex than TCP WebSockets?

**Exercise 3.8.** SICP 3.4 discusses the "joint bank account" problem: two processes simultaneously withdrawing from a shared account. In theworld, two computations simultaneously emit conflicting events. Design a reservation system (hotel rooms) using the Log. A room can only be booked once. Two computations try to book the same room simultaneously. How do you resolve the conflict using only append-only events? (Hint: first-writer-wins with a query-before-emit check. What's the race window?)

**Exercise 3.9.** theworld's scoped() creates a fold boundary for Supervised and other modifiers. Design a scoped() variant that creates a LOG boundary — a sub-Log that is visible only within the scope. Events written to the sub-Log are not visible to the parent World. Events from the parent World ARE visible to the sub-scope. What would this enable? What would it break?

**Exercise 3.10.** Moseley and Marks (2006) classify state as essential (user cares about it) or accidental (implementation artifact). For a chat application with theworld (users, rooms, messages), enumerate: (a) essential state (what events does the user generate?), (b) essential logic (what relationships must hold?), (c) accidental state (what derived data improves performance?). Design the event types and Lens queries for each.