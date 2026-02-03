"""Exception trigger — handle specific exception types.

    endpoint(runner).expose(
        ExceptionTrigger(ValidationError),
        delegate(handle_validation_error),
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

E = TypeVar("E", bound=Exception)


@dataclass(frozen=True, slots=True)
class ExceptionTrigger(Generic[E]):
    """Fires when exception of specified type is raised.

    Attributes:
        exception_type: Exception class to handle.
        propagate: Whether to re-raise after handling. Default False.

    Example::

        async def handle_db_error(exc: TortoiseException) -> ErrorResponse:
            return ErrorResponse(error=f"Database error: {exc}")

        endpoint(runner).expose(
            ExceptionTrigger(TortoiseException),
            delegate(handle_db_error),
        )
    """

    exception_type: type[E]
    propagate: bool = False


__all__ = ("ExceptionTrigger",)
