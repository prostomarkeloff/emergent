# Bridge Vision — Universal Application Extraction

## Core Insight

**Everything is `Trigger × Codec × Capabilities`.**

- `Trigger` = WHERE to expose (extensible, any type)
- `Codec` = WHAT execution shape (extensible, any type)
- `Capabilities` = compiler plugins (self-contained)

Application is intentionally simple — just `list[Endpoint]`. All extensibility comes from new Trigger/Codec types, not new fields.

---

## Architecture: Core + Bridgers (like Compile + Targets)

**CORE IS COMPLETELY GENERIC — like compile/ core.**

```
bridge/
├── _core.py           # BridgeContext, ExtractedHandler — GENERIC
├── _analyze.py        # HandlerAnalysis — PYTHON INTROSPECTION ONLY
├── _pipelines.py      # extract_unified — GENERIC extraction pipeline
├── _capabilities.py   # BridgeCompilable, Purifier — GENERIC protocols
└── bridgers/          # FRAMEWORK-SPECIFIC (like compile/targets/)
    ├── fastapi/
    │   ├── _scanner.py       # Scan FastAPI app for routes
    │   ├── _capabilities.py  # FastAPI-specific capabilities
    │   └── _triggers.py      # Build triggers from FastAPI routes
    └── django/
        ├── _scanner.py
        ├── _capabilities.py
        └── _triggers.py
```

---

## Bridger = Compiler Target in Reverse

**Bridgers know ALL patterns of their framework and provide them as capabilities.**

Just like compile/targets/fastapi.py knows how to compile TO FastAPI,
bridge/bridgers/fastapi/ knows how to extract FROM FastAPI.

```python
# Bridger provides framework-specific capabilities
from emergent.wire.bridge.bridgers.fastapi import capabilities as fastapi_caps

wire_app = fastapi_bridger.extract(
    app,
    capabilities=(
        # FastAPI-specific: knows about Depends()
        fastapi_caps.MapDepends({get_db: test_db}),

        # FastAPI-specific: route-level capability
        fastapi_caps.RouteCapability(pattern="api_*", add_tags=["api"]),

        # Generic: works on any framework
        SkipByName(pattern="debug_.*"),
        WrapAsDelegate(),
    ),
)
```

---

## Capability Categories

| Category | Scope | Examples |
|----------|-------|----------|
| **Generic (core)** | Any framework | `SkipByName`, `WrapAsync`, `CatchErrors` |
| **Framework-specific (bridger)** | FastAPI/Django/etc | `MapDepends`, `RouteCapability` |
| **Handler wrapping** | Purifier | `WrapAsync`, `IsolateGlobal` |
| **Context transform** | BridgeCompilable | `SetCodec`, `AddCapability` |

---

## Two Orthogonal Problems

```
┌─────────────────────────────────────────────────────────────┐
│                      BRIDGING                                │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   1. DISCOVERY              2. TRANSFORMATION                │
│   ────────────              ────────────────                │
│   WHAT exists?              HOW to rewrite?                 │
│                                                              │
│   • Manual mapping          • Capabilities (STRONG!)        │
│   • Explicit declaration    • Purifiers                     │
│   • Optional automation     • Symbol rewriting              │
│                                                              │
│   NO HEURISTICS!            Self-contained plugins          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Philosophy: Manual Mapping First

**NO HEURISTICS by default.** User explicitly declares what to discover/rewrite.

```python
# WRONG — magic auto-discovery
wire_app = sources.fastapi(app)  # "figures out" dependencies magically

# RIGHT — explicit manual mapping
wire_app = sources.fastapi(
    app,
    capabilities=(
        # User KNOWS get_db exists, explicitly maps it
        MapDepends({get_db: create_test_session}),

        # User KNOWS redis global exists, explicitly isolates it
        IsolateGlobal("myapp.services", "redis", FakeRedis),

        # User KNOWS these handlers need timeout
        AddCapability(Timeout(30), for_pattern="external_.*"),
    ),
)
```

### Optional Automation via Capabilities

Automation is **opt-in** through specialized capabilities:

```python
@dataclass(frozen=True, slots=True)
class AutoDiscoverDepends(BridgeCapability):
    """OPTIONAL: Auto-discover Depends() in handlers.

    User explicitly opts into automation.
    """

    default_factory: Callable[[type], Callable]  # How to create deps

    def compile_bridge(self, ctx):
        # Analyze handler, find Depends(), add to discovered
        deps = _find_all_depends(ctx.handler)
        for dep_func, param_name in deps:
            # User provided factory for auto-resolution
            factory = self.default_factory(dep_func)
            # ... apply mapping
