"""Bridge bridgers — framework-specific extraction (like compile/targets/).

Each bridger knows ALL patterns of its framework and provides:
- Scanner: how to find routes/handlers
- Capabilities: framework-specific transformation capabilities
- Triggers: how to build wire Triggers from framework routes

    from emergent.wire.bridge.bridgers import fastapi, asgi
    from emergent.wire.bridge.bridgers._base import AddTrigger

    wire_app = build_application(legacy_app, capabilities=(...))
"""

from emergent.wire.bridge.bridgers._base import AddTrigger

__all__: list[str] = ["AddTrigger"]

# ASGI (no external deps)
from emergent.wire.bridge.bridgers import asgi as asgi

__all__.append("asgi")

# FastAPI (optional)
try:
    from emergent.wire.bridge.bridgers import fastapi as fastapi
    from emergent.wire.bridge.bridgers.fastapi import FASTAPI_BRIDGER as FASTAPI_BRIDGER

    __all__.append("fastapi")
    __all__.append("FASTAPI_BRIDGER")
except ImportError:
    pass
