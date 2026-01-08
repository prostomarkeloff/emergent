"""
Graph analysis — static inspection without execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ═══════════════════════════════════════════════════════════════════════════════
# GraphStats — Analysis Result
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True, slots=True)
class GraphStats:
    """Statistics about computation graph."""
    node_count: int
    edge_count: int
    max_depth: int
    parallel_groups: int
    has_virtuals: bool
    virtual_count: int
    cached_nodes: tuple[str, ...]


# ═══════════════════════════════════════════════════════════════════════════════
# analyze() — Analyze Graph Structure
# ═══════════════════════════════════════════════════════════════════════════════

def analyze(target: type[Any]) -> GraphStats:
    """
    Analyze computation graph from target node.
    
    Traverses dependencies without executing.
    
    Example:
        stats = G.analyze(ProcessOrder)
        print(f"Nodes: {stats.node_count}, Parallel groups: {stats.parallel_groups}")
    """
    visited: set[type[Any]] = set()
    edges: set[tuple[type[Any], type[Any]]] = set()
    virtuals: list[type[Any]] = []
    cached: list[str] = []
    
    def traverse(node_type: type[Any], depth: int) -> int:
        if node_type in visited:
            return 0
        visited.add(node_type)
        
        max_d = depth
        
        # Check if virtual
        if getattr(node_type, "__is_virtual__", False):
            virtuals.append(node_type)
        
        # Check if cached
        if getattr(node_type, "__cache__", None):
            cached.append(node_type.__name__)
        
        # Get dependencies
        deps: set[type[Any]] = getattr(node_type, "__dependencies__", set())
        for dep in deps:
            edges.add((node_type, dep))
            max_d = max(max_d, traverse(dep, depth + 1))
        
        return max_d
    
    max_depth = traverse(target, 0)
    
    # Calculate parallel groups (nodes at same depth can run in parallel)
    # Simplified: just count layers
    parallel_groups = max_depth + 1 if max_depth > 0 else 1
    
    return GraphStats(
        node_count=len(visited),
        edge_count=len(edges),
        max_depth=max_depth,
        parallel_groups=parallel_groups,
        has_virtuals=len(virtuals) > 0,
        virtual_count=len(virtuals),
        cached_nodes=tuple(cached),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = ("GraphStats", "analyze")
