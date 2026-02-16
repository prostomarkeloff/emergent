"""Tests for generalized scope tier system.

Exercises exotic tier hierarchies well beyond the standard App → Request.
Verifies parent-walking, compose derivation, with_scope runtime addition,
and materialize routing across N tiers.

Hierarchy under test:

    App → Session → Request → Turn
                                │
                            (leaf, created per-execution)

4 tiers, 3 pre-existing scopes, 1 leaf scope created at runtime.
"""

from __future__ import annotations

from types import MappingProxyType

import pytest
from nodnod import Scope

from emergent.graph._family import ScopeFamily
from emergent.wire.compile._lifetime import Tier, App, Request, ScopeLayer


# ── Exotic tiers ──────────────────────────────────────────────────────────────

Session = Tier(parent=App)
# Request is already Tier(parent=App), but for our deep chain we need
# Request-under-Session.  Redefine locally:
DeepRequest = Tier(parent=Session)
Turn = Tier(parent=DeepRequest)


# ── Dummy types bound to tiers ───────────────────────────────────────────────

class DBPool: ...
class Config: ...

class SessionData: ...
class RateLimiter: ...

class CurrentUser: ...
class RequestSpan: ...

class TurnCounter: ...
class ReplyDraft: ...


# ── Family ────────────────────────────────────────────────────────────────────

DEEP_FAMILY: ScopeFamily[Tier] = (
    ScopeFamily[Tier]()
    .bind(App, DBPool, Config)
    .bind(Session, SessionData, RateLimiter)
    .bind(DeepRequest, CurrentUser, RequestSpan)
    .bind(Turn, TurnCounter, ReplyDraft)
)


# ═════════════════════════════════════════════════════════════════════════════
# ScopeLayer — parent walking
# ═════════════════════════════════════════════════════════════════════════════


class TestParentWalking:
    """layer.parent walks leaf.parent chain → nearest scope in `scopes`."""

    def test_standard_two_tier(self) -> None:
        """Classic App → Request.  Parent of Request is App scope."""
        app_scope = Scope(detail="app")
        family = ScopeFamily[Tier]().bind(App, DBPool).bind(Request, CurrentUser)
        layer = ScopeLayer(
            scopes=MappingProxyType({App: app_scope}),
            family=family,
            leaf=Request,
        )
        assert layer.parent is app_scope

    def test_deep_four_tier_leaf_at_turn(self) -> None:
        """Turn → DeepRequest → Session → App.  All scopes present."""
        app_scope = Scope(detail="app")
        session_scope = Scope(detail="session")
        request_scope = Scope(detail="req")

        layer = ScopeLayer(
            scopes=MappingProxyType({
                App: app_scope,
                Session: session_scope,
                DeepRequest: request_scope,
            }),
            family=DEEP_FAMILY,
            leaf=Turn,
        )
        # Turn.parent = DeepRequest, which IS in scopes
        assert layer.parent is request_scope

    def test_skip_missing_intermediate(self) -> None:
        """Turn → DeepRequest(missing) → Session → App.
        Should skip DeepRequest and land on Session."""
        app_scope = Scope(detail="app")
        session_scope = Scope(detail="session")

        layer = ScopeLayer(
            scopes=MappingProxyType({App: app_scope, Session: session_scope}),
            family=DEEP_FAMILY,
            leaf=Turn,
        )
        # Turn.parent = DeepRequest (not in scopes)
        # DeepRequest.parent = Session (in scopes) → found
        assert layer.parent is session_scope

    def test_skip_two_missing_intermediates(self) -> None:
        """Turn → DeepRequest(missing) → Session(missing) → App.
        Skips two levels, lands on App."""
        app_scope = Scope(detail="app")

        layer = ScopeLayer(
            scopes=MappingProxyType({App: app_scope}),
            family=DEEP_FAMILY,
            leaf=Turn,
        )
        assert layer.parent is app_scope

    def test_no_ancestor_scope_raises(self) -> None:
        """Leaf whose entire ancestor chain has no scope → LookupError."""
        orphan = Tier()  # parent=None, no ancestors at all
        child = Tier(parent=orphan)

        layer = ScopeLayer(
            scopes=MappingProxyType({}),
            family=ScopeFamily[Tier](),
            leaf=child,
        )
        with pytest.raises(LookupError, match="No scope found"):
            _ = layer.parent


