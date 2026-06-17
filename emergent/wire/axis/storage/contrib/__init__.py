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


def __getattr__(name: str) -> ModuleType | list[str]:
    """Resolve backends (and ``__all__``) lazily and *dynamically*.

    Both ``__all__`` and each backend are recomputed from ``_available`` on
    access rather than frozen at import time. A frozen snapshot is fragile: a
    fallback test that hides a dependency and reloads this module (to exercise
    the optional-backend path) would leave a stale ``__all__`` behind, polluting
    sibling tests in the same process. Recomputing means there is no snapshot to
    corrupt — availability always reflects reality at the moment of access.
    """
    if name == "__all__":
        return [backend for backend in _BACKENDS if _available(backend)]
    if name in _BACKENDS and _available(name):
        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
