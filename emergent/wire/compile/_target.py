"""Target compiler — open-world codec→wrapper dispatch via WrapPhase.

Same pattern as schema compilation:
    from_codec(codec, trigger) → Ctx → fold(capabilities) → Ctx → assemble → Route

CodecBinding pairs a codec type with its from_codec initializer.
TargetCompiler holds bindings + pipeline fold config + assembler.

    from emergent.wire.compile._target import CodecBinding, TargetCompiler

    # Extend with new codec — zero emergent changes
    my_compiler = FASTAPI_COMPILER + CodecBinding(StreamingCodec, streaming_from_codec)

    # Swap existing binding
    traced = FASTAPI_COMPILER.replace_binding(RequestResponseCodec, traced_from_codec)

    # Strip down
    minimal = FASTAPI_COMPILER.without_binding(StatefulCodec)
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any, Callable, TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from emergent.wire.axis.surface._handler import Handler
    from emergent.wire.axis.surface._app import Application
    from emergent.wire.compile._core import Axes


_Trigger = TypeVar("_Trigger")


# ═══════════════════════════════════════════════════════════════════════════════
# CodecBinding — one codec for one trigger type
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class CodecBinding[Trigger]:
    """Bind a codec type to its from_codec initializer for a target.

    Pairs codec_type with from_codec function. Immutable value.
    Identified by codec_type — the natural identity key.

    The from_codec signature: (codec, trigger) → WrapContext.
    Codec is a DATA SOURCE — not a capability. It doesn't fold.
    from_codec reads its typed fields to seed the initial wrap context.

    Same pattern as CompilationPhase.initial: Callable[[str, type], Ctx].
    """

    codec_type: type
    from_codec: Callable[..., Any]
    _legacy: bool = False

    @property
    def wrap(self) -> Callable[..., Any]:
        """Backward compat alias for from_codec."""
        return self.from_codec

    @property
    def legacy(self) -> bool:
        """Whether this binding uses legacy wrap signature."""
        return self._legacy

    def same_slot(self, other: CodecBinding[Trigger]) -> bool:
        """True if other handles the same codec_type."""
        return self.codec_type is other.codec_type


# ═══════════════════════════════════════════════════════════════════════════════
# TargetCompiler — open-world set of codec bindings
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class TargetCompiler[Trigger]:
    """Full target compiler — open-world by construction.

    Same pattern as SchemaCompiler:
        from_codec(codec, trigger) → Ctx → fold(capabilities) → Ctx → assemble → Route

    Holds:
        trigger_type — filter for scan
        bindings — codec→from_codec mapping (identity by codec_type)
        pipeline_protocol — Protocol for pipeline fold (isinstance check)
        pipeline_method — method name for pipeline fold
        assemble — (WrapContext, Handler, Axes) → Route

    Algebraic operations (keyed by codec_type):
        compiler_a + compiler_b     # left-biased union (idempotent)
        compiler_a | compiler_b     # right-biased merge (override)
        compiler_a - compiler_b     # restriction (remove bindings)
        compiler_a & compiler_b     # intersection
        codec_type in compiler      # membership by codec_type
        compiler[RequestResponseCodec]  # lookup by codec_type

    Example:
        FASTAPI_COMPILER = TargetCompiler(
            trigger_type=HTTPRouteTrigger,
            bindings=(
                CodecBinding(RequestResponseCodec, rrc_from_codec),
                CodecBinding(StatefulCodec, stateful_from_codec),
            ),
            pipeline_protocol=FastAPIPipelineCompilable,
            pipeline_method="compile_fastapi_pipeline",
            assemble=assemble_fastapi_route,
        )

        # User extends
        my_compiler = FASTAPI_COMPILER + CodecBinding(StreamingCodec, streaming_from_codec)
    """

    trigger_type: type[Trigger]
    adapters: tuple[CodecBinding[Trigger], ...]
    pipeline_protocol: type = type(None)
    pipeline_method: str = ""
    assemble: Callable[..., Any] | None = None

    @property
    def bindings(self) -> tuple[CodecBinding[Trigger], ...]:
        """Alias — adapters and bindings are the same thing."""
        return self.adapters

    # ─── Lego operations (with guards) ────────────────────────────────

    def with_binding(
        self,
        codec_type: type,
        from_codec: Callable[..., Any],
    ) -> TargetCompiler[Trigger]:
        """Add codec binding. Raises ValueError if codec_type already present."""
        if any(b.codec_type is codec_type for b in self.adapters):
            raise ValueError(
                f"codec_type {codec_type.__qualname__} already present — "
                f"use replace_binding() or | for override"
            )
        return replace(
            self,
            adapters=(*self.adapters, CodecBinding(codec_type, from_codec)),
        )

    def replace_binding(
        self,
        codec_type: type,
        from_codec: Callable[..., Any],
    ) -> TargetCompiler[Trigger]:
        """Swap from_codec for existing codec. Raises KeyError if not found."""
        if not any(b.codec_type is codec_type for b in self.adapters):
            raise KeyError(f"No binding with codec_type {codec_type.__qualname__}")
        new_adapters = tuple(
            CodecBinding(codec_type, from_codec) if b.codec_type is codec_type else b
            for b in self.adapters
        )
        return replace(self, adapters=new_adapters)

    def without_binding(self, codec_type: type) -> TargetCompiler[Trigger]:
        """Remove binding by codec_type. Returns NEW compiler."""
        return replace(
            self,
            adapters=tuple(b for b in self.adapters if b.codec_type is not codec_type),
        )

    # Backward compat — stores wrap fn as legacy binding
    def with_codec(
        self,
        codec_type: type,
        wrap: Callable[..., Any],
    ) -> TargetCompiler[Trigger]:
        """Add codec adapter (legacy wrap signature)."""
        if any(b.codec_type is codec_type for b in self.adapters):
            raise ValueError(
                f"codec_type {codec_type.__qualname__} already present — "
                f"use replace_codec() or | for override"
            )
        return replace(
            self,
            adapters=(*self.adapters, CodecBinding(codec_type, wrap, _legacy=True)),
        )

    def replace_codec(
        self,
        codec_type: type,
        wrap: Callable[..., Any],
    ) -> TargetCompiler[Trigger]:
        """Swap wrapper for existing codec (legacy wrap signature)."""
        if not any(b.codec_type is codec_type for b in self.adapters):
            raise KeyError(f"No adapter with codec_type {codec_type.__qualname__}")
        new_adapters = tuple(
            CodecBinding(codec_type, wrap, _legacy=True) if b.codec_type is codec_type else b
            for b in self.adapters
        )
        return replace(self, adapters=new_adapters)

    without_codec = without_binding

    # ─── Algebraic operations (keyed by codec_type) ───────────────────

    def __add__(
        self, other: TargetCompiler[Trigger] | CodecBinding[Trigger],
    ) -> TargetCompiler[Trigger]:
        """Left-biased union. Idempotent: A + A == A."""
        if isinstance(other, CodecBinding):
            other = replace(self, adapters=(other,))
        if self.trigger_type is not other.trigger_type:
            raise TypeError(
                f"Cannot combine TargetCompilers with different trigger types: "
                f"{self.trigger_type.__qualname__} vs {other.trigger_type.__qualname__}"
            )
        seen = {b.codec_type for b in self.adapters}
        extra = tuple(b for b in other.adapters if b.codec_type not in seen)
        return replace(self, adapters=(*self.adapters, *extra))

    def __or__(
        self, other: TargetCompiler[Trigger] | CodecBinding[Trigger],
    ) -> TargetCompiler[Trigger]:
        """Right-biased merge. Other's bindings override self's by codec_type."""
        if isinstance(other, CodecBinding):
            other = replace(self, adapters=(other,))
        if self.trigger_type is not other.trigger_type:
            raise TypeError(
                f"Cannot merge TargetCompilers with different trigger types: "
                f"{self.trigger_type.__qualname__} vs {other.trigger_type.__qualname__}"
            )
        override = {b.codec_type: b for b in other.adapters}
        self_keys = {b.codec_type for b in self.adapters}
        result = [override.get(b.codec_type, b) for b in self.adapters]
        for b in other.adapters:
            if b.codec_type not in self_keys:
                result.append(b)
        return replace(self, adapters=tuple(result))

    def __sub__(
        self, other: TargetCompiler[Trigger] | CodecBinding[Trigger] | type,
    ) -> TargetCompiler[Trigger]:
        """Restriction — remove by codec_type."""
        if isinstance(other, TargetCompiler):
            remove_keys: set[type] = {b.codec_type for b in other.adapters}
        elif isinstance(other, CodecBinding):
            remove_keys = {other.codec_type}
        else:
            remove_keys = {other}
        return replace(
            self,
            adapters=tuple(b for b in self.adapters if b.codec_type not in remove_keys),
        )

    def __and__(self, other: TargetCompiler[Trigger]) -> TargetCompiler[Trigger]:
        """Intersection by codec_type. Self's versions retained."""
        other_keys = {b.codec_type for b in other.adapters}
        return replace(
            self,
            adapters=tuple(b for b in self.adapters if b.codec_type in other_keys),
        )

    def __contains__(self, item: object) -> bool:
        """Membership by codec_type. Accepts CodecBinding or bare type."""
        if isinstance(item, CodecBinding):
            key = item.codec_type
        elif isinstance(item, type):
            key = item
        else:
            return False
        return any(b.codec_type is key for b in self.adapters)

    def __len__(self) -> int:
        return len(self.adapters)

    def __iter__(self) -> Iterator[CodecBinding[Trigger]]:
        return iter(self.adapters)

    def __bool__(self) -> bool:
        return len(self.adapters) > 0

    def __getitem__(self, codec_type: type) -> CodecBinding[Trigger]:
        """Lookup binding by codec_type. Raises KeyError if not found."""
        for b in self.adapters:
            if b.codec_type is codec_type:
                return b
        raise KeyError(codec_type)

    # ─── Compilation ──────────────────────────────────────────────────

    def scan_and_wrap(
        self,
        app: Application,
        axes: Axes,
    ) -> Iterator[tuple[Trigger, Handler[Any], Any]]:
        """Scan app for all registered codecs, wrap each handler.

        Yields (trigger, handler, wrapped) for each matched handler.

        Pipeline: from_codec(codec, trigger) → fold(capabilities) → assemble → route

        When axes.trace is set, emits ScanEvent/WrapEvent for each match.
        """
        from emergent.wire.axis.surface._scan import scan
        from emergent.wire.compile._core import fold

        trace = axes.trace

        for binding in self.adapters:
            for trigger, handler in scan(app, self.trigger_type, binding.codec_type):
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

                if binding.legacy:
                    # Legacy: wrap(handler, trigger, axes) → route
                    wrapped = binding.from_codec(handler, trigger, axes)
                elif self.assemble is not None and self.pipeline_method:
                    # WrapPhase: from_codec → fold → assemble
                    ctx = binding.from_codec(handler.codec, trigger)
                    ctx = fold(
                        handler.capabilities, ctx,
                        self.pipeline_protocol, self.pipeline_method,
                        trace=trace,
                    )
                    wrapped = self.assemble(ctx, handler, axes)
                else:
                    # Fallback legacy: from_codec IS the wrap function
                    wrapped = binding.from_codec(handler, trigger, axes)

                if trace is not None:
                    from emergent.wire.compile._trace import WrapEvent

                    trace.wrap(WrapEvent(
                        codec_type=binding.codec_type.__qualname__,
                        trigger_repr=repr(trigger),
                        result_type=type(wrapped).__qualname__,
                    ))

                yield trigger, handler, wrapped


def wrap_for_stack(
    handler: Handler[Any],
    trigger: _Trigger,
    axes: Axes,
    compiler: TargetCompiler[_Trigger],
) -> Any:
    """Find the right binding and wrap handler for stack compilation.

    Shared across all targets — generic over the trigger type.
    """
    from emergent.wire.compile._core import fold

    if compiler.assemble is None:
        raise ValueError("Compiler has no assemble function")
    for binding in compiler.bindings:
        if isinstance(handler.codec, binding.codec_type):
            ctx = binding.from_codec(handler.codec, trigger)
            ctx = fold(
                handler.capabilities, ctx,
                compiler.pipeline_protocol, compiler.pipeline_method,
                trace=axes.trace,
            )
            return compiler.assemble(ctx, handler, axes)
    raise ValueError(f"No adapter for codec type: {type(handler.codec)}")


# Backward compat alias
CodecAdapter = CodecBinding


__all__ = (
    "CodecAdapter",
    "CodecBinding",
    "TargetCompiler",
)