# ═════════════════════════════════════════════════════════════════════════════
# ScopeLayer — compose derivation
# ═════════════════════════════════════════════════════════════════════════════


class TestComposeDerivation:
    """layer.compose derives from family.types_for(leaf)."""

    def test_leaf_turn_compose(self) -> None:
        layer = ScopeLayer(
            scopes=MappingProxyType({App: Scope()}),
            family=DEEP_FAMILY,
            leaf=Turn,
        )
        assert layer.compose == frozenset({TurnCounter, ReplyDraft})

    def test_leaf_session_compose(self) -> None:
        layer = ScopeLayer(
            scopes=MappingProxyType({App: Scope()}),
            family=DEEP_FAMILY,
            leaf=Session,
        )
        assert layer.compose == frozenset({SessionData, RateLimiter})

    def test_leaf_with_no_bindings(self) -> None:
        """Leaf tier with nothing bound → empty compose."""
        empty_tier = Tier(parent=App)
        layer = ScopeLayer(
            scopes=MappingProxyType({App: Scope()}),
            family=ScopeFamily[Tier](),
            leaf=empty_tier,
        )
        assert layer.compose == frozenset()


# ═════════════════════════════════════════════════════════════════════════════
# ScopeLayer — with_scope (runtime tier addition)
# ═════════════════════════════════════════════════════════════════════════════


class TestWithScope:
    """with_scope returns a new layer with additional tier→scope mapping."""

    def test_add_intermediate_tier(self) -> None:
        """Start with {App}, add Session at runtime."""
        app_scope = Scope(detail="app")
        session_scope = Scope(detail="session")

        layer = ScopeLayer(
            scopes=MappingProxyType({App: app_scope}),
            family=DEEP_FAMILY,
            leaf=Turn,
        )
        # Before: parent walks Turn → DeepRequest → Session(missing) → App
        assert layer.parent is app_scope

        new_layer = layer.with_scope(Session, session_scope)

        # After: Session is now in scopes, but parent still walks
        # Turn → DeepRequest(missing) → Session → found
        assert new_layer.parent is session_scope
        # Original unchanged (frozen)
        assert layer.parent is app_scope

    def test_add_deeprequest_tier(self) -> None:
        """Add DeepRequest scope at runtime → parent is now DeepRequest."""
        app_scope = Scope(detail="app")
        req_scope = Scope(detail="req")

        layer = ScopeLayer(
            scopes=MappingProxyType({App: app_scope}),
            family=DEEP_FAMILY,
            leaf=Turn,
        )
        new_layer = layer.with_scope(DeepRequest, req_scope)
        assert new_layer.parent is req_scope

    def test_with_scope_preserves_family_and_leaf(self) -> None:
        layer = ScopeLayer(
            scopes=MappingProxyType({App: Scope()}),
            family=DEEP_FAMILY,
            leaf=Turn,
        )
        new_layer = layer.with_scope(Session, Scope())
        assert new_layer.family is layer.family
        assert new_layer.leaf is layer.leaf

    def test_chain_multiple_with_scope(self) -> None:
        """Chain two with_scope calls to build up the full tier set."""
        app_scope = Scope(detail="app")
        session_scope = Scope(detail="session")
        req_scope = Scope(detail="req")

        layer = (
            ScopeLayer(
                scopes=MappingProxyType({App: app_scope}),
                family=DEEP_FAMILY,
                leaf=Turn,
            )
            .with_scope(Session, session_scope)
            .with_scope(DeepRequest, req_scope)
        )

        # Turn.parent = DeepRequest, which is now in scopes
        assert layer.parent is req_scope
        assert Session in layer.scopes
        assert layer.scopes[Session] is session_scope


# ═════════════════════════════════════════════════════════════════════════════
# Materialize — N-tier routing
# ═════════════════════════════════════════════════════════════════════════════


