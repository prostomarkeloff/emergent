"""Tests for graph analysis — static inspection without execution.

Covers: GraphStats, analyze() for various graph shapes:
single node, linear chain, diamond, virtual nodes, cached nodes.
"""

from __future__ import annotations

from emergent.graph._analyze import GraphStats, analyze


# ===============================================================================
# Test node hierarchy
# ===============================================================================


class LeafA:
    """Node with no dependencies."""
    __dependencies__: set[type] = set()


class LeafB:
    """Another leaf node."""
    __dependencies__: set[type] = set()


class MiddleNode:
    """Node with one dependency."""
    __dependencies__: set[type] = {LeafA}


class TopNode:
    """Node with two dependencies (diamond shape)."""
    __dependencies__: set[type] = {MiddleNode, LeafB}


class LinearA:
    __dependencies__: set[type] = set()


class LinearB:
    __dependencies__: set[type] = {LinearA}


class LinearC:
    __dependencies__: set[type] = {LinearB}


class VirtualNode:
    """Simulates a virtual node."""
    __is_virtual__ = True
    __dependencies__: set[type] = set()


class CachedNode:
    """Simulates a cached node."""
    __cache__ = True
    __dependencies__: set[type] = set()


class MixedRoot:
    """Root that depends on virtual, cached, and regular nodes."""
    __dependencies__: set[type] = {VirtualNode, CachedNode, LeafA}


# ===============================================================================
# GraphStats
# ===============================================================================


class TestGraphStats:
    def test_dataclass_fields(self) -> None:
        stats = GraphStats(
            node_count=5,
            edge_count=4,
            max_depth=3,
            parallel_groups=2,
            has_virtuals=True,
            virtual_count=1,
            cached_nodes=("CachedNode",),
        )
        assert stats.node_count == 5
        assert stats.edge_count == 4
        assert stats.max_depth == 3
        assert stats.parallel_groups == 2
        assert stats.has_virtuals is True
        assert stats.virtual_count == 1
        assert stats.cached_nodes == ("CachedNode",)

    def test_frozen(self) -> None:
        stats = GraphStats(
            node_count=1,
            edge_count=0,
            max_depth=0,
            parallel_groups=1,
            has_virtuals=False,
            virtual_count=0,
            cached_nodes=(),
        )
        # frozen dataclass should not allow mutation
        try:
            stats.node_count = 99  # type: ignore[misc]
            assert False, "Expected frozen dataclass to raise"
        except AttributeError:
            pass


# ===============================================================================
# analyze — single node
# ===============================================================================


class TestAnalyzeSingleNode:
    def test_leaf_node(self) -> None:
        stats = analyze(LeafA)
        assert stats.node_count == 1
        assert stats.edge_count == 0
        assert stats.max_depth == 0
        assert stats.parallel_groups == 1
        assert stats.has_virtuals is False
        assert stats.virtual_count == 0
        assert stats.cached_nodes == ()


# ===============================================================================
# analyze — linear chain
# ===============================================================================


class TestAnalyzeLinearChain:
    def test_chain_of_three(self) -> None:
        stats = analyze(LinearC)
        assert stats.node_count == 3
        assert stats.edge_count == 2
        assert stats.max_depth == 2
        assert stats.parallel_groups == 3
        assert stats.has_virtuals is False


# ===============================================================================
# analyze — diamond
# ===============================================================================


class TestAnalyzeDiamond:
    def test_diamond_shape(self) -> None:
        stats = analyze(TopNode)
        # TopNode -> MiddleNode -> LeafA, TopNode -> LeafB
        assert stats.node_count == 4
        assert stats.edge_count == 3
        assert stats.max_depth == 2
        assert stats.has_virtuals is False


# ===============================================================================
# analyze — virtual nodes
# ===============================================================================


class TestAnalyzeVirtualNodes:
    def test_detects_virtual(self) -> None:
        stats = analyze(VirtualNode)
        assert stats.has_virtuals is True
        assert stats.virtual_count == 1

    def test_mixed_root_with_virtual(self) -> None:
        stats = analyze(MixedRoot)
        assert stats.has_virtuals is True
        assert stats.virtual_count == 1


# ===============================================================================
# analyze — cached nodes
# ===============================================================================


class TestAnalyzeCachedNodes:
    def test_detects_cached(self) -> None:
        stats = analyze(CachedNode)
        assert stats.cached_nodes == ("CachedNode",)

    def test_mixed_root_with_cached(self) -> None:
        stats = analyze(MixedRoot)
        assert "CachedNode" in stats.cached_nodes


# ===============================================================================
# analyze — node with no __dependencies__
# ===============================================================================


class TestAnalyzeNoDependencies:
    def test_plain_class(self) -> None:
        class PlainClass:
            pass

        stats = analyze(PlainClass)
        assert stats.node_count == 1
        assert stats.edge_count == 0
        assert stats.max_depth == 0


# ===============================================================================
# analyze — edge deduplication
# ===============================================================================


class TestAnalyzeEdgeDedup:
    def test_shared_dependency_counted_once(self) -> None:
        """If two nodes share a dependency, the shared node is visited once."""

        class Shared:
            __dependencies__: set[type] = set()

        class A:
            __dependencies__: set[type] = {Shared}

        class B:
            __dependencies__: set[type] = {Shared}

        class Root:
            __dependencies__: set[type] = {A, B}

        stats = analyze(Root)
        # Root, A, B, Shared = 4 nodes
        assert stats.node_count == 4
        # Root->A, Root->B, A->Shared, B->Shared = 4 edges
        assert stats.edge_count == 4
