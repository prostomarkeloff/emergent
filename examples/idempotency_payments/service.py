"""
Payment Service — idempotent payments with combinators.
"""

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from kungfu import Result, Ok, Error
from combinators import flow, lift as L

from emergent import idempotency as I

from examples.idempotency_payments.db import OrderTable
from examples.idempotency_payments.domain import (
    Order,
    OrderStatus,
    OrderError,
    OrderErrors,
)
from examples.idempotency_payments.store import create_order_store, OrderPending


# ═══════════════════════════════════════════════════════════════════════════════
# Request / Response
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class CreateOrderRequest:
    idempotency_key: str
    customer_id: str
    amount_cents: int
    currency: str = "USD"
    description: str | None = None


@dataclass(frozen=True, slots=True)
class PaymentResult:
    transaction_id: str
    provider: str


# ═══════════════════════════════════════════════════════════════════════════════
# Payment Provider (simulated)
# ═══════════════════════════════════════════════════════════════════════════════


class PaymentProvider:
    def __init__(self) -> None:
        self.call_count = 0

    async def charge(self, amount: int, currency: str, customer: str) -> PaymentResult:
        self.call_count += 1
        print(f"  [STRIPE] Charging {amount / 100:.2f} {currency}")
        return PaymentResult(
            transaction_id=f"ch_{uuid.uuid4().hex[:16]}",
            provider="stripe",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Payment Service
# ═══════════════════════════════════════════════════════════════════════════════


class PaymentService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider: PaymentProvider,
    ) -> None:
        self._session = session_factory
        self._provider = provider
        self._store = create_order_store(session_factory)

    async def create_order(self, req: CreateOrderRequest) -> Result[Order, OrderError]:
        """Create order with idempotent payment."""
        order_id = f"ord_{uuid.uuid4().hex[:12]}"

        pending = OrderPending(
            order_id=order_id,
            customer_id=req.customer_id,
            amount_cents=req.amount_cents,
            currency=req.currency,
            description=req.description,
        )

        # Idempotent payment via combinators
        executor = (
            I.idempotent(self._charge)
            .key(lambda r: r.idempotency_key)
            .store(self._store.with_pending(pending))
            .policy(I.Policy())
            .build()
        )
        result = await executor.run(req)

        match result:
            case Ok(idem):
                if idem.from_cache:
                    print("  [CACHE HIT]")
                return await self._fetch_order(req.idempotency_key)
            case Error(e):
                return Error(OrderError(e.kind.name, e.message))

    def _charge(self, req: CreateOrderRequest):
        """Charge via provider using combinators."""
        return (
            flow(
                L.catching_async(
                    lambda: self._provider.charge(
                        req.amount_cents, req.currency, req.customer_id
                    ),
                    on_error=lambda e: OrderErrors.provider_error(str(e)),
                )
            )
            .map(lambda p: json.dumps({"tx": p.transaction_id, "provider": p.provider}))
            .compile()
        )

    async def _fetch_order(self, key: str) -> Result[Order, OrderError]:
        async with self._session() as session:
            row = (
                await session.execute(
                    select(OrderTable).where(OrderTable.idempotency_key == key)
                )
            ).scalar_one_or_none()

            if not row:
                return Error(OrderErrors.invalid_request("Not found"))

            # Parse transaction from idempotency_value
            tx_id = None
            if row.idempotency_value:
                data = json.loads(row.idempotency_value)
                tx_id = data.get("tx")

            return Ok(
                Order(
                    id=row.id,
                    idempotency_key=row.idempotency_key,
                    customer_id=row.customer_id,
                    amount_cents=row.amount_cents,
                    currency=row.currency,
                    description=row.description,
                    status=OrderStatus(row.idempotency_status),
                    transaction_id=tx_id,
                    payment_provider=row.payment_provider,
                    error_message=row.idempotency_error,
                    created_at=row.created_at,
                    completed_at=row.completed_at,
                )
            )