class TestMaterializeDeep:
    """family.materialize routes types to correct scopes across 4 tiers."""

    def test_full_four_tier_materialize(self) -> None:
        app_scope = Scope(detail="app")
        session_scope = Scope(detail="session")
        req_scope = Scope(detail="req")
        turn_scope = Scope(detail="turn")

        mapped = DEEP_FAMILY.materialize({
            App: app_scope,
            Session: session_scope,
            DeepRequest: req_scope,
            Turn: turn_scope,
        })

        assert mapped[DBPool] is app_scope
        assert mapped[Config] is app_scope
        assert mapped[SessionData] is session_scope
        assert mapped[RateLimiter] is session_scope
        assert mapped[CurrentUser] is req_scope
        assert mapped[RequestSpan] is req_scope
        assert mapped[TurnCounter] is turn_scope
        assert mapped[ReplyDraft] is turn_scope

    def test_partial_materialize_skips_missing_tiers(self) -> None:
        """Only App and Turn scopes provided — Session/DeepRequest types skipped."""
        app_scope = Scope(detail="app")
        turn_scope = Scope(detail="turn")

        mapped = DEEP_FAMILY.materialize({App: app_scope, Turn: turn_scope})

        assert mapped[DBPool] is app_scope
        assert mapped[TurnCounter] is turn_scope
        # Session-tier types not in mapped (no Session scope)
        assert SessionData not in mapped
        assert CurrentUser not in mapped

    def test_materialize_matches_family_mapped_pattern(self) -> None:
        """Simulate what _family_mapped does: {**layer.scopes, layer.leaf: scope}."""
        app_scope = Scope(detail="app")
        session_scope = Scope(detail="session")
        req_scope = Scope(detail="req")
        turn_scope = Scope(detail="turn")

        layer = ScopeLayer(
            scopes=MappingProxyType({
                App: app_scope,
                Session: session_scope,
                DeepRequest: req_scope,
            }),
            family=DEEP_FAMILY,
            leaf=Turn,
        )

        # This is exactly what _family_mapped computes:
        mapped = layer.family.materialize({**layer.scopes, layer.leaf: turn_scope})

        assert mapped[DBPool] is app_scope
        assert mapped[SessionData] is session_scope
        assert mapped[CurrentUser] is req_scope
        assert mapped[TurnCounter] is turn_scope


# ═════════════════════════════════════════════════════════════════════════════
# Family algebra with exotic tiers
# ═════════════════════════════════════════════════════════════════════════════


class TestFamilyAlgebraExotic:
    """ScopeFamily operations work correctly with deep hierarchies."""

    def test_merge_two_families_different_tiers(self) -> None:
        """Merge App-tier family with Turn-tier family."""
        base = ScopeFamily[Tier]().bind(App, DBPool, Config)
        turn_ext = ScopeFamily[Tier]().bind(Turn, TurnCounter, ReplyDraft)

        combined = base | turn_ext
        assert combined.types_for(App) == frozenset({DBPool, Config})
        assert combined.types_for(Turn) == frozenset({TurnCounter, ReplyDraft})

    def test_unbind_from_deep_tier(self) -> None:
        updated = DEEP_FAMILY.unbind(TurnCounter)
        assert updated.types_for(Turn) == frozenset({ReplyDraft})
        # Other tiers unaffected
        assert updated.types_for(App) == frozenset({DBPool, Config})

    def test_tier_of_with_deep_types(self) -> None:
        assert DEEP_FAMILY.tier_of(TurnCounter) is Turn
        assert DEEP_FAMILY.tier_of(SessionData) is Session
        assert DEEP_FAMILY.tier_of(DBPool) is App

    def test_to_groups_four_tiers(self) -> None:
        groups = DEEP_FAMILY.to_groups()
        assert groups[App] == frozenset({DBPool, Config})
        assert groups[Session] == frozenset({SessionData, RateLimiter})
        assert groups[DeepRequest] == frozenset({CurrentUser, RequestSpan})
        assert groups[Turn] == frozenset({TurnCounter, ReplyDraft})


# ═════════════════════════════════════════════════════════════════════════════
# Integration — real nodnod Scope parent-child with tier system
# ═════════════════════════════════════════════════════════════════════════════


