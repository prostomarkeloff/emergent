"""Derivation patterns — reusable Op constants and pattern capabilities."""

from emergent.wire.derive.patterns.lookup import COUNT, EXISTS
from emergent.wire.derive.patterns.methods import (
    MethodDialect,
    Methods,
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

__all__ = (
    "EXISTS",
    "COUNT",
    # Methods
    "Methods",
    "MethodDialect",
    "methods",
    # Decorators
    "method",
    "op",
    "post",
    "get",
    "put",
    "delete",
    "patch",
    "command",
)
