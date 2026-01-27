"""
ShippingEstimate — just shipping costs for items.

Demonstrates COMPOSITION: only address + items → shipping.
No totals, no tax, no payment.
"""

from dataclasses import dataclass

from kungfu import Ok, Error, Result

from emergent import graph as G
from examples.full_stack.domain import Cart, CheckoutError
from examples.full_stack.nodes._user import AddressNode
from examples.full_stack.nodes._items import ItemsDataNode


@dataclass
class ShippingLine:
    """Shipping for one item."""

    product_name: str
    quantity: int
    carrier: str
    cost: int
    days: int


@dataclass
class ShippingEstimate:
    """Shipping estimate for all items."""

    ship_to_city: str
    ship_to_state: str
    lines: list[ShippingLine]
    total_cost: int
    estimated_days: int


@G.node
class ShippingEstimateNode:
    """
    Shipping estimate — just shipping costs.

    COMPOSITION EXAMPLE:
    Depends on: AddressNode, ItemsDataNode (which needs LoyaltyNode)
    Does NOT depend on: TaxNode, FraudCheckNode, CheckoutSagaNode

    Shows minimal subgraph for specific use case.
    """

    def __init__(self, data: ShippingEstimate) -> None:
        self.data = data

    @classmethod
    async def __compose__(
        cls,
        address: AddressNode,
        items: ItemsDataNode,
    ) -> "ShippingEstimateNode":
        lines = [
            ShippingLine(
                product_name=item.product.name,
                quantity=item.item.quantity,
                carrier=item.shipping.carrier,
                cost=item.shipping.cost,
                days=item.shipping.days,
            )
            for item in items.items
        ]

        total_cost = sum(line.cost for line in lines)
        max_days = max((line.days for line in lines), default=0)

        estimate = ShippingEstimate(
            ship_to_city=address.data.city,
            ship_to_state=address.data.state,
            lines=lines,
            total_cost=total_cost,
            estimated_days=max_days,
        )
        return cls(estimate)

    @classmethod
    async def execute(cls, cart: Cart) -> Result[ShippingEstimate, CheckoutError]:
        """
        Get shipping estimate.

        Only runs: user address → items (product + shipping)
        Does NOT run: fraud, payment, order creation
        """
        print("\n    Calculating shipping estimate:")
        try:
            result = await G.compose(cls, cart)
            print("    ✓ Shipping estimate ready")
            return Ok(result.data)
        except CheckoutError as e:
            print(f"    ✗ Failed: {e.message}")
            return Error(e)


__all__ = ("ShippingLine", "ShippingEstimate", "ShippingEstimateNode")
