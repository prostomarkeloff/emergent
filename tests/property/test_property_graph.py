# pyright: reportPrivateUsage=false
"""Property-based tests for ScopeFamily — type-to-tier mapping algebra."""

from __future__ import annotations

from emergent.graph._family import ScopeFamily


def _make_types(n: int) -> list[type]:
    """Create N unique types via type()."""
    return [type(f"T{i}", (), {}) for i in range(n)]


def _make_tiers(n: int) -> list[str]:
    """Create N unique tier keys."""
    return [f"tier_{i}" for i in range(n)]


class TestMergeRightBiased:
    """ScopeFamily merge (|) is right-biased: f2's bindings override f1's on conflict."""

    def test_right_wins_on_conflict(self) -> None:
        types = _make_types(3)
        f1 = ScopeFamily[str]().bind("app", types[0], types[1]).bind("req", types[2])
        f2 = ScopeFamily[str]().bind("override", types[0])

        merged = f1 | f2

        # types[0] was "app" in f1, "override" in f2 => right wins
        assert merged.tier_of(types[0]) == "override"
        # types[1] still from f1
        assert merged.tier_of(types[1]) == "app"
        # types[2] still from f1
        assert merged.tier_of(types[2]) == "req"

    def test_no_conflict_both_preserved(self) -> None:
        types = _make_types(4)
        f1 = ScopeFamily[str]().bind("a", types[0], types[1])
        f2 = ScopeFamily[str]().bind("b", types[2], types[3])

        merged = f1 | f2

        assert merged.tier_of(types[0]) == "a"
        assert merged.tier_of(types[1]) == "a"
        assert merged.tier_of(types[2]) == "b"
        assert merged.tier_of(types[3]) == "b"


class TestMergeAssociativity:
    """Merge associativity: (f1 | f2) | f3 produces same bindings as f1 | (f2 | f3)."""

    def test_three_way_associativity(self) -> None:
        types = _make_types(6)
        f1 = ScopeFamily[str]().bind("x", types[0], types[1])
        f2 = ScopeFamily[str]().bind("y", types[2], types[3])
        f3 = ScopeFamily[str]().bind("z", types[4], types[5])

        left = (f1 | f2) | f3
        right = f1 | (f2 | f3)

        for t in types:
            assert left.tier_of(t) == right.tier_of(t)

    def test_associativity_with_conflicts(self) -> None:
        types = _make_types(3)
        # All three families bind types[0] to different tiers
        f1 = ScopeFamily[str]().bind("a", types[0])
        f2 = ScopeFamily[str]().bind("b", types[0], types[1])
        f3 = ScopeFamily[str]().bind("c", types[0], types[2])

        left = (f1 | f2) | f3
        right = f1 | (f2 | f3)

        # Both should resolve types[0] to "c" (rightmost wins)
        for t in types:
            assert left.tier_of(t) == right.tier_of(t)

        assert left.tier_of(types[0]) == "c"


class TestMergeIdempotence:
    """Merge idempotence: f | f == f."""

    def test_self_merge_is_identity(self) -> None:
        types = _make_types(5)
        f = (
            ScopeFamily[str]()
            .bind("app", types[0], types[1])
            .bind("req", types[2], types[3], types[4])
        )

        merged = f | f

        for t in types:
            assert merged.tier_of(t) == f.tier_of(t)

        assert dict(merged.bindings) == dict(f.bindings)

    def test_empty_self_merge(self) -> None:
        f = ScopeFamily[str]()
        merged = f | f
        assert dict(merged.bindings) == {}


class TestBindAccumulation:
    """Bind accumulation: N binds produce family with N unique mappings."""

    def test_distinct_types_accumulate(self) -> None:
        n = 10
        types = _make_types(n)
        tiers = _make_tiers(n)

        f = ScopeFamily[str]()
        for i in range(n):
            f = f.bind(tiers[i], types[i])

        assert len(f.bindings) == n
        for i in range(n):
            assert f.tier_of(types[i]) == tiers[i]

    def test_multi_type_bind(self) -> None:
        types = _make_types(5)
        f = ScopeFamily[str]().bind("shared", *types)

        assert len(f.bindings) == 5
        for t in types:
            assert f.tier_of(t) == "shared"

    def test_rebind_overwrites(self) -> None:
        types = _make_types(1)
        f = ScopeFamily[str]().bind("old", types[0]).bind("new", types[0])

        assert len(f.bindings) == 1
        assert f.tier_of(types[0]) == "new"


class TestEmptyFamilyMergeIdentity:
    """Empty family merge identity: empty | f == f, f | empty == f."""

    def test_empty_left_identity(self) -> None:
        types = _make_types(3)
        empty = ScopeFamily[str]()
        f = ScopeFamily[str]().bind("a", types[0]).bind("b", types[1], types[2])

        result = empty | f

        assert dict(result.bindings) == dict(f.bindings)

    def test_empty_right_identity(self) -> None:
        types = _make_types(3)
        empty = ScopeFamily[str]()
        f = ScopeFamily[str]().bind("a", types[0]).bind("b", types[1], types[2])

        result = f | empty

        assert dict(result.bindings) == dict(f.bindings)

    def test_both_empty(self) -> None:
        empty1 = ScopeFamily[str]()
        empty2 = ScopeFamily[str]()

        result = empty1 | empty2

        assert dict(result.bindings) == {}


class TestQueryMethods:
    """Verify query methods types_for, tier_of, to_groups work correctly."""

    def test_types_for(self) -> None:
        types = _make_types(4)
        f = ScopeFamily[str]().bind("app", types[0], types[1]).bind("req", types[2], types[3])

        assert f.types_for("app") == frozenset({types[0], types[1]})
        assert f.types_for("req") == frozenset({types[2], types[3]})
        assert f.types_for("missing") == frozenset()

    def test_tier_of_unbound(self) -> None:
        types = _make_types(2)
        f = ScopeFamily[str]().bind("app", types[0])

        assert f.tier_of(types[0]) == "app"
        assert f.tier_of(types[1]) is None

    def test_to_groups(self) -> None:
        types = _make_types(4)
        f = ScopeFamily[str]().bind("app", types[0], types[1]).bind("req", types[2], types[3])

        groups = f.to_groups()
        assert groups["app"] == frozenset({types[0], types[1]})
        assert groups["req"] == frozenset({types[2], types[3]})


class TestUnbind:
    """Unbind removes types from the family."""

    def test_unbind_removes_mapping(self) -> None:
        types = _make_types(3)
        f = ScopeFamily[str]().bind("app", types[0], types[1], types[2])

        f2 = f.unbind(types[1])

        assert f2.tier_of(types[0]) == "app"
        assert f2.tier_of(types[1]) is None
        assert f2.tier_of(types[2]) == "app"
        assert len(f2.bindings) == 2

    def test_unbind_missing_is_noop(self) -> None:
        types = _make_types(2)
        f = ScopeFamily[str]().bind("app", types[0])
        f2 = f.unbind(types[1])

        assert dict(f2.bindings) == dict(f.bindings)
