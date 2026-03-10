"""Adaptation — removed in derivelib proxy.

Use emergent.wire.derive directly for capability-aware adaptation.
derivelib will be removed in emergent 1.0.0.
"""

_MSG = (
    "derivelib.adapt has been removed. "
    "Use emergent.wire.derive directly for capability-aware adaptation. "
    "derivelib will be removed in emergent 1.0.0."
)


def __getattr__(name: str) -> object:
    raise ImportError(_MSG)
