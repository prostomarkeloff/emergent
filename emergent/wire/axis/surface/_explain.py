"""Surface explain — self-description of application topology.

Two layers:
  1. Dict-returning: application_dict(), endpoint_dict(), exposure_dict()
  2. Human-readable: explain_application(), explain_endpoint()

    from emergent.wire.axis.surface._explain import (
        application_dict, explain_application, SURFACE_EXPLAIN,
    )

    data = application_dict(app)            # -> dict
    text = explain_application(app)         # -> str

Open-world: unknown trigger/codec/capability types get generic fallback.
Custom handlers via Mapping[type, SurfaceExplainHandler].
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TypeGuard

from emergent.wire.axis.surface._app import Application
from emergent.wire.axis.surface._endpoint import Endpoint
from emergent.wire.axis.surface._types import Exposure
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.telegrinder import TelegrinderTrigger
from emergent.wire.axis.surface.triggers.event import EventTrigger
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec
from emergent.wire.axis.surface.codecs.stateful import StatefulCodec
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec
from emergent.wire.axis.surface.codecs.immediate import ImmediateCodec, ImmediateFactoryCodec


# ═══════════════════════════════════════════════════════════════════════════════
# Types
# ═══════════════════════════════════════════════════════════════════════════════


type SurfaceExplainHandler = Callable[[Any], dict[str, Any]]


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _dataclass_dict(obj: object) -> dict[str, Any]:
    """Any frozen dataclass -> dict via dataclass fields contract."""
    d: dict[str, Any] = {"type": type(obj).__name__}
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            val = getattr(obj, f.name)
            d[f.name] = val.__name__ if isinstance(val, type) else val
    return d


def _unknown_dict(obj: object) -> dict[str, Any]:
    """Fallback for unknown types — just the type name."""
    return _dataclass_dict(obj)


# ═══════════════════════════════════════════════════════════════════════════════
# Trigger Handlers
# ═══════════════════════════════════════════════════════════════════════════════


def _explain_http_trigger(t: HTTPRouteTrigger) -> dict[str, Any]:
    d: dict[str, Any] = {"type": "HTTPRouteTrigger", "method": t.method, "path": t.path}
    if t.headers:
        d["headers"] = sorted(t.headers)
    return d


def _explain_cli_trigger(t: CLITrigger) -> dict[str, Any]:
    d: dict[str, Any] = {"type": "CLITrigger", "command": t.command}
    if t.description:
        d["description"] = t.description
    return d


def _explain_telegrinder_trigger(t: TelegrinderTrigger) -> dict[str, Any]:
    d: dict[str, Any] = {"type": "TelegrinderTrigger", "view": t.view}
    rules: tuple[object, ...] = t.rules  # ABCRule behind TYPE_CHECKING — treat as object
    if rules:
        d["rules"] = [type(r).__name__ for r in rules]
    return d


def _explain_event_trigger(t: EventTrigger[object]) -> dict[str, Any]:
    return {"type": "EventTrigger", "event_type": t.event_type.__name__}


# ═══════════════════════════════════════════════════════════════════════════════
# Codec Handlers
# ═══════════════════════════════════════════════════════════════════════════════


def _explain_rrc(c: RequestResponseCodec) -> dict[str, Any]:
    return {
        "type": "RequestResponseCodec",
        "request": c.request.__name__,
        "response": c.response.__name__,
    }


def _explain_stateful(c: StatefulCodec) -> dict[str, Any]:
    d: dict[str, Any] = {
        "type": "StatefulCodec",
        "flow": c.flow.__name__,
    }
    resp = c.response
    d["response"] = resp.__name__ if isinstance(resp, type) else str(resp)
    d["key_node"] = c.key_node.__name__
    return d


def _explain_delegate(c: DelegateCodec) -> dict[str, Any]:
    d: dict[str, Any] = {
        "type": "DelegateCodec",
        "handler": getattr(c.handler, "__name__", repr(c.handler)),
    }
    return d


def _explain_immediate(c: ImmediateCodec) -> dict[str, Any]:
    return {
        "type": "ImmediateCodec",
        "response": c.response.__name__,
    }


def _explain_immediate_factory(c: ImmediateFactoryCodec) -> dict[str, Any]:
    return {
        "type": "ImmediateFactoryCodec",
        "factory": getattr(c.factory, "__name__", repr(c.factory)),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-built handler mapping
# ═══════════════════════════════════════════════════════════════════════════════


SURFACE_EXPLAIN: Mapping[type, SurfaceExplainHandler] = {
    # Triggers
    HTTPRouteTrigger: _explain_http_trigger,
    CLITrigger: _explain_cli_trigger,
    TelegrinderTrigger: _explain_telegrinder_trigger,
    EventTrigger: _explain_event_trigger,
    # Codecs
    RequestResponseCodec: _explain_rrc,
    StatefulCodec: _explain_stateful,
    DelegateCodec: _explain_delegate,
    ImmediateCodec: _explain_immediate,
    ImmediateFactoryCodec: _explain_immediate_factory,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Dict-returning layer — structured data
# ═══════════════════════════════════════════════════════════════════════════════


def _explain_obj(
    obj: object,
    handlers: Mapping[type, SurfaceExplainHandler] | None,
) -> dict[str, Any]:
    """Explain any object using handler dispatch with fallback."""
    effective = handlers if handlers is not None else SURFACE_EXPLAIN
    handler = effective.get(type(obj))
    if handler is not None:
        return handler(obj)
    return _unknown_dict(obj)


def exposure_dict(
    exp: Exposure,
    handlers: Mapping[type, SurfaceExplainHandler] | None = None,
) -> dict[str, Any]:
    """One exposure as structured dict.

    Args:
        exp: Exposure instance
        handlers: Custom handlers (default: SURFACE_EXPLAIN)

    Returns:
        Dict with trigger, codec, and capabilities info.
    """
    d: dict[str, Any] = {
        "trigger": _explain_obj(exp.trigger, handlers),
        "codec": _explain_obj(exp.codec, handlers),
    }
    if exp.capabilities:
        d["capabilities"] = [_explain_obj(c, handlers) for c in exp.capabilities]
    return d


def endpoint_dict(
    ep: Endpoint,
    handlers: Mapping[type, SurfaceExplainHandler] | None = None,
) -> dict[str, Any]:
    """One endpoint as structured dict.

    Args:
        ep: Endpoint instance
        handlers: Custom handlers (default: SURFACE_EXPLAIN)

    Returns:
        Dict with exposure count and list of exposure dicts.
    """
    return {
        "exposure_count": len(ep.exposures),
        "exposures": [exposure_dict(e, handlers) for e in ep.exposures],
    }


def application_dict(
    app: Application,
    handlers: Mapping[type, SurfaceExplainHandler] | None = None,
) -> dict[str, Any]:
    """Full application as structured dict.

    Args:
        app: Application instance
        handlers: Custom handlers (default: SURFACE_EXPLAIN)

    Returns:
        Dict with endpoint count, global capabilities, and endpoint dicts.

    Example:
        data = application_dict(app)
        data["endpoint_count"]     # 3
        data["global_capabilities"] # list of cap dicts
        data["endpoints"]           # list of endpoint dicts
    """
    d: dict[str, Any] = {
        "endpoint_count": len(app.endpoints),
    }
    if app.capabilities:
        d["global_capabilities"] = [_explain_obj(c, handlers) for c in app.capabilities]
    d["endpoints"] = [endpoint_dict(ep, handlers) for ep in app.endpoints]
    return d


# ═══════════════════════════════════════════════════════════════════════════════
# Human-readable layer — formats from dicts
# ═══════════════════════════════════════════════════════════════════════════════


def explain_application(
    app: Application,
    handlers: Mapping[type, SurfaceExplainHandler] | None = None,
) -> str:
    """Human-readable explanation of an application. Formats from application_dict().

    Example:
        print(explain_application(app))
        # === Application (3 endpoints, 1 global cap) ===
        #   global: CORS(origins=('*',))
        #   ...
    """
    data = application_dict(app, handlers)
    return _format_application(data)


def explain_endpoint(
    ep: Endpoint,
    handlers: Mapping[type, SurfaceExplainHandler] | None = None,
) -> str:
    """Human-readable explanation of one endpoint. Formats from endpoint_dict()."""
    data = endpoint_dict(ep, handlers)
    return _format_endpoint(data, idx=1)


# ═══════════════════════════════════════════════════════════════════════════════
# Formatters (dict → str)
# ═══════════════════════════════════════════════════════════════════════════════


def _format_obj_short(d: dict[str, Any]) -> str:
    """Format an explain dict as a short string."""
    name = d.get("type", "?")
    rest = {k: v for k, v in d.items() if k != "type"}
    if not rest:
        return str(name)
    parts = ", ".join(f"{k}={_format_value(v)}" for k, v in rest.items())
    return f"{name}({parts})"


def _is_sequence(v: object) -> TypeGuard[Sequence[object]]:
    """TypeGuard: narrow object to Sequence[object] without Unknown propagation."""
    return isinstance(v, (list, tuple))


def _format_value(v: object) -> str:
    """Format a dict value for human-readable output."""
    if _is_sequence(v):
        return ", ".join(str(x) for x in v)
    return repr(v)


def _format_trigger_short(d: dict[str, Any]) -> str:
    """Format trigger dict as a compact label."""
    t = d.get("type", "?")
    if t == "HTTPRouteTrigger":
        return f"{d.get('method', '?')} {d.get('path', '?')}"
    if t == "CLITrigger":
        return f"{d.get('command', '?')} (cli)"
    if t == "TelegrinderTrigger":
        rules = d.get("rules", [])
        rules_str = ", ".join(str(r) for r in rules) if rules else ""
        return f"tg:{d.get('view', '?')}({rules_str})"
    if t == "EventTrigger":
        return f"Event {d.get('event_type', '?')}"
    return _format_obj_short(d)


def _format_application(data: dict[str, Any]) -> str:
    ep_count = data["endpoint_count"]
    global_caps = data.get("global_capabilities", [])
    cap_count = len(global_caps)

    header_parts = [f"{ep_count} endpoint{'s' if ep_count != 1 else ''}"]
    if cap_count:
        header_parts.append(f"{cap_count} global cap{'s' if cap_count != 1 else ''}")

    lines: list[str] = [f"=== Application ({', '.join(header_parts)}) ==="]

    if global_caps:
        cap_strs = [_format_obj_short(c) for c in global_caps]
        lines.append(f"  global: {', '.join(cap_strs)}")

    for i, ep_data in enumerate(data.get("endpoints", []), 1):
        lines.append("")
        lines.append(_format_endpoint(ep_data, idx=i))

    return "\n".join(lines)


def _format_endpoint(data: dict[str, Any], *, idx: int) -> str:
    exp_count = data["exposure_count"]
    lines: list[str] = [
        f"  Endpoint #{idx} ({exp_count} exposure{'s' if exp_count != 1 else ''}):"
    ]

    for exp_data in data.get("exposures", []):
        lines.append(_format_exposure(exp_data))

    return "\n".join(lines)


def _format_exposure(data: dict[str, Any]) -> str:
    trigger_str = _format_trigger_short(data["trigger"])
    codec_str = data["codec"].get("type", "?")

    lines: list[str] = [f"    [{trigger_str}] {codec_str}"]

    # Show codec details (request/response for RRC, flow for stateful)
    codec = data["codec"]
    codec_type = codec.get("type")
    if codec_type == "RequestResponseCodec":
        lines.append(f"      request: {codec.get('request')}, response: {codec.get('response')}")
    elif codec_type == "StatefulCodec":
        lines.append(f"      flow: {codec.get('flow')}, response: {codec.get('response')}")
    elif codec_type == "ImmediateCodec":
        lines.append(f"      response: {codec.get('response')}")
    elif codec_type == "DelegateCodec":
        lines.append(f"      handler: {codec.get('handler')}")

    # Capabilities
    caps = data.get("capabilities", [])
    if caps:
        cap_strs = [_format_obj_short(c) for c in caps]
        lines.append(f"      caps: {', '.join(cap_strs)}")

    return "\n".join(lines)


__all__ = (
    # Types
    "SurfaceExplainHandler",
    # Dict layer
    "application_dict",
    "endpoint_dict",
    "exposure_dict",
    # Human-readable layer
    "explain_application",
    "explain_endpoint",
    # Pre-built handlers
    "SURFACE_EXPLAIN",
)
