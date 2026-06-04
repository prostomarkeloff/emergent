"""Root conftest — hypothesis profiles, slow marker, py2rust path."""

import asyncio
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from hypothesis import settings, HealthCheck

_py2rust_src = str(Path(__file__).parent / "py2rust" / "src")
if _py2rust_src not in sys.path:
    sys.path.insert(0, _py2rust_src)


# ─── schemathesis fuzz is OPT-IN ─────────────────────────────────────────────
# tests/fuzz/ is schemathesis generative fuzzing: 10 tests at 40-80s each
# (~480s total) that dominate the whole suite's wall time. Off by default so the
# local loop stays fast; opt in with EMERGENT_FUZZ=1 (env, not a flag — pytest-fast
# does not forward arbitrary pytest args). Collection-level skip works for both
# plain pytest and pytest-fast.
if os.environ.get("EMERGENT_FUZZ") != "1":
    collect_ignore = ["tests/fuzz"]


# ─── Hypothesis profiles ────────────────────────────────────────────────────

settings.register_profile(
    "light",
    max_examples=10,
    deadline=None,
    suppress_health_check=list(HealthCheck),
)

settings.register_profile(
    "medium",
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

settings.register_profile(
    "tough",
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# Load profile from env var if set (avoids --hypothesis-profile flag timing issue)
_profile = os.environ.get("HYPOTHESIS_PROFILE")
if _profile:
    settings.load_profile(_profile)


# ─── Tiering: auto-mark heavy fuzz tests `slow` ───────────


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-mark everything under tests/fuzz/ as `slow` + `fuzz`.

    The schemathesis generative suite costs 40-80s per test (~480s total) and
    dominates wall time. Tiering it out of the default run (`addopts = -m "not
    slow"`) keeps the local loop sub-minute; CI runs the full suite via
    `pytest -m ""`. Marking by location means new fuzz tests inherit the tier
    automatically — no per-test decorator needed.
    """
    slow = pytest.mark.slow
    fuzz = pytest.mark.fuzz
    for item in items:
        parts = item.nodeid.replace("\\", "/").split("/")
        if "fuzz" in parts:
            item.add_marker(slow)
            item.add_marker(fuzz)


# ─── Sleep cap ──────────────

_TEST_SLEEP_CAP_SECONDS = 0.05


@pytest.fixture
def anyio_backend() -> str:
    """Force anyio tests onto asyncio only.

    emergent's runtime (nodnod EventLoopAgent) uses asyncio.Task/Future
    directly — it cannot run under trio (`RuntimeError: no current event
    loop`). The [trio] backend variants always failed; tests/run.py already
    filters them with `-k "not trio"`. Pinning the backend here drops the
    [trio] parametrization everywhere (pytest and pytest-fast alike).
    """
    return "asyncio"


@pytest.fixture(autouse=True)
def _cap_asyncio_sleep(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Cap ``asyncio.sleep`` to 0.05s in every test.

    Production/runtime code carries real sleeps (poll intervals, retry backoff,
    worker-loop delays). When a test drives those paths it stalls on real wall
    time. 0.05s still lets the asyncio scheduler interleave tasks and surfaces
    genuine race conditions, but never blocks the run. Timeout tests keep
    working: their timeouts (e.g. 0.01s) still fire before the capped sleep.
    """
    real_sleep = asyncio.sleep

    async def _capped(delay: float = 0) -> None:
        await real_sleep(min(float(delay), _TEST_SLEEP_CAP_SECONDS))

    monkeypatch.setattr(asyncio, "sleep", _capped)
    yield


_CONTRIB_PREFIX = "emergent.wire.axis.storage.contrib"


@pytest.fixture
def isolate_sys_modules() -> Iterator[None]:
    """Snapshot/restore the storage-contrib module subtree around a test.

    Optional-import fallback tests reload ``…storage.contrib`` (and hide its
    deps) to exercise the missing-backend path, surgically mutating
    ``sys.modules``. Without restoration those mutations leak into sibling tests
    in the same process — under serial pytest a later ``importlib.reload(...)``
    finds ``sys.modules[name]`` and the parent package's attribute pointing at
    different objects and raises. We scope strictly to the contrib subtree (the
    only thing these tests perturb) — restoring *all* of ``sys.modules`` would
    break object identity for unrelated modules sharing the worker. Opt in via
    ``pytestmark = pytest.mark.usefixtures("isolate_sys_modules")``.
    """

    def _in_subtree(key: str) -> bool:
        return key == _CONTRIB_PREFIX or key.startswith(_CONTRIB_PREFIX + ".")

    before = {k: v for k, v in sys.modules.items() if _in_subtree(k)}
    try:
        yield
    finally:
        for key in list(sys.modules):
            if _in_subtree(key) and key not in before:
                del sys.modules[key]
        # Restore originals and re-bind each as its parent's attribute, so
        # `from pkg import child` and importlib.reload see a consistent view.
        for key, module in before.items():
            sys.modules[key] = module
            if module is None:
                continue
            parent_name, _, child = key.rpartition(".")
            parent = sys.modules.get(parent_name)
            if parent is not None:
                parent.__dict__[child] = module
