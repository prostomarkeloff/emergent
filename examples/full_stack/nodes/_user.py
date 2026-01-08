"""
User — profile, loyalty, address, payment nodes.

Profile and Loyalty use CACHE for repeat checkouts.
"""

from kungfu import Ok, Error

from emergent import graph as G
from examples.full_stack.domain import (
    UserProfile,
    LoyaltyTier,
    Address,
    PaymentMethod,
    CheckoutError,
)
from examples.full_stack.repo import user_service
from examples.full_stack.nodes._input import CartNode
from examples.full_stack.nodes._cache import profile_cache, loyalty_cache


@G.node
class ProfileNode:
    """User profile — cached."""
    
    def __init__(self, data: UserProfile, cached: bool) -> None:
        self.data = data
        self.cached = cached

    @classmethod
    async def __compose__(cls, cart: CartNode) -> "ProfileNode":
        result = await profile_cache.get(cart.data.user_id)()
        match result:
            case Ok(cache_result):
                if cache_result.hit:
                    print(f"      [ProfileNode] CACHE HIT for user {cart.data.user_id.value}")
                return cls(cache_result.value, cache_result.hit)
            case Error(e):
                if isinstance(e, CheckoutError):
                    raise e
                raise CheckoutError("CACHE_ERROR", str(e))


@G.node
class LoyaltyNode:
    """User loyalty tier — cached."""
    
    def __init__(self, data: LoyaltyTier, cached: bool) -> None:
        self.data = data
        self.cached = cached

    @classmethod
    async def __compose__(cls, cart: CartNode) -> "LoyaltyNode":
        result = await loyalty_cache.get(cart.data.user_id)()
        match result:
            case Ok(cache_result):
                if cache_result.hit:
                    print(f"      [LoyaltyNode] CACHE HIT for user {cart.data.user_id.value}")
                return cls(cache_result.value, cache_result.hit)
            case Error(e):
                if isinstance(e, CheckoutError):
                    raise e
                raise CheckoutError("CACHE_ERROR", str(e))


@G.node
class AddressNode:
    """User default shipping address."""
    
    def __init__(self, data: Address) -> None:
        self.data = data

    @classmethod
    async def __compose__(cls, cart: CartNode) -> "AddressNode":
        address = await user_service.get_default_address(cart.data.user_id)
        return cls(address)


@G.node
class PaymentMethodNode:
    """User default payment method."""
    
    def __init__(self, data: PaymentMethod) -> None:
        self.data = data

    @classmethod
    async def __compose__(cls, cart: CartNode) -> "PaymentMethodNode":
        pm = await user_service.get_default_payment(cart.data.user_id)
        return cls(pm)


__all__ = ("ProfileNode", "LoyaltyNode", "AddressNode", "PaymentMethodNode")

