"""
Ops Composition — operations depending on other operations.

Handler receives Op instances with .get() method.
nodnod executes dependencies in parallel automatically.

Level 5: emergent.ops
Level 2: kungfu.Result
"""

from dataclasses import dataclass
from kungfu import Result, Ok, Error
from emergent import ops as O
from examples._infra import banner, run


# ═══════════════════════════════════════════════════════════════════════════════
# Domain
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ProductRepo:
    prices: dict[int, float]
    stock: dict[int, int]


repo = ProductRepo(
    prices={1: 99.99, 2: 149.99},
    stock={1: 42, 2: 0},
)


# ═══════════════════════════════════════════════════════════════════════════════
# Operations — Returning[T, E] with composition via fields
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class GetPrice(O.Returning[float, str]):
    product_id: int


@dataclass(frozen=True, slots=True)
class GetStock(O.Returning[int, str]):
    product_id: int


@dataclass(frozen=True, slots=True)
class BuildSummary(O.Returning[str, str]):
    """Composite operation — depends on GetPrice and GetStock."""

    product_id: int
    price: GetPrice  # ← dependency (executed in parallel)
    stock: GetStock  # ← dependency (executed in parallel)


# ═══════════════════════════════════════════════════════════════════════════════
# Handlers
# ═══════════════════════════════════════════════════════════════════════════════


async def get_price(req: GetPrice, r: ProductRepo) -> Result[float, str]:
    p = r.prices.get(req.product_id)
    return Ok(p) if p else Error("price_not_found")


async def get_stock(req: GetStock, r: ProductRepo) -> Result[int, str]:
    s = r.stock.get(req.product_id)
    return Ok(s) if s is not None else Error("stock_not_found")


async def build_summary(
    req: BuildSummary,
    price: GetPrice,  # ← Op with .get() → cached Result
    stock: GetStock,  # ← Op with .get() → cached Result
) -> Result[str, str]:
    # Dependencies already computed in parallel by nodnod
    p = await price  # instant
    s = await stock  # instant

    match (p, s):
        case (Ok(pv), Ok(sv)):
            status = "in stock" if sv > 0 else "OUT OF STOCK"
            return Ok(f"Product #{req.product_id}: ${pv:.2f}, {sv} units ({status})")
        case (Error(e), _) | (_, Error(e)):
            return Error(e)
        case _:
            return Error("unexpected")


# ═══════════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════════

runner = (
    O.ops()
    .on(GetPrice, get_price)
    .on(GetStock, get_stock)
    .on(BuildSummary, build_summary)
    .compile()
    .inject(ProductRepo, repo)
)


async def main() -> None:
    banner("Ops: Composition (Op depends on Op)")

    print("\n1. Simple op (no dependencies):")
    r1 = await runner(GetPrice(1))
    print(f"   → {r1}")

    print("\n2. Composite op (GetPrice + GetStock in parallel → BuildSummary):")
    r2 = await runner.run(
        BuildSummary(
            product_id=1,
            price=GetPrice(1),
            stock=GetStock(1),
        )
    )
    print(f"   → {r2}")

    print("\n3. Composite with out-of-stock product:")
    r3 = await runner.run(
        BuildSummary(
            product_id=2,
            price=GetPrice(2),
            stock=GetStock(2),
        )
    )
    print(f"   → {r3}")

    print("\n4. Error propagation:")
    r4 = await runner.run(
        BuildSummary(
            product_id=999,
            price=GetPrice(999),
            stock=GetStock(999),
        )
    )
    print(f"   → {r4}")

    print("\nDone!")


if __name__ == "__main__":
    run(main)
