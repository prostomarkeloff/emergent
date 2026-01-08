"""
Items — parallel fetch of per-item data using combinators.

Uses combinators.traverse_par + combinators.parallel for maximum parallelism.
"""

from dataclasses import dataclass

from kungfu import Ok, Error, LazyCoroResult

import combinators as C
from emergent import graph as G
from examples.full_stack.domain import (
    CartItem,
    Product,
    InventoryStatus,
    ProductPromotion,
    ShippingOption,
    ItemPricing,
    LoyaltyTier,
    CheckoutError,
)
from examples.full_stack.repo import (
    catalog_service,
    inventory_service,
    promotions_service,
    shipping_service,
)
from examples.full_stack.nodes._input import CartNode
from examples.full_stack.nodes._user import LoyaltyNode, AddressNode


@dataclass
class ItemData:
    """Aggregated data for one cart item."""
    item: CartItem
    product: Product
    inventory: InventoryStatus
    promotion: ProductPromotion | None
    shipping: ShippingOption
    pricing: ItemPricing


@G.node
class ItemsDataNode:
    """
    Fetch ALL per-item data in parallel using combinators.
    
    For each item:
    - Product details (catalog)
    - Inventory check
    - Promotions
    - Shipping (needs address)
    
    All items processed in parallel via combinators.traverse_par.
    """
    
    def __init__(self, items: list[ItemData]) -> None:
        self.items = items

    @classmethod
    async def __compose__(
        cls,
        cart: CartNode,
        loyalty: LoyaltyNode,
        address: AddressNode,
    ) -> "ItemsDataNode":
        
        def process_item(item: CartItem) -> LazyCoroResult[ItemData, CheckoutError]:
            """Build a lazy computation for one item."""
            
            fetch_product = C.catching_async(
                lambda pid=item.product_id: catalog_service.get(pid),
                on_error=lambda e: CheckoutError("CATALOG_ERROR", str(e)),
            )
            fetch_inventory = C.catching_async(
                lambda pid=item.product_id, q=item.quantity: inventory_service.check(pid, q),
                on_error=lambda e: CheckoutError("INVENTORY_ERROR", str(e)),
            )
            fetch_promo = C.catching_async(
                lambda pid=item.product_id: promotions_service.get_for_product(pid),
                on_error=lambda e: CheckoutError("PROMO_ERROR", str(e)),
            )
            fetch_shipping = C.catching_async(
                lambda pid=item.product_id: shipping_service.calculate(pid, address.data),
                on_error=lambda e: CheckoutError("SHIPPING_ERROR", str(e)),
            )
            
            return C.parallel(
                fetch_product,
                fetch_inventory,
                fetch_promo,
                fetch_shipping,
            ).map(lambda results: _build_item_data(item, results, loyalty.data))
        
        result = await C.traverse_par(cart.data.items, process_item)()
        
        match result:
            case Ok(items_data):
                return cls(items_data)
            case Error(e):
                raise e


def _build_item_data(
    item: CartItem,
    results: list[Product | InventoryStatus | ProductPromotion | None | ShippingOption],
    loyalty: LoyaltyTier,
) -> ItemData:
    """Calculate pricing from fetched data."""
    product = results[0]
    inventory = results[1]
    promotion = results[2]
    shipping = results[3]
    
    assert isinstance(product, Product)
    assert isinstance(inventory, InventoryStatus)
    assert isinstance(shipping, ShippingOption)
    
    unit_price = product.base_price
    product_discount = 0
    if isinstance(promotion, ProductPromotion):
        product_discount = unit_price * promotion.discount_percent // 100

    loyalty_discount = (unit_price - product_discount) * loyalty.discount_percent // 100
    subtotal = (unit_price - product_discount - loyalty_discount) * item.quantity

    pricing = ItemPricing(
        product_id=item.product_id,
        quantity=item.quantity,
        unit_price=unit_price,
        product_discount=product_discount * item.quantity,
        loyalty_discount=loyalty_discount * item.quantity,
        subtotal=subtotal,
    )

    promo = promotion if isinstance(promotion, ProductPromotion) else None
    return ItemData(item, product, inventory, promo, shipping, pricing)


__all__ = ("ItemData", "ItemsDataNode")

