"""
Saga — transactional inventory + payment with compensation.

Uses emergent.saga for automatic rollback on failure:
1. Reserve inventory for each item
2. Authorize payment
3. On failure → release all reservations
"""

from dataclasses import dataclass

from kungfu import Ok, Error

from emergent import graph as G
from emergent import saga as S
from examples.full_stack.domain import PaymentAuthorization, CheckoutError
from examples.full_stack.repo import (
    inventory_service,
    payment_service,
    InventoryReservation,
)
from examples.full_stack.nodes._items import ItemsDataNode
from examples.full_stack.nodes._user import PaymentMethodNode
from examples.full_stack.nodes._totals import GrandTotalNode
from examples.full_stack.nodes._fraud import FraudCheckNode


@dataclass
class CheckoutTransaction:
    """Result of the saga: reservations + payment auth."""

    reservations: list[InventoryReservation]
    payment: PaymentAuthorization


@G.node
class CheckoutSagaNode:
    """
    Saga: Reserve inventory → Authorize payment.

    Uses emergent.saga for automatic compensation on failure.
    If payment fails, all inventory reservations are released.
    """

    def __init__(self, data: CheckoutTransaction) -> None:
        self.data = data

    @classmethod
    async def __compose__(
        cls,
        items: ItemsDataNode,
        payment_method: PaymentMethodNode,
        total: GrandTotalNode,
        fraud: FraudCheckNode,  # Ensures fraud check runs first
    ) -> "CheckoutSagaNode":
        _ = fraud  # Dependency injection

        # Step 1: Reserve inventory for ALL items
        reservations: list[InventoryReservation] = []

        for item_data in items.items:
            reserve_step: S.SagaStep[InventoryReservation, CheckoutError] = (
                S.from_async(
                    lambda i=item_data: inventory_service.reserve(
                        i.item.product_id, i.item.quantity
                    ),
                    on_error=lambda e: CheckoutError("INVENTORY_ERROR", str(e)),
                    compensate=lambda r: inventory_service.release(r),
                )
            )

            saga_result = await S.run(reserve_step)
            match saga_result:
                case Ok(result):
                    reservations.append(result.value)
                case Error(saga_error):
                    print(
                        f"      [Saga] Inventory failed — rolling back {len(reservations)} reservations"
                    )
                    for res in reservations:
                        await inventory_service.release(res)
                    raise saga_error.error

        # Step 2: Authorize payment
        payment_step: S.SagaStep[PaymentAuthorization, CheckoutError] = S.from_async(
            lambda: payment_service.authorize(payment_method.data, total.total),
            on_error=lambda e: CheckoutError("PAYMENT_ERROR", str(e)),
            compensate=lambda auth: payment_service.void(auth),
        )

        payment_saga_result = await S.run(payment_step)
        match payment_saga_result:
            case Ok(result):
                auth = result.value
                if not auth.approved:
                    print("      [Saga] Payment declined — rolling back inventory")
                    for res in reservations:
                        await inventory_service.release(res)
                    raise CheckoutError("PAYMENT_DECLINED", "Card declined")

                return cls(CheckoutTransaction(reservations, auth))

            case Error(saga_error):
                print("      [Saga] Payment failed — rolling back inventory")
                for res in reservations:
                    await inventory_service.release(res)
                raise saga_error.error


__all__ = ("CheckoutTransaction", "CheckoutSagaNode")
