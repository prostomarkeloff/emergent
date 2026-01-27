"""
Domain — Complex e-commerce checkout.

This models a REAL checkout flow where:
- Cart has MULTIPLE items
- Each item needs inventory + pricing + promotions
- User needs profile + loyalty + payment methods + addresses
- Order needs tax (depends on address) + shipping per item
- Payment needs fraud check + authorization
- Final aggregation from ALL of the above

This creates a complex dependency graph that would be
NIGHTMARE to wire manually.
"""

from dataclasses import dataclass


# ═══════════════════════════════════════════════════════════════════════════════
# IDs
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class UserId:
    value: int


@dataclass(frozen=True)
class ProductId:
    value: str


@dataclass(frozen=True)
class AddressId:
    value: int


@dataclass(frozen=True)
class PaymentMethodId:
    value: str


@dataclass(frozen=True)
class OrderId:
    value: str


# ═══════════════════════════════════════════════════════════════════════════════
# User Domain
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class UserProfile:
    id: UserId
    name: str
    email: str


@dataclass(frozen=True)
class LoyaltyTier:
    level: str  # bronze, silver, gold, platinum
    discount_percent: int
    free_shipping_threshold: int


@dataclass(frozen=True)
class Address:
    id: AddressId
    user_id: UserId
    street: str
    city: str
    state: str
    zip_code: str
    country: str


@dataclass(frozen=True)
class PaymentMethod:
    id: PaymentMethodId
    user_id: UserId
    card_type: str
    last_four: str
    is_default: bool


# ═══════════════════════════════════════════════════════════════════════════════
# Product Domain
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Product:
    id: ProductId
    name: str
    base_price: int  # cents
    weight_grams: int
    category: str


@dataclass(frozen=True)
class InventoryStatus:
    product_id: ProductId
    available: int
    reserved: int
    warehouse: str


@dataclass(frozen=True)
class ProductPromotion:
    product_id: ProductId
    discount_percent: int
    reason: str


# ═══════════════════════════════════════════════════════════════════════════════
# Cart Domain
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class CartItem:
    product_id: ProductId
    quantity: int


@dataclass(frozen=True)
class Cart:
    user_id: UserId
    items: tuple[CartItem, ...]


# ═══════════════════════════════════════════════════════════════════════════════
# Pricing Domain
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ItemPricing:
    product_id: ProductId
    quantity: int
    unit_price: int
    product_discount: int  # from promotions
    loyalty_discount: int  # from tier
    subtotal: int


@dataclass(frozen=True)
class TaxCalculation:
    subtotal: int
    tax_rate: float
    tax_amount: int
    jurisdiction: str


@dataclass(frozen=True)
class ShippingOption:
    product_id: ProductId
    carrier: str
    cost: int
    days: int


# ═══════════════════════════════════════════════════════════════════════════════
# Payment Domain
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class FraudCheckResult:
    user_id: UserId
    risk_score: float
    approved: bool
    reason: str


@dataclass(frozen=True)
class PaymentAuthorization:
    payment_method_id: PaymentMethodId
    amount: int
    auth_code: str
    approved: bool


# ═══════════════════════════════════════════════════════════════════════════════
# Order Domain
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class OrderLineItem:
    product: Product
    quantity: int
    unit_price: int
    discounts: int
    shipping: ShippingOption
    line_total: int


@dataclass(frozen=True)
class OrderSummary:
    order_id: OrderId
    user: UserProfile
    loyalty_tier: LoyaltyTier
    shipping_address: Address
    payment_method: PaymentMethod
    items: tuple[OrderLineItem, ...]
    subtotal: int
    total_discounts: int
    shipping_total: int
    tax: TaxCalculation
    grand_total: int
    auth_code: str


# ═══════════════════════════════════════════════════════════════════════════════
# Errors
# ═══════════════════════════════════════════════════════════════════════════════


class CheckoutError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
