"""Target compiler — open-world codec→wrapper dispatch.

CodecAdapter pairs a codec type with its wrapper function.
TargetCompiler holds an open set of adapters.
No isinstance chains, no hardcoded lists.

    from emergent.wire.compile._target import CodecAdapter, TargetCompiler

    # Extend with new codec — zero emergent changes
    my_compiler = FASTAPI_COMPILER.with_codec(StreamingCodec, wrap_streaming)
    fapi = fastapi_compile(app, axes, compiler=my_compiler)

    # Swap existing wrapper
    traced = FASTAPI_COMPILER.replace_codec(RequestResponseCodec, wrap_rrc_traced)

    # Strip down
    minimal = FASTAPI_COMPILER.without_codec(StatefulCodec)
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from emergent.wire.axis.surface._handler import Handler
    from emergent.wire.axis.surface._app import Application
    from emergent.wire.compile._core import Axes


# ═══════════════════════════════════════════════════════════════════════════════
# CodecAdapter — one codec for one trigger type
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class CodecAdapter[Trigger]:
    """How to compile ONE codec type for ONE trigger type.

    Pairs codec_type with wrap function. Immutable value.

    The wrap function signature: (Handler, Trigger, Axes) -> wrapped.
    Return type is framework-specific:
    - FastAPI wraps return a callable (route function)
    - Telegrinder wraps return (handler_fn, rules_tuple)
    """

    codec_type: type
    wrap: Callable[..., Any]


# ═══════════════════════════════════════════════════════════════════════════════
# TargetCompiler — open-world set of codec adapters
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TargetCompiler[Trigger]:
    """Full target compiler — open-world by construction.

    Holds trigger type + open set of codec adapters.
    Immutable. Derive new compilers via .with_codec() / .replace_codec() / .without_codec().

    Example:
        FASTAPI_COMPILER = TargetCompiler(
            trigger_type=HTTPRouteTrigger,
            adapters=(
                CodecAdapter(RequestResponseCodec, wrap_rrc_fastapi),
                CodecAdapter(StatefulCodec, wrap_stateful_fastapi),
            ),
        )

        # User extends
        my_compiler = FASTAPI_COMPILER.with_codec(StreamingCodec, wrap_streaming)
    """

    trigger_type: type[Trigger]
    adapters: tuple[CodecAdapter[Trigger], ...]

    def with_codec(
        self,
        codec_type: type,
        wrap: Callable[..., Any],
    ) -> TargetCompiler[Trigger]:
        """Add codec adapter. Returns NEW compiler."""
        return replace(
            self,
            adapters=(*self.adapters, CodecAdapter(codec_type, wrap)),
        )

    def replace_codec(
        self,
        codec_type: type,
        wrap: Callable[..., Any],
    ) -> TargetCompiler[Trigger]:
        """Swap wrapper for existing codec. Returns NEW compiler."""
        new_adapters = tuple(
            CodecAdapter(codec_type, wrap) if a.codec_type is codec_type else a
            for a in self.adapters
        )
        return replace(self, adapters=new_adapters)

    def without_codec(self, codec_type: type) -> TargetCompiler[Trigger]:
        """Remove codec. Returns NEW compiler."""
        return replace(
            self,
            adapters=tuple(a for a in self.adapters if a.codec_type is not codec_type),
        )

    def scan_and_wrap(
        self,
        app: Application,
        axes: Axes,
    ) -> Iterator[tuple[Trigger, Handler[Any], Any]]:
        """Scan app for all registered codecs, wrap each handler.

        Yields (trigger, handler, wrapped) for each matched handler.
        The wrapped value is whatever adapter.wrap() returns — framework-specific.

        When axes.trace is set, emits ScanEvent/WrapEvent for each match.
        """
        from emergent.wire.axis.surface._scan import scan

        trace = axes.trace

        for adapter in self.adapters:
            for trigger, handler in scan(app, self.trigger_type, adapter.codec_type):
                if trace is not None:
                    from emergent.wire.compile._trace import ScanEvent

                    trace.scan(ScanEvent(
                        trigger_type=type(trigger).__qualname__,
                        trigger_repr=repr(trigger),
                        codec_type=type(handler.codec).__qualname__,
                        capabilities=tuple(
                            type(c).__qualname__ for c in handler.capabilities
                        ),
                    ))

                wrapped = adapter.wrap(handler, trigger, axes)

                if trace is not None:
                    from emergent.wire.compile._trace import WrapEvent

                    trace.wrap(WrapEvent(
                        codec_type=adapter.codec_type.__qualname__,
                        trigger_repr=repr(trigger),
                        result_type=type(wrapped).__qualname__,
                    ))

                yield trigger, handler, wrapped


__all__ = (
    "CodecAdapter",
    "TargetCompiler",
)
