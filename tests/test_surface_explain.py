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


# ─── Integration Tests ─────────────────────────────────────────────────────


class TestIntegrationExplainComplexApp:
    """Build a complex app with HTTP + CLI + delegate + immediate codecs,
    multiple endpoints with capabilities, global capabilities.
    """

    def test_explain_application_shows_all_trigger_types(self):
        def _my_delegate_handler():
            pass

        @dataclass
        class HelpResp:
            text: str = "help"

            @classmethod
            def produce(cls) -> HelpResp:
                return cls()

        ep_http = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/users"),
            RequestResponseCodec(Req, Resp),
        )
        ep_cli = endpoint(_runner()).expose(
            CLITrigger("scan", description="Scan targets"),
            RequestResponseCodec(Req, Resp),
        )
        ep_delegate = endpoint(_runner()).expose(
            HTTPRouteTrigger("POST", "/webhook"),
            delegate(_my_delegate_handler),
        )
        ep_immediate = endpoint(_runner()).expose(
            CLITrigger("help"),
            ImmediateCodec(response=HelpResp),
        )

        app = application(capabilities=(MockCap("global-auth"),)).mount(
            ep_http, ep_cli, ep_delegate, ep_immediate
        )

        text = explain_application(app)
        # All trigger formats present
        assert "GET /users" in text
        assert "scan (cli)" in text
        assert "POST /webhook" in text
        assert "help (cli)" in text
        # Codec types present
        assert "RequestResponseCodec" in text
        assert "DelegateCodec" in text
        assert "ImmediateCodec" in text
        # Global cap in header
        assert "global:" in text
        assert "MockCap" in text

    def test_application_dict_endpoint_count_and_global_caps(self):
        ep1 = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/a"), RequestResponseCodec(Req, Resp)
        )
        ep2 = endpoint(_runner()).expose(
            CLITrigger("b"), RequestResponseCodec(Req, Resp)
        )
        ep3 = endpoint(_runner()).expose(
            HTTPRouteTrigger("DELETE", "/c"), RequestResponseCodec(Req, Resp)
        )

        app = application(
            capabilities=(MockCap("rate-limit"), MockCap("logging")),
        ).mount(ep1, ep2, ep3)

        d = application_dict(app)
        assert d["endpoint_count"] == 3
        assert len(d["endpoints"]) == 3
        assert "global_capabilities" in d
        assert len(d["global_capabilities"]) == 2
        cap_types = [c["type"] for c in d["global_capabilities"]]
        assert cap_types == ["MockCap", "MockCap"]
        cap_names = [c["name"] for c in d["global_capabilities"]]
        assert cap_names == ["rate-limit", "logging"]

    def test_each_exposure_shows_correct_trigger_and_codec_type(self):
        def _handler():
            pass

        ep_http_rrc = endpoint(_runner()).expose(
            HTTPRouteTrigger("PUT", "/items"),
            RequestResponseCodec(Req, Resp),
        )
        ep_cli_delegate = endpoint(_runner()).expose(
            CLITrigger("deploy"),
            delegate(_handler),
        )

        app = application().mount(ep_http_rrc, ep_cli_delegate)
        d = application_dict(app)

        # First endpoint: HTTP + RRC
        exp0 = d["endpoints"][0]["exposures"][0]
        assert exp0["trigger"]["type"] == "HTTPRouteTrigger"
        assert exp0["trigger"]["method"] == "PUT"
        assert exp0["trigger"]["path"] == "/items"
        assert exp0["codec"]["type"] == "RequestResponseCodec"
        assert exp0["codec"]["request"] == "Req"
        assert exp0["codec"]["response"] == "Resp"

        # Second endpoint: CLI + Delegate
        exp1 = d["endpoints"][1]["exposures"][0]
        assert exp1["trigger"]["type"] == "CLITrigger"
        assert exp1["trigger"]["command"] == "deploy"
        assert exp1["codec"]["type"] == "DelegateCodec"
        assert exp1["codec"]["handler"] == "_handler"


