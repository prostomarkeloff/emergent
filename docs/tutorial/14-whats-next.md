# What's Next

You made it. Let's take stock.

---

## The four levels

You've seen every level of control emergent offers:

| Level | You write | emergent writes | Chapters |
|-------|-----------|----------------|----------|
| **1 — Pure derivation** | Dataclass + `@schema_meta` | Everything | [01](01-first-api.md), [06](06-nested.md), [07](07-multi-target.md) |
| **2 — Derivation + methods** | Dataclass + CRUD + hand-written methods + transforms | CRUD + wiring | [02](02-domain-logic.md), [03](03-pure-methods.md), [04](04-transforms.md), [05](05-auth.md) |
| **3 — Custom dialect** | `DeriveGeneratable` capability, handler templates | Schema inspection, provider binding, compilation | [09](09-custom-handlers.md), [10](10-custom-dialect.md), [11](11-state-machines.md) |
| **4 — Raw wire** | Endpoints, triggers, codecs | Compilation to target framework | [12](12-raw-wire.md), [13](13-bridge.md) |

Mix them freely. `User` at Level 1, `Payment` at Level 2, task queue at Level 3, health check at Level 4. They all compose into the same `Application` and compile together.

## Going deeper

The tutorial continues with advanced topics — the wire internals, the engine that makes all of the above work:

| Part | Chapters | What's in it |
|------|----------|-------------|
| **V — The Query Axis** | [15](15-queries.md), [16](16-providers.md) | Expression ASTs, providers, explain system |
| **VI — Scope, DI & Ops** | [17](17-ops-and-runners.md), [18](18-scope-and-di.md) | Operations, runners, auto-parallelization, dependency injection |
| **VII — Middleware & Storage** | [19](19-enrichers.md), [20](20-storage.md) | Runtime enrichers, KV/queue/pubsub/lock/counter patterns |
| **VIII — Compilation & The Full Picture** | [21](21-compilation.md), [22](22-stateful-codecs.md), [23](23-roulette.md), [24](24-design.md) | The fold primitive, stateful codecs, full multi-target walkthrough, design philosophy |
| **IX — Verify, Explain & The Thesis** | [25](25-verify-and-explain.md), [26](26-llm-sweet-spot.md), [27](27-handing-it-to-the-machine.md) | Verification, self-description, LLM-tractability, agent workflows |

## The reference docs

This tutorial taught you *how* to build things. The reference docs tell you *what exists*:

| Document | What's in it |
|----------|-------------|
| [universal-derivation.md](../universal-derivation.md) | Complete derivation reference: three-phase compilation, DeriveCtx, generators, modifiers, bridges |
| [multi_runtime.md](../multi_runtime.md) | Graph runtime: policies, work-stealing, capabilities, spawnable |
| [cheatsheet.md](../cheatsheet.md) | Every import, every pattern, every transform — at a glance |
| [architecture.md](../architecture.md) | The algebra: free algebras, catamorphisms, staging, sheaf structure |

## Ideas for what to build

If you want to practice:

- **A bookmark manager** with tags, search, and multi-target (HTTP + CLI). Uses: `http_crud`, `cli_crud`, transforms.
- **A simple kanban board** with lanes (backlog -> in-progress -> done). Uses: `WorkflowPattern` or custom transitions.
- **An API gateway** that bridges multiple legacy FastAPI services into one CLI. Uses: bridge, `AddTrigger`, `IsolateGlobal`.
- **Your own dialect** for something domain-specific: a quiz engine, a deployment pipeline, an approval workflow.

---

Ready to go deeper? **Next:** [Talking to Data →](15-queries.md)

Or if you're done building: *The framework is the projection. Your domain is the source. Write the shape. Derive the rest.*
