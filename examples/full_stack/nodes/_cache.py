"""
Cache — profile and loyalty caching.

Uses emergent.cache for transparent caching of user data.
"""

from kungfu import LazyCoroResult

import combinators as C
from emergent import cache as cache_module
from examples.full_stack.domain import (
    UserId,
    UserProfile,
    LoyaltyTier,
    CheckoutError,
)
from examples.full_stack.repo import user_service


# ═══════════════════════════════════════════════════════════════════════════════
# Profile Cache
# ═══════════════════════════════════════════════════════════════════════════════

def _make_profile_key(user_id: UserId) -> str:
    return f"profile:{user_id.value}"


def _fetch_profile(user_id: UserId) -> LazyCoroResult[UserProfile, CheckoutError]:
    return C.catching_async(
        lambda: user_service.get_profile(user_id),
        on_error=lambda e: CheckoutError("USER_NOT_FOUND", str(e)),
    )


profile_cache = (
    cache_module.cache(_make_profile_key, _fetch_profile)
    .tier(cache_module.LocalTier[UserProfile](max_size=100))
    .build()
)


# ═══════════════════════════════════════════════════════════════════════════════
# Loyalty Cache
# ═══════════════════════════════════════════════════════════════════════════════

def _make_loyalty_key(user_id: UserId) -> str:
    return f"loyalty:{user_id.value}"


def _fetch_loyalty(user_id: UserId) -> LazyCoroResult[LoyaltyTier, CheckoutError]:
    return C.catching_async(
        lambda: user_service.get_loyalty(user_id),
        on_error=lambda e: CheckoutError("LOYALTY_ERROR", str(e)),
    )


loyalty_cache = (
    cache_module.cache(_make_loyalty_key, _fetch_loyalty)
    .tier(cache_module.LocalTier[LoyaltyTier](max_size=100))
    .build()
)


__all__ = ("profile_cache", "loyalty_cache")