class TestIntegrationExplainWithCapabilities:
    """Endpoint with enrichers and transforms in capabilities."""

    def test_explain_endpoint_text_shows_capability_names(self):
        @dataclass(frozen=True)
        class EnricherCap:
            name: str = "Timeout"

        @dataclass(frozen=True)
        class TransformCap:
            name: str = "AsDict"

        ep = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/data"),
            RequestResponseCodec(Req, Resp),
            EnricherCap(name="Timeout"),
            TransformCap(name="AsDict"),
        )

        text = explain_endpoint(ep)
        # Capability names shown in the caps: line
        assert "caps:" in text
        assert "EnricherCap" in text
        assert "TransformCap" in text

    def test_endpoint_dict_lists_all_capabilities(self):
        @dataclass(frozen=True)
        class RateLimitCap:
            name: str = "RateLimit"
            rps: int = 100

        @dataclass(frozen=True)
        class RetryCap:
            name: str = "Retry"
            times: int = 3

        @dataclass(frozen=True)
        class CacheCap:
            name: str = "Cache"
            ttl: int = 60

        ep = endpoint(_runner()).expose(
            HTTPRouteTrigger("POST", "/process"),
            RequestResponseCodec(Req, Resp),
            RateLimitCap(),
            RetryCap(),
            CacheCap(),
        )

        d = endpoint_dict(ep)
        assert d["exposure_count"] == 1
        exp = d["exposures"][0]
        assert "capabilities" in exp
        assert len(exp["capabilities"]) == 3

        cap_types = [c["type"] for c in exp["capabilities"]]
        assert cap_types == ["RateLimitCap", "RetryCap", "CacheCap"]

        # Dataclass fields preserved
        assert exp["capabilities"][0]["rps"] == 100
        assert exp["capabilities"][1]["times"] == 3
        assert exp["capabilities"][2]["ttl"] == 60


class TestIntegrationExplainMultiExposureEndpoint:
    """Single endpoint exposed on multiple triggers (HTTP + CLI)."""

    def test_explain_endpoint_shows_both_exposures(self):
        ep = (
            endpoint(_runner())
            .expose(
                HTTPRouteTrigger("GET", "/items"),
                RequestResponseCodec(Req, Resp),
            )
            .expose(
                CLITrigger("list-items", description="List all items"),
                RequestResponseCodec(Req, Resp),
            )
        )

        text = explain_endpoint(ep)
        assert "2 exposures" in text
        assert "GET /items" in text
        assert "list-items (cli)" in text

    def test_each_exposure_correctly_identified_in_dict(self):
        ep = (
            endpoint(_runner())
            .expose(
                HTTPRouteTrigger("POST", "/submit"),
                RequestResponseCodec(Req, Resp),
                MockCap("http-only-cap"),
            )
            .expose(
                CLITrigger("submit"),
                RequestResponseCodec(Req, Resp),
            )
        )

        d = endpoint_dict(ep)
        assert d["exposure_count"] == 2
        assert len(d["exposures"]) == 2

        # First exposure: HTTP with capability
        http_exp = d["exposures"][0]
        assert http_exp["trigger"]["type"] == "HTTPRouteTrigger"
        assert http_exp["trigger"]["method"] == "POST"
        assert http_exp["trigger"]["path"] == "/submit"
        assert http_exp["codec"]["type"] == "RequestResponseCodec"
        assert "capabilities" in http_exp
        assert len(http_exp["capabilities"]) == 1
        assert http_exp["capabilities"][0]["name"] == "http-only-cap"

        # Second exposure: CLI without capabilities
        cli_exp = d["exposures"][1]
        assert cli_exp["trigger"]["type"] == "CLITrigger"
        assert cli_exp["trigger"]["command"] == "submit"
        assert cli_exp["codec"]["type"] == "RequestResponseCodec"
        assert "capabilities" not in cli_exp

    def test_multi_exposure_with_different_codecs(self):
        def _ws_handler():
            pass

        ep = (
            endpoint(_runner())
            .expose(
                HTTPRouteTrigger("GET", "/stream"),
                RequestResponseCodec(Req, Resp),
            )
            .expose(
                CLITrigger("stream"),
                delegate(_ws_handler),
            )
        )

        d = endpoint_dict(ep)
        assert d["exposure_count"] == 2

        assert d["exposures"][0]["codec"]["type"] == "RequestResponseCodec"
        assert d["exposures"][1]["codec"]["type"] == "DelegateCodec"
        assert d["exposures"][1]["codec"]["handler"] == "_ws_handler"

        text = explain_endpoint(ep)
        assert "RequestResponseCodec" in text
        assert "DelegateCodec" in text


