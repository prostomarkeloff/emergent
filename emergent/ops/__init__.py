"""
Ops — data-driven dispatch with automatic DI.

Clean functional style:
    from emergent import ops as O

    @dataclass(frozen=True, slots=True)
    class GetPrice(O.Op[float, str]):
        product_id: int

    async def get_price(req: GetPrice, db: Database) -> Result[float, str]:
        return Ok(await db.get_price(req.product_id))

    runner = (
        O.ops()
        .on(GetPrice, get_price)
        .compile()
        .inject(Database, db)
    )
    
    result = await runner.run(GetPrice(123))

With composition (handlers receive Op instances with .get()):
    @dataclass(frozen=True, slots=True)
    class BuildSummary(O.Op[str, str]):
        product_id: int
        price: GetPrice    # Dependency
        stock: GetStock    # Dependency

    async def build_summary(
        req: BuildSummary,
        price: GetPrice,    # Op with .get() method
        stock: GetStock,    # Op with .get() method
    ) -> Result[str, str]:
        p = await price  # or price.get()
        s = await stock
        
        match (p, s):
            case (Ok(pv), Ok(sv)): return Ok(f"${pv}, {sv} units")
            case _: return Error("failed")
"""

# Clean API
from emergent.ops._graph import (
    Op,
    Returns,
    Returning,
    OpsBuilder,
    Runner,
    ops,
)

# Policy
from emergent.ops._policy import (
    Policy,
    Retry,
    Timeout,
    IdemSpec,
    WAIT,
    FAIL,
    FORCE,
)

__all__ = (
    # Core
    "Op",
    "Returns",
    "Returning",
    "OpsBuilder",
    "Runner",
    "ops",
    # Policy
    "Policy",
    "Retry",
    "Timeout",
    "IdemSpec",
    "WAIT",
    "FAIL",
    "FORCE",
)
