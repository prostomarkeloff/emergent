"""Bridge registry — open-world framework detection.

FrameworkBridger bundles everything needed to bridge FROM one framework.
BridgeRegistry holds an open set of bridgers.
No isinstance chains, no hardcoded lists.

    from emergent.wire.bridge._registry import FrameworkBridger, BridgeRegistry

    # Extend with new framework — zero emergent changes
    my_registry = get_default_registry().with_bridger(DJANGO_BRIDGER)
    wire_app = build_application(django_app, registry=my_registry)

    # Swap existing bridger
    custom = get_default_registry().replace_bridger("fastapi", MY_FASTAPI_BRIDGER)

    # Strip down
    minimal = get_default_registry().without_bridger("fastapi")
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from emergent.wire.bridge._extractor import Extractor
    from emergent.wire.bridge._to_wire import ToWire
    from emergent.wire.bridge._types import RouteData


# ═══════════════════════════════════════════════════════════════════════════════
# FrameworkBridger — one framework's bridge configuration
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FrameworkBridger:
    """How to bridge FROM one framework — all pieces bundled.

    Pairs framework detection with extraction and conversion.
    Immutable value. Symmetric to CodecBinding in compile/_target.py.

    Attributes:
        name: Human-readable identifier ("fastapi", "django", etc.)
        can_bridge: Predicate — is this source from my framework?
        extractor: Composed extractor for all route types
        to_wire: Composed ToWire converter for all route types
    """

    name: str
    can_bridge: Callable[[object], bool]
    extractor: Extractor[RouteData]
    to_wire: ToWire[RouteData]


# ═══════════════════════════════════════════════════════════════════════════════
# BridgeRegistry — open-world set of framework bridgers
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class BridgeRegistry:
    """Open-world set of framework bridgers.

    Immutable. Derive new registries via .with_bridger() / .replace_bridger() / .without_bridger().
    Detection is first-match: iterate bridgers in order, first can_bridge() wins.

    Symmetric to TargetCompiler in compile/_target.py.

    Example:
        DEFAULT_REGISTRY = BridgeRegistry(bridgers=(FASTAPI_BRIDGER,))

        # User extends
        my_registry = DEFAULT_REGISTRY.with_bridger(DJANGO_BRIDGER)
    """

    bridgers: tuple[FrameworkBridger, ...]

    def detect(self, source: Any) -> FrameworkBridger | None:
        """Find first bridger that can handle this source.

        Returns None if no bridger matches — caller decides error handling.
        """
        for bridger in self.bridgers:
            if bridger.can_bridge(source):
                return bridger
        return None

    def with_bridger(self, bridger: FrameworkBridger) -> BridgeRegistry:
        """Add bridger. Returns NEW registry."""
        return replace(self, bridgers=(*self.bridgers, bridger))

    def replace_bridger(
        self,
        name: str,
        bridger: FrameworkBridger,
    ) -> BridgeRegistry:
        """Swap bridger by name. Returns NEW registry."""
        new_bridgers = tuple(
            bridger if b.name == name else b for b in self.bridgers
        )
        return replace(self, bridgers=new_bridgers)

    def without_bridger(self, name: str) -> BridgeRegistry:
        """Remove bridger by name. Returns NEW registry."""
        return replace(
            self,
            bridgers=tuple(b for b in self.bridgers if b.name != name),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Default Registry — lazy singleton
# ═══════════════════════════════════════════════════════════════════════════════


def _build_default_registry() -> BridgeRegistry:
    """Build default registry with auto-detected frameworks.

    try/except ImportError lives ONCE here — not triplicated.
    """
    bridgers: list[FrameworkBridger] = []

    try:
        from emergent.wire.bridge.bridgers.fastapi import FASTAPI_BRIDGER

        bridgers.append(FASTAPI_BRIDGER)
    except ImportError:
        pass

    return BridgeRegistry(bridgers=tuple(bridgers))


_default_registry: BridgeRegistry | None = None


def get_default_registry() -> BridgeRegistry:
    """Get the default registry (lazy, cached).

    Function rather than module-level constant to avoid
    import-time side effects (importing fastapi at module load).
    """
    global _default_registry
    if _default_registry is None:
        _default_registry = _build_default_registry()
    return _default_registry


__all__ = (
    "FrameworkBridger",
    "BridgeRegistry",
    "get_default_registry",
)
