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

from kungfu import Ok, Error, LazyCoroResult
from combinators import lift as L
from emergent import cache as C
from emergent.cache._types import Tier
from examples._infra import banner, run, UserId, User, NotFound, FakeDb


db = FakeDb()


# ═══════════════════════════════════════════════════════════════════════════════
# Custom tier with distinct name (simulates Redis)
# ═══════════════════════════════════════════════════════════════════════════════


class NamedTier[T]:
    """Wrapper to give tier a distinct name."""

    def __init__(self, inner: Tier[T], tier_name: str) -> None:
        self._inner = inner
        self._name = tier_name

    @property
    def name(self) -> str:
        return self._name

    async def get(self, key: str) -> T | None:
        return await self._inner.get(key)

    async def set(self, key: str, value: T) -> None:
        await self._inner.set(key, value)

    async def delete(self, key: str) -> bool:
        return await self._inner.delete(key)

    async def delete_pattern(self, pattern: str) -> int:
        return await self._inner.delete_pattern(pattern)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TIERS ARE GLOBAL — create once, inject everywhere
# ═══════════════════════════════════════════════════════════════════════════════

# L1: In-memory, per-instance (fast, no network)
l1_tier: Tier[User] = NamedTier(C.LocalTier(max_size=100), "L1-memory")

# L2: Simulated "remote" tier (in real app: Redis, Memcached)
l2_tier: Tier[User] = NamedTier(C.LocalTier(max_size=1000), "L2-redis")


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
