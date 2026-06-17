"""Tests for ImportError fallback branches in optional-dependency re-export modules.

These modules use try/except ImportError patterns to provide stub functions
when optional dependencies (sqlalchemy, httpx, fastapi, telegrinder) are not
installed. Since these dependencies ARE installed in the test environment,
we simulate their absence by patching sys.modules and reloading.

Covers:
- emergent.wire.axis.storage.contrib.sqlalchemy (lines 53-66)
- emergent.wire.axis.query.contrib.http (lines 82-99)
- emergent.wire.axis.query.contrib.sqlalchemy (lines 40-49)
- emergent.wire.axis.storage.contrib.__init__ (lines 18-19, 25)
- emergent.wire.axis.query.contrib.__init__ (lines 16-17, 24-25)
- emergent.wire.compile.targets.__init__ (lines 17-18, 28-29)
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Sequence

import pytest

# These tests reload modules and mutate sys.modules; isolate so they can't leak
# into siblings (a popped module would break a later importlib.reload).
pytestmark = pytest.mark.usefixtures("isolate_sys_modules")


@contextmanager
def _hide_packages(package_names: Sequence[str]) -> Iterator[None]:
    """Temporarily hide packages from sys.modules by setting them to None.

    This causes ``import <package>`` to raise ``ImportError`` for any module
    whose key starts with one of the given package names.  On exit every
    change is rolled back so subsequent tests are unaffected.

    We also remove any cached emergent sub-modules that re-export from the
    hidden packages so that ``importlib.reload`` re-executes the try/except.
    """
    saved: dict[str, object] = {}
    keys_to_block: list[str] = []

    # 1. Collect all currently-loaded modules that belong to the blocked packages
    for key in list(sys.modules):
        for pkg in package_names:
            if key == pkg or key.startswith(pkg + "."):
                saved[key] = sys.modules.pop(key)
                keys_to_block.append(key)
                break

    # 2. Set them to None so future imports raise ImportError
    for key in keys_to_block:
        sys.modules[key] = None  # type: ignore[assignment]

    # 3. Also ensure the bare package name itself is blocked
    for pkg in package_names:
        if pkg not in sys.modules:
            saved.setdefault(pkg, sys.modules.get(pkg))
            sys.modules[pkg] = None  # type: ignore[assignment]
            keys_to_block.append(pkg)

    try:
        yield
    finally:
        # Remove all the None sentinels we injected
        for key in keys_to_block:
            sys.modules.pop(key, None)
        # Restore originals
        for key, mod in saved.items():
            if mod is not None:
                sys.modules[key] = mod  # type: ignore[assignment]


def _remove_emergent_submodules(prefix: str) -> dict[str, object]:
    """Remove cached emergent sub-modules matching *prefix* so reload re-executes them."""
    removed: dict[str, object] = {}
    for key in list(sys.modules):
        if key.startswith(prefix):
            removed[key] = sys.modules.pop(key)
    return removed


def _restore_modules(saved: dict[str, object]) -> None:
    """Restore previously removed modules into sys.modules."""
    sys.modules.update(saved)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. emergent.wire.axis.storage.contrib.sqlalchemy  (lines 53-66)
# ---------------------------------------------------------------------------


class TestStorageContribSqlalchemyFallback:
    """When sqlalchemy is not installed, the re-export module provides stubs."""

    def test_stubs_raise_import_error(self) -> None:
        prefix = "emergent.wire.axis.storage.contrib"
        saved_emergent = _remove_emergent_submodules(prefix)
        try:
            with _hide_packages(["sqlalchemy"]):
                mod = importlib.import_module(
                    "emergent.wire.axis.storage.contrib.sqlalchemy"
                )
                importlib.reload(mod)

                with pytest.raises(ImportError, match="sqlalchemy is required"):
                    mod.sqlalchemy()

                with pytest.raises(ImportError, match="sqlalchemy is required"):
                    mod.compile_model()

                with pytest.raises(ImportError, match="sqlalchemy is required"):
                    mod.compile_expr()

                with pytest.raises(ImportError, match="sqlalchemy is required"):
                    mod.entity_to_model()

                with pytest.raises(ImportError, match="sqlalchemy is required"):
                    mod.model_to_entity()
        finally:
            _restore_modules(saved_emergent)
            # Reload the real module so later tests aren't affected
            mod = importlib.import_module(
                "emergent.wire.axis.storage.contrib.sqlalchemy"
            )
            importlib.reload(mod)

    def test_all_is_minimal(self) -> None:
        prefix = "emergent.wire.axis.storage.contrib"
        saved_emergent = _remove_emergent_submodules(prefix)
        try:
            with _hide_packages(["sqlalchemy"]):
                mod = importlib.import_module(
                    "emergent.wire.axis.storage.contrib.sqlalchemy"
                )
                importlib.reload(mod)

                assert mod.__all__ == ("sqlalchemy",)
        finally:
            _restore_modules(saved_emergent)
            mod = importlib.import_module(
                "emergent.wire.axis.storage.contrib.sqlalchemy"
            )
            importlib.reload(mod)


# ---------------------------------------------------------------------------
# 2. emergent.wire.axis.query.contrib.http  (lines 82-99)
# ---------------------------------------------------------------------------


class TestQueryContribHttpFallback:
    """When httpx is not installed, the re-export module provides stubs."""

    def test_stubs_raise_import_error(self) -> None:
        prefix = "emergent.wire.axis.query.contrib"
        saved_emergent = _remove_emergent_submodules(prefix)
        try:
            with _hide_packages(["httpx"]):
                mod = importlib.import_module(
                    "emergent.wire.axis.query.contrib.http"
                )
                importlib.reload(mod)

                stub_names = [
                    "api",
                    "page_size",
                    "offset_limit",
                    "cursor",
                    "bearer",
                    "api_key",
                    "basic",
                    "query_params",
                    "body_filters",
                ]
                for name in stub_names:
                    with pytest.raises(ImportError, match="httpx is required"):
                        getattr(mod, name)()
        finally:
            _restore_modules(saved_emergent)
            mod = importlib.import_module("emergent.wire.axis.query.contrib.http")
            importlib.reload(mod)

    def test_all_is_minimal(self) -> None:
        prefix = "emergent.wire.axis.query.contrib"
        saved_emergent = _remove_emergent_submodules(prefix)
        try:
            with _hide_packages(["httpx"]):
                mod = importlib.import_module(
                    "emergent.wire.axis.query.contrib.http"
                )
                importlib.reload(mod)

                assert mod.__all__ == ("api",)
        finally:
            _restore_modules(saved_emergent)
            mod = importlib.import_module("emergent.wire.axis.query.contrib.http")
            importlib.reload(mod)


# ---------------------------------------------------------------------------
# 3. emergent.wire.axis.query.contrib.sqlalchemy  (lines 40-49)
# ---------------------------------------------------------------------------


class TestQueryContribSqlalchemyFallback:
    """When sqlalchemy is not installed, the query re-export module provides stubs."""

    def test_stubs_raise_import_error(self) -> None:
        prefix = "emergent.wire.axis.query.contrib"
        saved_emergent = _remove_emergent_submodules(prefix)
        try:
            with _hide_packages(["sqlalchemy"]):
                mod = importlib.import_module(
                    "emergent.wire.axis.query.contrib.sqlalchemy"
                )
                importlib.reload(mod)

                with pytest.raises(
                    ImportError, match="sqlalchemy.*is required"
                ):
                    mod.provider()

                with pytest.raises(
                    ImportError, match="sqlalchemy.*is required"
                ):
                    mod.store()
        finally:
            _restore_modules(saved_emergent)
            mod = importlib.import_module(
                "emergent.wire.axis.query.contrib.sqlalchemy"
            )
            importlib.reload(mod)

    def test_all_is_minimal(self) -> None:
        prefix = "emergent.wire.axis.query.contrib"
        saved_emergent = _remove_emergent_submodules(prefix)
        try:
            with _hide_packages(["sqlalchemy"]):
                mod = importlib.import_module(
                    "emergent.wire.axis.query.contrib.sqlalchemy"
                )
                importlib.reload(mod)

                assert mod.__all__ == ("provider", "store")
        finally:
            _restore_modules(saved_emergent)
            mod = importlib.import_module(
                "emergent.wire.axis.query.contrib.sqlalchemy"
            )
            importlib.reload(mod)


# ---------------------------------------------------------------------------
# 4. emergent.wire.axis.storage.contrib.__init__  (lines 18-19, 25)
# ---------------------------------------------------------------------------


class TestStorageContribInitFallback:
    """When submodules are unavailable, storage contrib __init__ silently skips them."""

    def test_sqlalchemy_absent_from_all(self) -> None:
        prefix = "emergent.wire.axis.storage.contrib"
        saved_emergent = _remove_emergent_submodules(prefix)
        try:
            # Block the emergent submodule itself so __init__'s
            # ``from ... import sqlalchemy`` raises ImportError.
            with _hide_packages(
                ["sqlalchemy", "emergent.wire.axis.storage.contrib.sqlalchemy"]
            ):
                mod = importlib.import_module(
                    "emergent.wire.axis.storage.contrib"
                )
                importlib.reload(mod)

                assert "sqlalchemy" not in mod.__all__
                assert not hasattr(mod, "sqlalchemy")
        finally:
            _restore_modules(saved_emergent)
            mod = importlib.import_module("emergent.wire.axis.storage.contrib")
            importlib.reload(mod)

    def test_event_store_absent_from_all(self) -> None:
        """event_store is also optional; verify the except ImportError branch."""
        prefix = "emergent.wire.axis.storage.contrib"
        saved_emergent = _remove_emergent_submodules(prefix)
        try:
            # Block event_store submodule so the except branch fires.
            with _hide_packages(
                ["emergent.wire.axis.storage.contrib.event_store"]
            ):
                mod = importlib.import_module(
                    "emergent.wire.axis.storage.contrib"
                )
                importlib.reload(mod)

                assert "event_store" not in mod.__all__
        finally:
            _restore_modules(saved_emergent)
            mod = importlib.import_module("emergent.wire.axis.storage.contrib")
            importlib.reload(mod)


# ---------------------------------------------------------------------------
# 5. emergent.wire.axis.query.contrib.__init__  (lines 16-17, 24-25)
# ---------------------------------------------------------------------------


class TestQueryContribInitFallback:
    """When submodules are unavailable, query contrib __init__ skips them."""

    def test_http_absent_from_all(self) -> None:
        prefix = "emergent.wire.axis.query.contrib"
        saved_emergent = _remove_emergent_submodules(prefix)
        try:
            with _hide_packages(
                ["httpx", "emergent.wire.axis.query.contrib.http"]
            ):
                mod = importlib.import_module(
                    "emergent.wire.axis.query.contrib"
                )
                importlib.reload(mod)

                assert "http" not in mod.__all__
                assert not hasattr(mod, "http")
        finally:
            _restore_modules(saved_emergent)
            mod = importlib.import_module("emergent.wire.axis.query.contrib")
            importlib.reload(mod)

    def test_sqlalchemy_absent_from_all(self) -> None:
        prefix = "emergent.wire.axis.query.contrib"
        saved_emergent = _remove_emergent_submodules(prefix)
        try:
            with _hide_packages(
                ["sqlalchemy", "emergent.wire.axis.query.contrib.sqlalchemy"]
            ):
                mod = importlib.import_module(
                    "emergent.wire.axis.query.contrib"
                )
                importlib.reload(mod)

                assert "sqlalchemy" not in mod.__all__
                assert not hasattr(mod, "sqlalchemy")
        finally:
            _restore_modules(saved_emergent)
            mod = importlib.import_module("emergent.wire.axis.query.contrib")
            importlib.reload(mod)

    def test_both_absent(self) -> None:
        """When both submodules are unavailable, __all__ is empty."""
        prefix = "emergent.wire.axis.query.contrib"
        saved_emergent = _remove_emergent_submodules(prefix)
        try:
            with _hide_packages(
                [
                    "httpx",
                    "sqlalchemy",
                    "emergent.wire.axis.query.contrib.http",
                    "emergent.wire.axis.query.contrib.sqlalchemy",
                ]
            ):
                mod = importlib.import_module(
                    "emergent.wire.axis.query.contrib"
                )
                importlib.reload(mod)

                assert "http" not in mod.__all__
                assert "sqlalchemy" not in mod.__all__
                assert len(mod.__all__) == 0
        finally:
            _restore_modules(saved_emergent)
            mod = importlib.import_module("emergent.wire.axis.query.contrib")
            importlib.reload(mod)


# ---------------------------------------------------------------------------
# 6. emergent.wire.compile.targets.__init__  (lines 17-18, 28-29)
# ---------------------------------------------------------------------------


class TestCompileTargetsInitFallback:
    """When fastapi / telegrinder are absent, targets __init__ skips them."""

    def test_fastapi_absent_from_all(self) -> None:
        prefix = "emergent.wire.compile.targets"
        saved_emergent = _remove_emergent_submodules(prefix)
        try:
            with _hide_packages(
                ["fastapi", "emergent.wire.compile.targets.fastapi"]
            ):
                mod = importlib.import_module(
                    "emergent.wire.compile.targets"
                )
                importlib.reload(mod)

                assert "fastapi" not in mod.__all__
                assert not hasattr(mod, "fastapi")
                # cli and event should always remain
                assert "cli" in mod.__all__
                assert "event" in mod.__all__
        finally:
            _restore_modules(saved_emergent)
            mod = importlib.import_module("emergent.wire.compile.targets")
            importlib.reload(mod)

    def test_telegrinder_absent_from_all(self) -> None:
        prefix = "emergent.wire.compile.targets"
        saved_emergent = _remove_emergent_submodules(prefix)
        try:
            with _hide_packages(
                ["telegrinder", "emergent.wire.compile.targets.telegrinder"]
            ):
                mod = importlib.import_module(
                    "emergent.wire.compile.targets"
                )
                importlib.reload(mod)

                assert "telegrinder" not in mod.__all__
                assert not hasattr(mod, "telegrinder")
                assert "cli" in mod.__all__
                assert "event" in mod.__all__
        finally:
            _restore_modules(saved_emergent)
            mod = importlib.import_module("emergent.wire.compile.targets")
            importlib.reload(mod)

    def test_both_absent(self) -> None:
        """When both fastapi and telegrinder are missing, only cli and event remain."""
        prefix = "emergent.wire.compile.targets"
        saved_emergent = _remove_emergent_submodules(prefix)
        try:
            with _hide_packages(
                [
                    "fastapi",
                    "telegrinder",
                    "emergent.wire.compile.targets.fastapi",
                    "emergent.wire.compile.targets.telegrinder",
                ]
            ):
                mod = importlib.import_module(
                    "emergent.wire.compile.targets"
                )
                importlib.reload(mod)

                assert "fastapi" not in mod.__all__
                assert "telegrinder" not in mod.__all__
                assert "cli" in mod.__all__
                assert "event" in mod.__all__
                # cli + event always present; sqlalchemy present if installed
                assert len(mod.__all__) >= 2
        finally:
            _restore_modules(saved_emergent)
            mod = importlib.import_module("emergent.wire.compile.targets")
            importlib.reload(mod)
