"""compile_derive — three-phase derivation via fold_schema.

    from emergent.wire.derive import compile_derive, materialize

    @schema_meta(CRUD("/users", Users), Paginated(20))
    @dataclass
    class User:
        id: Annotated[int, Identity]
        name: str

    ctxs = compile_derive(User)
    endpoints = [materialize(ctx) for ctx in ctxs]

Multiple generators (e.g. http_crud + cli_crud) are compiled independently:

    @schema_meta(http_crud("/products", Store), cli_crud("product", Store))
    @dataclass
    class Product: ...

    ctxs = compile_derive(Product)  # [http_ctx, cli_ctx]
"""

from __future__ import annotations

from typing import Any

from emergent.wire.axis.schema._universal import get_schema_meta
from emergent.wire.compile._core import fold, fold_schema
from emergent.wire.derive._ctx import DeriveCtx
from emergent.wire.derive._protocols import (
    DeriveAugmentable,
    DeriveGeneratable,
    DeriveModifiable,
)


def _validate_specs[EntityT](ctx: DeriveCtx[EntityT]) -> None:
    """Check for duplicate spec names after a generate phase.

    Same op name with different triggers is valid (multi-target: HTTP + Telegram).
    Only reject true duplicates: same name + same trigger type + same source.
    """
    seen: dict[tuple[str, str, type], str] = {}
    for spec in ctx.specs:
        key = (spec.entity_name, spec.name, type(spec.trigger))
        if key in seen and seen[key] == spec.source:
            raise ValueError(
                f"Conflict: spec '{spec.name}' for '{spec.entity_name}' "
                f"generated twice by '{spec.source}'"
            )
        seen[key] = spec.source


def _make_ctx[EntityT](cls: type[EntityT]) -> DeriveCtx[EntityT]:
    """Create initial DeriveCtx from entity or plain class."""
    try:
        return DeriveCtx.from_entity(cls)
    except TypeError:
        return DeriveCtx.from_subject(cls)


def compile_derive[EntityT](cls: type[EntityT]) -> list[DeriveCtx[EntityT]]:
    """Three-phase derive compilation.

    Phase 1: DeriveGeneratable — CRUD generates OpSpecs
    Phase 2: DeriveModifiable  — Paginated/SoftDelete transform specs
    Phase 3: DeriveAugmentable — post-modification augmentation

    Multiple independent generators (e.g. http_crud + cli_crud) are
    compiled into separate DeriveCtx automatically. Shared modifiers
    and augmenters are applied to each context.

    Returns list[DeriveCtx] — one per generator group.
    Single generator → single-element list. Zero generators → single empty ctx.
    """
    caps = get_schema_meta(cls)

    generators: list[DeriveGeneratable] = []
    others: list[Any] = []
    for cap in caps:
        if isinstance(cap, DeriveGeneratable):
            generators.append(cap)
        else:
            others.append(cap)

    if len(generators) <= 1:
        # 0-1 generators — single fold, standard path
        ctx: DeriveCtx[EntityT] = _make_ctx(cls)
        ctx = fold_schema(cls, ctx, DeriveGeneratable, "compile_derive_generate")
        _validate_specs(ctx)
        ctx = fold_schema(cls, ctx, DeriveModifiable, "compile_derive_modify")
        ctx = fold_schema(cls, ctx, DeriveAugmentable, "compile_derive_augment")
        return [ctx]

    # Multiple generators — each gets its own DeriveCtx
    results: list[DeriveCtx[EntityT]] = []
    for gen in generators:
        ctx = _make_ctx(cls)

        # Phase 1: generate — only this generator
        ctx = gen.compile_derive_generate(ctx)
        _validate_specs(ctx)

        # Phase 2+3: modify & augment — generator itself + shared caps
        group: list[Any] = [gen, *others]
        ctx = fold(group, ctx, DeriveModifiable, "compile_derive_modify")
        ctx = fold(group, ctx, DeriveAugmentable, "compile_derive_augment")

        results.append(ctx)

    return results


__all__ = ("compile_derive",)
