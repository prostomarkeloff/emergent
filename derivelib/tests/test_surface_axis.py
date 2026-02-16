"""Tests for derivelib.axes.surface — DeriveOp, ExposeOp, AddGlobalCap."""

from __future__ import annotations

from dataclasses import dataclass

from kungfu import Ok, Result

from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

from derivelib._ctx import QueryCtx, SurfaceCtx
from derivelib._errors import DomainError
from derivelib._handler_templates import FetchMany, FetchOneById
from derivelib._project import entity_response, id_only, list_response, no_fields
from derivelib.axes.surface import AddGlobalCap, DeriveOp

from .conftest import User, user_schema


class TestDeriveOp:
    def test_adds_spec_to_ctx(self) -> None:
        schema = user_schema()
        ctx = SurfaceCtx(schema=schema)
        step = DeriveOp(
            name="List",
            input_proj=no_fields(),
            output=list_response(),
            handler_template=FetchMany(),
            trigger=HTTPRouteTrigger("GET", "/api/users"),
        )
        result = step.derive_surface(ctx)
        assert len(result.specs) == 1

    def test_spec_has_correct_name(self) -> None:
        schema = user_schema()
        ctx = SurfaceCtx(schema=schema)
        step = DeriveOp(
            name="Get",
            input_proj=id_only(),
            output=entity_response(),
            handler_template=FetchOneById(),
            trigger=HTTPRouteTrigger("GET", "/api/users/{id}"),
        )
        result = step.derive_surface(ctx)
        assert result.specs[0].name == "Get"

    def test_spec_preserves_trigger(self) -> None:
        schema = user_schema()
        ctx = SurfaceCtx(schema=schema)
        trigger = HTTPRouteTrigger("POST", "/api/users")
        step = DeriveOp(
            name="Create",
            input_proj=id_only(),
            output=entity_response(),
            handler_template=FetchOneById(),
            trigger=trigger,
        )
        result = step.derive_surface(ctx)
        assert result.specs[0].trigger is trigger

    def test_multiple_specs_accumulated(self) -> None:
        schema = user_schema()
        ctx = SurfaceCtx(schema=schema)
        step1 = DeriveOp(
            name="List",
            input_proj=no_fields(),
            output=list_response(),
            handler_template=FetchMany(),
            trigger=HTTPRouteTrigger("GET", "/api/users"),
        )
        step2 = DeriveOp(
            name="Get",
            input_proj=id_only(),
            output=entity_response(),
            handler_template=FetchOneById(),
            trigger=HTTPRouteTrigger("GET", "/api/users/{id}"),
        )
        ctx = step1.derive_surface(ctx)
        ctx = step2.derive_surface(ctx)
        assert len(ctx.specs) == 2


class TestAddGlobalCap:
    def test_adds_capability(self) -> None:
        @dataclass
        class MyCap(SurfaceCapability):
            pass

        schema = user_schema()
        ctx = SurfaceCtx(schema=schema)
        step = AddGlobalCap(cap=MyCap())
        result = step.derive_surface(ctx)
        assert len(result.capabilities) == 1
        assert isinstance(result.capabilities[0], MyCap)

    def test_multiple_caps(self) -> None:
        @dataclass
        class CapA(SurfaceCapability):
            pass

        @dataclass
        class CapB(SurfaceCapability):
            pass

        schema = user_schema()
        ctx = SurfaceCtx(schema=schema)
        ctx = AddGlobalCap(cap=CapA()).derive_surface(ctx)
        ctx = AddGlobalCap(cap=CapB()).derive_surface(ctx)
        assert len(ctx.capabilities) == 2