```

Usage — user explicitly enables automation:

```python
wire_app = sources.fastapi(
    app,
    capabilities=(
        # Opt-in to auto-discovery with explicit factory
        AutoDiscoverDepends(
            default_factory=lambda dep: lambda: Mock(spec=dep),
        ),
    ),
)
```

---

## Implemented Components

| Component | Location | Status |
|-----------|----------|--------|
| `StartupTrigger` | `wire/axis/surface/triggers/lifecycle.py` | ✅ DONE |
| `ShutdownTrigger` | `wire/axis/surface/triggers/lifecycle.py` | ✅ DONE |
| `ExceptionTrigger[E]` | `wire/axis/surface/triggers/exception.py` | ✅ DONE |
| `WebSocketTrigger` | `wire/axis/surface/triggers/websocket.py` | ✅ DONE |
| `Application.capabilities` | `wire/axis/surface/_app.py` | ✅ DONE |
| `FastAPIAppContext` | `wire/axis/_capability.py` | ✅ DONE |
| `FastAPIAppCompilable` | `wire/axis/_capability.py` | ✅ DONE |
| FastAPI compiler (lifespan) | `wire/compile/targets/fastapi.py` | ✅ DONE |
| Bridge unified extraction | `wire/bridge/sources/fastapi.py` | ✅ DONE |

---

## Symmetry: Compile ↔ Bridge

```
┌─────────────────────────────────────────────────────────────────────┐
│                      wire.Application                                │
│                                                                      │
│  capabilities: (CORS, RequestId, ...)     ← global middleware        │
│                                                                      │
│  endpoints:                                                          │
│    HTTPRouteTrigger     × RRC/Delegate    ← routes                   │
│    WebSocketTrigger     × DelegateCodec   ← websockets               │
│    StartupTrigger       × DelegateCodec   ← lifecycle                │
│    ShutdownTrigger      × DelegateCodec   ← lifecycle                │
│    ExceptionTrigger[E]  × DelegateCodec   ← error handlers           │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
              ↑                                        ↓
       bridge.extract                           compile.fastapi
       bridge.extract                           compile.cli
       bridge.extract                           compile.telegrinder
              ↑                                        ↓
┌─────────────────────────────────────────────────────────────────────┐
│                      Framework (FastAPI/CLI/TG)                      │
│                                                                      │
│  routes, websockets, middleware, lifecycle, exception_handlers       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Pain Points: Real Legacy Applications

### What Bridge Extracts (Automatic)

| Aspect | Extracted As | Status |
|--------|--------------|--------|
| HTTP routes | `HTTPRouteTrigger × DelegateCodec` | ✅ |
| WebSocket routes | `WebSocketTrigger × DelegateCodec` | ✅ |
| Startup handlers | `StartupTrigger × DelegateCodec` | ✅ |
| Shutdown handlers | `ShutdownTrigger × DelegateCodec` | ✅ |
| Exception handlers | `ExceptionTrigger × DelegateCodec` | ✅ |

### What Requires Manual Mapping

| Aspect | Problem | Solution (Manual) |
|--------|---------|-------------------|
| `Depends()` chains | Runtime resolved | `MapDepends({dep: factory})` |
| Module globals | Implicit dependency | `IsolateGlobal(module, attr, factory)` |
| Middleware | Different signatures | `AddCapability(...)` per handler |
| Config/env vars | Scattered `getenv()` | `InjectKwarg(name, factory)` |
| Database sessions | Context managers | `MapDepends` + session factory |

### What Needs New Triggers (Future)

