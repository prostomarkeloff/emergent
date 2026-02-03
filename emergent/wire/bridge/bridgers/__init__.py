"""Bridge bridgers — framework-specific extraction (like compile/targets/).

Each bridger knows ALL patterns of its framework and provides:
- Scanner: how to find routes/handlers
- Capabilities: framework-specific transformation capabilities
- Triggers: how to build wire Triggers from framework routes

    from emergent.wire.bridge.bridgers import fastapi, asgi
    from emergent.wire.bridge.bridgers._base import AddTrigger

    wire_app = fastapi.extract(legacy_app, capabilities=(...))
"""

from emergent.wire.bridge.bridgers import asgi, fastapi
from emergent.wire.bridge.bridgers._base import AddTrigger

__all__ = ("asgi", "fastapi", "AddTrigger")
