# emergent test suite

## Principles

1. **Behavioral over structural.** Tests verify that the system does the right thing — not that something exists. `provider.execute(filter(x > 5))` is compared against `[item for item in data if item.x > 5]`. If both agree, the system is correct.

2. **The encoding is the contract.** `fold(items, initial, protocol, method)` — this signature, this dispatch — is the invariant. Every test ultimately verifies that fold produces correct output for given input.

3. **Capabilities test themselves.** A capability declares `compile_pydantic`, `compile_openapi`, `compile_constraints`. Tests verify that the compiled output actually enforces the constraint: `Min(0)` → pydantic rejects `-1`, OpenAPI has `minimum: 0`, constraints has `min_value=0`. Same data, three independent checks.

4. **Cross-target consistency.** Same entity compiled to FastAPI AND testing target → same CRUD behavior. Differential tests catch target-specific bugs.

5. **Random programs find real bugs.** Generative tests build random entities with random capabilities, compile them, fuzz them with random HTTP traffic. This found: `page=0` crash, `OneOf` not enforced by pydantic, non-dict JSON body crash, RFC 9457 violations.

## Structure

```
tests/
  unit/              115 files   fast deterministic tests
  property/           52 files   hypothesis property-based tests
  behavioral/          6 files   oracle-based semantic tests
  integration/         3 files   stateful, metamorphic, differential
  fuzz/                7 files   schemathesis, generative fuzzing
  run.py                         unified runner (light/medium/tough)
  README.md                      this file
```

## Running

```bash
uv run python tests/run.py light     # ~1min   pre-commit
uv run python tests/run.py medium    # ~3min   CI push
uv run python tests/run.py tough     # ~15min  nightly
```

All modes run ALL tests. The difference is fuzzing intensity:
- **light** — hypothesis max_examples=10, skip @slow
- **medium** — hypothesis max_examples=50, all tests, + pyright
- **tough** — hypothesis defaults, + mutation testing, + coverage report, + pyright on tests

## Layers

### unit/ — "does the code run?"
Existing tests from development. Fast, deterministic. Cover specific code paths. Mostly structural assertions (`isinstance`, `len > 0`). Value: regression detection — if code stops executing, these catch it.

### property/ — "do algebraic laws hold?"
Hypothesis generates random inputs. Tests verify invariants:
- **fold**: composition, identity, handler precedence, traced equivalence
- **expr**: boolean algebra laws (De Morgan, commutativity, absorption)
- **simplify**: idempotence, semantic preservation, each rule fires
- **serialize**: roundtrip faithfulness for all 21 expression types
- **compiler algebra**: SchemaCompiler/TargetCompiler laws with ordered lists + instance bias
- **coverage**: structural tests for 93% line coverage on wire/ + ops/

### behavioral/ — "does the system do the right thing?"
Every assertion checks a computed VALUE against an independent oracle:
- **query**: filter/sort/limit results compared against Python list comprehension
- **schema**: `Min(0)` rejects `-1`, `OneOf("a","b")` rejects `"c"` — actual validation
- **storage**: roundtrip preserves every field value
- **coerce**: coerced expression evaluates same truth value on coerced data
- **cross-axis**: `MaxLen(100)` appears as `max_length=100` in Constraints AND `maxLength=100` in OpenAPI
- **algebra**: `A + B` compiles both phases with correct values, `A | B` overrides correctly

### integration/ — "do operations interact correctly?"
- **stateful**: hypothesis `RuleBasedStateMachine` — random CRUD sequences, model dict == database after every step
- **metamorphic**: create increases count by 1, delete decreases by 1, sort is permutation
- **differential**: same entity compiled to testing target AND FastAPI — same operation → same data

### fuzz/ — "does random traffic break anything?"
- **schemathesis**: compiled FastAPI apps fuzzed via OpenAPI schema — no 500s, no spec violations
- **generative**: random entities with random capabilities (including custom open-world caps) compiled and fuzzed
- **app.py**: pre-built test apps (CRUD, readonly, minimal) for schemathesis
