"""Derivation core types.

Derivation = tuple of steps. DerivationT = Derivation → Derivation.

    from derivelib._derivation import Derivation, DerivationT, Step
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from derivelib._protocols import (
        SchemaDerivable,
        QueryDerivable,
        StorageDerivable,
        SurfaceDerivable,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Core Types
# ═══════════════════════════════════════════════════════════════════════════════


# Step = union of axis protocols. A derivation step must implement at least one
# derive_* method. fold_derive dispatches on isinstance against each protocol.
type Step = SchemaDerivable | QueryDerivable | StorageDerivable | SurfaceDerivable

# Derivation: ordered tuple of steps
type Derivation = tuple[Step, ...]

# DerivationT: higher-order — transforms step lists
type DerivationT = Callable[[Derivation], Derivation]


__all__ = (
    "Derivation",
    "DerivationT",
)