class TestIntegrationExplainCustomHandlerPipeline:
    """Custom SurfaceExplainHandler handles unknown trigger/codec types."""

    def test_custom_trigger_handler_registered_and_used(self):
        @dataclass(frozen=True)
        class WebSocketTrigger:
            channel: str
            protocol: str = "wss"

        def _explain_ws_trigger(t: WebSocketTrigger) -> dict[str, str]:
            return {
                "type": "WebSocketTrigger",
                "channel": t.channel,
                "protocol": t.protocol,
            }

        custom_handlers = {**SURFACE_EXPLAIN, WebSocketTrigger: _explain_ws_trigger}

        ep = endpoint(_runner()).expose(
            WebSocketTrigger(channel="live-feed", protocol="wss"),
            RequestResponseCodec(Req, Resp),
        )
        app = application().mount(ep)

        text = explain_application(app, handlers=custom_handlers)
        assert "WebSocketTrigger" in text

        d = application_dict(app, handlers=custom_handlers)
        exp = d["endpoints"][0]["exposures"][0]
        assert exp["trigger"]["type"] == "WebSocketTrigger"
        assert exp["trigger"]["channel"] == "live-feed"
        assert exp["trigger"]["protocol"] == "wss"

    def test_custom_codec_handler_registered_and_used(self):
        @dataclass(frozen=True)
        class ProtobufCodec:
            message_type: str
            version: int = 3

        def _explain_protobuf(c: ProtobufCodec) -> dict[str, str | int]:
            return {
                "type": "ProtobufCodec",
                "message_type": c.message_type,
                "version": c.version,
            }

        custom_handlers = {**SURFACE_EXPLAIN, ProtobufCodec: _explain_protobuf}

        ep = endpoint(_runner()).expose(
            HTTPRouteTrigger("POST", "/rpc"),
            ProtobufCodec(message_type="UserRequest", version=3),
        )

        d = endpoint_dict(ep, handlers=custom_handlers)
        codec_d = d["exposures"][0]["codec"]
        assert codec_d["type"] == "ProtobufCodec"
        assert codec_d["message_type"] == "UserRequest"
        assert codec_d["version"] == 3

    def test_custom_trigger_and_codec_combined(self):
        @dataclass(frozen=True)
        class GRPCTrigger:
            service: str
            method: str

        @dataclass(frozen=True)
        class GRPCCodec:
            input_type: str
            output_type: str

        def _explain_grpc_trigger(t: GRPCTrigger) -> dict[str, str]:
            return {
                "type": "GRPCTrigger",
                "service": t.service,
                "method": t.method,
            }

        def _explain_grpc_codec(c: GRPCCodec) -> dict[str, str]:
            return {
                "type": "GRPCCodec",
                "input_type": c.input_type,
                "output_type": c.output_type,
            }

        custom_handlers = {
            **SURFACE_EXPLAIN,
            GRPCTrigger: _explain_grpc_trigger,
            GRPCCodec: _explain_grpc_codec,
        }

        ep = endpoint(_runner()).expose(
            GRPCTrigger(service="UserService", method="GetUser"),
            GRPCCodec(input_type="GetUserRequest", output_type="GetUserResponse"),
        )
        app = application().mount(ep)

        d = application_dict(app, handlers=custom_handlers)
        exp = d["endpoints"][0]["exposures"][0]

        assert exp["trigger"]["type"] == "GRPCTrigger"
        assert exp["trigger"]["service"] == "UserService"
        assert exp["trigger"]["method"] == "GetUser"

        assert exp["codec"]["type"] == "GRPCCodec"
        assert exp["codec"]["input_type"] == "GetUserRequest"
        assert exp["codec"]["output_type"] == "GetUserResponse"

        text = explain_application(app, handlers=custom_handlers)
        assert "GRPCTrigger" in text
        assert "GRPCCodec" in text

    def test_without_custom_handlers_falls_back_to_dataclass_dict(self):
        @dataclass(frozen=True)
        class MQTTTrigger:
            topic: str
            qos: int = 1

        ep = endpoint(_runner()).expose(
            MQTTTrigger(topic="sensors/temperature", qos=2),
            RequestResponseCodec(Req, Resp),
        )

        # No custom handlers -- uses default SURFACE_EXPLAIN which falls back
        d = endpoint_dict(ep)
        trigger_d = d["exposures"][0]["trigger"]
        assert trigger_d["type"] == "MQTTTrigger"
        assert trigger_d["topic"] == "sensors/temperature"
        assert trigger_d["qos"] == 2
