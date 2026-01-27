from kungfu import Error, Ok, Result
from pydantic import BaseModel
from emergent import wire as W

from emergent.wire import endpoint, application
from examples.ops_composition_example import (
    BuildSummary,
    GetPrice,
    GetStock,
    runner as ops_runner,
)


class BuildSummaryIn(BaseModel):
    product_id: int

    def to_domain(self) -> BuildSummary:
        pi = self.product_id
        return BuildSummary(product_id=pi, price=GetPrice(pi), stock=GetStock(pi))


class BuildSummaryOut(BaseModel):
    summary: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> "BuildSummaryOut":
        match dom:
            case Ok(sum):
                return cls(summary=sum)
            case Error(e):
                return cls(summary=f"Can't build summary: {e}")


endp = endpoint(ops_runner).expose(
    trigger=W.triggers.http.HTTPRouteTrigger(path="/build", method="GET"),
    codec=W.codecs.RequestResponseCodec(
        request=BuildSummaryIn, response=BuildSummaryOut
    ),
)

app = application().mount(endp)


fastapi_app = W.contrib.fastapi.from_application(app)
# Run yourself with uvicorn and look at the docs!
