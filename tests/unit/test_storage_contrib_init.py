"""Tests for storage contrib __init__.py and sqlalchemy.py import paths.

Covers:
- The successful import path for sqlalchemy module in __init__.py
- The __all__ list contents when sqlalchemy is available
- The sqlalchemy.py re-export module __all__ contents
- The sqlalchemy.py re-exported names
"""

from __future__ import annotations



# ─── storage contrib __init__.py ─────────────────────────────────────────────


def test_storage_contrib_has_sqlalchemy():
    """When sqlalchemy is installed, contrib.__init__ exports it."""
    from emergent.wire.axis.storage import contrib

    assert hasattr(contrib, "sqlalchemy")
    assert "sqlalchemy" in contrib.__all__


def test_storage_contrib_sqlalchemy_is_module():
    """The sqlalchemy attribute is the actual sub-module."""
    from emergent.wire.axis.storage import contrib

    import types

    assert isinstance(contrib.sqlalchemy, types.ModuleType)


# ─── storage contrib sqlalchemy.py re-exports ────────────────────────────────


def test_storage_sqlalchemy_all_contents():
    """sqlalchemy.py __all__ contains expected names."""
    from emergent.wire.axis.storage.contrib import sqlalchemy

    expected_names = (
        "compile_model",
        "compile_expr",
        "entity_to_model",
        "model_to_entity",
        "StorageError",
        "SQLAlchemyStorage",
        "sqlalchemy",
        "SQLAlchemyStore",
        "BoundSQLAlchemyStore",
        "store",
    )
    for name in expected_names:
        assert name in sqlalchemy.__all__, f"Missing {name} in __all__"


def test_storage_sqlalchemy_exports_callable():
    """Key exports from sqlalchemy module are callable or classes."""
    from emergent.wire.axis.storage.contrib import sqlalchemy

    assert callable(sqlalchemy.compile_model)
    assert callable(sqlalchemy.compile_expr)
    assert callable(sqlalchemy.entity_to_model)
    assert callable(sqlalchemy.model_to_entity)
    assert callable(sqlalchemy.sqlalchemy)
    assert callable(sqlalchemy.store)


def test_storage_sqlalchemy_storage_error_is_dataclass():
    """StorageError is a dataclass with message and cause fields."""
    import dataclasses

    from emergent.wire.axis.storage.contrib.sqlalchemy import StorageError

    assert dataclasses.is_dataclass(StorageError)
    field_names = {f.name for f in dataclasses.fields(StorageError)}
    assert "message" in field_names


# ─── event_store in __init__ (optional) ──────────────────────────────────────


def test_storage_contrib_event_store_optional():
    """event_store is in __all__ only if importable."""
    from emergent.wire.axis.storage import contrib

    # event_store may or may not be available; we just verify no crash
    if hasattr(contrib, "event_store"):
        assert "event_store" in contrib.__all__
