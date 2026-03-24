# Appendix A: theworld — Complete Reference

> "Everything is fold. Log is spacetime. Computation is existence."

This appendix provides a comprehensive reference for theworld — the operating system for computational agents built on emergent's encoding. The material here supplements the narrative treatment in Chapter 3, providing the detailed architecture, BEAM comparison, and API reference that a practitioner needs to build systems with theworld.

---

## A.1 Architecture Overview

```
┌──────────────────────────────────────────────────────┐
│                   World (the OS)                      │
│                                                       │
│  Log ═══════════════════════════════════════════════  │
│  │ append-only, type-indexed, push-based (_Notifier) │
│  │ query via Lens (fold over self-compiling ops)     │
│  │ InMemory | Kafka | ClickHouse (backend-agnostic)  │
│  ═══════════════════════════════════════════════════  │
│                                                       │
│  Scope ─────────────────────────────────────────────  │
│  │ parent-chained typed storage (L1 cache)           │
│  │ ScopeFamily: World → Agent → Op tiers             │
│  │ mapped_scopes: nodnod auto-resolves per tier      │
│  ─────────────────────────────────────────────────── │
│                                                       │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐   │
│  │ Agent A │ │ Agent B │ │ Agent C │ │   ...   │   │
│  │ caps=() │ │ caps=() │ │ caps=() │ │         │   │
│  │ frozen  │ │ frozen  │ │ frozen  │ │         │   │
│  └────┬────┘ └────┬────┘ └────┬────┘ └─────────┘   │
│       │           │           │                      │
│       ▼           ▼           ▼                      │
│  nodnod DAG ════════════════════════════════════════  │
│  │ Nodes declare deps in __compose__ signature       │
│  │ nodnod auto-parallelizes independent nodes        │
│  │ Either = fallback, ResultNode = error handling     │
│  ════════════════════════════════════════════════════ │
│                                                       │
│  RuntimePolicy ─────────────────────────────────────  │
│  │ Cooperative: asyncio event loop (default)         │
│  │ WorkStealing: N OS threads, LIFO/FIFO deques      │
│  │ Custom: CallbackAgent + NodeExecutor              │
│  ─────────────────────────────────────────────────── │
└──────────────────────────────────────────────────────┘
```

## A.2 The BEAM Comparison

theworld's design target is BEAM (Erlang VM) — the only production-proven system for massive concurrency + fault tolerance. WhatsApp: 2M connections/server. Discord: millions concurrent.

### A.2.1 Process Model

**BEAM:** Process = `{module, state, mailbox}`. Behavior = code (opaque). To understand what a process does, read the source code of its module.

**theworld:** Computation = `{identity, capabilities}`. Behavior = data (frozen, inspectable). To understand what a computation does: `explain(agent.capabilities)`.

```python
agent = life("trader",
    select.self(),
    select.type(MarketTick),
    KellyCriterion(max_bet=0.2),
    flow.every(1.0),
)

# INSPECTABLE:
explain(agent)  # → "trader: perceives own events + MarketTick, Kelly max_bet 0.2, every 1.0s"

# COMPOSABLE:
extended = replace(agent, capabilities=(*agent.capabilities, BrowserAccess()))

# VERIFIABLE:
issues = fold(agent.capabilities, VerifyCtx(), VerifyCompilable, "compile_verify")
```

**vs BEAM:** `process_info(Pid, dictionary)` → opaque Erlang terms. No structure. No types. No composition.

### A.2.2 Communication

**BEAM mailbox:** Selective receive scans ENTIRE mailbox linearly. 10K messages → 10K comparisons per receive. Cascading slowdown.

**theworld Log:** Type-indexed. O(1) type dispatch → O(bucket_size) identity filter. Push-based notification per type. Full history queryable.

| | BEAM mailbox | theworld Log |
|---|---|---|
| Insert | O(1) | O(1) + type index |
| Lookup by type | O(N) scan | **O(1)** type index |
| Persistence | Transient | **Persistent** |
| Visibility | Only receiver | **Any agent** via Lens |
| History | Consumed = gone | **Full history** |

### A.2.3 Scheduling

**BEAM:** Reduction counting, baked into Erlang bytecode. One reduction per instruction. N reductions per time slice.

**theworld:** RuntimePolicy = pluggable frozen dataclass. Cooperative (asyncio), WorkStealing (N OS threads), custom (CallbackAgent + NodeExecutor). Per-node scheduling via schema_meta fold.

### A.2.4 Supervision

**BEAM:** Static trees in code. `{one_for_one, 5, 60}` hardcoded.

**theworld:** Supervision = capability = data. `Supervised(max_restarts=5, backoff=1.0)` is a frozen dataclass. Evolvable: mutation can change strategy parameters.

### A.2.5 Hot Reload

**BEAM:** `code_change(OldVsn, State, Extra) → {ok, NewState}`. Manual state migration.

**theworld:** `put(log, Reload(capabilities=new_caps))` → HotReloadable diffs nodes, spawns/despawns. No state migration — state is in the Log.

### A.2.6 Summary

