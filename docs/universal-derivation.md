# Universal Derivation

Derive anything from anything. One domain, three algebras, full composition.

All examples below are from a single trading platform. Runnable:

```bash
uv run python docs/_test_universal_derive_examples.py
```

---

## The domain

Three types, three algebras, every kind of composition:

| Type | Kind | Algebras |
|------|------|----------|
| `Instrument` | Entity (dataclass) | CRUD + risk rules |
| `Order` | Entity (dataclass) | CRUD (readonly) + state machine + lifecycle endpoints + risk rules |
| `RiskEngine` | Plain class (NOT entity) | Methods + risk rules |

Two custom algebras reusable across all types:

- **State Machine** — `Lifecycle` capability → `StateMachineCtx` (transitions, guards, terminal states)
- **Risk Rules** — `RiskChecks` capability → `RulesCtx` (rules with severity) AND bridge to wire.derive endpoint

---

## Custom algebra: State Machine (Level 3)

Own context, own protocol, own compile. Not tied to wire.derive. Not endpoints.

```python
@dataclass(frozen=True, slots=True)
class TransitionDef:
    action: str
    source: str
    target: str
    guard: str = ""  # "risk_score < threshold"

@dataclass(frozen=True, slots=True)
class StateMachineCtx:
    subject: type
    initial_state: str = ""
    transitions: tuple[TransitionDef, ...] = ()
    terminal_states: frozenset[str] = frozenset()

@runtime_checkable
class StateMachineDerivable(Protocol):
    def derive_state_machine(self, ctx: StateMachineCtx) -> StateMachineCtx: ...

def compile_state_machine(cls: type) -> StateMachineCtx:
    return fold_schema(
        cls, StateMachineCtx(subject=cls),
        StateMachineDerivable, "derive_state_machine",
    )
```

Capability:

```python
@dataclass(frozen=True, slots=True)
class Lifecycle(SchemaCapability):
    initial: str
    transitions: tuple[tuple[str, str, str], ...]
    terminal: frozenset[str] = frozenset()
    guards: dict[str, str] = dataclass_field(default_factory=dict)

    def derive_state_machine(self, ctx: StateMachineCtx) -> StateMachineCtx:
        defs = tuple(
            TransitionDef(
                action=action, source=src, target=tgt,
                guard=self.guards.get(action, ""),
            )
            for action, src, tgt in self.transitions
        )
        return replace(
            ctx,
            initial_state=self.initial,
            transitions=(*ctx.transitions, *defs),
            terminal_states=ctx.terminal_states | self.terminal,
        )
```

This algebra has NO knowledge of HTTP, endpoints, or wire.derive. Pure domain logic.

---

## Custom algebra: Risk Rules (Level 3 + Bridge)

Dual-protocol capability — implements its own algebra AND bridges to wire.derive.

```python
@dataclass(frozen=True, slots=True)
class RiskRule:
    name: str
    severity: str  # "warning" | "block"
    condition: str
    message: str

@dataclass(frozen=True, slots=True)
class RulesCtx:
    subject: type
    rules: tuple[RiskRule, ...] = ()
    max_severity: str = "warning"

@runtime_checkable
class RiskDerivable(Protocol):
    def derive_risk(self, ctx: RulesCtx) -> RulesCtx: ...

def compile_risk_rules(cls: type) -> RulesCtx:
    return fold_schema(cls, RulesCtx(subject=cls), RiskDerivable, "derive_risk")
```

The capability implements **two protocols** — the bridge pattern:

```python
@dataclass(frozen=True, slots=True)
class RiskChecks(SchemaCapability):
    rules: tuple[tuple[str, str, str, str], ...]

    # Protocol 1: own algebra → RulesCtx
    def derive_risk(self, ctx: RulesCtx) -> RulesCtx:
        defs = tuple(
            RiskRule(name=n, severity=s, condition=c, message=m)
            for n, s, c, m in self.rules
        )
        max_sev = "block" if any(r.severity == "block" for r in defs) else ctx.max_severity
        return replace(ctx, rules=(*ctx.rules, *defs), max_severity=max_sev)

    # Protocol 2: bridge → wire.derive, generates GET /risk-rules endpoint
    def compile_derive_generate(self, ctx: DeriveCtx) -> DeriveCtx:
        # Run own algebra internally
        rules_ctx = self.derive_risk(RulesCtx(subject=ctx.entity))
        rules_snapshot = rules_ctx.rules
        subject = ctx.entity
        # ... build handler returning rules as JSON ...
        return ctx.add_operation((op_type, annotated, exposure))
```

Same `@schema_meta`, same capability — two completely different outputs depending on which fold runs.

