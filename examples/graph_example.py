"""
Graph — programs as topologies, not instructions.

The paradigm shift: you declare what depends on what.
The framework figures out how to execute.

Level 5: emergent.graph
Level 4: nodnod
Level 2: kungfu types
Level 1: Protocol
"""

from typing import Protocol
from dataclasses import dataclass
from emergent import graph as G
from examples._infra import banner, run, UserId, User


# Domain
@dataclass(frozen=True)
class Order:
    id: str
    user_id: UserId
    amount: int


@dataclass(frozen=True)
class Discount:
    percent: int
    reason: str


@dataclass(frozen=True)
class OrderResult:
    order_id: str
    user: User
    discount: Discount | None
    final_amount: int


# Nodes — each is a computation with typed dependencies
@G.node
class OrderInput:
    def __init__(self, data: Order) -> None:
        self.data = data

    @classmethod
    def __compose__(cls, order: Order) -> "OrderInput":
        return cls(order)


@G.node
class FetchUser:
    """Fetch user from repo."""

    def __init__(self, data: User) -> None:
        self.data = data

    @classmethod
    async def __compose__(cls, order: OrderInput) -> "FetchUser":
        # In real app: await repo.get_user(order.data.user_id)
        return cls(User(order.data.user_id, "Alice", "alice@example.com", "gold"))


@G.node
class CalcDiscount:
    """Calculate discount based on user tier."""

    def __init__(self, data: Discount | None) -> None:
        self.data = data

    @classmethod
    async def __compose__(cls, user: FetchUser) -> "CalcDiscount":
        # Depends on FetchUser — runs after it
        match user.data.tier:
            case "gold":
                return cls(Discount(20, "Gold member"))
            case "silver":
                return cls(Discount(10, "Silver member"))
            case _:
                return cls(None)


@G.node
class ProcessOrder:
    """Final order processing."""

    def __init__(self, data: OrderResult) -> None:
        self.data = data

    @classmethod
    async def __compose__(
        cls,
        order: OrderInput,
        user: FetchUser,
        discount: CalcDiscount,
    ) -> "ProcessOrder":
        # Framework knows the dependency graph:
        # OrderInput → FetchUser → CalcDiscount → ProcessOrder
        amount = order.data.amount
        final = amount * (100 - (discount.data.percent if discount.data else 0)) // 100
        return cls(OrderResult(order.data.id, user.data, discount.data, final))

    @classmethod
    async def execute(cls, order: Order) -> OrderResult:
        """Type-safe entry point — encapsulates all dependencies."""
        return (await G.compose(cls, order)).data


# DI with Protocol — swap implementations without changing the graph
class PaymentGateway(Protocol):
    async def charge(self, amount: int) -> str: ...


class StripePayment:
    async def charge(self, amount: int) -> str:
        print(f"  [Stripe] ${amount / 100:.2f}")
        return f"ch_{amount}"


class MockPayment:
    async def charge(self, amount: int) -> str:
        print(f"  [Mock] ${amount / 100:.2f}")
        return f"mock_{amount}"


@G.node
class ProcessPayment:
    """Payment processing with injected gateway."""

    def __init__(self, charge_id: str) -> None:
        self.charge_id = charge_id

    @classmethod
    async def __compose__(cls, gateway: PaymentGateway) -> "ProcessPayment":
        # Depends on abstract PaymentGateway — bound at runtime
        return cls(await gateway.charge(1999))


async def main() -> None:
    banner("Graph: Programs as Topologies")

    # The graph:
    # OrderInput → FetchUser → CalcDiscount → ProcessOrder
    #
    # If FetchUser and CalcDiscount didn't depend on each other,
    # they would run in parallel automatically.

    order = Order("ORD-001", UserId(42), 10000)
    result = await ProcessOrder.execute(order)

    print(f"\nOrder: {result.order_id}")
    print(f"User: {result.user.name} ({result.user.tier})")
    if result.discount:
        print(f"Discount: {result.discount.percent}%")
    print(f"Final: ${result.final_amount / 100:.2f}")

    banner("Graph: DI with Protocol")

    # Same graph, different bindings
    print("\nProduction (Stripe):")
    node = await G.run(ProcessPayment).inject_as(PaymentGateway, StripePayment())
    print(f"  → {node.charge_id}")

    print("\nTesting (Mock):")
    node = await G.run(ProcessPayment).inject_as(PaymentGateway, MockPayment())
    print(f"  → {node.charge_id}")


if __name__ == "__main__":
    run(main)