| Dimension | BEAM | theworld | Winner |
|---|---|---|---|
| Process model | Code + state | Capabilities (frozen, inspectable) | **theworld** |
| Communication | Mailbox O(N) | Log + Lens O(1) type-indexed | **theworld** |
| Scheduling | Reduction counting | RuntimePolicy (pluggable) | **theworld** |
| Supervision | Static trees | Capabilities (data, evolvable) | **theworld** |
| Hot reload | Manual code_change | Capability swap + verify | **theworld** |
| Distribution | Transparent RPC | Many Worlds + shared Log | **theworld** |
| Verification | Runtime crash | fold verify | **theworld** |
| Raw spawn speed | ~1µs/process | ~39µs/node type | **BEAM** |
| Memory per unit | ~300 bytes | ~600 bytes/type | **BEAM** |

BEAM wins on raw lightweight process creation. theworld wins on everything else.

## A.3 Core Types

### Event[D]

```python
@dataclass(frozen=True, slots=True)
class Event[D]:
    data: D
```

Pure data. No timestamp (capability of the Log). No kind (D's type IS the kind). No identity (capability on D via Identity annotation).

### Log[D]

Protocol: `append(event) → None`, `query(lens) → list[Event]`, `subscribe(lens) → AsyncIterator[Event]`.

Implementations:
- `InMemoryLog` — list + type index + notifiers
- `TieredLog` — routes by tier (Ephemeral/Local/Durable)
- `open_multi_log("db", *compilations)` — SQLite per-type tables via emergent wire SA compilation

### Lens

```python
Lens().of_type(MarketTick).of_identity("BTC").after(cursor)
```

Monoid: `Lens.then(other) = Lens(ops=self.ops + other.ops)`. Ops are frozen dataclasses — same encoding as everywhere. Two-level fold: capabilities → Lens (Level 1), Lens ops → backend context (Level 2).

Built-in ops: `OfType`, `OfIdentity`, `After`, `Deduplicate`, `ExactlyOnce`, `UniqueBy`, `Backpressure`, `AwaitConsistent`, `ViewSnapshot`, `TierFilter`.

Cross-compiled: `Filter`, `OrderBy`, `Limit`, `Offset` (from emergent query axis, via handler maps).

### Computation

```python
agent = life("trader",
    select.self(),                  # LensCompilable → builds Lens
    select.type(MarketTick),        # LensCompilable
    KellyCriterion(max_bet=0.2),    # ActionCompilable → produces events
    flow.every(1.0),                # LifecycleCompilable → timing
)
```

Five fold axes:
| Axis | Protocol | What it builds |
|------|----------|----------------|
| Perception | `compile_lens` | Lens — what the computation observes |
| Action | `compile_action` | Events — what the computation produces |
| Flow | `compile_lifecycle` | Timing — when the computation runs |
| Plan | `compile_plan` | Ops — async IO actions |
| World | `compile_world` | Node registration — how it joins the DAG |

### World

```python
world = World(log=log, computations=(agent, executor, Supervised()), policy=RuntimePolicy())
await world.run()
```

`run()`:
1. `fold(computations, WorldContext(log), WorldCompilable, "compile_world")` → nodes
2. `RuntimeAgent.with_policy(policy).build(nodes)` → agent
3. `agent.run(scope, mapped_scopes)` → execution

## A.4 Patterns

### Mortal Workers

Workers that die and restart, coordinating through the Log. No coordination protocol. No leader election. Query unclaimed work → compute → emit result → die → restart → repeat.

### ViewSnapshot

Materialized view checkpoint as a typed Event in the Log. O(Δ) recovery instead of O(all events). Readable by other computations through Lens.

### Log-HTTP

HTTP over Log — no TCP. Servers bind addresses in the Log. `serve(app, address)`. `call(log, address, method, path, body)`. Requests and responses are events.

### Channels (CSP)

Typed addresses over Log. `channel("tasks").send(log, data)`. `channel("tasks").recv(log, DataType)`. `select(log, case1, case2)` — multiplex across channels.

### Hot Reload

```python
await put(log, Reload(capabilities=(life("agent", ..., NewModel()),)))
```

HotReloadable watches for Reload events. Diffs nodes. Spawns new, despawns old. ReloadApplied confirms.

### Migration

```python
await put(log, NodeFork(life="heavy-worker", capabilities=(...), reason="overload"))
```

Another World watches for NodeFork events, reconstructs and runs the computation.

## A.5 Tiered Storage

```python
log = TieredLog(
    TierBinding(Ephemeral, InMemoryLog()),
    TierBinding(Durable, await open_multi_log("app.db", compile_sa(EventType, "events"))),
)
```

Events carry tier markers. `put(log, event, tier=Durable)` writes to SQLite. `put(log, event, tier=Ephemeral)` writes to memory only. `Lens().tier(Durable)` filters by tier.

SQLite backend uses emergent's wire compilation: `compile_sa(EventType, "table")` produces SQLAlchemy models from frozen dataclass definitions. Same compilation that generates Pydantic models and OpenAPI schemas.

## A.6 The Mathematical Structure

### Free Monoid

Capabilities: `tuple[Cap, ...]`. Concatenation: `caps_a + caps_b`. Identity: `()`. Free monoid — no equations between generators.

### Monoid Homomorphism

Lens: `Lens.then(other) = Lens(ops=self.ops + other.ops)`. `resolve_lens` maps Lens to `(Log → Events)`, preserving composition and identity.

### Catamorphism

`fold(items, initial, protocol, method)` — the unique structurally recursive consumer. At every level: field capabilities, query ops, Lens ops, computations, scheduling traits.

### Kan Extension

Two-level fold = left Kan extension along forgetful functor U: BackendOps → LensOps. Level 1 builds free structure (Lens). Level 2 interprets in concrete backend. New backend = new Level 2 only.