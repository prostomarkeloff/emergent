"""
UserInfo — fetch all user data.

Demonstrates COMPOSITION: only user-related nodes, no items or payments.
"""

from dataclasses import dataclass

from kungfu import Ok, Error, Result

from emergent import graph as G
from examples.full_stack.domain import UserId, Cart, CheckoutError
from examples.full_stack.nodes._input import CartNode
from examples.full_stack.nodes._user import (
    ProfileNode,
    LoyaltyNode,
    AddressNode,
    PaymentMethodNode,
)


@dataclass
class UserInfo:
    """Complete user information."""
    user_id: int
    name: str
    email: str
    loyalty_level: str
    loyalty_discount: int
    free_shipping_threshold: int
    address_city: str
    address_state: str
    address_full: str
    payment_type: str
    payment_last_four: str
    profile_cached: bool
    loyalty_cached: bool


@G.node
class UserInfoNode:
    """
    User info — just user data, no items.
    
    COMPOSITION EXAMPLE:
    Depends on: ProfileNode, LoyaltyNode, AddressNode, PaymentMethodNode
    Does NOT depend on: ItemsDataNode, TaxNode, FraudCheckNode, etc.
    """
    
    def __init__(self, data: UserInfo) -> None:
        self.data = data

    @classmethod
    async def __compose__(
        cls,
        cart: CartNode,
        profile: ProfileNode,
        loyalty: LoyaltyNode,
        address: AddressNode,
        payment: PaymentMethodNode,
    ) -> "UserInfoNode":
        info = UserInfo(
            user_id=cart.data.user_id.value,
            name=profile.data.name,
            email=profile.data.email,
            loyalty_level=loyalty.data.level,
            loyalty_discount=loyalty.data.discount_percent,
            free_shipping_threshold=loyalty.data.free_shipping_threshold,
            address_city=address.data.city,
            address_state=address.data.state,
            address_full=f"{address.data.street}, {address.data.city}, {address.data.state} {address.data.zip_code}",
            payment_type=payment.data.card_type,
            payment_last_four=payment.data.last_four,
            profile_cached=profile.cached,
            loyalty_cached=loyalty.cached,
        )
        return cls(info)

    @classmethod
    async def execute(cls, user_id: UserId) -> Result[UserInfo, CheckoutError]:
        """
        Fetch user info.
        
        Creates a minimal cart just to trigger the graph.
        Only runs user-related nodes.
        """
        # Minimal cart with no items — just to provide user_id
        cart = Cart(user_id, tuple())
        
        print(f"\n    Fetching user info for {user_id.value}:")
        try:
            result = await G.compose(cls, cart)
            print("    ✓ User info ready")
            return Ok(result.data)
        except CheckoutError as e:
            print(f"    ✗ Failed: {e.message}")
            return Error(e)


__all__ = ("UserInfo", "UserInfoNode")

