"""
Checkout nodes — modular graph components.

CORE NODES (building blocks):
- _cache.py    — cache setup for profile/loyalty
- _input.py    — CartNode (entry point)
- _user.py     — user data nodes (profile, loyalty, address, payment)
- _items.py    — per-item data fetching with combinators
- _totals.py   — subtotal, tax, grand total
- _fraud.py    — fraud check
- _saga.py     — inventory reservation + payment with compensation
- _order.py    — final order creation

COMPOSED VIEWS (reuse core nodes):
- _preview.py  — order preview without payment
- _userinfo.py — user info only
- _shipping.py — shipping estimate only

Each view is just a different composition of the same building blocks!
"""

from examples.full_stack.nodes._cache import profile_cache, loyalty_cache
from examples.full_stack.nodes._input import CartNode
from examples.full_stack.nodes._user import (
    ProfileNode,
    LoyaltyNode,
    AddressNode,
    PaymentMethodNode,
)
from examples.full_stack.nodes._items import ItemData, ItemsDataNode
from examples.full_stack.nodes._totals import SubtotalNode, TaxNode, GrandTotalNode
from examples.full_stack.nodes._fraud import FraudCheckNode
from examples.full_stack.nodes._saga import CheckoutTransaction, CheckoutSagaNode
from examples.full_stack.nodes._order import CreateOrderNode

# Composed views
from examples.full_stack.nodes._preview import OrderPreview, PreviewNode
from examples.full_stack.nodes._userinfo import UserInfo, UserInfoNode
from examples.full_stack.nodes._shipping import ShippingLine, ShippingEstimate, ShippingEstimateNode

__all__ = (
    # Cache
    "profile_cache",
    "loyalty_cache",
    # Core nodes
    "CartNode",
    "ProfileNode",
    "LoyaltyNode",
    "AddressNode",
    "PaymentMethodNode",
    "ItemData",
    "ItemsDataNode",
    "SubtotalNode",
    "TaxNode",
    "GrandTotalNode",
    "FraudCheckNode",
    "CheckoutTransaction",
    "CheckoutSagaNode",
    "CreateOrderNode",
    # Composed views
    "OrderPreview",
    "PreviewNode",
    "UserInfo",
    "UserInfoNode",
    "ShippingLine",
    "ShippingEstimate",
    "ShippingEstimateNode",
)

