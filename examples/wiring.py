"""Wire example — simple endpoint → FastAPI compilation.

Demonstrates the surface axis: endpoint + trigger + codec → compile to FastAPI.
"""

from kungfu import Error, Ok, Result
from pydantic import BaseModel

from emergent.wire.axis.surface import endpoint, application
from emergent.wire.axis.surface import codecs, triggers
from emergent.wire.compile.targets import fastapi
from examples.ops_composition_example import (
    BuildSummary,
    GetPrice,
    GetStock,
    runner as ops_runner,
)


class BuildSummaryIn(BaseModel):
    """Request model — converts to domain op."""

    product_id: int

    def to_domain(self) -> BuildSummary:
        pi = self.product_id
        return BuildSummary(product_id=pi, price=GetPrice(pi), stock=GetStock(pi))


class BuildSummaryOut(BaseModel):
    """Response model — converts from domain result."""

    summary: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> "BuildSummaryOut":
        match dom:
            case Ok(sum):
                return cls(summary=sum)
            case Error(e):
                return cls(summary=f"Can't build summary: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# Build wire endpoint
# ═══════════════════════════════════════════════════════════════════════════════

endp = endpoint(ops_runner).expose(
    trigger=triggers.http.HTTPRouteTrigger(path="/build", method="GET"),
    codec=codecs.rrc(request=BuildSummaryIn, response=BuildSummaryOut),
)

app = application().mount(endp)


# ═══════════════════════════════════════════════════════════════════════════════
# Compile to FastAPI
# ═══════════════════════════════════════════════════════════════════════════════

fastapi_app = fastapi.compile(app)
# Run with: uvicorn examples.wiring:fastapi_app --reload
# Then visit: http://localhost:8000/docs
