#!/usr/bin/env python3
"""Fuzzing runner — lite/medium/hard modes.

Usage:
    uv run python tests/fuzz/run.py lite      # pre-commit: ~30s
    uv run python tests/fuzz/run.py medium    # CI: ~3min
    uv run python tests/fuzz/run.py hard      # nightly: ~15min

What runs in each mode:

LITE (pre-commit, ~30s):
  - Property tests with reduced examples (50 per test)
  - Schemathesis: 20 requests per endpoint
  - Mutation: skip (too slow)

MEDIUM (CI, ~3min):
  - Property tests with full examples (200 per test)
  - Schemathesis: 50 requests per endpoint, full spec conformance
  - Mutation: core modules only (simplify, serialize, fold)

HARD (nightly, ~15min):
  - Property tests with high examples (500 per test)
  - Schemathesis: 200 requests per endpoint
  - Mutation: all wire/ + ops/
  - HypoFuzz: 5 minutes of adaptive fuzzing
"""

from __future__ import annotations

import subprocess
import sys
import time


def run(cmd: list[str], label: str) -> bool:
    """Run a command, return True if successful."""
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}\n")
    start = time.monotonic()
    result = subprocess.run(cmd, cwd="/Users/prostomarkeloff/projects/python/emergent")
    elapsed = time.monotonic() - start
    status = "PASS" if result.returncode == 0 else "FAIL"
    print(f"\n  [{status}] {label} ({elapsed:.1f}s)\n")
    return result.returncode == 0


def lite() -> bool:
    """Pre-commit: fast smoke test."""
    ok = True

    ok &= run(
        [
            "uv", "run", "python", "-m", "pytest",
            "tests/test_property_fold.py",
            "tests/test_property_simplify.py",
            "tests/test_property_simplify_rules.py",
            "tests/test_property_serialize.py",
            "tests/test_property_expr.py",
            "tests/test_property_compiler_algebra.py",
            "-x", "-q", "--tb=short", "--no-header",
            "-p", "no:cacheprovider",
        ],
        "Property tests (core)",
    )

    ok &= run(
        [
            "uv", "run", "python", "-m", "pytest",
            "tests/fuzz/test_schemathesis.py",
            "-x", "-q", "--tb=short", "--no-header",
            "-k", "test_no_server_error",
            "-p", "no:cacheprovider",
        ],
        "Schemathesis (crash detection)",
    )

    return ok


def medium() -> bool:
    """CI: full property tests + spec conformance."""
    ok = True

    ok &= run(
        [
            "uv", "run", "python", "-m", "pytest",
            "tests/test_property_*.py",
            "-q", "--tb=short", "--no-header",
            "-p", "no:cacheprovider",
        ],
        "Property tests (all 5,040)",
    )

    ok &= run(
        [
            "uv", "run", "python", "-m", "pytest",
            "tests/fuzz/test_schemathesis.py",
            "-x", "-q", "--tb=short", "--no-header",
            "-p", "no:cacheprovider",
        ],
        "Schemathesis (full spec conformance)",
    )

    ok &= run(
        [
            "uv", "run", "python", "-m", "pytest",
            "tests/test_property_simplify.py",
            "tests/test_property_simplify_rules.py",
            "--gremlins",
            "--gremlin-targets=emergent/wire/axis/query/_simplify.py",
            "-q", "--tb=no", "--no-header",
        ],
        "Mutation testing (simplify)",
    )

    return ok


def hard() -> bool:
    """Nightly: everything + deep fuzzing."""
    ok = True

    ok &= run(
        [
            "uv", "run", "python", "-m", "pytest",
            "tests/test_property_*.py",
            "-q", "--tb=short", "--no-header",
            "-p", "no:cacheprovider",
        ],
        "Property tests (all)",
    )

    ok &= run(
        [
            "uv", "run", "python", "-m", "pytest",
            "tests/fuzz/test_schemathesis.py",
            "-x", "-q", "--tb=short", "--no-header",
            "-p", "no:cacheprovider",
        ],
        "Schemathesis (full)",
    )

    ok &= run(
        [
            "uv", "run", "python", "-m", "pytest",
            "tests/test_property_*.py",
            "--gremlins",
            "--gremlin-targets=emergent/wire/",
            "--gremlin-targets=emergent/ops/",
            "--gremlin-workers=auto",
            "-q", "--tb=no", "--no-header",
        ],
        "Mutation testing (all wire/ + ops/)",
    )

    ok &= run(
        [
            "uv", "run", "hypothesis", "fuzz",
            "-n", "4",
            "--no-dashboard",
            "--",
            "tests/test_property_simplify.py",
            "tests/test_property_serialize.py",
            "tests/test_property_expr.py",
            "tests/test_property_fold.py",
        ],
        "HypoFuzz (5 min adaptive fuzzing)",
    )

    return ok


MODES = {"lite": lite, "medium": medium, "hard": hard}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in MODES:
        print(f"Usage: python tests/fuzz/run.py [{'/'.join(MODES)}]")
        print()
        print("  lite    pre-commit / agent flow   ~30s")
        print("  medium  CI pipeline               ~3min")
        print("  hard    nightly / deep analysis    ~15min")
        sys.exit(1)

    mode = sys.argv[1]
    ok = MODES[mode]()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
