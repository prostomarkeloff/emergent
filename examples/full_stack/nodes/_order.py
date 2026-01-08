"""
Order — final order creation node.

This is the terminal node that depends on all others.
"""

import time

from kungfu import Ok, Error, Result

from emergent import graph as G
from examples.full_stack.domain import (
    Cart,
    OrderLineItem,
    OrderSummary,
    OrderId,
    CheckoutError,
)
from examples.full_stack.nodes._user import (
    ProfileNode,
    LoyaltyNode,
    AddressNode,
    PaymentMethodNode,
)
from examples.full_stack.nodes._items import ItemsDataNode
from examples.full_stack.nodes._totals import SubtotalNode, TaxNode, GrandTotalNode
from examples.full_stack.nodes._saga import CheckoutSagaNode


_order_counter = 0


@G.node
class CreateOrderNode:
    """Final node: create the order from all gathered data."""
    
    def __init__(self, data: OrderSummary) -> None:
        self.data = data

    @classmethod
    async def __compose__(
        cls,
        profile: ProfileNode,
        loyalty: LoyaltyNode,
        address: AddressNode,
        payment_method: PaymentMethodNode,
        items: ItemsDataNode,
        subtotal: SubtotalNode,
        tax: TaxNode,
        total: GrandTotalNode,
        saga: CheckoutSagaNode,
    ) -> "CreateOrderNode":
        global _order_counter
        _order_counter += 1

        line_items = tuple(
            OrderLineItem(
                product=item.product,
                quantity=item.item.quantity,
                unit_price=item.pricing.unit_price,
                discounts=item.pricing.product_discount + item.pricing.loyalty_discount,
                shipping=item.shipping,
                line_total=item.pricing.subtotal + item.shipping.cost,
            )
            for item in items.items
        )

        order = OrderSummary(
            order_id=OrderId(f"ORD-{_order_counter:04d}"),
            user=profile.data,
            loyalty_tier=loyalty.data,
            shipping_address=address.data,
            payment_method=payment_method.data,
            items=line_items,
            subtotal=subtotal.subtotal,
            total_discounts=subtotal.discounts_total,
            shipping_total=subtotal.shipping_total,
            tax=tax.data,
            grand_total=total.total,
            auth_code=saga.data.payment.auth_code,
        )

        print(f"      [CreateOrder] {order.order_id.value}")
        print(f"        Inventory reservations: {[r.reservation_id for r in saga.data.reservations]}")
        return cls(order)

    @classmethod
    async def execute(cls, cart: Cart) -> Result[OrderSummary, CheckoutError]:
        """
        Execute the full checkout graph.
        
        FULL STACK demonstration:
        
        1. GRAPH: Auto-parallelizes independent nodes
           - User: profile*, loyalty*, address, payment (4 parallel)
           - Items: product, inventory, promo, shipping (4N parallel)
        
        2. CACHE: Profile and loyalty served from cache on repeat checkouts
           - First checkout: cache miss → fetch from service
           - Second checkout same user: cache hit → instant
        
        3. COMBINATORS: traverse_par + parallel for per-item fetching
           - Fail-fast semantics with Result[T, E]
        
        4. SAGA: Transactional inventory + payment
           - Reserve inventory (with release compensator)
           - Authorize payment (with void compensator)
           - On failure: automatic rollback
        
        (* = cached)
        """
        start = time.perf_counter()
        print("\n    Executing checkout graph:")
        try:
            result = await G.compose(cls, cart)
            elapsed = (time.perf_counter() - start) * 1000
            print(f"    ✓ Completed in {elapsed:.0f}ms")
            return Ok(result.data)
        except CheckoutError as e:
            elapsed = (time.perf_counter() - start) * 1000
            print(f"    ✗ Failed in {elapsed:.0f}ms: {e.message}")
            return Error(e)


__all__ = ("CreateOrderNode",)

