"""Scoped — bind modifiers to a specific generator.

With multiple generators, all modifiers apply to ALL generators.
Scoped lets you restrict modifiers to one generator explicitly:

    @schema_meta(
        scoped(
            http_crud("/users", Users, ops=(LIST, GET, CREATE)),
            ProjectResponse(exclude=("secret",)),
        ),
        scoped(
            http_crud("/users/me", Users, ops=(GET,)),
            Authenticated(BearerExtract(), validate),
        ),
        LoginOp("/login", ...),
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from emergent.wire.axis.schema._universal import SchemaCapability
from emergent.wire.compile._core import fold
from emergent.wire.derive._protocols import (
    DeriveAugmentable,
    DeriveGeneratable,
    DeriveModifiable,
)

if TYPE_CHECKING:
    from emergent.wire.derive._ctx import DeriveCtx


@dataclass(frozen=True, slots=True)
class Scoped(SchemaCapability):
    """Scope modifiers to a specific generator.

    Wraps a DeriveGeneratable with local DeriveModifiable/DeriveAugmentable
    caps that apply only to the specs produced by that generator.

        Scoped(http_crud("/users", Users), (ProjectResponse(exclude=("secret",)),))
        scoped(http_crud("/users", Users), ProjectResponse(exclude=("secret",)))
    """

    generator: SchemaCapability
    caps: tuple[SchemaCapability, ...]

    def compile_derive_generate(self, ctx: DeriveCtx) -> DeriveCtx:  # type: ignore[type-arg]
        # Phase 1: delegate to inner generator
        gen: DeriveGeneratable = self.generator  # type: ignore[assignment]
        ctx = gen.compile_derive_generate(ctx)

        # Apply scoped modifiers and augmenters
        caps_list = list(self.caps)
        ctx = fold(caps_list, ctx, DeriveModifiable, "compile_derive_modify")
        ctx = fold(caps_list, ctx, DeriveAugmentable, "compile_derive_augment")
        return ctx


def scoped(generator: SchemaCapability, *caps: SchemaCapability) -> Scoped:
    """Scope modifiers to a specific generator.

        @schema_meta(
            scoped(http_crud("/users", Users), ProjectResponse(exclude=("secret",))),
            scoped(http_crud("/users/me", Users, ops=(GET,)), Authenticated(...)),
        )
    """
    return Scoped(generator=generator, caps=caps)


__all__ = ("Scoped", "scoped")