---

## Lifecycle Bridge: State Machine → Endpoints

`LifecycleBridge` reads the state machine algebra and generates one POST endpoint per transition:

```python
@dataclass(frozen=True, slots=True)
class LifecycleBridge(SchemaCapability):
    base_path: str

    def compile_derive_generate(self, ctx: DeriveCtx) -> DeriveCtx:
        sm_ctx = compile_state_machine(ctx.entity)  # run Level 3 algebra
        for tr in sm_ctx.transitions:
            # generate POST /api/orders/validate, POST /api/orders/submit, etc.
            ctx = ctx.add_operation((op_type, handler, exposure))
        return ctx
```

This is composition: Level 3 algebra produces data, bridge converts it to endpoints.

---

## Putting it together

### Instrument: entity + CRUD + risk rules

```python
@schema_meta(
    http_crud("/api/instruments", InstrumentStore, ops=(LIST, GET, CREATE, DELETE)),
    RiskChecks(rules=(
        ("max_notional", "block", "notional > 10_000_000",
         "Single instrument notional exceeds $10M limit"),
        ("illiquid_check", "warning", "avg_volume < 1000",
         "Low liquidity instrument — manual review recommended"),
    )),
    Paginated(50),
)
@dataclass
class Instrument:
    id: Annotated[int, Identity]
    symbol: str
    exchange: str
    currency: str
```

Result:

```
Entity: Instrument
  Fields: id, symbol, exchange, currency
  Identity: id
  Provider: InstrumentStore
Operations (4 specs):
  List: GET /api/instruments [Read, Pageable, Sortable] ()
  Get: GET /api/instruments/{id} [Read, Idempotent, Cacheable] (id)
  Create: POST /api/instruments [Creates] (symbol, exchange, currency)
  Delete: DELETE /api/instruments/{id} [Deletes, Idempotent] (id)
Direct operations: 1
  InstrumentRiskRulesOp: GET /api/instrument/risk-rules
```

Simultaneously through risk rules algebra:

```python
rules_ctx = compile_risk_rules(Instrument)
# → RulesCtx(rules=(RiskRule("max_notional", "block", ...), RiskRule("illiquid_check", "warning", ...)))
```

### Order: entity + CRUD (readonly) + state machine + lifecycle endpoints + risk rules

Three algebras on one type. CRUD + Lifecycle + LifecycleBridge + RiskChecks + Readonly — all compose.

```python
@schema_meta(
    http_crud("/api/orders", OrderStore),
    Lifecycle(
        initial="new",
        transitions=(
            ("validate", "new", "validated"),
            ("submit", "validated", "submitted"),
            ("fill", "submitted", "filled"),
            ("partial_fill", "submitted", "partial"),
            ("cancel", "new", "cancelled"),
            ("cancel", "validated", "cancelled"),
            ("cancel", "submitted", "cancelled"),
            ("reject", "submitted", "rejected"),
        ),
        terminal=frozenset({"filled", "cancelled", "rejected"}),
        guards={
            "submit": "risk_score < threshold",
            "fill": "available_quantity >= order_quantity",
        },
    ),
    LifecycleBridge(base_path="/api/orders"),
    RiskChecks(rules=(
        ("max_order_size", "block", "quantity > 100_000",
         "Order quantity exceeds 100K limit"),
        ("price_deviation", "warning", "abs(price - mid) / mid > 0.05",
         "Price deviates >5% from mid"),
        ("self_trade", "block", "counterparty == self",
         "Self-trading detected"),
    )),
    Readonly(),
)
@dataclass
class Order:
    id: Annotated[int, Identity]
    instrument_id: int
    side: str
    quantity: int
    price: float
    status: str
```

Result — 11 endpoints from one `@schema_meta`:

```
Operations (2 specs):                          ← CRUD, filtered by Readonly
  List: GET /api/orders [Read, Pageable, Sortable] ()
  Get: GET /api/orders/{id} [Read, Idempotent, Cacheable] (id)
Direct operations: 9                           ← 8 lifecycle + 1 risk-rules
  OrderValidateOp: POST /api/orders/validate
  OrderSubmitOp: POST /api/orders/submit
  OrderFillOp: POST /api/orders/fill
  OrderPartial_FillOp: POST /api/orders/partial_fill
  OrderCancelOp: POST /api/orders/cancel      ← 3 cancel transitions (from 3 states)
  OrderCancelOp: POST /api/orders/cancel
  OrderCancelOp: POST /api/orders/cancel
  OrderRejectOp: POST /api/orders/reject
  OrderRiskRulesOp: GET /api/order/risk-rules
```

