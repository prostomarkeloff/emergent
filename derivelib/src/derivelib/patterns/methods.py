"""Methods pattern — proxy to emergent.wire.derive.patterns.methods.

DEPRECATED: Use emergent.wire.derive.patterns.methods directly.
derivelib will be removed in emergent 1.0.0.

    @derive(methods)
    class MyService:
        @staticmethod
        @post("/api/health")
        async def health() -> Result[str, DomainError]:
            return Ok("ok")
"""

from __future__ import annotations

from emergent.wire.derive.patterns.methods import (
    Methods,
    Methods as MethodsPattern,
    MethodDialect,
    TRIGGER_ENTRIES_ATTR,
    command,
    delete,
    get,
    method,
    methods,
    op,
    patch,
    post,
    put,
)

# Re-export ExposeMethod as blocked — it's an internal step type
_EXPOSE_METHOD_MSG = (
    "derivelib.patterns.methods.ExposeMethod has been removed. "
    "Use emergent.wire.derive.patterns.methods directly. "
    "derivelib will be removed in emergent 1.0.0."
)


def __getattr__(name: str) -> object:
    if name == "ExposeMethod":
        raise ImportError(_EXPOSE_METHOD_MSG)
    raise AttributeError(f"module 'derivelib.patterns.methods' has no attribute {name!r}")


__all__ = (
    # Decorators
    "method",
    "op",
    # HTTP aliases
    "post",
    "get",
    "put",
    "delete",
    "patch",
    # CLI alias
    "command",
    # Patterns
    "Methods",
    "MethodsPattern",
    "MethodDialect",
    "methods",
)
