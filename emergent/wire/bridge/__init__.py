"""Bridge axis — Framework → Application extraction.

Symmetric to compile:
- compile: Application → Framework (OUT)
- bridge:  Framework → Application (IN)

```python
from emergent.wire.bridge import extract, build_application, BridgeAxes
from emergent.wire.bridge.bridgers import fastapi

# Extract specific route types
http_routes = extract(app, fastapi.HTTPRouteData)

# Build wire Application (auto-detect)
wire_app = build_application(app)

# With capabilities
wire_app = build_application(
    app,
    capabilities=(
        fastapi.InferFromFastAPI(),
        fastapi.MapDepends({get_db: test_db}),
    ),
)

# With explicit axes
axes = BridgeAxes.for_fastapi()
wire_app = build_application(app, axes=axes)

# Cross-compile to CLI
from emergent.wire.compile import cli_compile
cli_parser = cli_compile(wire_app, compile_axes)
```
"""

# Axes (like compile.Axes)
from emergent.wire.bridge._axes import BridgeAxes

# Registry (open-world framework detection — like compile.TargetCompiler)
from emergent.wire.bridge._registry import (
    BridgeRegistry,
    FrameworkBridger,
    get_default_registry,
)

# Core types
from emergent.wire.bridge._types import Extracted, RouteData

# Extractor protocol and composition
from emergent.wire.bridge._extractor import (
    ComposedExtractor,
    Extractor,
    compose_extractors,
    filter_extractor,
    first_extractor,
)

# ToWire protocol
from emergent.wire.bridge._to_wire import ComposedToWire, ToWire, compose_to_wire

# Signature analysis (legacy — use _introspect for new code)
from emergent.wire.bridge._signature import (
    HandlerParameter,
    HandlerSignature,
    SignatureAnalyzer,
    analyze_signature,
    first_analyzer,
)

# Handler introspection — PURE facts, no heuristics
from emergent.wire.bridge._introspect import (
    ParameterKind,
    DecoratorInfo,
    # Unwrap strategies
    UnwrapStrategy,
    ClosureFallbackUnwrap,
    unwrap_handler,
    # Class methods
    extract_class_methods,
    get_view_class,
    # Descriptor
    resolve_descriptor,
    # Parameter
    ParameterShape,
    no_default,
    # Instance
    InstanceInfo,
    # Handler
    HandlerShape,
    DEFAULT_SKIP_PARAMS,
    analyze_handler,
)

# Detection protocols — bridgers implement semantic classification
from emergent.wire.bridge._detect import (
    BodyDetection,
    DIDetection,
    DecoratorMapping,
    DetectionResult,
    BodyDetector,
    DIDetector,
    DecoratorMapper,
    run_detectors,
)

# Codec helpers
from emergent.wire.bridge._codec import make_rrc, make_delegate

# Unified extraction
from emergent.wire.bridge._unified import ExtractedWithShape, build_extracted

# Patterns
from emergent.wire.bridge import _patterns as patterns

# Main functions
from emergent.wire.bridge._build import build_application
from emergent.wire.bridge._scan import extract

# Capabilities
from emergent.wire.bridge._capabilities import (
    # Context
    BridgeContext,
    # Protocols
    BridgeCompilable,
    Purifier,
    # Base
    BridgeCapability,
    # Fold primitive
    BridgeCapabilityHandler,
    fold_bridge,
    # Execution helpers
    apply_bridge_capabilities,
    apply_purifiers,
    chain_purifiers,
    # Lookup helpers
    find_all_bridge_capabilities,
    find_bridge_capability,
    # BridgeCompilable capabilities
    AddCapability,
    IncludeOnlyByName,
    SetCodecByName,
    SetRequestTypeByName,
    SetResponseTypeByName,
    SkipByName,
    SkipDeprecated,
    # Purifier capabilities — Handler wrapping
    CatchErrors,
    WrapAsync,
    # Purifier capabilities — Global/Module state
    IsolateGlobal,
    IsolateGlobalAsync,
    SetGlobal,
    # Purifier capabilities — Dependency injection
    InjectKwarg,
    InjectKwargAsync,
    # Purifier capabilities — Context management
    WithContext,
    WithContextSync,
    SetupTeardown,
    # Delegate wrapping
    WrapAsDelegate,
)

# Re-export submodules
from emergent.wire.bridge import _capabilities as capabilities
from emergent.wire.bridge import bridgers

__all__ = (
    # Axes
    "BridgeAxes",
    # Registry
    "FrameworkBridger",
    "BridgeRegistry",
    "get_default_registry",
    # Core types
    "RouteData",
    "Extracted",
    # Extractor
    "Extractor",
    "ComposedExtractor",
    "compose_extractors",
    "first_extractor",
    "filter_extractor",
    # ToWire
    "ToWire",
    "ComposedToWire",
    "compose_to_wire",
    # Signature analysis (legacy)
    "HandlerParameter",
    "HandlerSignature",
    "SignatureAnalyzer",
    "analyze_signature",
    "first_analyzer",
    # Handler introspection — PURE facts
    "ParameterKind",
    "DecoratorInfo",
    # Unwrap strategies
    "UnwrapStrategy",
    "ClosureFallbackUnwrap",
    "unwrap_handler",
    # Class methods
    "extract_class_methods",
    "get_view_class",
    # Descriptor
    "resolve_descriptor",
    # Parameter
    "ParameterShape",
    "no_default",
    # Instance
    "InstanceInfo",
    # Handler
    "HandlerShape",
    "DEFAULT_SKIP_PARAMS",
    "analyze_handler",
    # Detection protocols — bridger implements
    "BodyDetection",
    "DIDetection",
    "DecoratorMapping",
    "DetectionResult",
    "BodyDetector",
    "DIDetector",
    "DecoratorMapper",
    "run_detectors",
    # Codec helpers
    "make_rrc",
    "make_delegate",
    # Unified extraction
    "ExtractedWithShape",
    "build_extracted",
    # Patterns
    "patterns",
    # Main functions
    "extract",
    "build_application",
    # Context
    "BridgeContext",
    # Protocols
    "BridgeCompilable",
    "Purifier",
    # Base
    "BridgeCapability",
    # Fold primitive
    "BridgeCapabilityHandler",
    "fold_bridge",
    # Execution helpers
    "chain_purifiers",
    "apply_bridge_capabilities",
    "apply_purifiers",
    # Lookup helpers
    "find_bridge_capability",
    "find_all_bridge_capabilities",
    # BridgeCompilable capabilities
    "SkipDeprecated",
    "SkipByName",
    "IncludeOnlyByName",
    "AddCapability",
    "SetRequestTypeByName",
    "SetResponseTypeByName",
    "SetCodecByName",
    # Purifier capabilities — Handler wrapping
    "WrapAsync",
    "CatchErrors",
    # Purifier capabilities — Global/Module state
    "IsolateGlobal",
    "IsolateGlobalAsync",
    "SetGlobal",
    # Purifier capabilities — Dependency injection
    "InjectKwarg",
    "InjectKwargAsync",
    # Purifier capabilities — Context management
    "WithContext",
    "WithContextSync",
    "SetupTeardown",
    # Delegate wrapping
    "WrapAsDelegate",
    # Submodules
    "capabilities",
    "bridgers",
)