class TestIntegrationScopeInheritance:
    """Verify real nodnod Scope parent-child retrieval interacts correctly
    with the tier system: inject at App tier, retrieve from Request child."""

    def test_child_scope_retrieves_from_parent(self) -> None:
        """Request-tier child scope can retrieve DBPool injected into App scope."""
        app_scope = Scope(detail="app")
        pool = DBPool()
        app_scope.inject(DBPool, pool)

        req_scope = app_scope.create_child(detail="request")

        # nodnod parent walking: child sees parent's values
        result = req_scope.retrieve(DBPool)
        assert result.unwrap().value is pool

    def test_parent_does_not_see_child_values(self) -> None:
        """App scope must NOT see values injected only into Request child."""
        app_scope = Scope(detail="app")
        req_scope = app_scope.create_child(detail="request")

        user = CurrentUser()
        req_scope.inject(CurrentUser, user)

        # Parent cannot see child-injected value
        from kungfu import Nothing
        result = app_scope.retrieve(CurrentUser)
        assert isinstance(result, Nothing)

    def test_tier_layer_parent_matches_nodnod_parent(self) -> None:
        """ScopeLayer.parent returns the same scope that nodnod uses as prev."""
        app_scope = Scope(detail="app")
        req_scope = app_scope.create_child(detail="request")

        family = ScopeFamily[Tier]().bind(App, DBPool).bind(Request, CurrentUser)
        layer = ScopeLayer(
            scopes=MappingProxyType({App: app_scope}),
            family=family,
            leaf=Request,
        )

        # ScopeLayer.parent walks tier chain -> App scope
        assert layer.parent is app_scope
        # nodnod prev chain confirms the relationship
        assert req_scope.has_parent(app_scope)

    def test_deep_chain_parent_retrieval(self) -> None:
        """4-tier nodnod chain: Turn child retrieves App-injected value."""
        app_scope = Scope(detail="app")
        sess_scope = app_scope.create_child(detail="session")
        req_scope = sess_scope.create_child(detail="deep-request")
        turn_scope = req_scope.create_child(detail="turn")

        cfg = Config()
        app_scope.inject(Config, cfg)

        # Turn scope walks prev->prev->prev->App to find Config
        result = turn_scope.retrieve(Config)
        assert result.unwrap().value is cfg


# ═════════════════════════════════════════════════════════════════════════════
# Integration — Family materialize with real Scope objects
# ═════════════════════════════════════════════════════════════════════════════


class TestIntegrationFamilyMaterializeWithRealScopes:
    """Build a 4-tier family, create real nodnod Scope objects per tier,
    materialize, and verify routing."""

    def test_materialize_routes_to_correct_real_scopes(self) -> None:
        family: ScopeFamily[Tier] = (
            ScopeFamily[Tier]()
            .bind(App, DBPool, Config)
            .bind(Session, SessionData)
            .bind(DeepRequest, CurrentUser)
            .bind(Turn, TurnCounter)
        )

        app_scope = Scope(detail="app")
        sess_scope = app_scope.create_child(detail="session")
        req_scope = sess_scope.create_child(detail="deep-request")

        mapped = family.materialize({
            App: app_scope,
            Session: sess_scope,
            DeepRequest: req_scope,
        })

        # App-tier types routed to app_scope
        assert mapped[DBPool] is app_scope
        assert mapped[Config] is app_scope

        # Session-tier type routed to sess_scope
        assert mapped[SessionData] is sess_scope

        # DeepRequest-tier type routed to req_scope
        assert mapped[CurrentUser] is req_scope

    def test_turn_types_excluded_when_scope_missing(self) -> None:
        """Types bound to Turn are excluded because no Turn scope is provided."""
        family: ScopeFamily[Tier] = (
            ScopeFamily[Tier]()
            .bind(App, DBPool, Config)
            .bind(Session, SessionData)
            .bind(DeepRequest, CurrentUser)
            .bind(Turn, TurnCounter)
        )

        app_scope = Scope(detail="app")
        sess_scope = app_scope.create_child(detail="session")
        req_scope = sess_scope.create_child(detail="deep-request")

        mapped = family.materialize({
            App: app_scope,
            Session: sess_scope,
            DeepRequest: req_scope,
        })

        assert TurnCounter not in mapped

    def test_materialize_result_is_immutable(self) -> None:
        """materialize returns a MappingProxyType that cannot be mutated."""
        family = ScopeFamily[Tier]().bind(App, DBPool)
        app_scope = Scope(detail="app")
        mapped = family.materialize({App: app_scope})

        assert isinstance(mapped, MappingProxyType)
        with pytest.raises(TypeError):
            mapped[Config] = app_scope  # type: ignore[index]


