"""Shared execution pipeline for target compilation.

All smart logic (scope, extract, coerce, enrichers, execute) lives here.
Assemblers are DUMB — they just wrap execute_with_pipeline in a framework route.

    from emergent.wire.compile._pipeline import (
        CompiledPipeline, compile_pipeline, execute_with_pipeline,
    )

    # In assembler (3 lines):
    compiled = compile_pipeline(ctx, axes)
    async def _route(request):
        return await execute_with_pipeline(compiled, handler, axes, request)
    return FastAPIRoute(endpoint=_route, ...)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Protocol, TYPE_CHECKING

from nodnod import Scope

if TYPE_CHECKING:
    from emergent.wire.axis._capability import CoercionSpec
    from emergent.wire.axis.surface._handler import Handler
    from emergent.wire.compile._core import Axes
    from emergent.wire.compile._lifetime import ScopeLayer

logger = logging.getLogger("emergent.compile.pipeline")


# ═══════════════════════════════════════════════════════════════════════════════
# Extractor Protocol — extract raw dict from framework request
# ═══════════════════════════════════════════════════════════════════════════════


class Extractor(Protocol):
    """Extract raw dict from framework request object."""

    async def extract(self, request: object) -> dict[str, object]: ...


# ═══════════════════════════════════════════════════════════════════════════════
# CompiledPipeline — pre-compiled context ready to execute
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class CompiledPipeline:
    """WrapContext with coercion model pre-built. Ready to execute.

    Built at compile time by compile_pipeline(). Used at request time
    by execute_with_pipeline().

    Fields:
        execute: Codec-specific execution function (handler, scope, get_value) → response
        extractor: Framework-specific request extractor (or None for codecs without extraction)
        coerce_model: Pre-compiled coercion model type (or None)
        coercion: CoercionSpec for validation (or None)
        inject_type: Type to inject raw_request as into scope (e.g. fastapi.Request)
        error_type: Exception type for validation errors (or None)
    """

    execute: Callable[..., Any]
    extractor: Extractor | None = None
    coerce_model: type | None = None
    coercion: CoercionSpec | None = None
    inject_type: type = type(None)
    error_type: type | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# compile_pipeline — build coercion model at compile time
# ═══════════════════════════════════════════════════════════════════════════════


def compile_pipeline(ctx: object, axes: Axes) -> CompiledPipeline:
    """Build CompiledPipeline from WrapContext at compile time.

    Reads fields from ctx via getattr (WrapContext is target-specific).
    Compiles coercion model if both coercion and request_type are present.

    This is the compile-time step — happens once per endpoint, not per request.
    """
    coercion = getattr(ctx, "coercion", None)
    request_type = getattr(ctx, "request_type", None)

    coerce_model: type | None = None
    if coercion is not None and request_type is not None:
        ec = coercion.compiler.compile(request_type, axes)
        coerce_model = coercion.assemble(request_type, ec)

    execute_fn: Callable[..., Any] | None = getattr(ctx, "execute", None)
    if execute_fn is None:
        raise TypeError(
            f"WrapContext {type(ctx).__qualname__} has no 'execute' attribute — "
            f"cannot build CompiledPipeline"
        )

    return CompiledPipeline(
        execute=execute_fn,
        extractor=getattr(ctx, "extractor", None),
        coerce_model=coerce_model,
        coercion=coercion,
        inject_type=getattr(ctx, "inject_type", type(None)),
        error_type=getattr(ctx, "error_type", None),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Scope helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_scope(layer: ScopeLayer | None, detail: str = "handler") -> Scope:
    """Create child scope from layer, or fresh Scope."""
    if layer:
        return layer.parent.create_child(detail)
    return Scope()


def _family_mapped(layer: ScopeLayer | None, scope: Scope) -> dict[type, Scope]:
    """Compute mapped_scopes from layer's family."""
    if layer is None:
        return {}
    return dict(layer.family.materialize({**layer.scopes, layer.leaf: scope}))


# ═══════════════════════════════════════════════════════════════════════════════
# execute_with_pipeline — shared request-time execution
# ═══════════════════════════════════════════════════════════════════════════════


async def execute_with_pipeline(
    compiled: CompiledPipeline,
    handler: Handler[Any],
    axes: Axes,
    raw_request: object,
    target: str | None = None,
) -> object:
    """Shared: scope → inject → extract → coerce → enrichers → execute.

    Used by ALL assemblers. The assembler just wraps this in a route closure.

    Pipeline:
        1. Create scope (from axes.scope_layer or fresh)
        2. Inject raw_request by inject_type
        3. Compose family-scoped nodes (if layer configured)
        4. Extract raw dict from request (if extractor present)
        5. Coerce raw dict through validation model (if coercion present)
        6. Fold handler runtime capabilities (enrichers)
        7. Call compiled.execute(handler, scope, get_value)
    """
    from emergent.wire.axis.surface.enrichers import chain_enrichers
    from emergent.wire.compile._capabilities import fold_handler_runtime

    layer = axes.scope_layer
    scope = _make_scope(layer)
    try:
        async with scope:
            # 1. Inject framework request
            if compiled.inject_type is not type(None):
                scope.inject(compiled.inject_type, raw_request)

            # 2. Compose family-scoped nodes
            mapped = _family_mapped(layer, scope)
            if layer and layer.compose:
                from emergent.graph._compose import Composer

                composer = Composer.create(scope, mapped_scopes=mapped)
                await composer.compose_batch(set(layer.compose))

            # 3. Extract raw dict
            get_value: Callable[[str], object] | None = None
            if compiled.extractor is not None:
                raw = await compiled.extractor.extract(raw_request)

                # 4. Coerce through validation model
                if compiled.coercion is not None and compiled.coerce_model is not None:
                    try:
                        coerced = compiled.coercion.validate(compiled.coerce_model, raw)
                    except Exception as e:
                        if compiled.error_type is not None:
                            errors_fn = getattr(e, "errors", lambda: [{"msg": str(e)}])
                            raise compiled.error_type(errors_fn()) from e
                        raise
                else:
                    coerced = raw

                get_value = coerced.get  # type: ignore[union-attr]

            # 5. Execute with enrichers
            rt_ctx = fold_handler_runtime(handler.capabilities)

            async def core(s: Scope) -> object:
                return await compiled.execute(handler, s, get_value)

            if rt_ctx.enrichers:
                return await chain_enrichers(rt_ctx.enrichers, core, target=target)(scope)
            return await core(scope)
    except Exception:
        logger.exception("Pipeline execution failed for %s", type(handler.codec).__name__)
        raise


__all__ = (
    "Extractor",
    "CompiledPipeline",
    "compile_pipeline",
    "execute_with_pipeline",
)
