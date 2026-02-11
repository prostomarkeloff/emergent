"""Pattern Derivation — entity + pattern → wire Application.

v4: deps removed. Infrastructure dependencies resolved via compose.Node
    (nodnod node composition at runtime). Pattern.compile() takes only entity.

    from derivelib import derive, derive_application
    from derivelib.patterns import http_crud

    @derive(http_crud("/api/users", provider_node=UserProvider))
    @dataclass
    class User:
        id: Annotated[int, Identity]
        name: str

    app = build_application_from_decorated(User)
"""

from __future__ import annotations

from typing import Callable, Protocol, TypeVar, runtime_checkable

from emergent.wire.axis.surface import (
    Exposure,
    Endpoint,
    Application,
    application,
    empty_runner,
)

from ._derivation import Derivation
from ._fold import fold_derive, materialize

T = TypeVar("T")

type ExposureT = Callable[[Exposure], Exposure]


def _compose(*fns: ExposureT) -> ExposureT:
    """Chain ExposureT transforms left-to-right."""

    def composed(exp: Exposure) -> Exposure:
        for fn in fns:
            exp = fn(exp)
        return exp

    return composed


# ═══════════════════════════════════════════════════════════════════════════════
# Pattern Protocol
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class Pattern(Protocol):
    """Pattern protocol — entity → derivation steps.

    compile() returns a Derivation (tuple of steps), NOT an Endpoint.
    The steps are folded by fold_derive, then materialized to Endpoint.

    Infrastructure dependencies (providers, backends) are resolved
    at runtime via compose.Node on generated request types — no deps parameter.

    Example:
        @dataclass
        class MyCRUDDialect:
            provider_node: type

            def compile(self, entity: type) -> Derivation:
                return (
                    inspect_entity(),
                    require_identity(),
                    bind_provider(self.provider_node),
                    *crud_exposures(http_triggers("/api/users")),
                )
    """

    def compile(self, entity: type) -> Derivation:
        """Compile pattern into derivation steps."""
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Derive Decorator — stores patterns, returns original class
# ═══════════════════════════════════════════════════════════════════════════════


DERIVE_PATTERNS_KEY = "__derive_patterns__"
DERIVE_EXPOSURES_KEY = "__derive_exposures__"
DERIVE_DERIVATIONS_KEY = "__derive_derivations__"


def derive(
    *args: Pattern | Exposure | ExposureT,
) -> Callable[[type[T]], type[T]]:
    """Decorator to attach patterns, exposures, and derivations to a type.

    Patterns are stored but NOT compiled — they get compiled at
    derive_application time with deps.

    Accepts:
        Pattern[D]  — compiled to Derivation at build time
        Exposure    — direct exposures (added to empty endpoint)
        ExposureT   — post-processing transform on materialized exposures

    Returns the ORIGINAL CLASS unchanged — User is still usable as User.

    Example:
        @derive(http_crud("/api/users"))
        @dataclass
        class User:
            id: int
            email: str

        # User is still a regular class!
        user = User(id=1, email="alice@example.com")
    """

    def decorator(cls: type[T]) -> type[T]:
        patterns: list[Pattern] = []
        exposures: list[Exposure] = []
        derivations: list[ExposureT] = []

        for arg in args:
            if isinstance(arg, Exposure):
                exposures.append(arg)
            elif isinstance(arg, Pattern):
                patterns.append(arg)
            elif callable(arg):
                # Derivation (ExposureT)
                derivations.append(arg)

        setattr(cls, DERIVE_PATTERNS_KEY, tuple(patterns))
        setattr(cls, DERIVE_EXPOSURES_KEY, tuple(exposures))
        setattr(cls, DERIVE_DERIVATIONS_KEY, tuple(derivations))
        return cls

    return decorator


def get_patterns(entity: type) -> tuple[Pattern, ...]:
    """Get patterns attached to an entity by @derive."""
    return getattr(entity, DERIVE_PATTERNS_KEY, ())


def get_exposures(entity: type) -> tuple[Exposure, ...]:
    """Get direct exposures attached to an entity by @derive."""
    return getattr(entity, DERIVE_EXPOSURES_KEY, ())


