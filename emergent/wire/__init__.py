"""Wire — axes of data composition.

    from emergent.wire import axis, compile

    # Surface primitives
    from emergent.wire.axis.surface import Application, endpoint, scan
    from emergent.wire.axis.surface.codecs import rrc
    from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
    from emergent.wire.axis.surface import capabilities as C

    # Compilation
    from emergent.wire.compile.targets import fastapi, cli, telegrinder

    app = fastapi.compile(wire_app)
"""

from emergent.wire import axis, compile

__all__ = ("axis", "compile")
