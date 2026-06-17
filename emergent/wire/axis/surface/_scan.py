"""Scan toolkit — extract typed (trigger, handler) pairs from wire primitives.

The Trigger × Codec product space defines all possible exposures.
``scan`` and ``scan_stack`` extract the region a compiler claims:

    from emergent.wire.axis.surface import scan, scan_stack
    from emergent.wire.axis.surface.triggers.cli import CLITrigger
    from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec

    # By trigger only (any codec)
    scan(app, CLITrigger)

    # By both axes
    scan(app, CLITrigger, RequestResponseCodec)

    # AppStack → tree of (trigger, handler) pairs
    scan_stack(stack, CLITrigger, RequestResponseCodec)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from emergent.wire.axis.surface._app import Application
from emergent.wire.axis.surface._endpoint import Endpoint
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface._stack import AppStack

T = TypeVar("T")

# ── Named type aliases (house style: alias instead of inline dict[...]) ──
type MountMap[T] = dict[str, "StackView[T] | list[tuple[T, Handler[Any]]]"]


@dataclass(slots=True)
class StackView(Generic[T]):
    """Tree of (trigger, handler) pairs extracted from an AppStack."""

    root: list[tuple[T, Handler[Any]]]
    mounts: MountMap[T]


def scan_endpoint(
    endp: Endpoint,
    trigger: type[T],
    codec: type | None = None,
) -> list[tuple[T, Handler[Any]]]:
    """Extract matching (trigger, handler) pairs from a single Endpoint."""
    results: list[tuple[T, Handler[Any]]] = []
    for exp in endp.exposures:
        if not isinstance(exp.trigger, trigger):
            continue
        if codec is not None and not isinstance(exp.codec, codec):
            continue
        results.append((
            exp.trigger,
            Handler(codec=exp.codec, runner=endp.runner, capabilities=exp.capabilities),
        ))
    return results


def scan(
    app: Application,
    trigger: type[T],
    codec: type | None = None,
) -> list[tuple[T, Handler[Any]]]:
    """Extract matching (trigger, handler) pairs from an Application.

    Filters the Trigger × Codec product space:
    - By trigger only: ``scan(app, CLITrigger)``
    - By both axes: ``scan(app, CLITrigger, RequestResponseCodec)``
    """
    return [
        pair
        for endp in app.endpoints
        for pair in scan_endpoint(endp, trigger, codec)
    ]


def scan_stack(
    stack: AppStack,
    trigger: type[T],
    codec: type | None = None,
) -> StackView[T]:
    """Walk AppStack and extract typed (trigger, handler) tree."""
    root = scan(stack.root_app, trigger, codec)
    mounts: MountMap[T] = {}
    for prefix, mounted in stack.mounts.items():
        if isinstance(mounted, AppStack):
            mounts[prefix] = scan_stack(mounted, trigger, codec)
        else:
            mounts[prefix] = scan(mounted, trigger, codec)
    return StackView(root=root, mounts=mounts)
