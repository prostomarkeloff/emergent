"""Domain models."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OrderStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Order:
    id: str
    idempotency_key: str
    customer_id: str
    amount_cents: int
    currency: str
    description: str | None
    status: OrderStatus
    transaction_id: str | None
    payment_provider: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class OrderError:
    code: str
    message: str


class OrderErrors:
    @staticmethod
    def provider_error(msg: str) -> OrderError:
        return OrderError("PROVIDER_ERROR", msg)

    @staticmethod
    def invalid_request(msg: str) -> OrderError:
        return OrderError("INVALID_REQUEST", msg)
