"""FastAPI bridger — extract FastAPI apps to wire Application.

    from emergent.wire.bridge.bridgers import fastapi

    # Extract app
    wire_app = fastapi.extract(legacy_app)

    # Use FastAPI-specific capabilities
    wire_app = fastapi.extract(
        legacy_app,
        capabilities=(
            fastapi.capabilities.MapDepends({get_db: test_db}),
        ),
    )
"""

from emergent.wire.bridge.bridgers.fastapi import _capabilities as capabilities
from emergent.wire.bridge.bridgers.fastapi._extract import extract
from emergent.wire.bridge.bridgers.fastapi._scanner import (
    FastAPIAppProtocol,
    FastAPIInspector,
    FastAPIRouterProtocol,
)
from emergent.wire.bridge.bridgers.fastapi._triggers import (
    FastAPITriggerBuilder,
    FastAPITriggerData,
)

__all__ = (
    # Main entry point
    "extract",
    # Capabilities module
    "capabilities",
    # Types
    "FastAPITriggerData",
    "FastAPIAppProtocol",
    "FastAPIRouterProtocol",
    # Inspector
    "FastAPIInspector",
    # Builder
    "FastAPITriggerBuilder",
)
