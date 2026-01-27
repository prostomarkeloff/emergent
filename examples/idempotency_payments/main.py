"""
Idempotent Payments Example

Run: uv run python examples/idempotency_payments/main.py
"""

import uuid

from combinators import batch, lift as L
from kungfu import Ok, Error

from examples._infra import run, banner
from examples.idempotency_payments.db import create_database
from examples.idempotency_payments.service import (
    PaymentService,
    PaymentProvider,
    CreateOrderRequest,
)


async def main() -> None:
    banner("Idempotent Payments")

    session_factory, engine = await create_database()
    provider = PaymentProvider()
    service = PaymentService(session_factory, provider)

    try:
        # 1. First request
        print("1. First request:")
        req = CreateOrderRequest(
            idempotency_key=f"order_{uuid.uuid4().hex[:8]}",
            customer_id="cust_123",
            amount_cents=9999,
        )
        r1 = await service.create_order(req)
        match r1:
            case Ok(order):
                print(f"   Order: {order.id}, TX: {order.transaction_id}")
            case Error(e):
                print(f"   Error: {e.code}")
        print(f"   API calls: {provider.call_count}\n")

        # 2. Retry (cached)
        print("2. Retry (cached):")
        r2 = await service.create_order(req)
        match r2:
            case Ok(order):
                print(f"   Order: {order.id}, TX: {order.transaction_id}")
            case Error(e):
                print(f"   Error: {e.code}")
        print(f"   API calls: {provider.call_count} (no new call!)\n")

        # 3. Concurrent (5 requests via combinators.batch)
        print("3. Concurrent (5 requests):")
        concurrent_req = CreateOrderRequest(
            idempotency_key=f"order_{uuid.uuid4().hex[:8]}",
            customer_id="cust_456",
            amount_cents=19999,
        )
        before = provider.call_count

        await batch(
            range(5),
            handler=lambda _: L.catching_async(
                lambda: service.create_order(concurrent_req),
                on_error=str,
            ),
            concurrency=5,
        )
        print(f"   API calls: {provider.call_count - before} (only 1!)\n")

        print(f"Summary: {provider.call_count} API calls for 7 requests")

    finally:
        await engine.dispose()


if __name__ == "__main__":
    run(main)
