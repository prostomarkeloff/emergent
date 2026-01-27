"""
Ops — data-driven dispatch with automatic DI and parallelization.

Replaces match/case with declarative registration:
    from emergent import ops as O

    @dataclass(frozen=True, slots=True)
    class GetUser(O.Returning[User, NotFound]):
        user_id: int

    async def get_user(req: GetUser, db: Database) -> Result[User, NotFound]:
        return await db.get(req.user_id)

    runner = O.ops().on(GetUser, get_user).compile().inject(Database, db)
    result = await runner.run(GetUser(42))

Composition (handlers receive Op with .get()):
    @dataclass(frozen=True, slots=True)
    class BuildSummary(O.Returning[str, str]):
        product_id: int
        price: GetPrice    # Dependency
        stock: GetStock    # Dependency

    async def build_summary(
        req: BuildSummary,
        price: GetPrice,    # has .get() → cached Result
        stock: GetStock,    # has .get() → cached Result
    ) -> Result[str, str]:
        p = await price  # instant (already computed in parallel)
        s = await stock
        ...

Policies (retry, timeout, idempotency) are achieved via composition
with combinators.py and other emergent modules: saga, cache, idempotency.
"""

from emergent.ops._graph import (
    Op,
    Returns,
    Returning,
    OpsBuilder,
    Runner,
    ops,
)

__all__ = (
    "Op",
    "Returns",
    "Returning",
    "OpsBuilder",
    "Runner",
    "ops",
)
