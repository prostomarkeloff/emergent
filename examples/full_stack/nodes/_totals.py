"""
Totals — subtotal, tax, grand total nodes.
"""

from emergent import graph as G
from examples.full_stack.domain import TaxCalculation
from examples.full_stack.repo import tax_service
from examples.full_stack.nodes._items import ItemsDataNode
from examples.full_stack.nodes._user import AddressNode


@G.node
class SubtotalNode:
    """Aggregate item subtotals, shipping, and discounts."""
    
    def __init__(self, subtotal: int, shipping_total: int, discounts_total: int) -> None:
        self.subtotal = subtotal
        self.shipping_total = shipping_total
        self.discounts_total = discounts_total

    @classmethod
    async def __compose__(cls, items: ItemsDataNode) -> "SubtotalNode":
        subtotal = sum(item.pricing.subtotal for item in items.items)
        shipping = sum(item.shipping.cost for item in items.items)
        discounts = sum(
            item.pricing.product_discount + item.pricing.loyalty_discount
            for item in items.items
        )
        print(f"      [Subtotal] Items: ${subtotal/100:.2f}, "
              f"Shipping: ${shipping/100:.2f}, Discounts: ${discounts/100:.2f}")
        return cls(subtotal, shipping, discounts)


@G.node
class TaxNode:
    """Calculate tax based on subtotal and shipping address."""
    
    def __init__(self, data: TaxCalculation) -> None:
        self.data = data

    @classmethod
    async def __compose__(cls, subtotal: SubtotalNode, address: AddressNode) -> "TaxNode":
        tax = await tax_service.calculate(subtotal.subtotal, address.data)
        return cls(tax)


@G.node
class GrandTotalNode:
    """Sum of subtotal + shipping + tax."""
    
    def __init__(self, total: int) -> None:
        self.total = total

    @classmethod
    async def __compose__(cls, subtotal: SubtotalNode, tax: TaxNode) -> "GrandTotalNode":
        total = subtotal.subtotal + subtotal.shipping_total + tax.data.tax_amount
        print(f"      [GrandTotal] ${total/100:.2f}")
        return cls(total)


__all__ = ("SubtotalNode", "TaxNode", "GrandTotalNode")

