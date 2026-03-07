"""Derivation protocols — dispatch targets for compile_derive.

Three protocols for the three-phase derive fold:

  DeriveGeneratable  — capabilities that GENERATE endpoints (e.g., CRUD)
  DeriveModifiable   — capabilities that MODIFY generated endpoints (e.g., Paginated, SoftDelete)
  DeriveAugmentable  — capabilities that AUGMENT after modification (e.g., backlinks)

    from emergent.wire.derive import DeriveGeneratable, DeriveModifiable, DeriveAugmentable
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable, TYPE_CHECKING

if TYPE_CHECKING:
    from emergent.wire.derive._ctx import DeriveCtx


@runtime_checkable
class DeriveGeneratable(Protocol):
    """Schema-level capability that GENERATES endpoints.

    Phase 1 of compile_derive. Capabilities implementing this protocol
    produce OpSpecs from entity schema (e.g., CRUD generates 6 endpoints).

    fold_schema folds these via compile_derive_generate.
    """

    def compile_derive_generate(self, ctx: "DeriveCtx") -> "DeriveCtx": ...


@runtime_checkable
class DeriveModifiable(Protocol):
    """Schema-level capability that MODIFIES generated endpoints.

    Phase 2 of compile_derive. Capabilities implementing this protocol
    transform OpSpecs produced by Phase 1 (e.g., Paginated replaces
    FetchMany handler, SoftDelete replaces Delete handler).

    fold_schema folds these via compile_derive_modify.
    """

    def compile_derive_modify(self, ctx: "DeriveCtx") -> "DeriveCtx": ...


@runtime_checkable
class DeriveAugmentable(Protocol):
    """Schema-level capability that AUGMENTS after modification.

    Phase 3 of compile_derive. Can generate additional specs
    based on the already-modified set (e.g., NestedCRUD adding
    backlinks to parent after child CRUD is set up).

    fold_schema folds these via compile_derive_augment.
    """

    def compile_derive_augment(self, ctx: "DeriveCtx") -> "DeriveCtx": ...


__all__ = (
    "DeriveGeneratable",
    "DeriveModifiable",
    "DeriveAugmentable",
)