| Aspect | Current Status | Future Trigger |
|--------|----------------|----------------|
| Celery tasks | Not extracted | `CeleryTaskTrigger` |
| Scheduled jobs | Not extracted | `ScheduleTrigger` |
| Message queues | Not extracted | `MessageQueueTrigger` |
| GraphQL | Not extracted | `GraphQLTrigger` |
| gRPC | Not extracted | `GRPCTrigger` |

---

## Capability Categories

### 1. BridgeCompilable — Context Transformation

Transform extraction metadata at compile-time:

```python
# Skip handlers
SkipDeprecated()
SkipByName(names={"debug_handler"})
IncludeOnlyByName(pattern="api_.*")

# Set types explicitly
SetRequestTypeByName({"create_user": CreateUserRequest})
SetResponseTypeByName({"get_users": UsersResponse})
SetCodecByName({"special": custom_codec})

# Add surface capabilities
AddCapability(Timeout(30), for_pattern="external_.*")
```

### 2. Purifier — Handler Wrapping

Static handler transformation at extraction-time:

```python
# Async conversion
WrapAsync()

# Error handling
CatchErrors(on_error=lambda e: ErrorResponse(str(e)))

# Global isolation (symbol rewriting!)
IsolateGlobal("myapp.db", "redis", FakeRedis)
IsolateGlobalAsync("myapp.db", "session", create_session)

# Dependency injection
InjectKwarg("config", lambda: load_config())
InjectKwargAsync("db", create_async_session)

# Depends() mapping
MapDepends(
    depends_map={get_db: create_test_db},
    scope_map={get_user: User},  # For compose dialect
)
```

### 3. Codec Setting

```python
# Wrap as delegate (preserves handler signature)
WrapAsDelegate()

# Mount ASGI app
MountASGI(django_app, prefix="/django")
```

---

## Writing New Bridge Source (e.g., Django)

### 1. Define Scanner

```python
def scan_django_routes(urlpatterns) -> list[tuple[DjangoRouteData, Callable]]:
    """Extract (trigger_data, handler) pairs from Django URLs."""
    results = []
    for pattern in urlpatterns:
        if hasattr(pattern, 'callback'):
            # Function-based view
            results.append((
                DjangoRouteData(path=pattern.pattern, name=pattern.name),
                pattern.callback,
            ))
        elif hasattr(pattern, 'cls'):
            # Class-based view — extract methods
            for method in ('get', 'post', 'put', 'delete'):
                if hasattr(pattern.cls, method):
                    results.append((
                        DjangoRouteData(path=pattern.pattern, method=method),
                        getattr(pattern.cls, method),
                    ))
    return results
```

### 2. Define Inspector

```python
@dataclass(frozen=True, slots=True)
class DjangoInspector:
    def request_type(self, handler) -> type | None:
        # Django views receive HttpRequest
        return None  # No typed request in Django

    def response_type(self, handler) -> type | None:
        # Inspect return annotation if present
        hints = get_type_hints(handler)
        return hints.get("return")
```

### 3. Define Trigger Builder

```python
@dataclass(frozen=True, slots=True)
class DjangoTriggerBuilder:
    def build(self, data: DjangoRouteData) -> Trigger:
        return HTTPRouteTrigger(
            method=data.method or "GET",
            path=data.path,
        )
```

### 4. Implement Extract Function

```python
def extract(urlpatterns, capabilities=()) -> Application:
    from emergent.wire.axis.surface import application, endpoint, empty_runner
    from emergent.wire.axis.surface.codecs.delegate import delegate

    inspector = DjangoInspector()
    runner = empty_runner()
    endpoints = []

    for route_data, handler in scan_django_routes(urlpatterns):
        trigger = HTTPRouteTrigger(
            method=route_data.method or "GET",
            path=route_data.path,
        )
        ep = endpoint(runner).expose(
            trigger,
            delegate(handler, response=inspector.response_type(handler)),
        )
        endpoints.append(ep)

    wire_app = application()
    for ep in endpoints:
        wire_app = wire_app.mount(ep)

    return wire_app
```

---

