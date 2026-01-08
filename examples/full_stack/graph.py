"""
Checkout Graph — Full Stack: Graph + Combinators + Cache + Saga.

This example demonstrates ALL emergent patterns working together:

┌─────────────────────────────────────────────────────────────────────────────┐
│  LAYER            TOOL              PURPOSE                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  Macro deps       emergent.graph    Node dependencies, auto-parallelization │
│  Micro parallel   combinators       traverse_par, parallel (per-item fetch) │
│  Data caching     emergent.cache    Profile/loyalty caching                 │
│  Transactions     emergent.saga     Inventory + Payment with compensation   │
└─────────────────────────────────────────────────────────────────────────────┘

The flow:
1. GRAPH: orchestrates nodes (profile, loyalty, address, payment, items...)
2. CACHE: profile and loyalty served from cache on repeat checkouts
3. COMBINATORS: parallel fetch of product/inventory/promo/shipping per item
4. SAGA: reserve inventory → authorize payment (with rollback on failure)

Structure:
    nodes/
    ├── _cache.py    — profile/loyalty caching
    ├── _input.py    — CartNode (entry point)
    ├── _user.py     — ProfileNode, LoyaltyNode, AddressNode, PaymentMethodNode
    ├── _items.py    — ItemsDataNode (parallel per-item fetch)
    ├── _totals.py   — SubtotalNode, TaxNode, GrandTotalNode
    ├── _fraud.py    — FraudCheckNode
    ├── _saga.py     — CheckoutSagaNode (inventory + payment transaction)
    └── _order.py    — CreateOrderNode (final node)

NOTE: Run same checkout twice to see cache hits!
"""

# Re-export all nodes for convenient access
from examples.full_stack.nodes import (
    # Cache instances
    profile_cache,
    loyalty_cache,
    # Core nodes
    CartNode,
    ProfileNode,
    LoyaltyNode,
    AddressNode,
    PaymentMethodNode,
    ItemData,
    ItemsDataNode,
    SubtotalNode,
    TaxNode,
    GrandTotalNode,
    FraudCheckNode,
    CheckoutTransaction,
    CheckoutSagaNode,
    CreateOrderNode,
    # Composed views
    OrderPreview,
    PreviewNode,
    UserInfo,
    UserInfoNode,
    ShippingLine,
    ShippingEstimate,
    ShippingEstimateNode,
)

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