def get_derivations(entity: type) -> tuple[ExposureT, ...]:
    """Get derivations attached to an entity by @derive."""
    return getattr(entity, DERIVE_DERIVATIONS_KEY, ())


# ═══════════════════════════════════════════════════════════════════════════════
# Internal: Compile pattern → Endpoint via fold
# ═══════════════════════════════════════════════════════════════════════════════


def _compile_pattern[EntityT](
    entity: type[EntityT],
    pattern: Pattern,
) -> Endpoint:
    """Compile a single pattern through fold_derive + materialize."""
    derivation = pattern.compile(entity)
    ctx = fold_derive(derivation, entity)
    return materialize(ctx)


# ═══════════════════════════════════════════════════════════════════════════════
# Derivation Functions
# ═══════════════════════════════════════════════════════════════════════════════


def derive_application(
    *pairs: tuple[type, Pattern],
) -> list[Endpoint]:
    """Compile entity-pattern pairs.

    Pipeline: Pattern.compile() → Derivation → fold_derive → materialize → Endpoint

    Example:
        endpoints = derive_application(
            (User, http_crud("/api/users", provider_node=UserProvider)),
        )
    """
    result: list[Endpoint] = []
    for entity, pattern in pairs:
        result.append(_compile_pattern(entity, pattern))
    return result


def derive_endpoints(
    entity: type,
    *patterns: Pattern,
) -> list[Endpoint]:
    """Compile patterns for a single entity.

    Example:
        endpoints = derive_endpoints(
            User,
            http_crud("/api/users", provider_node=UserProvider),
        )
    """
    result: list[Endpoint] = []
    for pattern in patterns:
        result.append(_compile_pattern(entity, pattern))
    return result


def derive_from_decorated(
    *entities: type,
    patterns: tuple[type[Pattern], ...] | None = None,
) -> list[Endpoint]:
    """Compile patterns from @derive decorated entities.

    Args:
        *entities: Entity classes decorated with @derive
        patterns: Optional tuple of pattern types to compile. If None, compile ALL patterns.

    Example:
        @derive(http_crud("/api/users", provider_node=UserProvider))
        @dataclass
        class User: ...

        endpoints = derive_from_decorated(User)
    """
    result: list[Endpoint] = []
    for entity in entities:
        all_patterns = get_patterns(entity)
        direct_exposures = get_exposures(entity)
        derivations = get_derivations(entity)

        # Filter patterns if requested
        if patterns is not None:
            selected_patterns = tuple(
                p for p in all_patterns
                if any(isinstance(p, pattern_type) for pattern_type in patterns)
            )
        else:
            selected_patterns = all_patterns

        for pattern in selected_patterns:
            endpoint = _compile_pattern(entity, pattern)

            # Apply ExposureT derivations to materialized exposures
            if derivations:
                transform = _compose(*derivations)
                new_exposures = [transform(e) for e in endpoint.exposures]
                endpoint = Endpoint(runner=endpoint.runner, exposures=new_exposures)

            result.append(endpoint)

        # Handle direct exposures (without runner)
        if direct_exposures:
            exposures = list(direct_exposures)
            if derivations:
                transform = _compose(*derivations)
                exposures = [transform(e) for e in exposures]
            result.append(Endpoint(runner=empty_runner(), exposures=exposures))

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
    *pairs: tuple[type, Pattern],
) -> Application:
    """Build Application from entity-pattern pairs.

    Example:
        app = build_application(
            (User, http_crud("/api/users", provider_node=UserProvider)),
        )
        fastapi_app = fastapi.compile(app)
    """
    return _endpoints_to_app(derive_application(*pairs))


def build_endpoint(
    entity: type,
    pattern: Pattern,
) -> Endpoint:
    """Build single Endpoint from entity + pattern."""
    return _compile_pattern(entity, pattern)


def build_application_from_decorated(
    *entities: type,
    patterns: tuple[type[Pattern], ...] | None = None,
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
    # Pattern Protocol
    "Pattern",
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
    # Keys (internal)
    "DERIVE_PATTERNS_KEY",
    "DERIVE_EXPOSURES_KEY",
    "DERIVE_DERIVATIONS_KEY",
)
