"""
Ops — data-driven dispatch (replaces match/case).

Instead of:
    match operation:
        case CreateUser(...): create_user(...)
        case GetUser(...): get_user(...)

You write:
    ops().on(CreateUser, create_user).on(GetUser, get_user).compile()

Level 5: emergent.ops
Level 2: kungfu.Result
"""

from dataclasses import dataclass
from kungfu import Result, Ok, Error
from emergent import ops as O
from examples._infra import banner, run, UserId, User, NotFound, FakeDb


db = FakeDb()


# ═══════════════════════════════════════════════════════════════════════════════
# Operations — frozen dataclasses inheriting from Returning[T, E]
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class GetUser(O.Returning[User, NotFound]):
    user_id: UserId


@dataclass(frozen=True, slots=True)
class CreateUser(O.Returning[User, str]):
    name: str
    email: str


# ═══════════════════════════════════════════════════════════════════════════════
# Handlers — plain async functions
# ═══════════════════════════════════════════════════════════════════════════════


async def get_user(req: GetUser) -> Result[User, NotFound]:
    return await db.get_user(req.user_id)


async def create_user(req: CreateUser) -> Result[User, str]:
    uid = UserId(len(db.users) + 1)
    user = User(uid, req.name, req.email)
    db.users[uid.value] = user
    return Ok(user)


# ═══════════════════════════════════════════════════════════════════════════════
# Runner — ops().on(...).compile()
# ═══════════════════════════════════════════════════════════════════════════════

runner = O.ops().on(GetUser, get_user).on(CreateUser, create_user).compile()


async def main() -> None:
    banner("Ops: Data-Driven Dispatch")

    # Execute operations via runner
    print("\n1. Get existing user:")
    r1 = await runner.run(GetUser(UserId(1)))
    match r1:
        case Ok(u):
            print(f"   → {u.name} ({u.email})")
        case Error(e):
            print(f"   → Error: {e}")

    print("\n2. Create new user:")
    r2 = await runner.run(CreateUser("Charlie", "charlie@example.com"))
    match r2:
        case Ok(u):
            print(f"   → Created: {u.name}")
        case Error(e):
            print(f"   → Error: {e}")

    print("\n3. Get non-existent user:")
    r3 = await runner.run(GetUser(UserId(999)))
    match r3:
        case Ok(u):
            print(f"   → {u.name}")
        case Error(e):
            print(f"   → Error: {e}")

    print("\nDone!")


if __name__ == "__main__":
    run(main)
