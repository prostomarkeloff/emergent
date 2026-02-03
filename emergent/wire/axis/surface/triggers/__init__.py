"""
Triggers — describe how endpoints are exposed.

    from emergent.wire.axis.surface import triggers

    # Transport triggers
    triggers.http.HTTPRouteTrigger(...)
    triggers.cli.CLITrigger(...)
    triggers.telegrinder.TelegrindTrigger(...)
    triggers.websocket.WebSocketTrigger(...)

    # Lifecycle triggers
    triggers.lifecycle.StartupTrigger(...)
    triggers.lifecycle.ShutdownTrigger(...)

    # Exception triggers
    triggers.exception.ExceptionTrigger(...)
"""

from emergent.wire.axis.surface.triggers import (
    http,
    cli,
    telegrinder,
    lifecycle,
    exception,
    websocket,
)

# Re-export commonly used triggers at package level
from emergent.wire.axis.surface.triggers.lifecycle import (
    StartupTrigger,
    ShutdownTrigger,
)
from emergent.wire.axis.surface.triggers.exception import ExceptionTrigger
from emergent.wire.axis.surface.triggers.websocket import WebSocketTrigger


__all__ = (
    # Modules
    "http",
    "cli",
    "telegrinder",
    "lifecycle",
    "exception",
    "websocket",
    # Direct exports
    "StartupTrigger",
    "ShutdownTrigger",
    "ExceptionTrigger",
    "WebSocketTrigger",
)
