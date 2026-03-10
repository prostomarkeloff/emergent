"""Pattern Derivation — proxy to emergent.wire.derive.

DEPRECATED: Use emergent.wire.derive directly.
derivelib will be removed in emergent 1.0.0.

    from derivelib import derive, build_application_from_decorated
    from derivelib.patterns import http_crud

    @derive(http_crud("/api/users", provider_node=UserProvider))
    @dataclass
    class User:
        id: Annotated[int, Identity]
        name: str

    app = build_application_from_decorated(User)
"""

from __future__ import annotations

from typing import TypeVar

from emergent.wire.axis.schema._universal import (
    SchemaCapability,
    get_schema_meta,
    schema_meta,
)
from emergent.wire.axis.surface import (
    Application,
    Endpoint,
    application,
)
from emergent.wire.derive._compile import compile_derive
from emergent.wire.derive._materialize import materialize

T = TypeVar("T")


# ═══════════════════════════════════════════════════════════════════════════════
# Derive Decorator — proxies to @schema_meta
# ═══════════════════════════════════════════════════════════════════════════════


def derive(
    *args: SchemaCapability,
) -> type[T] | type:
    """Decorator to attach capabilities to a type.

    Proxies to @schema_meta() from emergent.wire.derive.

    Example:
        @derive(http_crud("/api/users"))
        @dataclass
        class User:
            id: int
            email: str
    """
    return schema_meta(*args)


def get_patterns(entity: type) -> tuple[SchemaCapability, ...]:
    """Get capabilities attached to an entity by @derive."""
    return get_schema_meta(entity)


def get_exposures(entity: type) -> tuple[object, ...]:
    """Get direct exposures attached to an entity.

    In the proxy implementation, always returns empty tuple.
    Use emergent.wire.derive directly for advanced exposure control.
    """
    return ()


def get_derivations(entity: type) -> tuple[object, ...]:
    """Get derivations attached to an entity.

    In the proxy implementation, always returns empty tuple.
    Use emergent.wire.derive directly for advanced derivation control.
    """
    return ()


# ═══════════════════════════════════════════════════════════════════════════════
# Compilation: compile_derive + materialize
# ═══════════════════════════════════════════════════════════════════════════════


def _compile_entity(entity: type) -> list[Endpoint]:
    """Compile entity via wire.derive's compile_derive."""
    return [materialize(ctx) for ctx in compile_derive(entity)]


# ═══════════════════════════════════════════════════════════════════════════════
# Derivation Functions
# ═══════════════════════════════════════════════════════════════════════════════


def derive_application(
    *pairs: tuple[type, SchemaCapability],
) -> list[Endpoint]:
    """Compile entity-capability pairs.

    Example:
        endpoints = derive_application(
            (User, http_crud("/api/users", provider_node=UserProvider)),
        )
    """
    result: list[Endpoint] = []
    for entity, cap in pairs:
        schema_meta(cap)(entity)
        result.extend(_compile_entity(entity))
    return result


def derive_endpoints(
    entity: type,
    *patterns: SchemaCapability,
) -> list[Endpoint]:
    """Compile capabilities for a single entity.

    Example:
        endpoints = derive_endpoints(
            User,
            http_crud("/api/users", provider_node=UserProvider),
        )
    """
    schema_meta(*patterns)(entity)
    return _compile_entity(entity)


def derive_from_decorated(
    *entities: type,
    patterns: tuple[type, ...] | None = None,
) -> list[Endpoint]:
    """Compile capabilities from @derive decorated entities.

    Args:
        *entities: Entity classes decorated with @derive
        patterns: Ignored in proxy (kept for signature compatibility)

    Example:
        @derive(http_crud("/api/users", provider_node=UserProvider))
        @dataclass
        class User: ...

        endpoints = derive_from_decorated(User)
    """
    result: list[Endpoint] = []
    for entity in entities:
        result.extend(_compile_entity(entity))
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Application/Endpoint Builders
# ═══════════════════════════════════════════════════════════════════════════════


def _endpoints_to_app(endpoints: list[Endpoint]) -> Application:
    """Mount endpoints into application."""
    app = application()
    for ep in endpoints:
        app = app.mount(ep)
    return app


def build_application(
    *pairs: tuple[type, SchemaCapability],
) -> Application:
    """Build Application from entity-capability pairs.

    Example:
        app = build_application(
            (User, http_crud("/api/users", provider_node=UserProvider)),
        )
    """
    return _endpoints_to_app(derive_application(*pairs))


def build_endpoint(
    entity: type,
    pattern: SchemaCapability,
) -> Endpoint:
    """Build single Endpoint from entity + capability."""
    schema_meta(pattern)(entity)
    endpoints = _compile_entity(entity)
    return endpoints[0]


def build_application_from_decorated(
    *entities: type,
    patterns: tuple[type, ...] | None = None,
) -> Application:
    """Build Application from @derive decorated entities.

    Example:
        @derive(http_crud("/api/users", provider_node=UserProvider))
        class User: ...

        app = build_application_from_decorated(User)
    """
    return _endpoints_to_app(derive_from_decorated(*entities, patterns=patterns))


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = (
    # Decorator
    "derive",
    # Accessors
    "get_patterns",
    "get_exposures",
    "get_derivations",
    # Derivation
    "derive_application",
    "derive_endpoints",
    "derive_from_decorated",
    # Application builders
    "build_application",
    "build_endpoint",
    "build_application_from_decorated",
)
