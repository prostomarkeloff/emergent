"""Bridge axes — explicit context for extraction.

Symmetric to compile.Axes — enables extensibility without global state.

    from emergent.wire.bridge import BridgeAxes, build_application

    # Default axes (auto-detection via registry)
    wire_app = build_application(fastapi_app)

    # Custom registry
    from emergent.wire.bridge._registry import get_default_registry
    my_registry = get_default_registry().with_bridger(DJANGO_BRIDGER)
    axes = BridgeAxes(schema=my_inspector, registry=my_registry)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from emergent.wire.axis.schema._inspect import FieldInfo
    from emergent.wire.bridge._registry import BridgeRegistry
    from emergent.wire.bridge._signature import HandlerSignature


# ═══════════════════════════════════════════════════════════════════════════════
# Bridge Axes
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class BridgeAxes:
    """Bridge-specific axes for extraction and conversion.

    Symmetric to compile.Axes — explicit context, no global state.
    Registry handles framework detection (open-world).

    Attributes:
        schema: Type inspector for structured types (dataclass, Pydantic, etc.).
        signature_analyzer: Handler signature analyzer.
        registry: Optional BridgeRegistry override.
                  If None, get_default_registry() is used at call time.
    """

    schema: Callable[[type], dict[str, FieldInfo]]
    signature_analyzer: Callable[[Callable[..., object]], HandlerSignature]
    registry: BridgeRegistry | None = None

    @classmethod
    def default(cls) -> BridgeAxes:
        """Create BridgeAxes with default settings.

        Uses auto-detection via BridgeRegistry for framework detection.
        """
        from emergent.wire.axis.schema import inspect_type
        from emergent.wire.bridge._signature import analyze_signature

        return cls(
            schema=inspect_type,
            signature_analyzer=analyze_signature,
        )

    @classmethod
    def for_fastapi(cls) -> BridgeAxes:
        """Create BridgeAxes with FastAPI bridger pinned.

        .. deprecated::
            Use BridgeAxes.default() instead — the registry
            auto-detects FastAPI. This method is retained for
            backwards compatibility.
        """
        from emergent.wire.axis.schema import inspect_type
        from emergent.wire.bridge._registry import BridgeRegistry
        from emergent.wire.bridge._signature import analyze_signature
        from emergent.wire.bridge.bridgers.fastapi import FASTAPI_BRIDGER

        return cls(
            schema=inspect_type,
            signature_analyzer=analyze_signature,
            registry=BridgeRegistry(bridgers=(FASTAPI_BRIDGER,)),
        )


__all__ = ("BridgeAxes",)