## Future: New Trigger Types

### CeleryTaskTrigger

```python
@dataclass(frozen=True, slots=True)
class CeleryTaskTrigger:
    """Background task trigger."""
    name: str
    queue: str = "default"
    retry_policy: RetryPolicy | None = None

# Extraction
for task in celery_app.tasks.values():
    trigger = CeleryTaskTrigger(
        name=task.name,
        queue=task.queue,
    )
    ep = endpoint(runner).expose(trigger, delegate(task.run))
```

### ScheduleTrigger

```python
@dataclass(frozen=True, slots=True)
class ScheduleTrigger:
    """Periodic/cron task trigger."""
    schedule: str  # cron expression
    name: str | None = None
```

### MessageQueueTrigger

```python
@dataclass(frozen=True, slots=True)
class MessageQueueTrigger:
    """Message queue consumer trigger."""
    queue: str
    consumer_group: str | None = None
```

---

## Key Principles

1. **NO HEURISTICS** — User explicitly declares mappings
2. **Manual first** — Automation is opt-in via capabilities
3. **Capabilities are macros** — Symbol rewriting power
4. **Trigger × Codec × Capabilities** — Universal pattern
5. **DelegateCodec** — Universal executor for extracted handlers
6. **Scanners discover, capabilities transform** — Separation of concerns

---

## Platform Gap: Bridge vs Compile

Bridge is NOT a platform yet. Compare with compile:

```
compile/ (PLATFORM)                    bridge/ (AD-HOC)
─────────────────────                  ────────────────────
_core.py                               _core.py
├── Axes                               ├── BridgeAxes (THIN)
├── FieldConstraints                   ├── ExtractedHandler
├── extract_constraints()              ├── BridgeResult
├── extract_all_constraints()          └── extract_all() (THIN)
├── ScopeSetup protocol
└── scan_all_codecs()                  ❌ NO scan_all_* equivalent

_execute.py                            _extract.py (THIN!)
├── execute_rrc_unified()              └── extract_handler_unified()
├── execute_stateful_unified()             (just 1 function!)
├── execute_immediate_unified()
└── execute_delegate_unified()         ❌ NO extraction pipelines

_capabilities.py                       _capabilities.py ✅
├── apply_response_capabilities()      ├── apply_bridge_capabilities()
├── apply_fastapi_capabilities()       ├── apply_purifiers()
└── find_capability()                  └── all capabilities

_generate.py                           ❌ MISSING
├── to_pydantic()                      Need: _analyze.py
├── to_argparse_args()                 ├── analyze_handler()
└── ArgSpec                            ├── discover_dependencies()
                                       └── HandlerAnalysis

_request.py                            ❌ MISSING
├── build_request()                    Need: _resolve.py
└── compose dialect handling           ├── resolve_dependencies()
                                       └── dependency graph

_rrc.py                                ❌ MISSING
├── execute_rrc()                      Need: _pipelines.py
└── chain_enrichers()                  ├── extract_http_pipeline()
                                       ├── extract_lifecycle_pipeline()
                                       └── extract_websocket_pipeline()

_stateful.py                           ❌ MISSING
├── load_state()                       Need: _validate.py
├── save_state()                       ├── validate_extraction()
├── execute_stateful_turn()            ├── check_dependencies_mapped()
└── execute_stateful_done()            └── ExtractionReport

targets/                               sources/
├── fastapi.py                         ├── fastapi.py
├── cli.py                             └── (ad-hoc, no protocol)
└── telegrinder.py
    (all follow same pattern)          ❌ NO SourceProtocol
```

---

## Missing Platform Components

### 1. `_analyze.py` — Handler Introspection

Reverse of compile's `_generate.py`. Analyzes handler to extract metadata.

