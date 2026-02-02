"""Bridge axis — Framework → Application extraction.

Bridges extract handlers from existing frameworks and convert them
to wire Application for migration or unification.

Structure mirrors compile/:
- compile/targets: Application → Framework (OUT)
- bridge/sources:  Framework → BridgeResult (IN)

```python
from emergent.wire.bridge import sources, capabilities as BC

# Extract from FastAPI
result = sources.fastapi(
    existing_app,
    capabilities=(
        BC.SkipDeprecated(),
        BC.AddCapability(C.enricher.Timeout(seconds=30)),
        BC.IsolateGlobal(
            module_path="app.db",
            attr_name="session",
            factory=create_session,
        ),
    ),
)

# Inspect extracted handlers
for h in result:
    print(f"{h.trigger_data['method']} {h.trigger_data['path']}")
    print(f"  request: {h.request_type}, response: {h.response_type}")

# Convert to wire Application
wire_app = sources.fastapi_compile(result, runner)
```
"""

from emergent.wire.bridge._core import (
    # Handler types
    SyncHandler,
    AsyncHandler,
    AnyHandler,
)
from emergent.wire.bridge._capabilities import (
    # Context
    BridgeContext,
    # Protocols
    BridgeCompilable,
    Purifier,
    # Base
    BridgeCapability,
    # Execution helpers
    chain_purifiers,
    apply_bridge_capabilities,
    apply_purifiers,
    # Lookup helpers
    find_bridge_capability,
    find_all_bridge_capabilities,
    # BridgeCompilable capabilities
    SkipDeprecated,
    SkipByName,
    AddCapability,
    SetRequestTypeByName,
    SetResponseTypeByName,
    # Purifier capabilities
    WrapAsync,
    CatchErrors,
    IsolateGlobal,
    IsolateGlobalAsync,
    InjectKwarg,
    InjectKwargAsync,
    # ASGI mounting
    MountASGI,
    # Delegate wrapping (THIN — framework handles params)
    WrapAsDelegate,
)
from emergent.wire.bridge._convert import to_application
from emergent.wire.bridge._core import (
    # Protocols
    HandlerInspector,
    TriggerBuilder,
    # Axes
    BridgeAxes,
    # Core types
    ExtractedHandler,
    BridgeResult,
    # Extraction
    extract_all,
)
from emergent.wire.bridge._extract import extract_handler_unified

# Re-export submodules
from emergent.wire.bridge import sources
from emergent.wire.bridge import _capabilities as capabilities

__all__ = (
    # Types
    "SyncHandler",
    "AsyncHandler",
    "AnyHandler",
    # Context
    "BridgeContext",
    # Protocols
    "BridgeCompilable",
    "Purifier",
    "HandlerInspector",
    "TriggerBuilder",
    # Axes
    "BridgeAxes",
    # Base
    "BridgeCapability",
    # Execution helpers
    "chain_purifiers",
    "apply_bridge_capabilities",
    "apply_purifiers",
    # Lookup helpers
    "find_bridge_capability",
    "find_all_bridge_capabilities",
    # Core types
    "ExtractedHandler",
    "BridgeResult",
    # BridgeCompilable capabilities
    "SkipDeprecated",
    "SkipByName",
    "AddCapability",
    "SetRequestTypeByName",
    "SetResponseTypeByName",
    # Purifier capabilities
    "WrapAsync",
    "CatchErrors",
    "IsolateGlobal",
    "IsolateGlobalAsync",
    "InjectKwarg",
    "InjectKwargAsync",
    # ASGI mounting
    "MountASGI",
    # Delegate wrapping (THIN — framework handles params)
    "WrapAsDelegate",
    # Functions
    "extract_all",
    "extract_handler_unified",
    "to_application",
    # Submodules
    "capabilities",
    "sources",
)
