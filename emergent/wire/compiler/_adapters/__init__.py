"""Framework adapters for functional compiler.

Each adapter provides:
- compile(Application, Axes) → FrameworkArtifact
- compile_stack(AppStack, Axes) → FrameworkArtifact
- wrap_rrc/wrap_stateful for custom composition
"""

__all__: list[str] = []

# FastAPI
try:
    from emergent.wire.compiler._adapters._fastapi import (
        fastapi_compile as fastapi_compile,
        fastapi_compile_stack as fastapi_compile_stack,
        wrap_rrc_fastapi as wrap_rrc_fastapi,
        wrap_stateful_fastapi as wrap_stateful_fastapi,
    )
    __all__.extend([
        "fastapi_compile",
        "fastapi_compile_stack",
        "wrap_rrc_fastapi",
        "wrap_stateful_fastapi",
    ])
except ImportError:
    pass

# CLI
from emergent.wire.compiler._adapters._cli import (
    cli_compile as cli_compile,
    cli_compile_stack as cli_compile_stack,
    cli_run as cli_run,
    wrap_rrc_cli as wrap_rrc_cli,
    wrap_stateful_cli as wrap_stateful_cli,
)
__all__.extend([
    "cli_compile",
    "cli_compile_stack",
    "cli_run",
    "wrap_rrc_cli",
    "wrap_stateful_cli",
])

# Telegrinder
try:
    from emergent.wire.compiler._adapters._telegrinder import (
        telegrinder_compile as telegrinder_compile,
        wrap_rrc_telegrinder as wrap_rrc_telegrinder,
        wrap_stateful_telegrinder as wrap_stateful_telegrinder,
        register_handler as register_handler,
        compose_store_key as compose_store_key,
        resolve_transition as resolve_transition,
        HasActiveFlowState as HasActiveFlowState,
    )
    __all__.extend([
        "telegrinder_compile",
        "wrap_rrc_telegrinder",
        "wrap_stateful_telegrinder",
        "register_handler",
        "compose_store_key",
        "resolve_transition",
        "HasActiveFlowState",
    ])
except ImportError:
    pass