# ═════════════════════════════════════════════════════════════════════════════
# Integration — ScopeLayer parent walking with deep hierarchy
# ═════════════════════════════════════════════════════════════════════════════


class TestIntegrationScopeLayerParentWalking:
    """ScopeLayer with deep hierarchy -- verify parent walks skip missing tiers."""

    def test_parent_skips_deeprequest_lands_on_session(self) -> None:
        """Leaf=Turn, scopes={App, Session}.
        Turn.parent=DeepRequest (missing) -> Session (found)."""
        app_scope = Scope(detail="app")
        sess_scope = app_scope.create_child(detail="session")

        layer = ScopeLayer(
            scopes=MappingProxyType({App: app_scope, Session: sess_scope}),
            family=DEEP_FAMILY,
            leaf=Turn,
        )

        assert layer.parent is sess_scope

    def test_with_scope_deeprequest_changes_parent(self) -> None:
        """After with_scope(DeepRequest, ...) parent returns deep_scope."""
        app_scope = Scope(detail="app")
        sess_scope = app_scope.create_child(detail="session")
        deep_scope = sess_scope.create_child(detail="deep-request")

        layer = ScopeLayer(
            scopes=MappingProxyType({App: app_scope, Session: sess_scope}),
            family=DEEP_FAMILY,
            leaf=Turn,
        )

        # Before: parent is sess_scope (skips DeepRequest)
        assert layer.parent is sess_scope

        updated = layer.with_scope(DeepRequest, deep_scope)

        # After: parent is deep_scope (DeepRequest now present)
        assert updated.parent is deep_scope

    def test_with_scope_does_not_mutate_original(self) -> None:
        """with_scope is immutable -- original layer unchanged."""
        app_scope = Scope(detail="app")
        sess_scope = app_scope.create_child(detail="session")
        deep_scope = sess_scope.create_child(detail="deep-request")

        layer = ScopeLayer(
            scopes=MappingProxyType({App: app_scope, Session: sess_scope}),
            family=DEEP_FAMILY,
            leaf=Turn,
        )

        _ = layer.with_scope(DeepRequest, deep_scope)

        # Original still has only App and Session
        assert DeepRequest not in layer.scopes
        assert layer.parent is sess_scope


# ═════════════════════════════════════════════════════════════════════════════
# Integration — Family algebra: merge, bind, unbind in complex scenario
# ═════════════════════════════════════════════════════════════════════════════


class TestIntegrationFamilyAlgebra:
    """Test merge (|), bind, unbind across overlapping tier families."""

    def test_merge_right_wins_on_session_conflict(self) -> None:
        """family_a binds SessionData to Session; family_b binds RateLimiter
        to Session.  After merge, Session has both (different types, no conflict)."""
        family_a: ScopeFamily[Tier] = (
            ScopeFamily[Tier]()
            .bind(App, DBPool, Config)
            .bind(Session, SessionData)
        )
        family_b: ScopeFamily[Tier] = (
            ScopeFamily[Tier]()
            .bind(Session, RateLimiter)
            .bind(DeepRequest, CurrentUser, RequestSpan)
        )

        merged = family_a | family_b

        # App types only in family_a -- preserved
        assert merged.types_for(App) == frozenset({DBPool, Config})
        # Session: family_a contributes SessionData, family_b contributes RateLimiter
        assert merged.types_for(Session) == frozenset({SessionData, RateLimiter})
        # DeepRequest only in family_b -- preserved
        assert merged.types_for(DeepRequest) == frozenset({CurrentUser, RequestSpan})

    def test_merge_right_wins_on_same_type_conflict(self) -> None:
        """Same type bound to different tiers -- right side wins."""
        family_a = ScopeFamily[Tier]().bind(App, DBPool)
        family_b = ScopeFamily[Tier]().bind(Session, DBPool)

        merged = family_a | family_b

        # DBPool was in App (left) and Session (right) -> right wins
        assert merged.tier_of(DBPool) is Session
        assert merged.types_for(App) == frozenset()
        assert merged.types_for(Session) == frozenset({DBPool})

    def test_tier_of_on_merged_family(self) -> None:
        family_a = ScopeFamily[Tier]().bind(App, DBPool, Config)
        family_b = ScopeFamily[Tier]().bind(DeepRequest, CurrentUser)

        merged = family_a | family_b

        assert merged.tier_of(DBPool) is App
        assert merged.tier_of(Config) is App
        assert merged.tier_of(CurrentUser) is DeepRequest
        assert merged.tier_of(TurnCounter) is None

    def test_to_groups_on_merged_family(self) -> None:
        family_a: ScopeFamily[Tier] = (
            ScopeFamily[Tier]()
            .bind(App, DBPool)
            .bind(Session, SessionData)
        )
        family_b: ScopeFamily[Tier] = (
            ScopeFamily[Tier]()
            .bind(Session, RateLimiter)
            .bind(DeepRequest, CurrentUser)
        )

        merged = family_a | family_b
        groups = merged.to_groups()

        assert groups[App] == frozenset({DBPool})
        assert groups[Session] == frozenset({SessionData, RateLimiter})
        assert groups[DeepRequest] == frozenset({CurrentUser})
        assert Turn not in groups

    def test_unbind_after_merge(self) -> None:
        """Unbind a type from a merged family."""
        family_a = ScopeFamily[Tier]().bind(App, DBPool, Config)
        family_b = ScopeFamily[Tier]().bind(Session, SessionData, RateLimiter)

        merged = family_a | family_b
        trimmed = merged.unbind(Config, RateLimiter)

        assert trimmed.types_for(App) == frozenset({DBPool})
        assert trimmed.types_for(Session) == frozenset({SessionData})
        assert trimmed.tier_of(Config) is None
        assert trimmed.tier_of(RateLimiter) is None


