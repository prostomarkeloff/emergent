"""Game store — ledger-based balance via relational query axis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated
from enum import Enum

from kungfu import Result, Ok, Error

from emergent.wire.axis.query import (
    relational_store,
    MemoryRelationalProvider,
    PrefixedNextId,
    SequenceNextId,
)
from emergent.wire.axis.schema import Identity


class TxType(Enum):
    CREDIT = "credit"
    DEBIT = "debit"


@dataclass
class Transaction:
    """Ledger transaction — immutable event."""
    id: Annotated[str, Identity]
    login: str
    tx_type: TxType
    amount: int
    reason: str
    created_at: datetime = field(default_factory=datetime.now)


class GameStore:
    """Ledger-based game storage with atomic transactions.

    Balance = sum(credits) - sum(debits)

    All balance-affecting operations are atomic to prevent
    race conditions in concurrent access.
    """

    INITIAL_BALANCE = 100

    def __init__(self) -> None:
        self._provider = MemoryRelationalProvider[Transaction](
            next_id=PrefixedNextId("tx_", SequenceNextId())
        )
        self._transactions = relational_store(Transaction, self._provider)

    async def _get_balance_unlocked(self, login: str) -> int:
        """Calculate balance (caller must hold lock)."""
        txs = await self._transactions.filter(lambda t: t.login == login).fetch_many()
        return sum(
            tx.amount if tx.tx_type == TxType.CREDIT else -tx.amount
            for tx in txs
        )

    async def ensure_balance(self, login: str) -> None:
        """Credit initial balance if user has no transactions (atomic)."""
        async with self._provider.atomic():
            has_tx = await self._transactions.filter(lambda t: t.login == login).exists()
            if not has_tx:
                await self._transactions.insert(Transaction(
                    id=await self._provider.next_id(),
                    login=login,
                    tx_type=TxType.CREDIT,
                    amount=self.INITIAL_BALANCE,
                    reason="initial",
                ))

    async def get_balance(self, login: str) -> int:
        """Calculate balance from ledger (atomic read)."""
        async with self._provider.atomic():
            return await self._get_balance_unlocked(login)

    async def place_bet(self, login: str, amount: int, bet: str) -> Result[int, str]:
        """Place bet atomically. Returns new balance or error.

        Atomic: check balance + debit in single transaction.
        """
        async with self._provider.atomic():
            balance = await self._get_balance_unlocked(login)
            if amount > balance:
                return Error(f"insufficient balance: have {balance}, need {amount}")

            await self._transactions.insert(Transaction(
                id=await self._provider.next_id(),
                login=login,
                tx_type=TxType.DEBIT,
                amount=amount,
                reason=f"bet:{bet}",
            ))
            return Ok(balance - amount)

    async def record_win(self, login: str, amount: int, bet: str) -> int:
        """Record win (credit). Returns new balance."""
        async with self._provider.atomic():
            await self._transactions.insert(Transaction(
                id=await self._provider.next_id(),
                login=login,
                tx_type=TxType.CREDIT,
                amount=amount,
                reason=f"win:{bet}",
            ))
            return await self._get_balance_unlocked(login)

    async def get_history(self, login: str, limit: int = 10) -> list[Transaction]:
        """Recent transactions."""
        return await (
            self._transactions
            .filter(lambda t: t.login == login)
            .order_by(lambda t: t.created_at.desc())
            .limit(limit)
            .fetch_many()
        )
