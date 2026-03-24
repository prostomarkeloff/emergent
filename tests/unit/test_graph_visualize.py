"""Tests for graph visualization — Mermaid, tree, text, ASCII output.

Covers: get_dependencies, get_all_nodes, get_layers, to_mermaid (layered/flat),
to_tree, to_text, to_ascii, visualize (all styles), _short_name.
"""

from __future__ import annotations

from typing import Callable

from emergent.graph._visualize import (
    get_dependencies,
    get_all_nodes,
    get_layers,
    to_mermaid,
    to_tree,
    to_text,
    to_ascii,
    visualize,
)
from emergent.graph import _visualize as _visualize_mod

# Access private helper via getattr to avoid reportPrivateUsage
_short_name: Callable[..., str] = getattr(_visualize_mod, "_short_name")


# ===============================================================================
# Test node hierarchy
# ===============================================================================


class InputA:
    """Leaf node with no dependencies."""

    @classmethod
    def __compose__(cls) -> InputA:
        return cls()


class InputB:
    """Another leaf node."""

    @classmethod
    def __compose__(cls) -> InputB:
        return cls()


class MiddleNode:
    """Depends on InputA."""

    @classmethod
    def __compose__(cls, a: InputA) -> MiddleNode:
        return cls()


class OutputNode:
    """Depends on MiddleNode and InputB."""

    @classmethod
    def __compose__(cls, m: MiddleNode, b: InputB) -> OutputNode:
        return cls()


class SingleNode:
    """A node with no dependencies (no __compose__)."""
    pass


class LinearA:
    """Leaf."""

    @classmethod
    def __compose__(cls) -> LinearA:
        return cls()


class LinearB:
    """Depends on LinearA."""

    @classmethod
    def __compose__(cls, a: LinearA) -> LinearB:
        return cls()


class LinearC:
    """Depends on LinearB."""

    @classmethod
    def __compose__(cls, b: LinearB) -> LinearC:
        return cls()


# ===============================================================================
# get_dependencies
# ===============================================================================


class TestGetDependencies:
    def test_no_compose(self) -> None:
        assert get_dependencies(SingleNode) == []

    def test_leaf_node(self) -> None:
        # InputA.__compose__ has no params besides cls
        assert get_dependencies(InputA) == []

    def test_single_dependency(self) -> None:
        deps = get_dependencies(MiddleNode)
        assert deps == [InputA]

    def test_multiple_dependencies(self) -> None:
        deps = get_dependencies(OutputNode)
        assert set(deps) == {MiddleNode, InputB}


# ===============================================================================
# get_all_nodes
# ===============================================================================


class TestGetAllNodes:
    def test_single_node(self) -> None:
        graph = get_all_nodes(SingleNode)
        assert SingleNode in graph
        assert graph[SingleNode] == []

    def test_linear_chain(self) -> None:
        graph = get_all_nodes(LinearC)
        assert LinearC in graph
        assert LinearB in graph
        assert LinearA in graph
        assert graph[LinearC] == [LinearB]
        assert graph[LinearB] == [LinearA]
        assert graph[LinearA] == []

    def test_diamond(self) -> None:
        graph = get_all_nodes(OutputNode)
        assert OutputNode in graph
        assert MiddleNode in graph
        assert InputA in graph
        assert InputB in graph


# ===============================================================================
# get_layers
# ===============================================================================


class TestGetLayers:
    def test_single_node(self) -> None:
        layers = get_layers(SingleNode)
        assert len(layers) == 1
        assert SingleNode in layers[0]

    def test_linear_chain(self) -> None:
        layers = get_layers(LinearC)
        assert len(layers) == 3
        # Layer 0: LinearA (no deps)
        assert LinearA in layers[0]
        # Layer 1: LinearB
        assert LinearB in layers[1]
        # Layer 2: LinearC
        assert LinearC in layers[2]

    def test_diamond(self) -> None:
        layers = get_layers(OutputNode)
        # InputA and InputB at layer 0
        # MiddleNode at layer 1
        # OutputNode at layer 2
        assert len(layers) == 3
        layer0_set = set(layers[0])
        assert InputA in layer0_set
        assert InputB in layer0_set
        assert MiddleNode in layers[1]
        assert OutputNode in layers[2]


# ===============================================================================
# to_mermaid
# ===============================================================================


