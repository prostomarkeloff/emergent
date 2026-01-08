"""
Graph visualization for full_stack checkout.

Uses emergent.graph visualization directly.

Usage:
    uv run python -m examples.full_stack.visualize
    uv run python -m examples.full_stack.visualize --style=tree
    uv run python -m examples.full_stack.visualize --node=preview
"""

from __future__ import annotations

import argparse
from typing import Any

from emergent import graph as G

from examples.full_stack.nodes import (
    CreateOrderNode,
    PreviewNode,
    UserInfoNode,
    ShippingEstimateNode,
)


NODES: dict[str, type[Any]] = {
    "checkout": CreateOrderNode,
    "preview": PreviewNode,
    "user": UserInfoNode,
    "shipping": ShippingEstimateNode,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize checkout graph")
    parser.add_argument(
        "--style", "-s",
        choices=["ascii", "mermaid", "tree", "text", "layers"],
        default="ascii",
        help="Output style (default: ascii)",
    )
    parser.add_argument(
        "--node", "-n",
        choices=list(NODES.keys()),
        default="checkout",
        help="Node to visualize (default: checkout)",
    )
    args = parser.parse_args()
    
    target = NODES[args.node]
    
    print(f"# {args.node.upper()} ({args.style})\n")
    print(G.visualize(target, args.style))


if __name__ == "__main__":
    main()
