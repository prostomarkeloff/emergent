"""
Preview — order preview without payment.

Demonstrates COMPOSITION: reuses existing nodes to create a new "view"
without any new service calls or logic — just a different subset of the graph.
"""

from dataclasses import dataclass

from kungfu import Ok, Error, Result

from emergent import graph as G
from examples.full_stack.domain import (
    Cart,
    CheckoutError,
)
from examples.full_stack.nodes._user import (
    ProfileNode,
    LoyaltyNode,
    AddressNode,
)
from examples.full_stack.nodes._items import ItemData, ItemsDataNode
from examples.full_stack.nodes._totals import SubtotalNode, TaxNode, GrandTotalNode


@dataclass
class OrderPreview:
    """Preview of an order — totals calculated but no payment."""

    user_name: str
    loyalty_level: str
    loyalty_discount_percent: int
    shipping_city: str
    shipping_state: str
    items: list[ItemData]
    subtotal: int
    discounts: int
    shipping: int
    tax_rate: float
    tax_amount: int
    grand_total: int


@G.node
class PreviewNode:
    """
    Order preview — calculate totals without payment.

    COMPOSITION EXAMPLE:
    This node depends on ProfileNode, LoyaltyNode, AddressNode,
    ItemsDataNode, SubtotalNode, TaxNode, GrandTotalNode.

    It does NOT depend on FraudCheckNode or CheckoutSagaNode.
    The graph only executes what's needed!
    """

    def __init__(self, data: OrderPreview) -> None:
        self.data = data

    @classmethod
    async def __compose__(
        cls,
        profile: ProfileNode,
        loyalty: LoyaltyNode,
        address: AddressNode,
        items: ItemsDataNode,
        subtotal: SubtotalNode,
        tax: TaxNode,
        total: GrandTotalNode,
    ) -> "PreviewNode":
        preview = OrderPreview(
            user_name=profile.data.name,
            loyalty_level=loyalty.data.level,
            loyalty_discount_percent=loyalty.data.discount_percent,
            shipping_city=address.data.city,
            shipping_state=address.data.state,
            items=items.items,
            subtotal=subtotal.subtotal,
            discounts=subtotal.discounts_total,
            shipping=subtotal.shipping_total,
            tax_rate=tax.data.tax_rate,
            tax_amount=tax.data.tax_amount,
            grand_total=total.total,
        )
        return cls(preview)

    @classmethod
    async def execute(cls, cart: Cart) -> Result[OrderPreview, CheckoutError]:
        """
        Execute preview — NO payment, NO fraud check.

        Only runs: user data → items → totals → tax
        Does NOT run: fraud, saga, payment
        """
        print("\n    Calculating order preview (no payment):")
        try:
            result = await G.compose(cls, cart)
            print("    ✓ Preview ready")
            return Ok(result.data)
        except CheckoutError as e:
            print(f"    ✗ Preview failed: {e.message}")
            return Error(e)


__all__ = ("OrderPreview", "PreviewNode")
