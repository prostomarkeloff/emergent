"""
Graph visualization — Mermaid diagrams, tree output.

    from emergent import graph as G

    print(G.to_mermaid(CheckoutNode))
    print(G.visualize(CheckoutNode, style="tree"))
"""

from __future__ import annotations

import inspect
from typing import Literal, Any, get_type_hints


def get_dependencies(node_type: type[Any]) -> list[type[Any]]:
    """Extract dependencies from __compose__ signature."""
    compose = getattr(node_type, "__compose__", None)
    if compose is None:
        return []

    try:
        hints = get_type_hints(compose)
    except Exception:
        return []

    deps: list[type[Any]] = []
    sig = inspect.signature(compose)
    for name, _ in sig.parameters.items():
        if name == "cls":
            continue
        hint = hints.get(name)
        if hint is not None and isinstance(hint, type):
            deps.append(hint)

    return deps


def get_all_nodes(target: type[Any]) -> dict[type[Any], list[type[Any]]]:
    """Build full dependency graph."""
    graph: dict[type[Any], list[type[Any]]] = {}

    def traverse(node: type[Any]) -> None:
        if node in graph:
            return
        deps = get_dependencies(node)
        graph[node] = deps
        for dep in deps:
            traverse(dep)

    traverse(target)
    return graph


def get_layers(target: type[Any]) -> list[list[type[Any]]]:
    """
    Get nodes organized by layers (topological sort).

    Layer 0: nodes with no dependencies (inputs)
    Layer 1: nodes that depend only on layer 0
    ...
    Last layer: target node
    """
    graph = get_all_nodes(target)

    # Calculate depth for each node
    depths: dict[type[Any], int] = {}

    def get_depth(node: type[Any]) -> int:
        if node in depths:
            return depths[node]

        deps = graph.get(node, [])
        if not deps:
            depths[node] = 0
            return 0

        max_dep_depth = max(get_depth(d) for d in deps)
        depths[node] = max_dep_depth + 1
        return depths[node]

    for node in graph:
        get_depth(node)

    # Group by depth
    max_depth = max(depths.values()) if depths else 0
    layers: list[list[type[Any]]] = [[] for _ in range(max_depth + 1)]

    for node, depth in depths.items():
        layers[depth].append(node)

    return layers


def to_mermaid(target: type[Any], layered: bool = True) -> str:
    """
    Generate Mermaid diagram.

    Args:
        target: Root node type
        layered: If True, use subgraphs for layers (nicer visual)

    Example:
        print(G.to_mermaid(CheckoutNode))
    """
    graph = get_all_nodes(target)

    if layered:
        layers = get_layers(target)
        lines = ["graph TD"]

        # Add subgraphs for each layer
        for i, layer in enumerate(layers):
            if not layer:
                continue
            layer_name = f"L{i}" if i > 0 else "Input"
            lines.append(f"    subgraph {layer_name}")
            for node in sorted(layer, key=lambda n: n.__name__):
                lines.append(f"        {node.__name__}")
            lines.append("    end")

        # Add edges
        lines.append("")
        for node, deps in graph.items():
            for dep in deps:
                lines.append(f"    {node.__name__} --> {dep.__name__}")

        return "\n".join(lines)

    # Simple flat graph
    lines = ["graph TD"]
    for node, deps in graph.items():
        for dep in deps:
            lines.append(f"    {node.__name__} --> {dep.__name__}")
    return "\n".join(lines)


def to_tree(target: type[Any]) -> str:
    """Generate tree representation."""
    lines: list[str] = []
    visited: set[type[Any]] = set()

    def traverse(node: type[Any], prefix: str = "", is_last: bool = True) -> None:
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{node.__name__}")

        if node in visited:
            return
        visited.add(node)

        deps = get_dependencies(node)
        new_prefix = prefix + ("    " if is_last else "│   ")

        for i, dep in enumerate(deps):
            traverse(dep, new_prefix, i == len(deps) - 1)

    lines.append(target.__name__)
    visited.add(target)
    deps = get_dependencies(target)
    for i, dep in enumerate(deps):
        traverse(dep, "", i == len(deps) - 1)

    return "\n".join(lines)


