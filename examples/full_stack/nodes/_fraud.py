"""
Fraud — fraud check validation.
"""

from emergent import graph as G
from examples.full_stack.domain import FraudCheckResult, CheckoutError
from examples.full_stack.repo import fraud_service
from examples.full_stack.nodes._input import CartNode
from examples.full_stack.nodes._totals import GrandTotalNode


@G.node
class FraudCheckNode:
    """Check for fraudulent transactions."""

    def __init__(self, data: FraudCheckResult) -> None:
        self.data = data

    @classmethod
    async def __compose__(
        cls, cart: CartNode, total: GrandTotalNode
    ) -> "FraudCheckNode":
        result = await fraud_service.check(cart.data.user_id, total.total)
        if not result.approved:
            raise CheckoutError("FRAUD_REJECTED", result.reason)
        return cls(result)


__all__ = ("FraudCheckNode",)
