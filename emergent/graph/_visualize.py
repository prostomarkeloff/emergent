"""
Graph visualization — Mermaid diagrams, text output.
"""

from __future__ import annotations

from typing import Literal, Any

# ═══════════════════════════════════════════════════════════════════════════════
# to_mermaid() — Generate Mermaid Diagram
# ═══════════════════════════════════════════════════════════════════════════════

def to_mermaid(target: type[Any]) -> str:
    """
    Generate Mermaid diagram from computation graph.
    
    Example:
        print(G.to_mermaid(ProcessOrder))
        # graph TD
        #   ProcessOrder --> FetchUser
        #   ProcessOrder --> PaymentGateway
        #   FetchUser --> Database
    """
    visited: set[type[Any]] = set()
    edges: list[tuple[str, str]] = []
    
    def traverse(node_type: type[Any]) -> None:
        if node_type in visited:
            return
        visited.add(node_type)
        
        node_name = node_type.__name__
        
        # Get dependencies
        deps: set[type[Any]] = getattr(node_type, "__dependencies__", set())
        for dep in deps:
            dep_name = dep.__name__
            edges.append((node_name, dep_name))
            traverse(dep)
    
    traverse(target)
    
    lines = ["graph TD"]
    for src, dst in edges:
        lines.append(f"  {src} --> {dst}")
    
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# visualize() — Generate Visual Output
# ═══════════════════════════════════════════════════════════════════════════════

def visualize(
    target: type[Any],
    style: Literal["mermaid", "text", "tree"] = "mermaid",
) -> str:
    """
    Visualize computation graph.
    
    Styles:
    - mermaid: Mermaid diagram syntax
    - text: Simple text representation
    - tree: Tree structure
    
    Example:
        print(G.visualize(ProcessOrder, style="tree"))
    """
    if style == "mermaid":
        return to_mermaid(target)
    
    if style == "text":
        visited: set[type[Any]] = set()
        lines: list[str] = []
        
        def traverse_text(node_type: type[Any]) -> None:
            if node_type in visited:
                return
            visited.add(node_type)
            
            deps: set[type[Any]] = getattr(node_type, "__dependencies__", set())
            dep_names = [d.__name__ for d in deps]
            
            if dep_names:
                lines.append(f"{node_type.__name__} <- {', '.join(dep_names)}")
            else:
                lines.append(f"{node_type.__name__} (leaf)")
            
            for dep in deps:
                traverse_text(dep)
        
        traverse_text(target)
        return "\n".join(lines)
    
    if style == "tree":
        tree_lines: list[str] = []
        
        def traverse_tree(node_type: type[Any], indent: int = 0) -> None:
            prefix = "  " * indent + ("└─ " if indent > 0 else "")
            tree_lines.append(f"{prefix}{node_type.__name__}")
            
            deps: set[type[Any]] = getattr(node_type, "__dependencies__", set())
            for dep in deps:
                traverse_tree(dep, indent + 1)
        
        traverse_tree(target)
        return "\n".join(tree_lines)
    
    raise ValueError(f"Unknown style: {style}")


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = ("to_mermaid", "visualize")
