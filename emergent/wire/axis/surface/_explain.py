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
Custom handlers via ExplainHandlers.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TypeGuard

from emergent.wire.axis._explain import (
    ExplainContext,
    Explainable,
    callable_name,
    to_dict,
)
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


type JsonDict = dict[str, Any]
type SurfaceExplainHandler = Callable[[Any], JsonDict]
type ExplainHandlers = Mapping[type, SurfaceExplainHandler]


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _dataclass_dict(obj: Any) -> JsonDict:
    """Any frozen dataclass -> dict via dataclass fields contract."""
    d: JsonDict = {"type": type(obj).__name__}
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            val = getattr(obj, f.name)
            d[f.name] = val.__name__ if isinstance(val, type) else val
    return d


def _unknown_dict(obj: Any) -> JsonDict:
    """Fallback for unknown types — just the type name."""
    return _dataclass_dict(obj)


# ═══════════════════════════════════════════════════════════════════════════════
# Trigger / Codec handler shims
#
# Triggers and codecs self-describe via `compile_explain` (the shared `Explainable`
# protocol) — that is the path `_explain_obj` takes for real objects. These
# module-level functions are kept (tests import them and call them directly, often
# with duck-typed mocks) with their original field-reading bodies, so they remain
# byte-identical and do not depend on a real `compile_explain` being present.
# ═══════════════════════════════════════════════════════════════════════════════


def _explain_http_trigger(t: HTTPRouteTrigger) -> JsonDict:
    d: JsonDict = {"type": "HTTPRouteTrigger", "method": t.method, "path": t.path}
    if t.headers:
        d["headers"] = sorted(t.headers)
    return d


def _explain_cli_trigger(t: CLITrigger) -> JsonDict:
    d: JsonDict = {"type": "CLITrigger", "command": t.command}
    if t.description:
        d["description"] = t.description
    return d


def _explain_telegrinder_trigger(t: TelegrinderTrigger) -> JsonDict:
    d: JsonDict = {"type": "TelegrinderTrigger", "view": t.view}
    rules: tuple[Any, ...] = t.rules  # ABCRule behind TYPE_CHECKING — treat as object
    if rules:
        d["rules"] = [type(r).__name__ for r in rules]
    return d


def _explain_event_trigger(t: EventTrigger[Any]) -> JsonDict:
    return {"type": "EventTrigger", "event_type": t.event_type.__name__}


def _explain_rrc(c: RequestResponseCodec) -> JsonDict:
    return {
        "type": "RequestResponseCodec",
        "request": c.request.__name__,
        "response": c.response.__name__,
    }


def _explain_stateful(c: StatefulCodec) -> JsonDict:
    d: JsonDict = {
        "type": "StatefulCodec",
        "flow": c.flow.__name__,
    }
    resp = c.response
    d["response"] = resp.__name__ if isinstance(resp, type) else str(resp)
    d["key_node"] = c.key_node.__name__
    return d


def _explain_delegate(c: DelegateCodec) -> JsonDict:
    d: JsonDict = {
        "type": "DelegateCodec",
        "handler": callable_name(c.handler),
    }
    return d


def _explain_immediate(c: ImmediateCodec) -> JsonDict:
    return {
        "type": "ImmediateCodec",
        "response": c.response.__name__,
    }


def _explain_immediate_factory(c: ImmediateFactoryCodec) -> JsonDict:
    return {
        "type": "ImmediateFactoryCodec",
        "factory": callable_name(c.factory),
    }


# Back-compat: these single-object shims are no longer the dispatch path (that is
# the Explainable protocol via `_explain_obj`); they are kept only for direct import
# by tests/tooling. This tuple keeps the references live without re-registering them.
_LEGACY_SHIMS: tuple[Callable[[Any], JsonDict], ...] = (
    _explain_http_trigger,
    _explain_cli_trigger,
    _explain_telegrinder_trigger,
    _explain_event_trigger,
    _explain_rrc,
    _explain_stateful,
    _explain_delegate,
    _explain_immediate,
    _explain_immediate_factory,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Handler mapping — empty (triggers/codecs self-describe); override channel
# ═══════════════════════════════════════════════════════════════════════════════


SURFACE_EXPLAIN: ExplainHandlers = {}


# ═══════════════════════════════════════════════════════════════════════════════
# Dict-returning layer — structured data
# ═══════════════════════════════════════════════════════════════════════════════


def _explain_obj(
    obj: Any,
    handlers: ExplainHandlers | None,
) -> JsonDict:
    """Explain any object: override handler → `Explainable` protocol → fallback."""
    effective = handlers if handlers is not None else SURFACE_EXPLAIN
    handler = effective.get(type(obj))
    if handler is not None:
        return handler(obj)
    if isinstance(obj, Explainable):
        ctx = obj.compile_explain(ExplainContext())
        return to_dict(ctx.nodes[-1], type_key="type")
    return _unknown_dict(obj)


def exposure_dict(
    exp: Exposure,
    handlers: ExplainHandlers | None = None,
) -> JsonDict:
    """One exposure as structured dict.

    Args:
        exp: Exposure instance
        handlers: Custom handlers (default: SURFACE_EXPLAIN)

    Returns:
        Dict with trigger, codec, and capabilities info.
    """
    d: JsonDict = {
        "trigger": _explain_obj(exp.trigger, handlers),
        "codec": _explain_obj(exp.codec, handlers),
    }
    if exp.capabilities:
        d["capabilities"] = [_explain_obj(c, handlers) for c in exp.capabilities]
    return d


def endpoint_dict(
    ep: Endpoint,
    handlers: ExplainHandlers | None = None,
) -> JsonDict:
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
    handlers: ExplainHandlers | None = None,
) -> JsonDict:
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
    d: JsonDict = {
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
    handlers: ExplainHandlers | None = None,
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
    handlers: ExplainHandlers | None = None,
) -> str:
    """Human-readable explanation of one endpoint. Formats from endpoint_dict()."""
    data = endpoint_dict(ep, handlers)
    return _format_endpoint(data, idx=1)


# ═══════════════════════════════════════════════════════════════════════════════
# Formatters (dict → str)
# ═══════════════════════════════════════════════════════════════════════════════


def _format_obj_short(d: JsonDict) -> str:
    """Format an explain dict as a short string."""
    name = d.get("type", "?")
    rest = {k: v for k, v in d.items() if k != "type"}
    if not rest:
        return str(name)
    parts = ", ".join(f"{k}={_format_value(v)}" for k, v in rest.items())
    return f"{name}({parts})"


def _is_sequence(v: Any) -> TypeGuard[Sequence[Any]]:
    """TypeGuard: narrow object to Sequence[object] without Unknown propagation."""
    return isinstance(v, (list, tuple))


def _format_value(v: Any) -> str:
    """Format a dict value for human-readable output."""
    if _is_sequence(v):
        return ", ".join(str(x) for x in v)
    return repr(v)


def _format_trigger_short(d: JsonDict) -> str:
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


def _format_application(data: JsonDict) -> str:
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


def _format_endpoint(data: JsonDict, *, idx: int) -> str:
    exp_count = data["exposure_count"]
    lines: list[str] = [
        f"  Endpoint #{idx} ({exp_count} exposure{'s' if exp_count != 1 else ''}):"
    ]

    for exp_data in data.get("exposures", []):
        lines.append(_format_exposure(exp_data))

    return "\n".join(lines)


def _format_exposure(data: JsonDict) -> str:
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
