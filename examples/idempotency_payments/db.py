"""
Database layer — SQLAlchemy models with IdempotencyMixin.

Note: Используем IdempotencyMixin из emergent — добавляет нужные колонки автоматически.
"""

from datetime import datetime

from sqlalchemy import String, DateTime, Integer, Text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from emergent.idempotency import IdempotencyMixin


# ═══════════════════════════════════════════════════════════════════════════════
# Base
# ═══════════════════════════════════════════════════════════════════════════════

class Base(DeclarativeBase):
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Orders Table — with IdempotencyMixin
# ═══════════════════════════════════════════════════════════════════════════════

class OrderTable(Base, IdempotencyMixin):
    """
    Orders table with built-in idempotency.

    Note: IdempotencyMixin добавляет:
    - idempotency_key: str (unique)
    - idempotency_status: str ("pending" | "completed" | "failed")
    - idempotency_value: str | None (JSON result)
    - idempotency_error: str | None
    - idempotency_expires_at: datetime | None
    """
    __tablename__ = "orders"

    # Primary key
    id: Mapped[str] = mapped_column(String(50), primary_key=True)

    # Order data
    customer_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Payment result (when completed)
    transaction_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payment_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Database Setup
# ═══════════════════════════════════════════════════════════════════════════════

from sqlalchemy.ext.asyncio import AsyncEngine


async def create_database(
    url: str = "sqlite+aiosqlite:///:memory:",
) -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    """Create database and return (session_factory, engine)."""
    engine = create_async_engine(url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    return async_sessionmaker(engine, expire_on_commit=False), engine
