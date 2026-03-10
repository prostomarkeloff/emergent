"""Compatibility bridge — chainable wrapper over wire.derive capabilities.

Bridges derivelib's `http_crud(...).chain(readonly(), paginated(20))` API
to wire.derive's flat SchemaCapability model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from emergent.wire.axis.schema._universal import SchemaCapability
from emergent.wire.derive._ctx import DeriveCtx


@dataclass(frozen=True, slots=True)
class ChainableCapability(SchemaCapability):
    """Wraps a wire.derive SchemaCapability with .chain() support.

    Implements both DeriveGeneratable and DeriveModifiable by delegation:
    - compile_derive_generate delegates to inner capability
    - compile_derive_modify applies chained transform capabilities in order
    """

    inner: SchemaCapability = field(default_factory=SchemaCapability)
    transforms: tuple[SchemaCapability, ...] = ()

    def chain(self, *caps: SchemaCapability) -> ChainableCapability:
        """Chain additional capabilities (from transform functions).

        Returns a new ChainableCapability with transforms appended.
        """
        return ChainableCapability(
            inner=self.inner,
            transforms=(*self.transforms, *caps),
        )

    def compile_derive_generate(self, ctx: DeriveCtx[object]) -> DeriveCtx[object]:
        if hasattr(self.inner, "compile_derive_generate"):
            return self.inner.compile_derive_generate(ctx)
        return ctx

    def compile_derive_modify(self, ctx: DeriveCtx[object]) -> DeriveCtx[object]:
        if hasattr(self.inner, "compile_derive_modify"):
            ctx = self.inner.compile_derive_modify(ctx)
        for t in self.transforms:
            if hasattr(t, "compile_derive_modify"):
                ctx = t.compile_derive_modify(ctx)
        return ctx

    def compile_derive_augment(self, ctx: DeriveCtx[object]) -> DeriveCtx[object]:
        if hasattr(self.inner, "compile_derive_augment"):
            return self.inner.compile_derive_augment(ctx)
        return ctx
