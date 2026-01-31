"""Functional compiler infrastructure — multi-axis-aware.

Compilers are pure functions: (Application, Axes) → FrameworkArtifact

    from emergent.wire.compiler import Axes, fastapi_compile, cli_compile

    # Axes passed explicitly, no global state
    axes = Axes.default()

    # Compile to different frameworks
    fastapi_app = fastapi_compile(wire_app, axes)
    cli_parser = cli_compile(wire_app, axes)

## Type Generation from Schema Axis

    from emergent.wire.compiler import to_pydantic, to_argparse_args

    # Generate Pydantic model from dataclass + schema capabilities
    @dataclass
    class User:
        email: Annotated[str, MaxLen(255), openapi.Description("User email")]

    UserModel = to_pydantic(User, axes)
    # → Pydantic model with max_length=255, description="User email"

    # Generate argparse arguments
    args = to_argparse_args(User, axes)

## Architecture

    Axes ─────────────────────────────────────────────────────────────
    │
    ├── schema: inspect_dataclass  ← field capabilities
    │
    └── (surface/storage via codec/trigger)

    compile = axes → (app → framework_artifact)

    ┌─────────────────────────────────────────────────────────────────┐
    │  Application                                                    │
    │  ├── Endpoint                                                   │
    │  │   ├── (HTTPRouteTrigger, RRC)  ─┬→ wrap_rrc_fastapi          │
    │  │   ├── (HTTPRouteTrigger, Stateful) → wrap_stateful_fastapi   │
    │  │   ├── (CLITrigger, RRC)  ───────┬→ wrap_rrc_cli              │
    │  │   └── (CLITrigger, Stateful) ───→ wrap_stateful_cli          │
    │  └── ...                                                        │
    └─────────────────────────────────────────────────────────────────┘

## Building Blocks

- `execute_rrc(handler, request)` — universal RRC pipeline
- `execute_stateful_turn(...)` — single stateful turn
- `execute_stateful_done(...)` — Done handling
- `extract_constraints(FieldInfo)` — schema → FieldConstraints
"""

# Core
from emergent.wire.compiler._core import (
    Axes,
    FieldConstraints,
    extract_constraints,
    extract_all_constraints,
)

# Type generation
from emergent.wire.compiler._generate import (
    to_pydantic,
    to_argparse_args,
    ArgSpec,
    to_datanode,
    to_datanode_auto,
    to_datanode_from_context,
)

# RRC
from emergent.wire.compiler._rrc import (
    execute_rrc,
    compile_rrc,
)

# Stateful
from emergent.wire.compiler._stateful import (
    execute_stateful_turn,
    execute_stateful_done,
    load_state,
    save_state,
    delete_state,
    get_stateful_metadata,
)

# Adapters
try:
    from emergent.wire.compiler._adapters._fastapi import (
        fastapi_compile,
        fastapi_compile_stack,
    )
except ImportError:
    pass

from emergent.wire.compiler._adapters._cli import (
    cli_compile,
    cli_compile_stack,
    cli_run,
)

# Telegrinder adapter
try:
    from emergent.wire.compiler._adapters._telegrinder import telegrinder_compile
except ImportError:
    pass


__all__ = (
    # Core
    "Axes",
    "FieldConstraints",
    "extract_constraints",
    "extract_all_constraints",
    # Type generation
    "to_pydantic",
    "to_argparse_args",
    "ArgSpec",
    "to_datanode",
    "to_datanode_auto",
    "to_datanode_from_context",
    # RRC
    "execute_rrc",
    "compile_rrc",
    # Stateful
    "execute_stateful_turn",
    "execute_stateful_done",
    "load_state",
    "save_state",
    "delete_state",
    "get_stateful_metadata",
    # Adapters
    "fastapi_compile",
    "fastapi_compile_stack",
    "cli_compile",
    "cli_compile_stack",
    "cli_run",
    "telegrinder_compile",
)
