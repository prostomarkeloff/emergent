"""Tests for universal derivation — derive from any subject, not just entities.

Covers all 3 levels:
- Level 1: Non-entity subjects → Endpoints
- Level 2: Non-entity subjects → Different outputs (custom consumers)
- Level 3: Fully parametric (custom context + fold_schema)
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Annotated, Protocol, runtime_checkable

import pytest
from kungfu import Ok, Result

from emergent.wire.axis.schema._universal import Identity, SchemaCapability, schema_meta
from emergent.wire.compile._core import fold_schema
from emergent.wire.derive._compile import compile_derive
from emergent.wire.derive._ctx import DeriveCtx
from emergent.wire.derive._errors import DomainError
from emergent.wire.derive._explain import derive_dict, explain_derive
from emergent.wire.derive._materialize import materialize
from emergent.wire.derive._protocols import DeriveGeneratable


# ═══════════════════════════════════════════════════════════════════════════════
# Test fixtures: non-entity subjects
# ═══════════════════════════════════════════════════════════════════════════════


class PlainService:
    """Not a dataclass. No fields. No identity."""

    version = "1.0"


@dataclass(frozen=True, slots=True)
class CustomGeneratable(SchemaCapability):
    """Capability that generates operations from class attributes."""

    def compile_derive_generate(self, ctx: DeriveCtx) -> DeriveCtx:  # type: ignore[type-arg]
        subject = ctx.entity
        version = getattr(subject, "version", "unknown")

        from emergent.wire.axis.surface import Exposure
        from emergent.wire.axis.surface.codecs import rrc
        from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
        from emergent.wire.derive._codegen import annotate_handler, create_dataclass

        # Build a simple health-check operation
        op_type = create_dataclass(f"{subject.__name__}HealthOp", [], frozen=True)

        async def handler(_op: object) -> Result[object, DomainError]:
            return Ok({"status": "ok", "version": version})

        req_type = create_dataclass(f"{subject.__name__}HealthReq", [], frozen=True)
        resp_type = create_dataclass(f"{subject.__name__}HealthResp", [], frozen=True)

        annotated = annotate_handler(handler, op_type)
        exposure = Exposure(
            trigger=HTTPRouteTrigger("GET", "/health"),
            codec=rrc(req_type, resp_type),
        )
        return ctx.add_operation((op_type, annotated, exposure))


# ═══════════════════════════════════════════════════════════════════════════════
# Level 1: Non-entity subjects → Endpoints
# ═══════════════════════════════════════════════════════════════════════════════


class TestNonEntityDeriveEndpoints:
    def test_plain_class_with_custom_generatable(self) -> None:
        """Plain class + DeriveGeneratable → compile_derive → materialize → endpoint."""

        @schema_meta(CustomGeneratable())
        class MyService:
            version = "2.0"

        [ctx] = compile_derive(MyService)
        assert ctx.entity is MyService
        assert ctx.fields == {}
        assert ctx.identity_fields == {}
        assert len(ctx.operations) == 1

        endpoint = materialize(ctx)
        assert len(endpoint.exposures) == 1

    def test_from_subject_manually(self) -> None:
        """DeriveCtx.from_subject creates context with empty fields."""
        ctx = DeriveCtx.from_subject(PlainService)
        assert ctx.entity is PlainService
        assert ctx.fields == {}
        assert ctx.identity_fields == {}
        assert ctx.identity_names() == ()
        assert ctx.non_identity_fields() == {}
        assert ctx.specs == ()
        assert ctx.operations == ()

    def test_from_subject_accumulation_works(self) -> None:
        """from_subject context supports all accumulation methods."""
        ctx = DeriveCtx.from_subject(PlainService)

        from emergent.wire.axis.surface.capabilities import SurfaceCapability

        @dataclass(frozen=True, slots=True)
        class TestCap(SurfaceCapability):
            pass

        ctx2 = ctx.add_capability(TestCap())
        assert len(ctx2.capabilities) == 1
        assert ctx.capabilities == ()  # immutable


# ═══════════════════════════════════════════════════════════════════════════════
# Entity derivation unchanged (regression)
# ═══════════════════════════════════════════════════════════════════════════════


class TestEntityDeriveUnchanged:
    def test_from_entity_still_works(self) -> None:
        """from_entity with dataclass still inspects fields."""

        @dataclass
        class User:
            id: Annotated[int, Identity]
            name: str

        ctx = DeriveCtx.from_entity(User)
        assert ctx.entity is User
        assert "id" in ctx.fields
        assert "name" in ctx.fields
        assert "id" in ctx.identity_fields

    def test_compile_derive_on_entity(self) -> None:
        """compile_derive on entity still goes through from_entity path."""

        @dataclass
        class Item:
            id: Annotated[int, Identity]
            label: str

        [ctx] = compile_derive(Item)
        assert "id" in ctx.fields
        assert "id" in ctx.identity_fields


# ═══════════════════════════════════════════════════════════════════════════════
# CRUD on non-entity → clear error
# ═══════════════════════════════════════════════════════════════════════════════


class TestCrudOnNonEntity:
    def test_crud_on_plain_class_raises(self) -> None:
        """CRUD on non-entity gives clear error about missing Identity."""
        from emergent.wire.derive._crud import http_crud

        @schema_meta(http_crud("/api/stuff", type("FakeProvider", (), {})))
        class NotAnEntity:
            pass

        with pytest.raises((TypeError, ValueError)):
            compile_derive(NotAnEntity)  # raises during generate phase


# ═══════════════════════════════════════════════════════════════════════════════
# Explain on non-entity
# ═══════════════════════════════════════════════════════════════════════════════


class TestExplainNonEntity:
    def test_explain_derive_empty_fields(self) -> None:
        """explain_derive works when fields is empty."""
        ctx = DeriveCtx.from_subject(PlainService)
        text = explain_derive(ctx)
        assert "PlainService" in text

    def test_derive_dict_empty_fields(self) -> None:
        """derive_dict works when fields is empty."""
        ctx = DeriveCtx.from_subject(PlainService)
        d = derive_dict(ctx)
        assert d["entity"] == "PlainService"
        assert d["fields"] == []
        assert d["identity_fields"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# Level 3: Fully parametric — custom context + fold_schema
# ═══════════════════════════════════════════════════════════════════════════════


class TestFullyParametricDerivation:
    def test_custom_context_and_protocol(self) -> None:
        """Custom context + custom protocol + fold_schema = fully parametric derivation."""

        @dataclass(frozen=True, slots=True)
        class EventSpec:
            name: str
            source_state: str
            target_state: str

        @dataclass(frozen=True, slots=True)
        class EventCtx:
            aggregate: type
            events: tuple[EventSpec, ...] = ()

        @runtime_checkable
        class EventDerivable(Protocol):
            def derive_events(self, ctx: EventCtx) -> EventCtx: ...

        @dataclass(frozen=True, slots=True)
        class EventSourced(SchemaCapability):
            transitions: tuple[tuple[str, str, str], ...] = ()

            def derive_events(self, ctx: EventCtx) -> EventCtx:
                new_events = tuple(
                    EventSpec(name=name, source_state=src, target_state=tgt)
                    for name, src, tgt in self.transitions
                )
                return replace(ctx, events=(*ctx.events, *new_events))

        @schema_meta(EventSourced(transitions=(
            ("confirm", "pending", "confirmed"),
            ("ship", "confirmed", "shipped"),
        )))
        class Order:
            pass

        # Custom compile function — NOT compile_derive, NOT DeriveCtx
        event_ctx = fold_schema(Order, EventCtx(aggregate=Order), EventDerivable, "derive_events")

        assert event_ctx.aggregate is Order
        assert len(event_ctx.events) == 2
        assert event_ctx.events[0].name == "confirm"
        assert event_ctx.events[0].source_state == "pending"
        assert event_ctx.events[1].name == "ship"
        assert event_ctx.events[1].target_state == "shipped"

    def test_multiple_capabilities_fold(self) -> None:
        """Multiple capabilities fold into same custom context."""

        @dataclass(frozen=True, slots=True)
        class RuleSpec:
            name: str
            check: str

        @dataclass(frozen=True, slots=True)
        class RulesCtx:
            subject: type
            rules: tuple[RuleSpec, ...] = ()

        @runtime_checkable
        class RuleDerivable(Protocol):
            def derive_rules(self, ctx: RulesCtx) -> RulesCtx: ...

        @dataclass(frozen=True, slots=True)
        class MaxAmount(SchemaCapability):
            limit: int

            def derive_rules(self, ctx: RulesCtx) -> RulesCtx:
                rule = RuleSpec(name="max_amount", check=f"amount <= {self.limit}")
                return replace(ctx, rules=(*ctx.rules, rule))

        @dataclass(frozen=True, slots=True)
        class AllowedCurrencies(SchemaCapability):
            currencies: tuple[str, ...]

            def derive_rules(self, ctx: RulesCtx) -> RulesCtx:
                rule = RuleSpec(name="allowed_currencies", check=f"currency in {self.currencies}")
                return replace(ctx, rules=(*ctx.rules, rule))

        @schema_meta(MaxAmount(10000), AllowedCurrencies(("USD", "EUR")))
        class PaymentRules:
            pass

        rules_ctx = fold_schema(PaymentRules, RulesCtx(subject=PaymentRules), RuleDerivable, "derive_rules")

        assert len(rules_ctx.rules) == 2
        assert rules_ctx.rules[0].name == "max_amount"
        assert rules_ctx.rules[1].name == "allowed_currencies"
