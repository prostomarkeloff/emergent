"""Lifecycle triggers — app startup/shutdown.

    endpoint(runner).expose(StartupTrigger(order=0), delegate(init_db))
    endpoint(runner).expose(ShutdownTrigger(), delegate(close_db))
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StartupTrigger:
    """Fires once when application starts.

    Attributes:
        order: Execution order (lower = earlier). Default 0.

    Example::

        async def init_database():
            await Tortoise.init(db_url="...")

        endpoint(runner).expose(
            StartupTrigger(order=0),
            delegate(init_database),
        )
    """

    order: int = 0


@dataclass(frozen=True, slots=True)
class ShutdownTrigger:
    """Fires once when application stops.

    Attributes:
        order: Execution order (lower = earlier). Default 0.

    Example::

        async def close_connections():
            await Tortoise.close_connections()

        endpoint(runner).expose(
            ShutdownTrigger(),
            delegate(close_connections),
        )
    """

    order: int = 0


__all__ = (
    "StartupTrigger",
    "ShutdownTrigger",
)
