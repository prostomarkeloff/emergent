"""Framework compilation targets.

    from emergent.wire.compile.targets import fastapi, cli, telegrinder, event

    app = fastapi.compile(wire_app)
    parser = cli.compile(wire_app, prog="my-tool")
    dispatch = telegrinder.compile(wire_app)
    dispatcher = event.compile(wire_app)
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

# Telegrinder (RuntimeError: telegrinder may fail at import time on some
# Python versions due to asyncio.get_event_loop() removal in 3.14+)
try:
    from emergent.wire.compile.targets import telegrinder as telegrinder
    __all__.append("telegrinder")
except (ImportError, RuntimeError):
    pass

# Event (always available)
from emergent.wire.compile.targets import event as event
__all__.append("event")
