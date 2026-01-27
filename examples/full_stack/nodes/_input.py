"""
Input — CartNode (entry point to the graph).
"""

from emergent import graph as G
from examples.full_stack.domain import Cart


@G.node
class CartNode:
    """Entry point: wraps the Cart input."""

    def __init__(self, data: Cart) -> None:
        self.data = data

    @classmethod
    def __compose__(cls, cart: Cart) -> "CartNode":
        return cls(cart)


__all__ = ("CartNode",)
