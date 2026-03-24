# pyright: reportPrivateUsage=false
"""Property-based tests for concurrent mutations with atomic() on MemoryRelationalProvider.

Uses hypothesis to verify transactional guarantees: rollback on error,
commit on success, serialization of concurrent transactions, and lock release.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
import hypothesis.strategies as st
from hypothesis import given, settings

from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider


@dataclass(frozen=True, slots=True)
class Record:
    id: int
    value: int


records_st = st.lists(
    st.builds(Record, id=st.integers(0, 10_000), value=st.integers(-1000, 1000)),
    min_size=1,
    max_size=50,
)


@pytest.mark.asyncio
@given(items=records_st)
@settings(max_examples=30)
async def test_rollback_on_error(items: list[Record]) -> None:
    """Insert items inside atomic(), raise an exception -> data restored to pre-transaction state."""
    provider: MemoryRelationalProvider[Record] = MemoryRelationalProvider()
    original_data = list(provider.data)
    assert original_data == []

    with pytest.raises(RuntimeError, match="forced"):
        async with provider.atomic():
            for item in items:
                await provider.insert(item)
            # All items inserted inside transaction
            assert len(provider.data) == len(items)
            raise RuntimeError("forced")

    # After rollback, data is restored
    assert provider.data == original_data


@pytest.mark.asyncio
@given(items=records_st)
@settings(max_examples=30)
async def test_commit_on_success(items: list[Record]) -> None:
    """Insert items inside atomic(), no exception -> data persisted."""
    provider: MemoryRelationalProvider[Record] = MemoryRelationalProvider()

    async with provider.atomic():
        for item in items:
            await provider.insert(item)

    assert provider.data == items


@pytest.mark.asyncio
@given(
    batch1=records_st,
    batch2=records_st,
)
@settings(max_examples=20)
async def test_multiple_successful_transactions(
    batch1: list[Record], batch2: list[Record]
) -> None:
    """Each atomic block's changes visible to the next."""
    provider: MemoryRelationalProvider[Record] = MemoryRelationalProvider()

    async with provider.atomic():
        for item in batch1:
            await provider.insert(item)

    assert provider.data == batch1

    async with provider.atomic():
        for item in batch2:
            await provider.insert(item)

    assert provider.data == batch1 + batch2


@pytest.mark.asyncio
@given(
    initial=records_st,
    extra=records_st,
)
@settings(max_examples=20)
async def test_rollback_preserves_original_state_exactly(
    initial: list[Record], extra: list[Record]
) -> None:
    """Rollback restores the exact pre-transaction snapshot, not an empty list."""
    provider: MemoryRelationalProvider[Record] = MemoryRelationalProvider(data=initial)
    snapshot_before = list(provider.data)

    with pytest.raises(ValueError, match="rollback"):
        async with provider.atomic():
            for item in extra:
                await provider.insert(item)
            # mid-transaction state includes both initial + extra
            assert len(provider.data) == len(initial) + len(extra)
            raise ValueError("rollback")

    assert provider.data == snapshot_before


@pytest.mark.asyncio
async def test_lock_release_no_deadlock() -> None:
    """After atomic() exits (success or failure), the next atomic() can proceed."""
    provider: MemoryRelationalProvider[Record] = MemoryRelationalProvider()

    # First transaction: success
    async with provider.atomic():
        await provider.insert(Record(id=1, value=10))

    # Second transaction: failure
    with pytest.raises(RuntimeError):
        async with provider.atomic():
            await provider.insert(Record(id=2, value=20))
            raise RuntimeError("fail")

    # Third transaction: should not deadlock
    async with provider.atomic():
        await provider.insert(Record(id=3, value=30))

    # Only records from successful transactions remain
    assert provider.data == [Record(id=1, value=10), Record(id=3, value=30)]


@pytest.mark.asyncio
async def test_serialization_no_interleave() -> None:
    """Two concurrent atomic() blocks don't interleave operations.

    Because atomic() holds an asyncio.Lock, the second transaction
    waits until the first completes. We verify ordering by checking
    that the final data reflects sequential execution.
    """
    provider: MemoryRelationalProvider[Record] = MemoryRelationalProvider()
    execution_order: list[str] = []

    async def transaction_a() -> None:
        async with provider.atomic():
            execution_order.append("a_start")
            await provider.insert(Record(id=1, value=100))
            # Yield control — but lock prevents B from entering
            await asyncio.sleep(0.01)
            await provider.insert(Record(id=2, value=200))
            execution_order.append("a_end")

    async def transaction_b() -> None:
        # Small delay to ensure A acquires lock first
        await asyncio.sleep(0.001)
        async with provider.atomic():
            execution_order.append("b_start")
            await provider.insert(Record(id=3, value=300))
            execution_order.append("b_end")

    await asyncio.gather(transaction_a(), transaction_b())

    # A must complete before B starts (serialization)
    assert execution_order == ["a_start", "a_end", "b_start", "b_end"]
    # Data reflects sequential execution: A's records first, then B's
    assert provider.data == [
        Record(id=1, value=100),
        Record(id=2, value=200),
        Record(id=3, value=300),
    ]
