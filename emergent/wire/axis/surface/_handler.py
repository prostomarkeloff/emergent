"""Handler — compiled (codec, runner) bundle, generic over codec type."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar, TYPE_CHECKING

if TYPE_CHECKING:
    from emergent.ops._graph import Runner
    from emergent.wire.axis.surface.capabilities import SurfaceCapability

C = TypeVar("C")


@dataclass(slots=True)
class Handler(Generic[C]):
    """Compiled exposure: codec + runner + capabilities.

    The codec determines execution semantics (request-response,
    streaming, event, etc.). The runner executes domain ops.
    Capabilities modify behavior at compile/runtime.

    Together they form the unit that a compiler bridges to its
    target framework.

    Each codec module provides its own ``execute`` function:

        from emergent.wire.axis.surface.codecs import rrc

        response = await rrc.execute(handler, request)

    The codec owns the execution pipeline. Handler is just the
    typed bundle that carries (codec, runner, capabilities) between
    scan and the compiler's bridge code.
    """

    codec: C
    runner: Runner
    capabilities: tuple[SurfaceCapability, ...] = field(default_factory=tuple)
