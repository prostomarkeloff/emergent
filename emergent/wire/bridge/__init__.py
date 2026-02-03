"""Bridge axis — Framework → Application extraction.

Bridges extract handlers from existing frameworks and convert them
to wire Application for migration or unification.

Structure mirrors compile/:
- compile/targets: Application → Framework (OUT)
- bridge/bridgers: Framework → BridgeResult (IN)

```python
from emergent.wire.bridge import bridgers, capabilities as BC

# Extract from FastAPI
wire_app = bridgers.fastapi.extract(
    existing_app,
    capabilities=(
        BC.SkipDeprecated(),
        BC.AddCapability(C.enricher.Timeout(seconds=30)),
        bridgers.fastapi.capabilities.MapDepends({...}),
    ),
)
```
"""

from emergent.wire.bridge._core import (
    # Handler types
    SyncHandler,
    AsyncHandler,
    AnyHandler,
    # Wire data
    WireData,
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
    IncludeOnlyByName,
    AddCapability,
    SetRequestTypeByName,
    SetResponseTypeByName,
    SetCodecByName,
    # Purifier capabilities
    WrapAsync,
    CatchErrors,
    IsolateGlobal,
    IsolateGlobalAsync,
    InjectKwarg,
    InjectKwargAsync,
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
from emergent.wire.bridge import bridgers
from emergent.wire.bridge import _capabilities as capabilities

# Cross-compilation
from emergent.wire.bridge.bridgers._base import AddTrigger

__all__ = (
    # Types
    "SyncHandler",
    "AsyncHandler",
    "AnyHandler",
    # Wire data
    "WireData",
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
    "IncludeOnlyByName",
    "AddCapability",
    "SetRequestTypeByName",
    "SetResponseTypeByName",
    "SetCodecByName",
    # Purifier capabilities
    "WrapAsync",
    "CatchErrors",
    "IsolateGlobal",
    "IsolateGlobalAsync",
    "InjectKwarg",
    "InjectKwargAsync",
    # Delegate wrapping (THIN — framework handles params)
    "WrapAsDelegate",
    # Cross-compilation
    "AddTrigger",
    # Functions
    "extract_all",
    "extract_handler_unified",
    "to_application",
    # Submodules
    "capabilities",
    "bridgers",
)
