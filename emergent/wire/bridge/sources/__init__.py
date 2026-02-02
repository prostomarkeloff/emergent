"""Bridge sources — framework-specific extractors.

Each source extracts handlers from a specific framework.
Sources are analogous to compile/targets but in reverse direction.

```
compile/targets: Application → Framework
bridge/sources:  Framework → BridgeResult → Application
```

Usage:
    from emergent.wire.bridge import sources

    # Extract from FastAPI
    result = sources.fastapi(legacy_app)

    # Convert to wire Application
    wire_app = sources.fastapi_compile(result, runner)
"""

from emergent.wire.bridge.sources.fastapi import (
    FastAPIInspector,
    FastAPITriggerBuilder,
    FastAPITriggerData,
    compile as fastapi_compile,
    extract as fastapi,
    extract_fastapi,
)

__all__ = (
    # FastAPI
    "fastapi",
    "fastapi_compile",
    "extract_fastapi",
    "FastAPITriggerData",
    "FastAPIInspector",
    "FastAPITriggerBuilder",
)
