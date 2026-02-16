"""Compile — axis data → framework artifacts.

Compilers are pure functions: (Application, Axes) → FrameworkArtifact

    from emergent.wire.compile import Axes
    from emergent.wire.compile.targets import fastapi, cli, telegrinder

    # Axes passed explicitly, no global state
    axes = Axes.default()

    # Compile to different frameworks
    fastapi_app = fastapi.compile(wire_app, axes)
    cli_parser = cli.compile(wire_app, axes)

## Type Generation from Schema Axis

    from emergent.wire.compile import to_pydantic, to_argparse_args

    UserModel = to_pydantic(User, axes)
    args = to_argparse_args(Register, axes)

## Building Blocks

- `execute_rrc(handler, request)` — universal RRC pipeline
- `execute_stateful_turn(...)` — single stateful turn
- `execute_stateful_done(...)` — Done handling
- `extract_constraints(FieldInfo)` — schema → FieldConstraints
"""

# Core
from emergent.wire.compile._core import (
    ScopeSetup,
    Axes,
    ItemHandler,
    CapabilityHandler,
    fold,
    fold_field,
    traced_fold,
    FieldConstraints,
    extract_constraints,
    extract_all_constraints,
)

# Trace (self-describing compilation)
from emergent.wire.compile._trace import (
    TraceCollector,
    ListCollector,
    FoldStep,
    FoldTrace,
    FieldPhaseTrace,
    FieldTrace,
    TypeTrace,
    ScanEvent,
    WrapEvent,
    CapabilityEvent,
)

# Explain (query trace data)
from emergent.wire.compile._explain import (
    # Dict layer
    trace_dict,
    field_dict,
    type_dict,
    # Human-readable layer
    explain,
    explain_field,
    explain_type,
    # Structured query
    get_field_trace,
    get_phase_trace,
    changed_fields,
    active_capabilities,
)

# Open-world compiler infrastructure
from emergent.wire.compile._phase import (
    CompilationPhase,
    FieldCompilation,
    compile_fields,
    PYDANTIC_PHASE,
    OPENAPI_PHASE,
    ARGPARSE_PHASE,
    REQUEST_BUILD_PHASE,
    TG_INPUT_PHASE,
    TG_RENDER_PHASE,
    FASTAPI_PHASES,
    CLI_PHASES,
    TG_PHASES,
)

from emergent.wire.compile._target import (
    CodecAdapter,
    TargetCompiler,
)

# Capabilities
from emergent.wire.compile._capabilities import (
    apply_response_capabilities,
    find_capability,
    find_all_capabilities,
    has_capability,
)

# Type generation
from emergent.wire.compile._generate import (
    to_pydantic,
    to_argparse_args,
    ArgSpec,
    PydanticHandler,
    ArgparseHandler,
    to_datanode,
    to_datanode_auto,
    to_datanode_from_context,
    to_telegram_fields,
)

# Schema generation (OpenAPI, JSON Schema)
from emergent.wire.compile._schema import (
    to_openapi_schema,
    to_json_schema,
)

# RRC
from emergent.wire.compile._rrc import (
    execute_rrc,
)

# Stateful
from emergent.wire.compile._stateful import (
    execute_stateful_turn,
    execute_stateful_done,
    load_state,
    save_state,
    delete_state,
    get_stateful_metadata,
)

# Request building
from emergent.wire.compile._request import (
    build_request,
    build_request_sync,
)

# Delegate support
from emergent.wire.compile._delegate import (
    resolve_handler_params,
)

# Unified execution (makes adapters trivial)
from emergent.wire.compile._execute import (
    ValueGetter,
    ScopeInjector,
    ResponseFormatter,
    execute_rrc_unified,
    execute_stateful_unified,
    execute_immediate_unified,
)

# Scope tiers
from emergent.wire.compile._lifetime import (
    Tier,
    App,
    Request,
    ScopeTiers,
    ScopeLayer,
)

# Targets subpackage
from emergent.wire.compile import targets


__all__ = (
    # Core
    "ScopeSetup",
    "Axes",
    "ItemHandler",
    "CapabilityHandler",
    "fold",
    "fold_field",
    "traced_fold",
    "FieldConstraints",
    "extract_constraints",
    "extract_all_constraints",
    # Trace
    "TraceCollector",
    "ListCollector",
    "FoldStep",
    "FoldTrace",
    "FieldPhaseTrace",
    "FieldTrace",
    "TypeTrace",
    "ScanEvent",
    "WrapEvent",
    "CapabilityEvent",
    # Explain (dict layer)
    "trace_dict",
    "field_dict",
    "type_dict",
    # Explain (human-readable)
    "explain",
    "explain_field",
    "explain_type",
    # Explain (structured query)
    "get_field_trace",
    "get_phase_trace",
    "changed_fields",
    "active_capabilities",
    # Open-world compiler infrastructure
    "CompilationPhase",
    "FieldCompilation",
    "compile_fields",
    "PYDANTIC_PHASE",
    "OPENAPI_PHASE",
    "ARGPARSE_PHASE",
    "REQUEST_BUILD_PHASE",
    "TG_INPUT_PHASE",
    "TG_RENDER_PHASE",
    "FASTAPI_PHASES",
    "CLI_PHASES",
    "TG_PHASES",
    "CodecAdapter",
    "TargetCompiler",
    # Capabilities
    "apply_response_capabilities",
    "find_capability",
    "find_all_capabilities",
    "has_capability",
    # Type generation
    "to_pydantic",
    "to_argparse_args",
    "ArgSpec",
    "PydanticHandler",
    "ArgparseHandler",
    "to_datanode",
    "to_datanode_auto",
    "to_datanode_from_context",
    "to_telegram_fields",
    # Schema generation
    "to_openapi_schema",
    "to_json_schema",
    # RRC
    "execute_rrc",
    # Stateful
    "execute_stateful_turn",
    "execute_stateful_done",
    "load_state",
    "save_state",
    "delete_state",
    "get_stateful_metadata",
    # Request building
    "build_request",
    "build_request_sync",
    # Delegate support
    "resolve_handler_params",
    # Unified execution
    "ValueGetter",
    "ScopeInjector",
    "ResponseFormatter",
    "execute_rrc_unified",
    "execute_stateful_unified",
    "execute_immediate_unified",
    # Scope tiers
    "Tier",
    "App",
    "Request",
    "ScopeTiers",
    "ScopeLayer",
    # Targets
    "targets",
)
