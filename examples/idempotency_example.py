"""
Idempotency Example — operations execute exactly once per key.

Run: uv run python examples/idempotency_example.py
"""

import asyncio
from dataclasses import dataclass

from kungfu import Ok, Error, LazyCoroResult
from combinators import lift as L

from emergent import idempotency as I
from examples._infra import banner, run


# ═══════════════════════════════════════════════════════════════════════════════
# Domain
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Payment:
    tx_id: str
    amount: float


call_count = 0


def charge(order_id: str) -> LazyCoroResult[Payment, str]:
    """Simulate payment API call."""

    async def impl() -> Payment:
        global call_count
        call_count += 1
        print(f"  [API] Charging order {order_id} (call #{call_count})")
        await asyncio.sleep(0.05)
        return Payment(tx_id=f"tx_{order_id}_{call_count}", amount=99.99)

    return L.catching_async(impl, on_error=str)


# ═══════════════════════════════════════════════════════════════════════════════
# Idempotent Executor
# ═══════════════════════════════════════════════════════════════════════════════

executor = (
    I.idempotent(charge)
    .key(lambda order_id: f"payment:{order_id}")
    .policy(I.Policy().with_ttl(hours=1))
    .build()
)


# ═══════════════════════════════════════════════════════════════════════════════
# Demo
# ═══════════════════════════════════════════════════════════════════════════════


async def main() -> None:
    global call_count
    banner("Idempotency")

    # 1. First call — executes
    print("\n1. First call:")
    r1 = await executor.run("order-123")
    match r1:
        case Ok(r):
            print(f"   tx={r.value.tx_id}, cached={r.from_cache}")
        case Error(e):
            print(f"   error: {e}")
    print(f"   API calls: {call_count}")

    # 2. Retry — cached
    print("\n2. Retry (same key):")
    r2 = await executor.run("order-123")
    match r2:
        case Ok(r):
            print(f"   tx={r.value.tx_id}, cached={r.from_cache}")
        case Error(e):
            print(f"   error: {e}")
    print(f"   API calls: {call_count} (no new call!)")

    # 3. Different key — executes
    print("\n3. Different key:")
    r3 = await executor.run("order-456")
    match r3:
        case Ok(r):
            print(f"   tx={r.value.tx_id}, cached={r.from_cache}")
        case Error(e):
            print(f"   error: {e}")
    print(f"   API calls: {call_count}")

    print(f"\nSummary: {call_count} API calls for 3 requests")


if __name__ == "__main__":
    run(main)
