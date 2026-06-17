"""Request pipeline capabilities — Coercion + Extraction.

Capabilities carry framework-specific compile_*_pipeline methods (same pattern
as MaxLen carrying compile_pydantic + compile_openapi + compile_sqlalchemy).

    from emergent.wire.axis.surface.capabilities._pipeline import (
        Coercion, Extraction, PYDANTIC, NO_COERCION,
        EXTRACT_FORM, EXTRACT_JSON, EXTRACT_QUERY,
    )

    # Swap coercion per-endpoint
    endpoint(runner).expose(trigger, rrc(Req, Resp), MSGSPEC)

    # Swap extraction
    endpoint(runner).expose(trigger, rrc(Req, Resp), EXTRACT_FORM)
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Protocol, TYPE_CHECKING, runtime_checkable

from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
from emergent.wire.axis._capability import CoercionSpec

if TYPE_CHECKING:
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Coercion capability — ONE class, parameterized by CoercionSpec
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Coercion(SurfaceCapability):
    """Request coercion strategy. Capabilities carry framework-specific impls.

    Use pre-built constants (PYDANTIC, NO_COERCION) or build custom::

        MY_COERCION = Coercion(CoercionSpec(
            compiler=SchemaCompiler(phases=(MY_PHASE,)),
            assemble=my_assemble,
            validate=my_validate,
        ))
        endpoint(runner).expose(trigger, rrc(Req, Resp), MY_COERCION)
    """

    spec: CoercionSpec | None  # None = no coercion

    def compile_fastapi_pipeline(self, ctx: Any) -> Any:
        """Set coercion on FastAPI pipeline context."""
        return replace(ctx, coercion=self.spec)

    def compile_cli_pipeline(self, ctx: Any) -> Any:
        """Set coercion on CLI pipeline context."""
        return replace(ctx, coercion=self.spec)

    def compile_telegram_pipeline(self, ctx: Any) -> Any:
        """Set coercion on Telegram pipeline context."""
        return replace(ctx, coercion=self.spec)


# ═══════════════════════════════════════════════════════════════════════════════
# Extraction capability — ONE class, parameterized per framework
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Extraction(SurfaceCapability):
    """Request extraction strategy. Per-framework extractors.

    Use pre-built constants (EXTRACT_FORM, EXTRACT_JSON, EXTRACT_QUERY)
    or build custom::

        MY_EXTRACTION = Extraction(fastapi=MyCustomExtractor())
        endpoint(runner).expose(trigger, rrc(Req, Resp), MY_EXTRACTION)
    """

    # Per-framework extractors. Each is a frozen dataclass with async extract() method.
    # None = don't override (use framework default).
    fastapi: object | None = None
    cli: object | None = None
    telegram: object | None = None
    testing: object | None = None
    event: object | None = None

    def compile_fastapi_pipeline(self, ctx: Any) -> Any:
        """Set extractor on FastAPI pipeline context."""
        if self.fastapi is not None:
            return replace(ctx, extractor=self.fastapi)
        return ctx

    def compile_cli_pipeline(self, ctx: Any) -> Any:
        """Set extractor on CLI pipeline context."""
        if self.cli is not None:
            return replace(ctx, extractor=self.cli)
        return ctx

    def compile_telegram_pipeline(self, ctx: Any) -> Any:
        """Set extractor on Telegram pipeline context."""
        if self.telegram is not None:
            return replace(ctx, extractor=self.telegram)
        return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-built constants — lazy to avoid circular imports
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class _CoercionSpecFactory(Protocol):
    def __call__(self) -> CoercionSpec: ...


def _get_pydantic_coercion() -> CoercionSpec:
    import emergent.wire.compile._generate as _gen

    # _pydantic_coercion is exported in _generate.__all__ despite the underscore
    # prefix. Read it from the module namespace (not reflection builtins) and
    # structurally verify it before calling — avoids reportPrivateUsage without a
    # cross-module rename of the definer.
    factory = _gen.__dict__.get("_pydantic_coercion")
    if not isinstance(factory, _CoercionSpecFactory):
        msg = "emergent.wire.compile._generate._pydantic_coercion is unavailable"
        raise RuntimeError(msg)
    return factory()


# Mutable holder — avoids pyright "constant redefinition" for uppercase names.
_pydantic_holder: Coercion = Coercion(spec=None)  # placeholder, initialized lazily

NO_COERCION: Coercion = Coercion(spec=None)

# Declared for static analysis; resolved at runtime via __getattr__ below.
PYDANTIC: Coercion


def __getattr__(name: str) -> Coercion:
    """Module-level __getattr__ for lazy PYDANTIC initialization."""
    if name == "PYDANTIC":
        global _pydantic_holder
        if _pydantic_holder.spec is None:
            spec = _get_pydantic_coercion()
            _pydantic_holder = Coercion(spec=spec)
        return _pydantic_holder
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


# EXTRACT_FORM, EXTRACT_JSON, EXTRACT_QUERY are created by framework targets
# (they depend on framework-specific extractor types).
# See targets/fastapi.py for FastAPI versions.


__all__ = (
    "Coercion",
    "Extraction",
    "PYDANTIC",
    "NO_COERCION",
)