def to_text(target: type[Any]) -> str:
    """Generate text representation with layers."""
    layers = get_layers(target)
    lines: list[str] = []

    for i, layer in enumerate(reversed(layers)):
        if not layer:
            continue
        depth = len(layers) - 1 - i
        indent = "  " * depth
        names = ", ".join(sorted(n.__name__ for n in layer))
        lines.append(f"{indent}[{depth}] {names}")

    return "\n".join(lines)


def _short_name(name: str, max_len: int = 12) -> str:
    """Shorten node name for ASCII box."""
    name = name.replace("Node", "")
    if len(name) <= max_len:
        return name
    return name[:max_len - 2] + ".."


def to_ascii(target: type[Any]) -> str:
    """
    Generate ASCII box diagram with layers.

    Shows nodes as boxes organized by execution layer.
    Parallel nodes (same layer) run concurrently.

    Example:
        print(G.to_ascii(CheckoutNode))
    """
    layers = get_layers(target)

    if not layers:
        return "(empty graph)"

    layer_count = len(layers)
    box_inner = 14
    box_width = box_inner + 2  # borders
    gap = 2

    def make_box(name: str) -> tuple[str, str, str]:
        short = _short_name(name, box_inner)
        return (
            "┌" + "─" * box_inner + "┐",
            "│" + short.center(box_inner) + "│",
            "└" + "─" * box_inner + "┘",
        )

    lines: list[str] = []

    # Find max layer width for centering
    max_nodes = max(len(layer) for layer in layers)
    max_width = max_nodes * box_width + (max_nodes - 1) * gap

    # Draw from top (output) to bottom (input)
    for layer_idx in range(layer_count - 1, -1, -1):
        layer = layers[layer_idx]
        if not layer:
            continue

        sorted_nodes = sorted(layer, key=lambda n: n.__name__)
        node_count = len(sorted_nodes)

        # Build boxes
        boxes = [make_box(n.__name__) for n in sorted_nodes]
        layer_width = node_count * box_width + (node_count - 1) * gap
        padding = (max_width - layer_width) // 2

        # Layer annotation
        if layer_idx == layer_count - 1:
            anno = "OUTPUT"
        elif layer_idx == 0:
            anno = "INPUT"
        elif node_count > 1:
            anno = f"PARALLEL x{node_count}"
        else:
            anno = ""

        # Draw boxes side by side, centered
        for row in range(3):
            parts = [box[row] for box in boxes]
            row_line = " " * padding + (" " * gap).join(parts)
            lines.append(row_line)

        # Annotation below
        if anno:
            center_pos = padding + layer_width // 2 - len(anno) // 2
            lines.append(" " * center_pos + anno)

        # Draw connector arrow
        if layer_idx > 0:
            arrow_pos = padding + layer_width // 2
            lines.append(" " * arrow_pos + "│")
            lines.append(" " * arrow_pos + "▼")

    return "\n".join(lines)


def visualize(
    target: type[Any],
    style: Literal["mermaid", "tree", "text", "layers", "ascii"] = "mermaid",
) -> str:
    """
    Visualize computation graph.

    Styles:
    - mermaid: Mermaid diagram with layered subgraphs
    - ascii: ASCII box diagram with layers
    - tree: Tree structure
    - text: Layer-based text view
    - layers: Simple layer listing

    Example:
        print(G.visualize(ProcessOrder, style="ascii"))
    """
    match style:
        case "mermaid":
            return to_mermaid(target, layered=True)
        case "ascii":
            return to_ascii(target)
        case "tree":
            return to_tree(target)
        case "text":
            return to_text(target)
        case "layers":
            layers = get_layers(target)
            lines: list[str] = []
            for i, layer in enumerate(layers):
                names = ", ".join(n.__name__ for n in layer)
                lines.append(f"Layer {i}: {names}")
            return "\n".join(lines)


__all__ = ("to_mermaid", "to_tree", "to_text", "to_ascii", "visualize", "get_layers", "get_dependencies")
