"""Tests for derivelib._effects — derivation effect hierarchy and dispatch."""

from __future__ import annotations

from derivelib._effects import (
    Auditable,
    Bulk,
    Cacheable,
    Creates,
    Deletes,
    Deprecated,
    DerivationEffect,
    Emits,
    Filterable,
    Idempotent,
    Mutation,
    Pageable,
    Public,
    RateLimited,
    Read,
    Searchable,
    Sortable,
    Updates,
    Validated,
    Versioned,
    get_effect,
    has_effect,
)


class TestEffectHierarchy:
    def test_creates_is_mutation(self) -> None:
        assert isinstance(Creates(), Mutation)

    def test_updates_is_mutation(self) -> None:
        assert isinstance(Updates(), Mutation)

    def test_deletes_is_mutation(self) -> None:
        assert isinstance(Deletes(), Mutation)

    def test_mutation_is_not_creates(self) -> None:
        assert not isinstance(Mutation(), Creates)

    def test_read_is_not_mutation(self) -> None:
        assert not isinstance(Read(), Mutation)

    def test_all_are_derivation_effects(self) -> None:
        effects = [
            Read(), Mutation(), Idempotent(), Creates(), Updates(), Deletes(),
            Pageable(), Sortable(), Cacheable(), Filterable(), Searchable(),
            Public(), RateLimited(), Validated(), Versioned(), Bulk(),
            Auditable(), Emits(), Deprecated(),
        ]
        for e in effects:
            assert isinstance(e, DerivationEffect)


class TestHasEffect:
    def test_direct_match(self) -> None:
        assert has_effect((Read(),), Read)

    def test_hierarchy_match(self) -> None:
        assert has_effect((Creates(),), Mutation)

    def test_no_match(self) -> None:
        assert not has_effect((Read(),), Mutation)

    def test_empty_effects(self) -> None:
        assert not has_effect((), Read)

    def test_multiple_effects(self) -> None:
        effects = (Read(), Pageable(), Sortable())
        assert has_effect(effects, Read)
        assert has_effect(effects, Pageable)
        assert has_effect(effects, Sortable)
        assert not has_effect(effects, Mutation)


class TestGetEffect:
    def test_direct_match(self) -> None:
        p = Pageable(default_size=50)
        result = get_effect((p,), Pageable)
        assert result is p
        assert result is not None
        assert result.default_size == 50

    def test_hierarchy_match(self) -> None:
        c = Creates()
        result = get_effect((c,), Mutation)
        assert result is c

    def test_no_match(self) -> None:
        assert get_effect((Read(),), Mutation) is None

    def test_empty(self) -> None:
        assert get_effect((), Read) is None

    def test_first_match_wins(self) -> None:
        p1 = Pageable(default_size=10)
        p2 = Pageable(default_size=50)
        result = get_effect((p1, p2), Pageable)
        assert result is p1


class TestDataCarryingEffects:
    def test_pageable_defaults(self) -> None:
        p = Pageable()
        assert p.default_size == 20

    def test_sortable_defaults(self) -> None:
        s = Sortable()
        assert s.default_field == ""
        assert s.default_order == "asc"

    def test_cacheable_defaults(self) -> None:
        c = Cacheable()
        assert c.ttl == 0

    def test_rate_limited_defaults(self) -> None:
        r = RateLimited()
        assert r.rpm == 60

    def test_versioned_defaults(self) -> None:
        v = Versioned()
        assert v.version_field == "version"

    def test_bulk_defaults(self) -> None:
        b = Bulk()
        assert b.max_batch_size == 100

    def test_deprecated_defaults(self) -> None:
        d = Deprecated()
        assert d.since == ""
        assert d.message == ""

    def test_custom_values(self) -> None:
        p = Pageable(default_size=100)
        assert p.default_size == 100

        s = Sortable(default_field="name", default_order="desc")
        assert s.default_field == "name"
        assert s.default_order == "desc"