```python
@dataclass(frozen=True, slots=True)
class HandlerAnalysis:
    """Analysis result for a handler."""
    name: str
    parameters: tuple[ParameterInfo, ...]
    return_type: type | None
    is_async: bool
    depends: tuple[DependsInfo, ...]      # FastAPI Depends()
    globals_used: tuple[GlobalInfo, ...]  # Module globals accessed
    closures: tuple[str, ...]             # Closure variables


@dataclass(frozen=True, slots=True)
class ParameterInfo:
    name: str
    annotation: type | None
    default: Any
    is_depends: bool
    depends_func: Callable | None


@dataclass(frozen=True, slots=True)
class DependsInfo:
    param_name: str
    depends_func: Callable
    nested: tuple[DependsInfo, ...]  # Nested Depends() chain


def analyze_handler(handler: Callable) -> HandlerAnalysis:
    """Analyze handler and extract all metadata.

    NO HEURISTICS — just extracts what's there.
    """
    ...


def analyze_parameters(handler: Callable) -> tuple[ParameterInfo, ...]:
    """Extract parameter info from handler signature."""
    ...


def analyze_depends(handler: Callable) -> tuple[DependsInfo, ...]:
    """Extract Depends() info from handler parameters."""
    ...
```

### 2. `_resolve.py` — Dependency Resolution

Reverse of compile's `_request.py`. Builds dependency graph.

```python
@dataclass(frozen=True, slots=True)
class DependencyGraph:
    """Graph of handler dependencies."""
    root: str  # Handler name
    nodes: frozenset[str]
    edges: tuple[tuple[str, str], ...]  # (from, to)
    depends_funcs: dict[str, Callable]  # node → Depends function


def build_dependency_graph(handler: Callable) -> DependencyGraph:
    """Build dependency graph for handler.

    Discovers Depends() chains (nested dependencies).
    """
    ...


def find_unmapped_dependencies(
    graph: DependencyGraph,
    mapped: frozenset[Callable],
) -> frozenset[Callable]:
    """Find dependencies not covered by MapDepends."""
    ...


def topological_sort(graph: DependencyGraph) -> tuple[str, ...]:
    """Sort dependencies in execution order."""
    ...
```

### 3. `_pipelines.py` — Extraction Pipelines

Like compile's `_execute.py`. Unified extraction for each trigger type.

```python
def extract_http_unified(
    route_data: Any,
    handler: Callable,
    axes: BridgeAxes,
    capabilities: Sequence[BridgeCapability],
) -> ExtractedHandler | None:
    """Unified HTTP route extraction pipeline.

    Steps:
    1. Analyze handler
    2. Build context with analysis
    3. Apply BridgeCompilable capabilities
    4. Apply Purifiers
    5. Validate (optional)
    6. Return ExtractedHandler
    """
    ...


def extract_lifecycle_unified(
    lifecycle_data: Any,
    handler: Callable,
    axes: BridgeAxes,
    capabilities: Sequence[BridgeCapability],
) -> ExtractedHandler | None:
    """Unified lifecycle extraction pipeline."""
    ...


def extract_websocket_unified(
    ws_data: Any,
    handler: Callable,
    axes: BridgeAxes,
    capabilities: Sequence[BridgeCapability],
) -> ExtractedHandler | None:
    """Unified websocket extraction pipeline."""
    ...


def extract_exception_unified(
    exc_data: Any,
    handler: Callable,
    axes: BridgeAxes,
    capabilities: Sequence[BridgeCapability],
) -> ExtractedHandler | None:
    """Unified exception handler extraction pipeline."""
    ...
```

### 4. `_validate.py` — Extraction Validation

Like compile's implicit validation. Explicit validation for bridge.

```python
@dataclass(frozen=True, slots=True)
class ExtractionReport:
    """Validation report for extraction."""
    handler_name: str
    is_valid: bool
    unmapped_depends: tuple[str, ...]
    unmapped_globals: tuple[str, ...]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]


def validate_extraction(
    ctx: BridgeContext,
    analysis: HandlerAnalysis,
    mapped_depends: frozenset[Callable],
) -> ExtractionReport:
    """Validate that extraction is complete.

    Checks:
    - All Depends() mapped or handler going back to same framework
    - No obvious errors
    """
    ...


def validate_all(
    handlers: Sequence[ExtractedHandler],
    analyses: Sequence[HandlerAnalysis],
    capabilities: Sequence[BridgeCapability],
) -> tuple[ExtractionReport, ...]:
    """Validate all extracted handlers."""
    ...
```

