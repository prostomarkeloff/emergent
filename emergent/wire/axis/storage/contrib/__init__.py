"""Storage contrib backends.

    from emergent.wire.axis.storage.contrib import sqlalchemy
    from emergent.wire.axis.storage.contrib import event_store

    users = sqlalchemy.sqlalchemy(session, User, "users")

Note: Each backend is optional and requires its dependency.
"""

import importlib
import importlib.util
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from emergent.wire.axis.storage.contrib import event_store as event_store
    from emergent.wire.axis.storage.contrib import sqlalchemy as sqlalchemy

_BACKENDS = ("sqlalchemy", "event_store")


def _available(name: str) -> bool:
    """Whether a backend submodule can be located, without executing it.

    find_spec locates the module (so an absent submodule/dependency is
    reported), but does NOT run its body — which is what avoids the
    package-init circular import that eagerly importing the submodule used
    to trigger (and silently swallow). find_spec returns None for modules
    hidden via ``sys.modules[name] = None``, matching the optional-backend
    fallback tests.
    """
    try:
        return importlib.util.find_spec(f"{__name__}.{name}") is not None
    except (ImportError, ValueError):
        return False


__all__ = [name for name in _BACKENDS if _available(name)]


def __getattr__(name: str) -> ModuleType:
    """Import an available backend submodule lazily, after full init."""
    if name in __all__:
        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
