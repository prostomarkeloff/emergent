"""Tests for derivelib._builders — ExposureBuilder and EndpointBuilder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import pytest
from kungfu import Ok, Result

from emergent.wire.axis.schema import Identity
from emergent.wire.axis.surface import Exposure
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

from derivelib._builders import ExposureBuilder, EndpointBuilder, exposure

from .conftest import User


class TestExposureBuilder:
    def test_creates_builder(self) -> None:
        b = exposure("create", User)
        assert isinstance(b, ExposureBuilder)

    def test_fluent_chain(self) -> None:
        trigger = HTTPRouteTrigger("POST", "/api/users")

        async def handler(op: object) -> Result[int, object]:
            return Ok(1)

        b = (
            exposure("create", User)
            .request(name=str, email=str)
            .response(id=int)
            .handler(handler)
            .trigger(trigger)
        )
        assert isinstance(b, ExposureBuilder)

    def test_build_produces_triple(self) -> None:
        trigger = HTTPRouteTrigger("POST", "/api/users")

        async def handler(op: object) -> Result[int, object]:
            return Ok(1)

        op_type, annotated_handler, exp = (
            exposure("create", User)
            .request(name=str, email=str)
            .response(id=int)
            .handler(handler)
            .trigger(trigger)
            .build()
        )
        assert op_type.__name__ == "UserCreateOp"
        assert callable(annotated_handler)
        assert isinstance(exp, Exposure)

    def test_build_without_trigger_raises(self) -> None:
        async def handler(op: object) -> Result[int, object]:
            return Ok(1)

        b = (
            exposure("create", User)
            .request(name=str)
            .response(id=int)
            .handler(handler)
        )
        with pytest.raises(ValueError, match="Trigger not set"):
            b.build()

    def test_build_without_handler_raises(self) -> None:
        trigger = HTTPRouteTrigger("POST", "/api/users")
        b = (
            exposure("create", User)
            .request(name=str)
            .response(id=int)
            .trigger(trigger)
        )
        with pytest.raises(ValueError, match="Handler not set"):
            b.build()

    def test_response_with_defaults(self) -> None:
        trigger = HTTPRouteTrigger("POST", "/api/users")

        async def handler(op: object) -> Result[bool, object]:
            return Ok(True)

        op_type, _, exp = (
            exposure("action", User)
            .request(name=str)
            .response(success=(bool, True))
            .handler(handler)
            .trigger(trigger)
            .build()
        )
        assert op_type is not None

    def test_op_type_has_request_fields(self) -> None:
        trigger = HTTPRouteTrigger("POST", "/api/users")

        async def handler(op: object) -> Result[int, object]:
            return Ok(1)

        op_type, _, _ = (
            exposure("create", User)
            .request(name=str, email=str)
            .response(id=int)
            .handler(handler)
            .trigger(trigger)
            .build()
        )
        instance = op_type(name="Alice", email="alice@example.com")
        assert instance.name == "Alice"
        assert instance.email == "alice@example.com"


class TestEndpointBuilder:
    def test_build_endpoint(self) -> None:
        trigger = HTTPRouteTrigger("POST", "/api/users")

        async def handler(op: object) -> Result[int, object]:
            return Ok(1)

        op_type, annotated_handler, exp = (
            exposure("create", User)
            .request(name=str)
            .response(id=int)
            .handler(handler)
            .trigger(trigger)
            .build()
        )
        builder = EndpointBuilder()
        endpoint = builder.build([(op_type, annotated_handler, exp)])
        assert len(endpoint.exposures) == 1
