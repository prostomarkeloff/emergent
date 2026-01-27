"""
Idempotency Store — typed SQLAlchemy store for orders.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from emergent.idempotency import SQLAlchemyStore, IdempotencyStatus

from examples.idempotency_payments.db import OrderTable


# ═══════════════════════════════════════════════════════════════════════════════
# Order Config — typed input for pending order creation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class OrderPending:
    """
    Data for creating pending order.

    Note: Typed dataclass — compile-time safety.
    """

    order_id: str
    customer_id: str
    amount_cents: int
    currency: str = "USD"
    description: str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Store Factory
# ═══════════════════════════════════════════════════════════════════════════════


def create_order_store(
    session_factory: async_sessionmaker[AsyncSession],
) -> SQLAlchemyStore[OrderTable, OrderPending]:
    """
    Create typed idempotency store for orders.

    Usage:
        store = create_order_store(session_factory)

        pending = OrderPending(
            order_id="ord_123",
            customer_id="cust_456",
            amount_cents=9999,
        )

        executor = (
            I.idempotent(process)
            .key(lambda req: req.idempotency_key)
            .store(store.with_pending(pending))
            .build()
        )
    """
    return SQLAlchemyStore(
        session_factory=session_factory,
        model=OrderTable,
        to_pending=_create_pending_order,
        to_insert=_create_insert_stmt,
    )


def _create_pending_order(key: str, pending: OrderPending) -> OrderTable:
    """Create pending OrderTable from typed data."""
    return OrderTable(
        id=pending.order_id,
        idempotency_key=key,
        idempotency_status=IdempotencyStatus.PROCESSING,
        customer_id=pending.customer_id,
        amount_cents=pending.amount_cents,
        currency=pending.currency,
        description=pending.description,
        created_at=datetime.now(),
    )


def _create_insert_stmt(model: OrderTable) -> Any:
    """Create INSERT ... ON CONFLICT DO NOTHING."""
    return (
        sqlite_insert(OrderTable)
        .values(
            id=model.id,
            idempotency_key=model.idempotency_key,
            idempotency_status=model.idempotency_status,
            customer_id=model.customer_id,
            amount_cents=model.amount_cents,
            currency=model.currency,
            description=model.description,
            created_at=model.created_at,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
