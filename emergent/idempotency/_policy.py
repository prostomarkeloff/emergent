"""
Idempotency policy — behavior configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum, auto


# ═══════════════════════════════════════════════════════════════════════════════
# On Pending — Conflict Resolution Strategy
# ═══════════════════════════════════════════════════════════════════════════════


class OnPending(Enum):
    """
    What to do when a request arrives while another is pending.

    Note: This is the core conflict resolution strategy.

    WAIT: Block and wait for pending to complete, return its result.
          Use when: Same client retrying after timeout.

    FAIL: Immediately return CONFLICT error.
          Use when: Independent concurrent requests should fail fast.

    FORCE: Ignore existing pending, execute anyway (DANGEROUS).
           Use when: You know what you're doing and need to override.
    """

    WAIT = auto()
    FAIL = auto()
    FORCE = auto()


# Singleton instances for convenience
WAIT = OnPending.WAIT
FAIL = OnPending.FAIL
FORCE = OnPending.FORCE


# ═══════════════════════════════════════════════════════════════════════════════
# Policy — Full Configuration
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Policy:
    """
    Idempotency policy configuration.

    Fluent builder pattern — chain methods to configure.

    Example:
        policy = (
            Policy()
            .with_ttl(seconds=3600)
            .with_on_pending(WAIT)
            .with_wait_timeout(seconds=30)
            .with_lock_timeout(seconds=10)
        )

    Note: Immutable — each method returns new Policy.
    Почему: Prevents accidental mutation, enables safe sharing.
    """

    result_ttl: timedelta | None = None
    conflict_strategy: OnPending = OnPending.WAIT
    pending_wait_timeout: timedelta = timedelta(seconds=30)
    lock_acquire_timeout: timedelta = timedelta(seconds=5)
    # Note: По дефолту False — ошибки не кешируются, можно retry.
    # Почему: Идемпотентность обычно нужна для успешных операций.
    # Зачем True: Защита от флуда при постоянных ошибках.
    persist_failed: bool = False
    failed_result_ttl: timedelta | None = None

    def with_ttl(
        self,
        *,
        seconds: float | None = None,
        minutes: float | None = None,
        hours: float | None = None,
        delta: timedelta | None = None,
    ) -> Policy:
        """
        Set TTL for completed records.

        After TTL, operation can be re-executed.

        Example:
            .with_ttl(seconds=3600)  # 1 hour
            .with_ttl(hours=24)      # 1 day
            .with_ttl(delta=timedelta(days=7))
        """
        if delta is not None:
            ttl_val = delta
        else:
            total_seconds = (seconds or 0) + (minutes or 0) * 60 + (hours or 0) * 3600
            ttl_val = timedelta(seconds=total_seconds) if total_seconds > 0 else None

        return Policy(
            result_ttl=ttl_val,
            conflict_strategy=self.conflict_strategy,
            pending_wait_timeout=self.pending_wait_timeout,
            lock_acquire_timeout=self.lock_acquire_timeout,
            persist_failed=self.persist_failed,
            failed_result_ttl=self.failed_result_ttl,
        )

    def with_on_pending(self, strategy: OnPending) -> Policy:
        """
        Set conflict resolution strategy.

        What to do when request arrives while another is pending.

        Example:
            .with_on_pending(I.WAIT)   # Wait for pending to complete
            .with_on_pending(I.FAIL)   # Fail immediately
        """
        return Policy(
            result_ttl=self.result_ttl,
            conflict_strategy=strategy,
            pending_wait_timeout=self.pending_wait_timeout,
            lock_acquire_timeout=self.lock_acquire_timeout,
            persist_failed=self.persist_failed,
            failed_result_ttl=self.failed_result_ttl,
        )

    def with_wait_timeout(
        self,
        *,
        seconds: float | None = None,
        delta: timedelta | None = None,
    ) -> Policy:
        """
        Set timeout for waiting on pending operations.

        Only applies when on_pending=WAIT.

        Example:
            .with_wait_timeout(seconds=30)
        """
        timeout = delta if delta else timedelta(seconds=seconds or 30)
        return Policy(
            result_ttl=self.result_ttl,
            conflict_strategy=self.conflict_strategy,
            pending_wait_timeout=timeout,
            lock_acquire_timeout=self.lock_acquire_timeout,
            persist_failed=self.persist_failed,
            failed_result_ttl=self.failed_result_ttl,
        )

    def with_lock_timeout(
        self,
        *,
        seconds: float | None = None,
        delta: timedelta | None = None,
    ) -> Policy:
        """
        Set timeout for acquiring execution lock.

        Example:
            .with_lock_timeout(seconds=5)
        """
        timeout = delta if delta else timedelta(seconds=seconds or 5)
        return Policy(
            result_ttl=self.result_ttl,
            conflict_strategy=self.conflict_strategy,
            pending_wait_timeout=self.pending_wait_timeout,
            lock_acquire_timeout=timeout,
            persist_failed=self.persist_failed,
            failed_result_ttl=self.failed_result_ttl,
        )

    def with_store_failed(self, store: bool = True) -> Policy:
        """
        Whether to store failed operation results.

        If True, failed results are cached (allows returning cached errors).
        If False, failed records are deleted (allows retry).

        Example:
            .with_store_failed(False)  # Allow retries on failure
        """
        return Policy(
            result_ttl=self.result_ttl,
            conflict_strategy=self.conflict_strategy,
            pending_wait_timeout=self.pending_wait_timeout,
            lock_acquire_timeout=self.lock_acquire_timeout,
            persist_failed=store,
            failed_result_ttl=self.failed_result_ttl,
        )

    def with_failed_ttl(
        self,
        *,
        seconds: float | None = None,
        delta: timedelta | None = None,
    ) -> Policy:
        """
        Set separate TTL for failed records.

        If not set, uses main TTL.

        Example:
            .with_failed_ttl(seconds=60)  # Failed results expire in 1 minute
        """
        ttl_val = delta if delta else timedelta(seconds=seconds or 0)
        return Policy(
            result_ttl=self.result_ttl,
            conflict_strategy=self.conflict_strategy,
            pending_wait_timeout=self.pending_wait_timeout,
            lock_acquire_timeout=self.lock_acquire_timeout,
            persist_failed=self.persist_failed,
            failed_result_ttl=ttl_val if ttl_val.total_seconds() > 0 else None,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = (
    "OnPending",
    "WAIT",
    "FAIL",
    "FORCE",
    "Policy",
)