### 5. `_source.py` — Source Protocol

Common interface for all sources (like targets follow same pattern).

```python
class SourceProtocol(Protocol[T]):
    """Protocol for bridge sources.

    All sources implement this for unified extraction.
    """

    def scan_http(self) -> Iterable[tuple[T, Callable]]:
        """Scan HTTP routes → (trigger_data, handler)."""
        ...

    def scan_lifecycle(self) -> Iterable[tuple[LifecycleData, Callable]]:
        """Scan lifecycle handlers."""
        ...

    def scan_websockets(self) -> Iterable[tuple[T, Callable]]:
        """Scan websocket handlers."""
        ...

    def scan_exceptions(self) -> Iterable[tuple[ExceptionData, Callable]]:
        """Scan exception handlers."""
        ...

    def get_inspector(self) -> HandlerInspector:
        """Get handler inspector for this source."""
        ...

    def get_trigger_builder(self) -> TriggerBuilder[T]:
        """Get trigger builder for this source."""
        ...


@dataclass(frozen=True, slots=True)
class LifecycleData:
    """Common lifecycle trigger data."""
    phase: Literal["startup", "shutdown"]
    order: int = 0


@dataclass(frozen=True, slots=True)
class ExceptionData:
    """Common exception trigger data."""
    exception_type: type[Exception]
```

### 6. Enhanced `_core.py` — Rich BridgeAxes

```python
@dataclass(frozen=True, slots=True)
class BridgeAxes:
    """Full extraction context — like compile.Axes but richer."""

    # Required
    inspector: HandlerInspector

    # Analysis (pluggable)
    analyzer: Callable[[Callable], HandlerAnalysis] = analyze_handler

    # Resolution (pluggable)
    resolver: Callable[[Callable], DependencyGraph] = build_dependency_graph

    # Validation (pluggable, optional)
    validator: Callable[[BridgeContext, HandlerAnalysis], ExtractionReport] | None = None

    # Schema introspection (optional)
    schema: Callable[[type], dict[str, FieldInfo]] | None = None

    @classmethod
    def default(cls, inspector: HandlerInspector) -> BridgeAxes:
        return cls(inspector=inspector)

    @classmethod
    def with_validation(cls, inspector: HandlerInspector) -> BridgeAxes:
        return cls(inspector=inspector, validator=validate_extraction)
```

### 7. Unified Extraction Loop

Like compile's `scan_all_codecs`.

```python
def extract_all_from_source[T](
    source: SourceProtocol[T],
    capabilities: Sequence[BridgeCapability] = (),
    axes: BridgeAxes | None = None,
) -> Application:
    """Unified extraction from any source.

    Like scan_all_codecs but for bridge.
    """
    _axes = axes or BridgeAxes.default(source.get_inspector())
    builder = source.get_trigger_builder()
    runner = empty_runner()
    endpoints: list[Endpoint] = []

    # HTTP
    for data, handler in source.scan_http():
        extracted = extract_http_unified(data, handler, _axes, capabilities)
        if extracted and extracted.codec:
            trigger = builder.build(data)
            ep = endpoint(runner).expose(trigger, extracted.codec, *extracted.surface_capabilities)
            endpoints.append(ep)

    # Lifecycle
    for data, handler in source.scan_lifecycle():
        extracted = extract_lifecycle_unified(data, handler, _axes, capabilities)
        if extracted and extracted.codec:
            trigger = StartupTrigger(order=data.order) if data.phase == "startup" else ShutdownTrigger(order=data.order)
            ep = endpoint(runner).expose(trigger, extracted.codec)
            endpoints.append(ep)

    # WebSocket
    for data, handler in source.scan_websockets():
        extracted = extract_websocket_unified(data, handler, _axes, capabilities)
        if extracted and extracted.codec:
            trigger = builder.build(data)
            ep = endpoint(runner).expose(trigger, extracted.codec, *extracted.surface_capabilities)
            endpoints.append(ep)

    # Exceptions
    for data, handler in source.scan_exceptions():
        extracted = extract_exception_unified(data, handler, _axes, capabilities)
        if extracted and extracted.codec:
            trigger = ExceptionTrigger(exception_type=data.exception_type)
            ep = endpoint(runner).expose(trigger, extracted.codec)
            endpoints.append(ep)

    app = application()
    for ep in endpoints:
        app = app.mount(ep)

    return app
```

