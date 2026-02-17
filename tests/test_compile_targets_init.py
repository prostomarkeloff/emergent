"""Tests for compile targets __init__.py import paths.

Covers:
- cli is always available
- event is always available
- fastapi is available when installed
- telegrinder is available when installed
- __all__ contains the correct entries
"""

from __future__ import annotations

import types

import pytest


def test_cli_always_available():
    """CLI target is always importable (no optional deps)."""
    from emergent.wire.compile.targets import cli

    assert isinstance(cli, types.ModuleType)


def test_event_always_available():
    """Event target is always importable (no optional deps)."""
    from emergent.wire.compile.targets import event

    assert isinstance(event, types.ModuleType)


def test_targets_all_has_cli():
    """__all__ always contains 'cli'."""
    from emergent.wire.compile import targets

    assert "cli" in targets.__all__


def test_targets_all_has_event():
    """__all__ always contains 'event'."""
    from emergent.wire.compile import targets

    assert "event" in targets.__all__


def test_fastapi_when_available():
    """fastapi target is in __all__ when fastapi is installed."""
    from emergent.wire.compile import targets

    try:
        import fastapi as _  # noqa: F811
    except ImportError:
        pytest.skip("fastapi not installed")

    assert "fastapi" in targets.__all__
    assert hasattr(targets, "fastapi")
    assert isinstance(targets.fastapi, types.ModuleType)


def test_telegrinder_when_available():
    """telegrinder target is in __all__ when telegrinder is installed."""
    from emergent.wire.compile import targets

    try:
        import telegrinder as _  # noqa: F811
    except ImportError:
        pytest.skip("telegrinder not installed")

    assert "telegrinder" in targets.__all__
    assert hasattr(targets, "telegrinder")
    assert isinstance(targets.telegrinder, types.ModuleType)


def test_targets_all_is_list():
    """__all__ is a mutable list (built dynamically)."""
    from emergent.wire.compile import targets

    assert isinstance(targets.__all__, list)


def test_targets_at_least_cli_and_event():
    """At minimum, cli and event are always present in __all__."""
    from emergent.wire.compile import targets

    assert len(targets.__all__) >= 2
    assert "cli" in targets.__all__
    assert "event" in targets.__all__
