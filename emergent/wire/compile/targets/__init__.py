"""Framework compilation targets.

    from emergent.wire.compile.targets import fastapi, cli, telegrinder

    app = fastapi.compile(wire_app)
    parser = cli.compile(wire_app, prog="my-tool")
    dispatch = telegrinder.compile(wire_app)
"""

__all__: list[str] = []

# FastAPI
try:
    from emergent.wire.compile.targets import fastapi as fastapi
    __all__.append("fastapi")
except ImportError:
    pass

# CLI (always available)
from emergent.wire.compile.targets import cli as cli
__all__.append("cli")

# Telegrinder
try:
    from emergent.wire.compile.targets import telegrinder as telegrinder
    __all__.append("telegrinder")
except ImportError:
    pass
