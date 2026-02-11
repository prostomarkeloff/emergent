"""
Cache — multi-tier caching with L1/L2 pattern.

Key concepts:
- Tier = storage backend (global, inject via DI)
- Cache = declarative builder (per-use-case, type-safe)
- Tiers STACK: .tier(L1).tier(L2) = check L1 → L2 → fetch

Level 5: emergent.cache
Level 3: combinators.lift
Level 2: kungfu.Result
"""

from typing import cast

from kungfu import Ok, Error, LazyCoroResult
from combinators import lift as L
from emergent import cache as C
from emergent.cache._types import LocalTier, Tier
from examples._infra import banner, run, UserId, User, NotFound, FakeDb


db = FakeDb()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TIERS ARE GLOBAL — create once, inject everywhere
# ═══════════════════════════════════════════════════════════════════════════════

# L1: In-memory, per-instance (fast, no network)
# LocalTier has a built-in `name` property that returns "local"
# Cast needed: LocalTier[T] returns Never as error type, but AnyTier expects object.
# Pyright can't see Never <: object in protocol return types due to coroutine wrapping.
# Safe at runtime: Never is the bottom type, compatible with any error type.
l1_tier = cast(Tier[User, object], LocalTier[User](max_size=100))

# L2: Simulated "remote" tier (in real app: Redis, Memcached)
# Same cast rationale as l1_tier above.
l2_tier = cast(Tier[User, object], LocalTier[User](max_size=1000))


# ═══════════════════════════════════════════════════════════════════════════════
# 2. FETCH FUNCTION — returns LazyCoroResult
# ═══════════════════════════════════════════════════════════════════════════════


def fetch_user(uid: UserId) -> LazyCoroResult[User, NotFound]:
    async def _fetch() -> User:
        print(f"  [ORIGIN] Fetching user {uid.value} from DB...")
        result = await db.get_user(uid)
        match result:
            case Ok(user):
                return user
            case Error(e):
                raise e

    return L.catching_async(
        _fetch,
        on_error=lambda e: e
        if isinstance(e, NotFound)
        else NotFound("User", uid.value),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 3. CACHE = BUILDER — stacks tiers, type-safe
# ═══════════════════════════════════════════════════════════════════════════════

user_cache = (
    C.cache(lambda uid: f"user:{uid.value}", fetch_user)
    .tier(l1_tier)  # L1: check first
    .tier(l2_tier)  # L2: check second
    .build()
)

# How it works:
# READ:       L1 → miss → L2 → miss → fetch()
# WRITE:      fetch() → store in L1 AND L2
# INVALIDATE: remove from L1 AND L2


async def main() -> None:
    banner("Cache: Tier Stacking (L1/L2 Pattern)")

    uid = UserId(1)

    print("\n1. First request (miss L1 → miss L2 → fetch from origin):")
    r1 = await user_cache.get(uid)
    match r1:
        case Ok(r):
            print(f"   tier={r.tier} hit={r.hit} → {r.value.name}")
        case Error(e):
            print(f"   error: {e}")

    print("\n2. Second request (hit L1):")
    r2 = await user_cache.get(uid)
    match r2:
        case Ok(r):
            print(f"   tier={r.tier} hit={r.hit} → {r.value.name}")
        case Error(e):
            print(f"   error: {e}")

    print("\n3. Clear L1 only, request again (miss L1 → hit L2):")
    await l1_tier.delete(f"user:{uid.value}")  # simulate L1 eviction
    r3 = await user_cache.get(uid)
    match r3:
        case Ok(r):
            print(f"   tier={r.tier} hit={r.hit} → {r.value.name}")
        case Error(e):
            print(f"   error: {e}")

    print("\n4. Invalidate ALL tiers, refetch:")
    await user_cache.invalidate(uid)
    r4 = await user_cache.get(uid)
    match r4:
        case Ok(r):
            print(f"   tier={r.tier} hit={r.hit} → {r.value.name}")
        case Error(e):
            print(f"   error: {e}")

    print("\nDone!")


if __name__ == "__main__":
    run(main)
