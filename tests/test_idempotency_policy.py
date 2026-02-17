"""Tests for emergent.idempotency._policy.

Covers:
    - OnPending enum values (WAIT, FAIL, FORCE)
    - Module-level singletons (WAIT, FAIL, FORCE)
    - Policy defaults
    - Policy.with_ttl — seconds, minutes, hours, delta, zero
    - Policy.with_on_pending — setting conflict strategy
    - Policy.with_wait_timeout — seconds, delta
    - Policy.with_lock_timeout — seconds, delta
    - Policy.with_store_failed — toggle persist_failed
    - Policy.with_failed_ttl — seconds, delta, zero
    - Immutability — each method returns new Policy, original unchanged
    - Fluent chaining
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from emergent.idempotency._policy import (
    OnPending,
    WAIT,
    FAIL,
    FORCE,
    Policy,
)


# ═══════════════════════════════════════════════════════════════════════════════
# OnPending Enum
# ═══════════════════════════════════════════════════════════════════════════════


class TestOnPending:
    def test_enum_values(self) -> None:
        assert OnPending.WAIT is not None
        assert OnPending.FAIL is not None
        assert OnPending.FORCE is not None

    def test_singletons_match_enum(self) -> None:
        assert WAIT is OnPending.WAIT
        assert FAIL is OnPending.FAIL
        assert FORCE is OnPending.FORCE

    def test_all_values_distinct(self) -> None:
        assert len(set([OnPending.WAIT, OnPending.FAIL, OnPending.FORCE])) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# Policy Defaults
# ═══════════════════════════════════════════════════════════════════════════════


class TestPolicyDefaults:
    def test_default_result_ttl_is_none(self) -> None:
        p = Policy()
        assert p.result_ttl is None

    def test_default_conflict_strategy_is_wait(self) -> None:
        p = Policy()
        assert p.conflict_strategy == OnPending.WAIT

    def test_default_pending_wait_timeout(self) -> None:
        p = Policy()
        assert p.pending_wait_timeout == timedelta(seconds=30)

    def test_default_lock_acquire_timeout(self) -> None:
        p = Policy()
        assert p.lock_acquire_timeout == timedelta(seconds=5)

    def test_default_persist_failed_is_false(self) -> None:
        p = Policy()
        assert p.persist_failed is False

    def test_default_failed_result_ttl_is_none(self) -> None:
        p = Policy()
        assert p.failed_result_ttl is None


# ═══════════════════════════════════════════════════════════════════════════════
# Policy.with_ttl
# ═══════════════════════════════════════════════════════════════════════════════


class TestPolicyWithTtl:
    def test_with_seconds(self) -> None:
        p = Policy().with_ttl(seconds=3600)
        assert p.result_ttl == timedelta(seconds=3600)

    def test_with_minutes(self) -> None:
        p = Policy().with_ttl(minutes=10)
        assert p.result_ttl == timedelta(minutes=10)

    def test_with_hours(self) -> None:
        p = Policy().with_ttl(hours=2)
        assert p.result_ttl == timedelta(hours=2)

    def test_with_combined_units(self) -> None:
        p = Policy().with_ttl(hours=1, minutes=30, seconds=45)
        expected = timedelta(hours=1, minutes=30, seconds=45)
        assert p.result_ttl == expected

    def test_with_delta(self) -> None:
        delta = timedelta(days=7)
        p = Policy().with_ttl(delta=delta)
        assert p.result_ttl == delta

    def test_delta_takes_precedence(self) -> None:
        delta = timedelta(days=1)
        p = Policy().with_ttl(seconds=999, delta=delta)
        assert p.result_ttl == delta

    def test_zero_values_result_in_none(self) -> None:
        p = Policy().with_ttl(seconds=0)
        assert p.result_ttl is None

    def test_no_args_result_in_none(self) -> None:
        p = Policy().with_ttl()
        assert p.result_ttl is None

    def test_preserves_other_fields(self) -> None:
        original = Policy(
            conflict_strategy=OnPending.FAIL,
            pending_wait_timeout=timedelta(seconds=10),
            lock_acquire_timeout=timedelta(seconds=2),
            persist_failed=True,
            failed_result_ttl=timedelta(seconds=60),
        )
        updated = original.with_ttl(seconds=100)
        assert updated.conflict_strategy == OnPending.FAIL
        assert updated.pending_wait_timeout == timedelta(seconds=10)
        assert updated.lock_acquire_timeout == timedelta(seconds=2)
        assert updated.persist_failed is True
        assert updated.failed_result_ttl == timedelta(seconds=60)


# ═══════════════════════════════════════════════════════════════════════════════
# Policy.with_on_pending
# ═══════════════════════════════════════════════════════════════════════════════


class TestPolicyWithOnPending:
    def test_set_to_fail(self) -> None:
        p = Policy().with_on_pending(OnPending.FAIL)
        assert p.conflict_strategy == OnPending.FAIL

    def test_set_to_force(self) -> None:
        p = Policy().with_on_pending(OnPending.FORCE)
        assert p.conflict_strategy == OnPending.FORCE

    def test_set_to_wait(self) -> None:
        p = Policy().with_on_pending(OnPending.WAIT)
        assert p.conflict_strategy == OnPending.WAIT

    def test_preserves_other_fields(self) -> None:
        original = Policy(result_ttl=timedelta(seconds=100))
        updated = original.with_on_pending(OnPending.FAIL)
        assert updated.result_ttl == timedelta(seconds=100)


# ═══════════════════════════════════════════════════════════════════════════════
# Policy.with_wait_timeout
# ═══════════════════════════════════════════════════════════════════════════════


class TestPolicyWithWaitTimeout:
    def test_with_seconds(self) -> None:
        p = Policy().with_wait_timeout(seconds=60)
        assert p.pending_wait_timeout == timedelta(seconds=60)

    def test_with_delta(self) -> None:
        delta = timedelta(minutes=2)
        p = Policy().with_wait_timeout(delta=delta)
        assert p.pending_wait_timeout == delta

    def test_default_when_no_seconds(self) -> None:
        p = Policy().with_wait_timeout()
        assert p.pending_wait_timeout == timedelta(seconds=30)

    def test_preserves_other_fields(self) -> None:
        original = Policy(result_ttl=timedelta(seconds=100))
        updated = original.with_wait_timeout(seconds=15)
        assert updated.result_ttl == timedelta(seconds=100)


# ═══════════════════════════════════════════════════════════════════════════════
# Policy.with_lock_timeout
# ═══════════════════════════════════════════════════════════════════════════════


class TestPolicyWithLockTimeout:
    def test_with_seconds(self) -> None:
        p = Policy().with_lock_timeout(seconds=10)
        assert p.lock_acquire_timeout == timedelta(seconds=10)

    def test_with_delta(self) -> None:
        delta = timedelta(seconds=20)
        p = Policy().with_lock_timeout(delta=delta)
        assert p.lock_acquire_timeout == delta

    def test_default_when_no_seconds(self) -> None:
        p = Policy().with_lock_timeout()
        assert p.lock_acquire_timeout == timedelta(seconds=5)

    def test_preserves_other_fields(self) -> None:
        original = Policy(
            conflict_strategy=OnPending.FORCE,
            result_ttl=timedelta(hours=1),
        )
        updated = original.with_lock_timeout(seconds=3)
        assert updated.conflict_strategy == OnPending.FORCE
        assert updated.result_ttl == timedelta(hours=1)


# ═══════════════════════════════════════════════════════════════════════════════
# Policy.with_store_failed
# ═══════════════════════════════════════════════════════════════════════════════


class TestPolicyWithStoreFailed:
    def test_enable_store_failed(self) -> None:
        p = Policy().with_store_failed(True)
        assert p.persist_failed is True

    def test_disable_store_failed(self) -> None:
        p = Policy(persist_failed=True).with_store_failed(False)
        assert p.persist_failed is False

    def test_default_is_true(self) -> None:
        p = Policy().with_store_failed()
        assert p.persist_failed is True

    def test_preserves_other_fields(self) -> None:
        original = Policy(result_ttl=timedelta(seconds=100))
        updated = original.with_store_failed(True)
        assert updated.result_ttl == timedelta(seconds=100)


# ═══════════════════════════════════════════════════════════════════════════════
# Policy.with_failed_ttl
# ═══════════════════════════════════════════════════════════════════════════════


class TestPolicyWithFailedTtl:
    def test_with_seconds(self) -> None:
        p = Policy().with_failed_ttl(seconds=120)
        assert p.failed_result_ttl == timedelta(seconds=120)

    def test_with_delta(self) -> None:
        delta = timedelta(minutes=5)
        p = Policy().with_failed_ttl(delta=delta)
        assert p.failed_result_ttl == delta

    def test_zero_seconds_gives_none(self) -> None:
        p = Policy().with_failed_ttl(seconds=0)
        assert p.failed_result_ttl is None

    def test_preserves_other_fields(self) -> None:
        original = Policy(persist_failed=True, result_ttl=timedelta(hours=1))
        updated = original.with_failed_ttl(seconds=60)
        assert updated.persist_failed is True
        assert updated.result_ttl == timedelta(hours=1)


# ═══════════════════════════════════════════════════════════════════════════════
# Immutability
# ═══════════════════════════════════════════════════════════════════════════════


class TestPolicyImmutability:
    def test_with_ttl_returns_new_instance(self) -> None:
        original = Policy()
        updated = original.with_ttl(seconds=100)
        assert original is not updated
        assert original.result_ttl is None
        assert updated.result_ttl == timedelta(seconds=100)

    def test_with_on_pending_returns_new_instance(self) -> None:
        original = Policy()
        updated = original.with_on_pending(OnPending.FAIL)
        assert original is not updated
        assert original.conflict_strategy == OnPending.WAIT
        assert updated.conflict_strategy == OnPending.FAIL

    def test_frozen_cannot_mutate(self) -> None:
        p = Policy()
        with pytest.raises(AttributeError):
            p.result_ttl = timedelta(seconds=1)  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# Fluent Chaining
# ═══════════════════════════════════════════════════════════════════════════════


class TestPolicyFluentChaining:
    def test_full_chain(self) -> None:
        policy = (
            Policy()
            .with_ttl(seconds=3600)
            .with_on_pending(WAIT)
            .with_wait_timeout(seconds=30)
            .with_lock_timeout(seconds=10)
            .with_store_failed(True)
            .with_failed_ttl(seconds=60)
        )
        assert policy.result_ttl == timedelta(seconds=3600)
        assert policy.conflict_strategy == OnPending.WAIT
        assert policy.pending_wait_timeout == timedelta(seconds=30)
        assert policy.lock_acquire_timeout == timedelta(seconds=10)
        assert policy.persist_failed is True
        assert policy.failed_result_ttl == timedelta(seconds=60)