# ═════════════════════════════════════════════════════════════════════════════
# Integration — ScopeLayer.compose derives correct types per leaf
# ═════════════════════════════════════════════════════════════════════════════


class TestIntegrationScopeLayerCompose:
    """ScopeLayer.compose returns exactly the types bound to the leaf tier."""

    def test_compose_returns_turn_types(self) -> None:
        """leaf=Turn -> compose returns only Turn-bound types."""
        layer = ScopeLayer(
            scopes=MappingProxyType({App: Scope(detail="app")}),
            family=DEEP_FAMILY,
            leaf=Turn,
        )
        assert layer.compose == frozenset({TurnCounter, ReplyDraft})

    def test_compose_returns_deeprequest_types(self) -> None:
        """leaf=DeepRequest -> compose returns only DeepRequest-bound types."""
        layer = ScopeLayer(
            scopes=MappingProxyType({App: Scope(detail="app")}),
            family=DEEP_FAMILY,
            leaf=DeepRequest,
        )
        assert layer.compose == frozenset({CurrentUser, RequestSpan})

    def test_compose_does_not_leak_across_tiers(self) -> None:
        """Turn compose must not include Session or DeepRequest types."""
        layer = ScopeLayer(
            scopes=MappingProxyType({App: Scope(detail="app")}),
            family=DEEP_FAMILY,
            leaf=Turn,
        )
        compose = layer.compose
        assert SessionData not in compose
        assert RateLimiter not in compose
        assert CurrentUser not in compose
        assert RequestSpan not in compose
        assert DBPool not in compose
        assert Config not in compose

    def test_compose_with_custom_family(self) -> None:
        """Build a custom family, verify compose picks up the right types."""
        custom_family: ScopeFamily[Tier] = (
            ScopeFamily[Tier]()
            .bind(App, DBPool)
            .bind(Session, SessionData, RateLimiter)
            .bind(DeepRequest, CurrentUser)
            .bind(Turn, TurnCounter, ReplyDraft)
        )

        turn_layer = ScopeLayer(
            scopes=MappingProxyType({App: Scope(detail="app")}),
            family=custom_family,
            leaf=Turn,
        )
        assert turn_layer.compose == frozenset({TurnCounter, ReplyDraft})

        session_layer = ScopeLayer(
            scopes=MappingProxyType({App: Scope(detail="app")}),
            family=custom_family,
            leaf=Session,
        )
        assert session_layer.compose == frozenset({SessionData, RateLimiter})

    def test_compose_empty_when_leaf_has_no_bindings(self) -> None:
        """A leaf tier with no bindings produces an empty compose."""
        orphan_tier = Tier(parent=App)
        layer = ScopeLayer(
            scopes=MappingProxyType({App: Scope(detail="app")}),
            family=DEEP_FAMILY,
            leaf=orphan_tier,
        )
        assert layer.compose == frozenset()
