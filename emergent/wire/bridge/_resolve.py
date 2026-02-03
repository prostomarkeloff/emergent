"""Dependency resolution — generic dependency graph utilities.

FRAMEWORK-AGNOSTIC — works with any dependency info provided by capabilities.
FastAPI Depends() detection is done by capabilities, not here.

    from emergent.wire.bridge._resolve import DependencyGraph

    # Capabilities provide the dependency info
    graph = DependencyGraph(...)
"""

from __future__ import annotations

from dataclasses import dataclass


# ═══════════════════════════════════════════════════════════════════════════════
# Data Types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class DependencyNode:
    """A node in the dependency graph.

    Generic — can represent any kind of dependency (Depends, global, etc.).
    The `kind` field identifies what type of dependency this is.
    """

    name: str
    kind: str  # "depends", "global", "closure", etc. — source defines these
    target: object  # The actual dependency (function, module attr, etc.)
    metadata: dict[str, object]  # Additional info from source


@dataclass(frozen=True, slots=True)
class DependencyGraph:
    """Graph of handler dependencies.

    Framework-agnostic — capabilities populate this with detected dependencies.
    """

    handler_name: str
    nodes: frozenset[DependencyNode]
    edges: tuple[tuple[str, str], ...]  # (from, to)

    @classmethod
    def empty(cls, handler_name: str) -> DependencyGraph:
        """Create empty graph for handler."""
        return cls(handler_name=handler_name, nodes=frozenset(), edges=())

    def add_node(self, node: DependencyNode) -> DependencyGraph:
        """Add node to graph."""
        return DependencyGraph(
            handler_name=self.handler_name,
            nodes=self.nodes | {node},
            edges=self.edges,
        )

    def add_edge(self, from_node: str, to_node: str) -> DependencyGraph:
        """Add edge to graph."""
        return DependencyGraph(
            handler_name=self.handler_name,
            nodes=self.nodes,
            edges=(*self.edges, (from_node, to_node)),
        )

    def get_nodes_by_kind(self, kind: str) -> frozenset[DependencyNode]:
        """Get all nodes of a specific kind."""
        return frozenset(n for n in self.nodes if n.kind == kind)

    def get_all_targets(self) -> frozenset[object]:
        """Get all dependency targets."""
        return frozenset(n.target for n in self.nodes)


# ═══════════════════════════════════════════════════════════════════════════════
# Graph Utilities
# ═══════════════════════════════════════════════════════════════════════════════


def find_unmapped(
    graph: DependencyGraph,
    mapped: frozenset[object],
) -> frozenset[DependencyNode]:
    """Find nodes whose targets are not in mapped set.

    Args:
        graph: Dependency graph
        mapped: Set of mapped targets (e.g., from MapDepends)

    Returns:
        Set of unmapped nodes
    """
    mapped_ids = frozenset(id(t) for t in mapped)
    return frozenset(n for n in graph.nodes if id(n.target) not in mapped_ids)


def topological_sort(graph: DependencyGraph) -> tuple[str, ...]:
    """Sort nodes in dependency order (leaves first).

    Args:
        graph: Dependency graph

    Returns:
        Tuple of node names in execution order
    """
    if not graph.nodes:
        return ()

    # Build adjacency — reversed (we want leaves first)
    node_names = {n.name for n in graph.nodes}
    incoming: dict[str, set[str]] = {name: set() for name in node_names}

    for from_node, to_node in graph.edges:
        if to_node in incoming:
            incoming[to_node].add(from_node)

    # Kahn's algorithm
    result: list[str] = []
    queue: list[str] = [name for name, deps in incoming.items() if not deps]

    while queue:
        node = queue.pop(0)
        result.append(node)

        for from_node, to_node in graph.edges:
            if from_node == node and to_node in incoming:
                incoming[to_node].discard(node)
                if not incoming[to_node]:
                    queue.append(to_node)

    return tuple(result)


def merge_graphs(*graphs: DependencyGraph) -> DependencyGraph:
    """Merge multiple dependency graphs.

    Args:
        graphs: Graphs to merge

    Returns:
        Combined graph
    """
    if not graphs:
        return DependencyGraph.empty("<merged>")

    all_nodes: set[DependencyNode] = set()
    all_edges: list[tuple[str, str]] = []

    for g in graphs:
        all_nodes.update(g.nodes)
        all_edges.extend(g.edges)

    return DependencyGraph(
        handler_name="<merged>",
        nodes=frozenset(all_nodes),
        edges=tuple(all_edges),
    )


__all__ = (
    # Data types
    "DependencyNode",
    "DependencyGraph",
    # Utilities
    "find_unmapped",
    "topological_sort",
    "merge_graphs",
)
