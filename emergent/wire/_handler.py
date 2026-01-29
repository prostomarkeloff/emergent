"""Handler — compiled (codec, runner) bundle, generic over codec type."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from emergent.ops._graph import Runner

C = TypeVar("C")


@dataclass(slots=True)
class Handler(Generic[C]):
    """Compiled exposure: codec + runner.

    The codec determines execution semantics (request-response,
    streaming, event, etc.). The runner executes domain ops.
    Together they form the unit that a compiler bridges to its
    target framework.

    Each codec module provides its own ``execute`` function:

        from emergent.wire.codecs import rrc

        response = await rrc.execute(handler, request)

    The codec owns the execution pipeline. Handler is just the
    typed bundle that carries (codec, runner) between scan and
    the compiler's bridge code.
    """

    codec: C
    runner: Runner
