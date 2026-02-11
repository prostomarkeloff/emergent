"""Tests for surface explain — dict layer, format layer, custom handlers."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from emergent.wire.axis.surface._app import Application, application
from emergent.wire.axis.surface._endpoint import Endpoint, endpoint
from emergent.wire.axis.surface._types import Exposure
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec
from emergent.wire.axis.surface.codecs.immediate import ImmediateCodec
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec, delegate
from emergent.wire.axis.surface._explain import (
    application_dict,
    endpoint_dict,
    exposure_dict,
    explain_application,
    explain_endpoint,
    SURFACE_EXPLAIN,
    SurfaceExplainHandler,
)
from emergent.ops import ops as _ops


# ─── Helpers ────────────────────────────────────────────────────────────────


def _runner():
    return _ops().compile()


@dataclass
class Req:
    pass


@dataclass
class Resp:
    pass


@dataclass(frozen=True)
class MockCap:
    name: str = "test"


# ─── Exposure Dict ──────────────────────────────────────────────────────────


class TestExposureDict:
    def test_http_trigger(self):
        exp = Exposure(
            trigger=HTTPRouteTrigger("GET", "/users"),
            codec=RequestResponseCodec(Req, Resp),
        )
        d = exposure_dict(exp)
        assert d["trigger"]["type"] == "HTTPRouteTrigger"
        assert d["trigger"]["method"] == "GET"
        assert d["trigger"]["path"] == "/users"

    def test_cli_trigger(self):
        exp = Exposure(
            trigger=CLITrigger("scan", description="Scan path"),
            codec=RequestResponseCodec(Req, Resp),
        )
        d = exposure_dict(exp)
        assert d["trigger"]["type"] == "CLITrigger"
        assert d["trigger"]["command"] == "scan"
        assert d["trigger"]["description"] == "Scan path"

    def test_rrc_codec(self):
        exp = Exposure(
            trigger=HTTPRouteTrigger("POST", "/create"),
            codec=RequestResponseCodec(Req, Resp),
        )
        d = exposure_dict(exp)
        assert d["codec"]["type"] == "RequestResponseCodec"
        assert d["codec"]["request"] == "Req"
        assert d["codec"]["response"] == "Resp"

    def test_delegate_codec(self):
        def my_handler():
            pass

        exp = Exposure(
            trigger=HTTPRouteTrigger("GET", "/test"),
            codec=delegate(my_handler),
        )
        d = exposure_dict(exp)
        assert d["codec"]["type"] == "DelegateCodec"
        assert d["codec"]["handler"] == "my_handler"

    def test_capabilities(self):
        exp = Exposure(
            trigger=HTTPRouteTrigger("GET", "/test"),
            codec=RequestResponseCodec(Req, Resp),
            capabilities=(MockCap("auth"),),
        )
        d = exposure_dict(exp)
        assert "capabilities" in d
        assert len(d["capabilities"]) == 1
        # MockCap is a dataclass → gets _dataclass_dict fallback
        assert d["capabilities"][0]["type"] == "MockCap"

    def test_no_capabilities_key_when_empty(self):
        exp = Exposure(
            trigger=HTTPRouteTrigger("GET", "/test"),
            codec=RequestResponseCodec(Req, Resp),
        )
        d = exposure_dict(exp)
        assert "capabilities" not in d


# ─── Endpoint Dict ──────────────────────────────────────────────────────────


class TestEndpointDict:
    def test_basic_endpoint(self):
        ep = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/users"),
            RequestResponseCodec(Req, Resp),
        )
        d = endpoint_dict(ep)
        assert d["exposure_count"] == 1
        assert len(d["exposures"]) == 1

    def test_multi_exposure(self):
        ep = (
            endpoint(_runner())
            .expose(HTTPRouteTrigger("GET", "/users"), RequestResponseCodec(Req, Resp))
            .expose(CLITrigger("list-users"), RequestResponseCodec(Req, Resp))
        )
        d = endpoint_dict(ep)
        assert d["exposure_count"] == 2


# ─── Application Dict ──────────────────────────────────────────────────────


class TestApplicationDict:
    def test_empty_app(self):
        app = application()
        d = application_dict(app)
        assert d["endpoint_count"] == 0
        assert d["endpoints"] == []
        assert "global_capabilities" not in d

    def test_app_with_endpoints(self):
        ep1 = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/a"), RequestResponseCodec(Req, Resp)
        )
        ep2 = endpoint(_runner()).expose(
            HTTPRouteTrigger("POST", "/b"), RequestResponseCodec(Req, Resp)
        )
        app = application().mount(ep1, ep2)
        d = application_dict(app)
        assert d["endpoint_count"] == 2
        assert len(d["endpoints"]) == 2

    def test_global_caps(self):
        app = application(capabilities=(MockCap("cors"),))
        d = application_dict(app)
        assert "global_capabilities" in d
        assert len(d["global_capabilities"]) == 1


# ─── Human-Readable Layer ───────────────────────────────────────────────────


class TestExplainApplication:
    def test_header(self):
        app = application()
        text = explain_application(app)
        assert "=== Application" in text
        assert "0 endpoints" in text

    def test_endpoints_shown(self):
        ep = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/users"), RequestResponseCodec(Req, Resp)
        )
        app = application().mount(ep)
        text = explain_application(app)
        assert "1 endpoint)" in text
        assert "Endpoint #1" in text
        assert "GET /users" in text
        assert "RequestResponseCodec" in text

    def test_global_caps_shown(self):
        app = application(capabilities=(MockCap("cors"),))
        text = explain_application(app)
        assert "global:" in text
        assert "MockCap" in text

    def test_rrc_details(self):
        ep = endpoint(_runner()).expose(
            HTTPRouteTrigger("POST", "/create"), RequestResponseCodec(Req, Resp)
        )
        app = application().mount(ep)
        text = explain_application(app)
        assert "request: Req" in text
        assert "response: Resp" in text


class TestExplainEndpoint:
    def test_basic(self):
        ep = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/test"), RequestResponseCodec(Req, Resp)
        )
        text = explain_endpoint(ep)
        assert "Endpoint #1" in text
        assert "1 exposure" in text

    def test_cli_trigger_format(self):
        ep = endpoint(_runner()).expose(
            CLITrigger("scan"), RequestResponseCodec(Req, Resp)
        )
        text = explain_endpoint(ep)
        assert "scan (cli)" in text


# ─── Open World ─────────────────────────────────────────────────────────────


class TestOpenWorld:
    def test_unknown_trigger(self):
        @dataclass(frozen=True)
        class CustomTrigger:
            channel: str

        exp = Exposure(
            trigger=CustomTrigger("my-channel"),
            codec=RequestResponseCodec(Req, Resp),
        )
        d = exposure_dict(exp)
        # Falls back to _dataclass_dict
        assert d["trigger"]["type"] == "CustomTrigger"
        assert d["trigger"]["channel"] == "my-channel"

    def test_unknown_codec(self):
        @dataclass(frozen=True)
        class CustomCodec:
            format: str

        exp = Exposure(
            trigger=HTTPRouteTrigger("GET", "/test"),
            codec=CustomCodec("msgpack"),
        )
        d = exposure_dict(exp)
        assert d["codec"]["type"] == "CustomCodec"
        assert d["codec"]["format"] == "msgpack"

    def test_custom_handler(self):
        @dataclass(frozen=True)
        class CustomTrigger:
            name: str

        def custom_handler(t: CustomTrigger) -> dict:
            return {"type": "Custom", "name": t.name, "extra": "info"}

        custom_handlers = {**SURFACE_EXPLAIN, CustomTrigger: custom_handler}

        exp = Exposure(
            trigger=CustomTrigger("test"),
            codec=RequestResponseCodec(Req, Resp),
        )
        d = exposure_dict(exp, handlers=custom_handlers)
        assert d["trigger"]["type"] == "Custom"
        assert d["trigger"]["extra"] == "info"
