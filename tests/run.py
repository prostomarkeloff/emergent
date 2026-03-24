#!/usr/bin/env python3
"""Unified test runner — same tests, different intensity.

Usage:
    uv run python tests/run.py light     # pre-commit     ~1min
    uv run python tests/run.py medium    # CI push        ~3min
    uv run python tests/run.py tough     # nightly        ~15min

All modes run the same pytest. The difference:
  - hypothesis max_examples (via profile)
  - whether @pytest.mark.slow tests run
  - whether mutation/coverage/pyright runs after
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent

IGNORES = [
    "--ignore=tests/unit/test_transpile.py",
]

BASE_ARGS = [
    "uv", "run", "python", "-m", "pytest", "tests/",
    *IGNORES,
    "-q", "--tb=short", "-k", "not trio",
    "-p", "no:cacheprovider",
]


def _run(cmd: list[str], label: str, profile: str | None = None) -> bool:
    print(f"\n  {label}")
    start = time.monotonic()
    env = {**__import__("os").environ}
    if profile:
        env["HYPOTHESIS_PROFILE"] = profile
    result = subprocess.run(cmd, cwd=str(ROOT), env=env)
    elapsed = time.monotonic() - start
    status = "✓" if result.returncode == 0 else "✗"
    print(f"  {status} {elapsed:.0f}s")
    return result.returncode == 0


def light() -> bool:
    """~1min: all tests except slow, hypothesis=10."""
    return _run([
        *BASE_ARGS,
        "-m", "not slow",
    ], "All tests (light)", profile="light")


def medium() -> bool:
    """~3min: all tests, hypothesis=50, + pyright."""
    ok = _run([
        *BASE_ARGS,
    ], "All tests (medium)", profile="medium")
    ok &= _run(["uv", "run", "pyright", "emergent/"], "Pyright")
    return ok


def tough() -> bool:
    """~15min: all tests full, + mutation, + coverage, + pyright."""
    ok = _run(BASE_ARGS, "All tests (full)")
    ok &= _run([
        "uv", "run", "python", "-m", "pytest",
        "tests/property/test_property_simplify.py",
        "tests/property/test_property_simplify_rules.py",
        "tests/property/test_property_fold.py",
        "tests/property/test_property_serialize.py",
        "--gremlins",
        "--gremlin-targets=emergent/wire/axis/query/_simplify.py",
        "--gremlin-targets=emergent/wire/compile/_core.py",
        "--gremlin-workers=auto", "-q", "--tb=no",
    ], "Mutation testing")
    ok &= _run([
        "uv", "run", "python", "-m", "pytest",
        "tests/property/", "tests/behavioral/",
        "-q", "--tb=no", "-k", "not trio",
        "--cov=emergent/wire", "--cov=emergent/ops",
        "--cov-report=term-missing:skip-covered",
        "-p", "no:cacheprovider",
    ], "Coverage")
    ok &= _run(["uv", "run", "pyright", "emergent/", "tests/"], "Pyright (all)")
    return ok


MODES = {"light": light, "medium": medium, "tough": tough}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in MODES:
        print("Usage: uv run python tests/run.py [light|medium|tough]")
        print()
        print("  light   pre-commit     ~1min")
        print("  medium  CI push        ~3min")
        print("  tough   nightly        ~15min")
        sys.exit(1)

    mode = sys.argv[1]
    start = time.monotonic()
    ok = MODES[mode]()
    elapsed = time.monotonic() - start
    print(f"\n  {'ALL PASSED' if ok else 'FAILURES'} ({elapsed:.0f}s)\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
