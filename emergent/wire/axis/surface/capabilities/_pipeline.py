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
from typing import TYPE_CHECKING

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

    def compile_fastapi_pipeline(self, ctx: object) -> object:
        """Set coercion on FastAPI pipeline context."""
        return replace(ctx, coercion=self.spec)  # type: ignore[arg-type]

    def compile_cli_pipeline(self, ctx: object) -> object:
        """Set coercion on CLI pipeline context."""
        return replace(ctx, coercion=self.spec)  # type: ignore[arg-type]

    def compile_telegram_pipeline(self, ctx: object) -> object:
        """Set coercion on Telegram pipeline context."""
        return replace(ctx, coercion=self.spec)  # type: ignore[arg-type]


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

    def compile_fastapi_pipeline(self, ctx: object) -> object:
        """Set extractor on FastAPI pipeline context."""
        if self.fastapi is not None:
            return replace(ctx, extractor=self.fastapi)  # type: ignore[arg-type]
        return ctx

    def compile_cli_pipeline(self, ctx: object) -> object:
        """Set extractor on CLI pipeline context."""
        if self.cli is not None:
            return replace(ctx, extractor=self.cli)  # type: ignore[arg-type]
        return ctx

    def compile_telegram_pipeline(self, ctx: object) -> object:
        """Set extractor on Telegram pipeline context."""
        if self.telegram is not None:
            return replace(ctx, extractor=self.telegram)  # type: ignore[arg-type]
        return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-built constants — lazy to avoid circular imports
# ═══════════════════════════════════════════════════════════════════════════════


def _get_pydantic_coercion() -> CoercionSpec:
    from emergent.wire.compile._generate import _pydantic_coercion

    return _pydantic_coercion()


# Will be populated when framework extractors are available
PYDANTIC = Coercion(spec=None)  # placeholder, set properly below
NO_COERCION = Coercion(spec=None)


def _init_constants() -> None:
    """Initialize pre-built constants. Called lazily on first use."""
    global PYDANTIC
    spec = _get_pydantic_coercion()
    # Frozen dataclass — need to create new instance
    PYDANTIC = Coercion(spec=spec)


# EXTRACT_FORM, EXTRACT_JSON, EXTRACT_QUERY are created by framework targets
# (they depend on framework-specific extractor types).
# See targets/fastapi.py for FastAPI versions.


__all__ = (
    "Coercion",
    "Extraction",
    "PYDANTIC",
    "NO_COERCION",
)