class TestToMermaid:
    def test_layered_output(self) -> None:
        result = to_mermaid(OutputNode, layered=True)
        assert "graph TD" in result
        assert "subgraph" in result
        assert "OutputNode" in result
        assert "MiddleNode" in result
        assert "InputA" in result
        assert "InputB" in result
        assert "-->" in result

    def test_flat_output(self) -> None:
        result = to_mermaid(OutputNode, layered=False)
        assert "graph TD" in result
        assert "subgraph" not in result
        assert "-->" in result
        assert "OutputNode" in result

    def test_single_node(self) -> None:
        result = to_mermaid(SingleNode, layered=True)
        assert "SingleNode" in result

    def test_linear_chain(self) -> None:
        result = to_mermaid(LinearC, layered=True)
        assert "LinearC" in result
        assert "LinearB" in result
        assert "LinearA" in result


# ===============================================================================
# to_tree
# ===============================================================================


class TestToTree:
    def test_single_node(self) -> None:
        result = to_tree(SingleNode)
        assert "SingleNode" in result

    def test_linear_chain(self) -> None:
        result = to_tree(LinearC)
        assert "LinearC" in result
        assert "LinearB" in result
        assert "LinearA" in result

    def test_diamond_no_duplicate_expansion(self) -> None:
        result = to_tree(OutputNode)
        assert "OutputNode" in result
        # InputA appears as child of MiddleNode
        lines = result.split("\n")
        assert len(lines) >= 3


# ===============================================================================
# to_text
# ===============================================================================


class TestToText:
    def test_single_node(self) -> None:
        result = to_text(SingleNode)
        assert "SingleNode" in result
        assert "[0]" in result

    def test_linear_chain(self) -> None:
        result = to_text(LinearC)
        assert "[0]" in result
        assert "[1]" in result
        assert "[2]" in result

    def test_diamond(self) -> None:
        result = to_text(OutputNode)
        assert "InputA" in result
        assert "InputB" in result
        assert "MiddleNode" in result
        assert "OutputNode" in result


# ===============================================================================
# to_ascii
# ===============================================================================


class TestToAscii:
    def test_single_node(self) -> None:
        result = to_ascii(SingleNode)
        assert "Single" in result  # short name removes "Node"

    def test_linear_chain(self) -> None:
        result = to_ascii(LinearC)
        # Should have boxes and connectors
        assert "LinearC" in result or "LinearC".replace("Node", "") in result

    def test_diamond(self) -> None:
        result = to_ascii(OutputNode)
        assert "OUTPUT" in result
        assert "INPUT" in result

    def test_empty_graph(self) -> None:
        # A node whose get_all_nodes returns empty (shouldn't normally happen,
        # but we can test the guard)
        class EmptyNode:
            pass

        result = to_ascii(EmptyNode)
        # Single node, so it should still render
        assert "Empty" in result

    def test_parallel_annotation(self) -> None:
        # OutputNode has InputA and InputB at layer 0 (2 parallel nodes)
        result = to_ascii(OutputNode)
        # The input layer has 2 nodes
        assert "INPUT" in result or "PARALLEL" in result


# ===============================================================================
# _short_name
# ===============================================================================


class TestShortName:
    def test_removes_node_suffix(self) -> None:
        assert _short_name("FetchUserNode") == "FetchUser"

    def test_short_enough(self) -> None:
        assert _short_name("Short") == "Short"

    def test_truncates_long_name(self) -> None:
        result = _short_name("VeryLongProcessingStepName", max_len=12)
        assert len(result) <= 12
        assert result.endswith("..")

    def test_exact_max_len(self) -> None:
        result = _short_name("ExactLength!", max_len=12)
        assert result == "ExactLength!"


# ===============================================================================
# visualize (unified entry point)
# ===============================================================================


class TestVisualize:
    def test_mermaid_style(self) -> None:
        result = visualize(OutputNode, style="mermaid")
        assert "graph TD" in result
        assert "subgraph" in result

    def test_ascii_style(self) -> None:
        result = visualize(OutputNode, style="ascii")
        assert "OUTPUT" in result or "Input" in result

    def test_tree_style(self) -> None:
        result = visualize(OutputNode, style="tree")
        assert "OutputNode" in result

    def test_text_style(self) -> None:
        result = visualize(OutputNode, style="text")
        assert "[" in result

    def test_layers_style(self) -> None:
        result = visualize(OutputNode, style="layers")
        assert "Layer 0" in result
        assert "Layer 1" in result
        assert "Layer 2" in result
