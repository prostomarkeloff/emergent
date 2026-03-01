# Raw Wire

Everything derivelib generates compiles down to wire primitives. derivelib is sugar — powerful sugar, but sugar. The wire layer is what actually talks to FastAPI, CLI, Telegram.

Sometimes you need it directly. A health check endpoint. A metrics route. A webhook receiver. Something where derivation makes no sense and you just want to wire a function to a URL.

---

## The fundamental API

One line:

```python
endpoint(runner).expose(trigger, codec, *capabilities)
```

That's the entire surface axis in one expression. A runner (executes domain ops), a trigger (where the endpoint lives), a codec (how requests are processed), and optional capabilities (middleware, metadata).

## A health check

```python
from dataclasses import dataclass

from kungfu import Ok, Result
from pydantic import BaseModel

from emergent.ops import ops
from emergent.wire.axis.surface import endpoint, application
from emergent.wire.axis.surface.codecs import rrc
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.compile.targets import fastapi


# ── Domain op ────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class HealthCheck:
    pass


async def handle_health(op: HealthCheck) -> Result[str, str]:
    return Ok("healthy")


runner = ops().on(HealthCheck, handle_health).compile()


# ── Request / Response ───────────────────────────────────────────────────────

class HealthRequest(BaseModel):
    def to_domain(self) -> HealthCheck:
        return HealthCheck()


class HealthResponse(BaseModel):
    status: str

    @classmethod
    def from_domain(cls, result: Result[str, str]) -> HealthResponse:
        match result:
            case Ok(s):
                return cls(status=s)
            case _:
                return cls(status="unhealthy")


# ── Wire it ──────────────────────────────────────────────────────────────────

app = application().mount(
    endpoint(runner).expose(
        HTTPRouteTrigger("GET", "/health"),
        rrc(HealthRequest, HealthResponse),
    ),
)

fastapi_app = fastapi.compile(app)
```

No `@derive`. No derivelib. Pure wire.

## The RRC codec

`rrc` stands for **request-response codec**. It's the standard execution path:

1. Incoming request → `Request.to_domain()` → domain `Op`
2. `Op` → runner → `Result[T, E]`
3. `Result` → `Response.from_domain(result)` → outgoing response

The codec mediates between the framework world (HTTP body, query params) and the domain world (typed ops and results). Each side speaks its own language; the codec translates.

## Other codecs

`rrc` isn't the only codec:

**`immediate(ResponseType)`** — no runner, no domain op. The response is produced statically. Good for version info, static pages, anything that doesn't need computation.

**`immediate_factory(lambda: ResponseType(...))`** — same, but calls a factory at request time.

**`stateful(FlowType, ResponseType)`** — multi-turn conversations. The codec manages state across interactions (used in Telegram bots).

**`delegate(HandlerType)`** — wraps an existing handler function. Used by the bridge to preserve legacy handler signatures.

## Multiple exposures

The sheaf, at the wire level:

```python
from emergent.wire.axis.surface.triggers.cli import CLITrigger

endp = (
    endpoint(runner)
    .expose(HTTPRouteTrigger("GET", "/health"), rrc(HealthRequest, HealthResponse))
    .expose(CLITrigger("health", "Check service health"), rrc(HealthRequest, HealthResponse))
)
```

One endpoint, two triggers. FastAPI sees the HTTP trigger. CLI sees the CLI trigger. Same runner, same logic, different entry points.

## Mixing wire and derivelib

Wire endpoints compose with derivelib-derived endpoints in the same application:

```python
from derivelib import build_application_from_decorated

# Derived endpoints
derived_app = build_application_from_decorated(User, Product)

# Wire endpoints
wire_app = application().mount(
    endpoint(runner).expose(
        HTTPRouteTrigger("GET", "/health"),
        rrc(HealthRequest, HealthResponse),
    ),
)

# Merge
full_app = derived_app + wire_app

# Compile everything together
fastapi_app = fastapi.compile(full_app)
```

derivelib generates wire Applications. Wire Applications compose with `+`. Everything compiles together. Level 1 entities next to Level 4 raw wire endpoints. No conflict.

---

**Next:** [Bridge →](13-bridge.md)