Simultaneously — Level 3 standalone outputs from the SAME capabilities:

```python
sm_ctx = compile_state_machine(Order)
# initial=new, 8 transitions, terminal={filled, cancelled, rejected}
# new --validate--> validated
# validated --submit [risk_score < threshold]--> submitted
# submitted --fill [available_quantity >= order_quantity]--> filled
# submitted --partial_fill--> partial
# ...

rules_ctx = compile_risk_rules(Order)
# 3 rules: max_order_size (block), price_deviation (warning), self_trade (block)
```

Three folds, three outputs, same capabilities, same `@schema_meta`.

### RiskEngine: NOT an entity — service class + methods + risk rules

No dataclass. No fields. No identity. Not an entity at all.

```python
@schema_meta(
    Methods(),
    RiskChecks(rules=(
        ("engine_load", "warning", "cpu_usage > 0.9",
         "Risk engine CPU above 90%"),
        ("stale_data", "block", "data_age_seconds > 30",
         "Market data is stale — risk calculations unreliable"),
    )),
)
class RiskEngine:
    @staticmethod
    @post("/api/risk/evaluate")
    async def evaluate(instrument_id: int, quantity: int, price: float) -> Result[dict, DomainError]:
        notional = quantity * price
        risk_score = min(notional / 1_000_000, 10.0)
        return Ok({
            "instrument_id": instrument_id,
            "notional": notional,
            "risk_score": round(risk_score, 2),
            "approved": risk_score < 5.0,
        })

    @staticmethod
    @get("/api/risk/status")
    async def status() -> Result[dict, DomainError]:
        return Ok({"status": "healthy", "engine": "RiskEngine", "version": "2.1"})
```

Result:

```
Entity: RiskEngine
  Fields:                                     ← empty — not an entity
Direct operations: 3
  RiskEngineEvaluateOp: POST /api/risk/evaluate
  RiskEngineStatusOp: GET /api/risk/status
  RiskEngineRiskRulesOp: GET /api/riskengine/risk-rules
```

### Cross-algebra: all types, all algebras

```python
# wire.derive → endpoints
for cls in (Instrument, Order, RiskEngine):
    ctx = compile_derive(cls)
    endpoint = materialize(ctx)
    # Instrument: entity=True,  specs=4, ops=1,  exposures=5
    # Order:      entity=True,  specs=2, ops=9,  exposures=11
    # RiskEngine: entity=False, specs=0, ops=3,  exposures=3

# State machine algebra → StateMachineCtx
for cls in (Instrument, Order, RiskEngine):
    sm = compile_state_machine(cls)
    # Instrument: none (no Lifecycle)
    # Order:      8 transitions
    # RiskEngine: none (no Lifecycle)

# Risk rules algebra → RulesCtx
for cls in (Instrument, Order, RiskEngine):
    rules = compile_risk_rules(cls)
    # Instrument: 2 rules, max_severity=block
    # Order:      3 rules, max_severity=block
    # RiskEngine: 2 rules, max_severity=block
```

Each fold sees only the capabilities that implement its protocol. Unknown capabilities are silently skipped (open-world). Same `@schema_meta`, different views.

---

## How it works

Three primitives:

1. **`@schema_meta(*caps)`** — attaches capabilities to any class. Plain `setattr`. No type inspection.

2. **`fold_schema(cls, ctx, protocol, method)`** — iterates `get_schema_meta(cls)`, calls `method` on each capability matching `protocol`, accumulates into `ctx`. Any class, any context type, any protocol.

3. **`isinstance` dispatch** — each capability implements the protocols it cares about. `RiskChecks` implements both `RiskDerivable` and `DeriveGeneratable`. `Lifecycle` implements only `StateMachineDerivable`. The fold skips what doesn't match.

`compile_derive` = `fold_schema` with `DeriveCtx` + 3 protocols.
`compile_state_machine` = `fold_schema` with `StateMachineCtx` + 1 protocol.
`compile_risk_rules` = `fold_schema` with `RulesCtx` + 1 protocol.

Same fold. Different contexts. Different outputs.

### Recipe

1. **Context** — frozen dataclass accumulator
2. **Protocol** — `@runtime_checkable`, one method: `def derive_X(self, ctx: MyCtx) -> MyCtx`
3. **Capabilities** — `SchemaCapability` + protocol method. Optionally also `compile_derive_generate` for wire.derive bridge
4. **Compile** — `fold_schema(cls, MyCtx(subject=cls), MyDerivable, "derive_X")`
5. **Bridge** (optional) — same capability implements `compile_derive_generate`, runs own algebra internally, converts result to wire operations
