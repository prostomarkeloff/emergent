# pyright: reportPrivateUsage=false
"""Property-based tests for the Surface axis.

Covers triggers, transforms, Application, Endpoint,
and capability helper functions.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass

from hypothesis import given
from hypothesis import strategies as st

from emergent.ops._graph import Runner, ops
from emergent.wire.axis.surface import Endpoint, application, endpoint
from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
from emergent.wire.axis.surface.capabilities._helpers import (
    deduplicate_capabilities,
    find_capability,
    has_capability,
    merge_capabilities,
)
from emergent.wire.axis.surface.transforms._trigger import Prefix, StripPrefix, URLPath
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger, Method


# ═══════════════════════════════════════════════════════════════════════════════
# Test-local helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _runner() -> Runner:
    """Create an empty Runner for Endpoint construction."""
    return ops().compile()


# Concrete capability stubs for testing helpers.

@dataclass(frozen=True, slots=True)
class _CapA(SurfaceCapability):
    value: int = 0


@dataclass(frozen=True, slots=True)
class _CapB(SurfaceCapability):
    label: str = ""


@dataclass(frozen=True, slots=True)
class _CapC(SurfaceCapability):
    flag: bool = False


# ═══════════════════════════════════════════════════════════════════════════════
# Strategies
# ═══════════════════════════════════════════════════════════════════════════════

# Short alphabetic segments for URL paths.
_segment = st.from_regex(r"[a-z]{1,8}", fullmatch=True)

_METHODS: list[Method] = ["GET", "POST", "PUT", "DELETE", "PATCH"]
_http_method: st.SearchStrategy[Method] = st.sampled_from(_METHODS)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. HTTPRouteTrigger is frozen
# ═══════════════════════════════════════════════════════════════════════════════


@given(method=_http_method, path=_segment)
def test_http_route_trigger_is_frozen(method: Method, path: str) -> None:
    trigger = HTTPRouteTrigger(method=method, path=f"/{path}")
    try:
        trigger.method = "PATCH"  # type: ignore[misc]
        raise AssertionError("Expected FrozenInstanceError")
    except FrozenInstanceError:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# 2. CLITrigger is frozen
# ═══════════════════════════════════════════════════════════════════════════════


@given(cmd=_segment)
def test_cli_trigger_is_frozen(cmd: str) -> None:
    trigger = CLITrigger(command=cmd)
    try:
        trigger.command = "other"  # type: ignore[misc]
        raise AssertionError("Expected FrozenInstanceError")
    except FrozenInstanceError:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# 3. URLPath composition
# ═══════════════════════════════════════════════════════════════════════════════


@given(a=_segment, b=_segment)
def test_urlpath_of_division_produces_correct_segments(a: str, b: str) -> None:
    path = URLPath.of(a) / b
    assert str(path) == f"/{a}/{b}"


@given(a=_segment, b=_segment, c=_segment)
def test_urlpath_chained_division(a: str, b: str, c: str) -> None:
    path = URLPath.of(a) / b / c
    assert str(path) == f"/{a}/{b}/{c}"


def test_urlpath_root() -> None:
    assert str(URLPath.root()) == "/"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Prefix.apply_trigger prepends path
# ═══════════════════════════════════════════════════════════════════════════════


@given(prefix_seg=_segment, route_seg=_segment, method=_http_method)
def test_prefix_apply_trigger_prepends(prefix_seg: str, route_seg: str, method: Method) -> None:
    prefix = Prefix.of(prefix_seg)
    trigger = HTTPRouteTrigger(method=method, path=f"/{route_seg}")
    result = prefix.apply_trigger(trigger)
    assert result.path == f"/{prefix_seg}/{route_seg}"
    # Method unchanged.
    assert result.method == method


# ═══════════════════════════════════════════════════════════════════════════════
# 5. StripPrefix.apply_trigger strips prefix
# ═══════════════════════════════════════════════════════════════════════════════


@given(prefix_seg=_segment, route_seg=_segment, method=_http_method)
def test_strip_prefix_removes_prefix(prefix_seg: str, route_seg: str, method: Method) -> None:
    trigger = HTTPRouteTrigger(method=method, path=f"/{prefix_seg}/{route_seg}")
    strip = StripPrefix.of(prefix_seg)
    result = strip.apply_trigger(trigger)
    assert result.path == f"/{route_seg}"
    assert result.method == method


@given(method=_http_method, seg=_segment)
def test_strip_prefix_noop_when_no_match(method: Method, seg: str) -> None:
    trigger = HTTPRouteTrigger(method=method, path=f"/{seg}")
    strip = StripPrefix.of("nonexistent")
    result = strip.apply_trigger(trigger)
    # When prefix is not present, trigger is returned unchanged.
    assert result.path == trigger.path


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Prefix composition: sequential Prefix applications
# ═══════════════════════════════════════════════════════════════════════════════


@given(a=_segment, b=_segment, route=_segment, method=_http_method)
def test_prefix_sequential_application(a: str, b: str, route: str, method: Method) -> None:
    """Applying Prefix(a) then Prefix(b) produces /b/a/route (outer prefix last)."""
    trigger = HTTPRouteTrigger(method=method, path=f"/{route}")
    t1 = Prefix.of(a).apply_trigger(trigger)
    t2 = Prefix.of(b).apply_trigger(t1)
    assert t2.path == f"/{b}/{a}/{route}"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Endpoint.expose returns new Endpoint, original unchanged
# ═══════════════════════════════════════════════════════════════════════════════


def test_endpoint_expose_returns_new_instance() -> None:
    runner = _runner()
    ep = endpoint(runner)
    trigger = HTTPRouteTrigger(method="GET", path="/test")
    codec = object()  # codec is just `object` type alias
    ep2 = ep.expose(trigger, codec)
    # Original is unchanged.
    assert ep.exposures == ()
    # New endpoint has one exposure.
    assert len(ep2.exposures) == 1
    assert ep2.exposures[0].trigger is trigger


def test_endpoint_expose_accumulates() -> None:
    runner = _runner()
    ep = endpoint(runner)
    t1 = HTTPRouteTrigger(method="GET", path="/a")
    t2 = HTTPRouteTrigger(method="POST", path="/b")
    codec = object()
    ep2 = ep.expose(t1, codec).expose(t2, codec)
    assert len(ep2.exposures) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Application + Application has endpoints from both
# ═══════════════════════════════════════════════════════════════════════════════


def test_application_add_combines_endpoints() -> None:
    runner = _runner()
    ep1 = endpoint(runner).expose(HTTPRouteTrigger("GET", "/a"), object())
    ep2 = endpoint(runner).expose(HTTPRouteTrigger("POST", "/b"), object())
    app1 = application().mount(ep1)
    app2 = application().mount(ep2)
    combined = app1 + app2
    assert len(combined.endpoints) == 2
    assert combined.endpoints[0] is ep1
    assert combined.endpoints[1] is ep2


def test_application_add_combines_capabilities() -> None:
    cap_a = _CapA(value=1)
    cap_b = _CapB(label="x")
    app1 = application(capabilities=(cap_a,))
    app2 = application(capabilities=(cap_b,))
    combined = app1 + app2
    assert len(combined.capabilities) == 2
    assert cap_a in combined.capabilities
    assert cap_b in combined.capabilities


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Application.mount accumulates endpoints
# ═══════════════════════════════════════════════════════════════════════════════


@given(n=st.integers(min_value=0, max_value=10))
def test_application_mount_accumulates(n: int) -> None:
    runner = _runner()
    app = application()
    endpoints: list[Endpoint] = []
    for i in range(n):
        ep = endpoint(runner).expose(
            HTTPRouteTrigger("GET", f"/ep{i}"), object()
        )
        endpoints.append(ep)
    app = app.mount(*endpoints)
    assert len(app.endpoints) == n


# ═══════════════════════════════════════════════════════════════════════════════
# 10. find_capability returns correct cap or None
# ═══════════════════════════════════════════════════════════════════════════════


def test_find_capability_returns_match() -> None:
    cap_a = _CapA(value=42)
    cap_b = _CapB(label="hello")
    caps: tuple[SurfaceCapability, ...] = (cap_a, cap_b)
    result = find_capability(caps, _CapA)
    assert result is cap_a


def test_find_capability_returns_none_when_absent() -> None:
    cap_a = _CapA(value=1)
    caps: tuple[SurfaceCapability, ...] = (cap_a,)
    result = find_capability(caps, _CapB)
    assert result is None


def test_find_capability_returns_first_of_type() -> None:
    first = _CapA(value=1)
    second = _CapA(value=2)
    caps: tuple[SurfaceCapability, ...] = (first, second)
    result = find_capability(caps, _CapA)
    assert result is first


# ═══════════════════════════════════════════════════════════════════════════════
# 11. has_capability returns True/False
# ═══════════════════════════════════════════════════════════════════════════════


def test_has_capability_true() -> None:
    caps: tuple[SurfaceCapability, ...] = (_CapA(value=0),)
    assert has_capability(caps, _CapA) is True


def test_has_capability_false() -> None:
    caps: tuple[SurfaceCapability, ...] = (_CapA(value=0),)
    assert has_capability(caps, _CapB) is False


def test_has_capability_empty() -> None:
    caps: tuple[SurfaceCapability, ...] = ()
    assert has_capability(caps, _CapA) is False


# ═══════════════════════════════════════════════════════════════════════════════
# 12. merge_capabilities combines tuples
# ═══════════════════════════════════════════════════════════════════════════════


def test_merge_capabilities_combines() -> None:
    a = (_CapA(value=1),)
    b = (_CapB(label="x"),)
    merged = merge_capabilities(a, b)
    assert len(merged) == 2


def test_merge_capabilities_override_by_type() -> None:
    """Later tuple overrides earlier by type."""
    base: tuple[SurfaceCapability, ...] = (_CapA(value=1), _CapB(label="old"))
    override: tuple[SurfaceCapability, ...] = (_CapA(value=99),)
    merged = merge_capabilities(base, override)
    # Only one _CapA, and it has the overridden value.
    cap_a_instances = [c for c in merged if isinstance(c, _CapA)]
    assert len(cap_a_instances) == 1
    assert cap_a_instances[0].value == 99


# ═══════════════════════════════════════════════════════════════════════════════
# 13. deduplicate_capabilities removes duplicates by type
# ═══════════════════════════════════════════════════════════════════════════════


def test_deduplicate_capabilities_keeps_last() -> None:
    first = _CapA(value=1)
    second = _CapA(value=2)
    caps: tuple[SurfaceCapability, ...] = (first, _CapB(label="x"), second)
    deduped = deduplicate_capabilities(caps)
    cap_a_instances = [c for c in deduped if isinstance(c, _CapA)]
    assert len(cap_a_instances) == 1
    # Last of type wins.
    assert cap_a_instances[0].value == 2


def test_deduplicate_capabilities_no_duplicates_unchanged() -> None:
    caps: tuple[SurfaceCapability, ...] = (_CapA(value=1), _CapB(label="x"), _CapC(flag=True))
    deduped = deduplicate_capabilities(caps)
    assert len(deduped) == 3
