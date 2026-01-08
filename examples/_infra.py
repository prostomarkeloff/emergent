"""Shared infrastructure for examples."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field

from kungfu import Result, Ok, Error


# Types
@dataclass(frozen=True, slots=True)
class UserId:
    value: int


@dataclass(frozen=True, slots=True)
class User:
    id: UserId
    name: str
    email: str
    tier: str = "standard"


# Errors
@dataclass(frozen=True, slots=True)
class Failure(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class NotFound(Exception):
    entity: str
    id: int | str

    def __str__(self) -> str:
        return f"{self.entity}:{self.id} not found"


# Fake DB
@dataclass(slots=True)
class FakeDb:
    users: dict[int, User] = field(default_factory=lambda: {
        1: User(UserId(1), "Alice", "alice@example.com", "gold"),
        2: User(UserId(2), "Bob", "bob@example.com", "silver"),
    })

    async def get_user(self, user_id: UserId) -> Result[User, NotFound]:
        await asyncio.sleep(0.01)
        user = self.users.get(user_id.value)
        return Ok(user) if user else Error(NotFound("User", user_id.value))


# Helpers
def banner(title: str) -> None:
    print(f"\n{'─' * 50}\n{title}\n{'─' * 50}")


def run(main: Callable[[], Coroutine[object, object, None]]) -> None:
    asyncio.run(main())