---

## Implementation Plan

### Phase 1: Core Analysis (`_analyze.py`)

| Task | Description | Depends On |
|------|-------------|------------|
| 1.1 | Define `ParameterInfo` dataclass | — |
| 1.2 | Define `DependsInfo` dataclass | — |
| 1.3 | Define `HandlerAnalysis` dataclass | 1.1, 1.2 |
| 1.4 | Implement `analyze_parameters()` | 1.1 |
| 1.5 | Implement `analyze_depends()` | 1.2 |
| 1.6 | Implement `analyze_handler()` | 1.3, 1.4, 1.5 |

### Phase 2: Dependency Resolution (`_resolve.py`)

| Task | Description | Depends On |
|------|-------------|------------|
| 2.1 | Define `DependencyGraph` dataclass | — |
| 2.2 | Implement `build_dependency_graph()` | 2.1, Phase 1 |
| 2.3 | Implement `find_unmapped_dependencies()` | 2.1 |
| 2.4 | Implement `topological_sort()` | 2.1 |

### Phase 3: Validation (`_validate.py`)

| Task | Description | Depends On |
|------|-------------|------------|
| 3.1 | Define `ExtractionReport` dataclass | — |
| 3.2 | Implement `validate_extraction()` | 3.1, Phase 1, Phase 2 |
| 3.3 | Implement `validate_all()` | 3.2 |

### Phase 4: Source Protocol (`_source.py`)

| Task | Description | Depends On |
|------|-------------|------------|
| 4.1 | Define `SourceProtocol` | — |
| 4.2 | Define `LifecycleData`, `ExceptionData` | — |
| 4.3 | Refactor `sources/fastapi.py` to implement protocol | 4.1, 4.2 |

### Phase 5: Extraction Pipelines (`_pipelines.py`)

| Task | Description | Depends On |
|------|-------------|------------|
| 5.1 | Implement `extract_http_unified()` | Phase 1 |
| 5.2 | Implement `extract_lifecycle_unified()` | Phase 1 |
| 5.3 | Implement `extract_websocket_unified()` | Phase 1 |
| 5.4 | Implement `extract_exception_unified()` | Phase 1 |

### Phase 6: Enhanced Core (`_core.py`)

| Task | Description | Depends On |
|------|-------------|------------|
| 6.1 | Enhance `BridgeAxes` with analyzer, resolver, validator | Phase 1, 2, 3 |
| 6.2 | Implement `extract_all_from_source()` | Phase 4, 5 |

### Phase 7: Migration & Cleanup

| Task | Description | Depends On |
|------|-------------|------------|
| 7.1 | Update `sources/fastapi.py` to use new pipelines | Phase 5, 6 |
| 7.2 | Deprecate old `_extract.py` functions | 7.1 |
| 7.3 | Update `bridge_vision.md` with final architecture | All |

---

## Target File Structure

```
bridge/
├── __init__.py
├── _core.py              # BridgeAxes, ExtractedHandler, extract_all_from_source
├── _analyze.py           # NEW: HandlerAnalysis, analyze_handler
├── _resolve.py           # NEW: DependencyGraph, build_dependency_graph
├── _validate.py          # NEW: ExtractionReport, validate_extraction
├── _pipelines.py         # NEW: extract_*_unified functions
├── _source.py            # NEW: SourceProtocol, common data types
├── _capabilities.py      # Existing: all capabilities
├── _convert.py           # Keep for backwards compat (thin)
├── _extract.py           # Deprecate, keep for backwards compat
├── bridge_vision.md
└── sources/
    ├── __init__.py
    ├── fastapi.py        # Implements SourceProtocol
    └── (future: django.py, flask.py, etc.)
```
