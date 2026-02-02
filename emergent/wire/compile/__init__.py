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
    FieldConstraints,
    extract_constraints,
    extract_all_constraints,
    scan_all_codecs,
)

# Capabilities
from emergent.wire.compile._capabilities import (
    CapabilityContext,
    FastAPICapabilityContext,
    CLICapabilityContext,
    TelegrinderCapabilityContext,
    apply_response_capabilities,
    apply_response_capabilities_async,
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

# Unified execution (makes adapters trivial)
from emergent.wire.compile._execute import (
    ValueGetter,
    ScopeInjector,
    ResponseFormatter,
    execute_rrc_unified,
    execute_stateful_unified,
    execute_immediate_unified,
)

# Targets subpackage
from emergent.wire.compile import targets


__all__ = (
    # Core
    "ScopeSetup",
    "Axes",
    "FieldConstraints",
    "extract_constraints",
    "extract_all_constraints",
    "scan_all_codecs",
    # Capabilities
    "CapabilityContext",
    "FastAPICapabilityContext",
    "CLICapabilityContext",
    "TelegrinderCapabilityContext",
    "apply_response_capabilities",
    "apply_response_capabilities_async",
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
    # Unified execution
    "ValueGetter",
    "ScopeInjector",
    "ResponseFormatter",
    "execute_rrc_unified",
    "execute_stateful_unified",
    "execute_immediate_unified",
    # Targets
    "targets",
)
