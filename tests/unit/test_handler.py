"""Tests for Handler dataclass at emergent/wire/axis/surface/_handler.py.

Handler[C] is a generic dataclass:
    @dataclass(slots=True)
    class Handler(Generic[C]):
        codec: C
        runner: Runner
        capabilities: tuple[SurfaceCapability, ...] = field(default_factory=tuple)

Tests cover construction, defaults, field access, and generic typing.
"""

from __future__ import annotations

from dataclasses import fields

from emergent.ops._graph import ops, Runner
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec
from emergent.wire.axis.surface.codecs.immediate import ImmediateFactoryCodec


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _runner() -> Runner:
    return ops().compile()


def _delegate_codec() -> DelegateCodec:
    def _fn() -> None:
        pass

    return DelegateCodec(handler=_fn)


def _factory_codec() -> ImmediateFactoryCodec:
    return ImmediateFactoryCodec(factory=lambda: None)


# A minimal SurfaceCapability implementation for testing.
# SurfaceCapability is a Protocol, so we satisfy it structurally.
class _DummyCapability:
    """Minimal SurfaceCapability satisfying the Protocol for tests."""

    ...


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Construction with all args
# ═══════════════════════════════════════════════════════════════════════════════


class TestHandlerConstruction:
    """Handler can be constructed with codec, runner, and capabilities."""

    def test_construction_with_all_args(self) -> None:
        codec = _delegate_codec()
        runner = _runner()
        cap = _DummyCapability()
        handler: Handler[DelegateCodec] = Handler(
            codec=codec,
            runner=runner,
            capabilities=(cap,),  # type: ignore[arg-type]
        )
        assert handler.codec is codec
        assert handler.runner is runner
        assert handler.capabilities == (cap,)

    def test_construction_with_factory_codec(self) -> None:
        codec = _factory_codec()
        runner = _runner()
        handler: Handler[ImmediateFactoryCodec] = Handler(
            codec=codec, runner=runner
        )
        assert handler.codec is codec
        assert isinstance(handler.runner, Runner)

    def test_construction_stores_runner_reference(self) -> None:
        runner = _runner()
        handler: Handler[DelegateCodec] = Handler(
            codec=_delegate_codec(), runner=runner
        )
        assert handler.runner is runner


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Default capabilities — empty tuple
# ═══════════════════════════════════════════════════════════════════════════════


class TestHandlerDefaultCapabilities:
    """Handler.capabilities defaults to an empty tuple when not provided."""

    def test_default_capabilities_is_empty_tuple(self) -> None:
        handler: Handler[DelegateCodec] = Handler(
            codec=_delegate_codec(), runner=_runner()
        )
        assert handler.capabilities == ()

    def test_default_capabilities_is_tuple_type(self) -> None:
        handler: Handler[DelegateCodec] = Handler(
            codec=_delegate_codec(), runner=_runner()
        )
        assert isinstance(handler.capabilities, tuple)

    def test_two_instances_have_independent_defaults(self) -> None:
        h1: Handler[DelegateCodec] = Handler(
            codec=_delegate_codec(), runner=_runner()
        )
        h2: Handler[DelegateCodec] = Handler(
            codec=_delegate_codec(), runner=_runner()
        )
        # Each instance gets its own empty tuple; they are equal but independent
        assert h1.capabilities == h2.capabilities
        assert h1.capabilities == ()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Field access
# ═══════════════════════════════════════════════════════════════════════════════


class TestHandlerFieldAccess:
    """Handler fields codec, runner, capabilities are accessible."""

    def test_codec_field_access(self) -> None:
        codec = _delegate_codec()
        handler: Handler[DelegateCodec] = Handler(
            codec=codec, runner=_runner()
        )
        assert handler.codec is codec

    def test_runner_field_access(self) -> None:
        runner = _runner()
        handler: Handler[DelegateCodec] = Handler(
            codec=_delegate_codec(), runner=runner
        )
        assert handler.runner is runner

    def test_capabilities_field_access(self) -> None:
        cap = _DummyCapability()
        handler: Handler[DelegateCodec] = Handler(
            codec=_delegate_codec(),
            runner=_runner(),
            capabilities=(cap,),  # type: ignore[arg-type]
        )
        assert len(handler.capabilities) == 1
        assert handler.capabilities[0] is cap

    def test_dataclass_fields_names(self) -> None:
        field_names = {f.name for f in fields(Handler)}
        assert "codec" in field_names
        assert "runner" in field_names
        assert "capabilities" in field_names


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Generic type parameter
# ═══════════════════════════════════════════════════════════════════════════════


class TestHandlerGenericTypeParameter:
    """Handler is generic over codec type C — different codec types work correctly."""

    def test_handler_with_delegate_codec(self) -> None:
        codec = _delegate_codec()
        handler: Handler[DelegateCodec] = Handler(
            codec=codec, runner=_runner()
        )
        assert isinstance(handler.codec, DelegateCodec)

    def test_handler_with_factory_codec(self) -> None:
        codec = _factory_codec()
        handler: Handler[ImmediateFactoryCodec] = Handler(
            codec=codec, runner=_runner()
        )
        assert isinstance(handler.codec, ImmediateFactoryCodec)

    def test_codec_attribute_retains_correct_type(self) -> None:
        def my_fn() -> str:
            return "hello"

        codec = DelegateCodec(handler=my_fn)
        handler: Handler[DelegateCodec] = Handler(
            codec=codec, runner=_runner()
        )
        # The codec's handler attribute is the original function
        assert handler.codec.handler is my_fn

    def test_factory_codec_attribute_retains_factory(self) -> None:
        factory_fn = lambda: 42

        codec = ImmediateFactoryCodec(factory=factory_fn)
        handler: Handler[ImmediateFactoryCodec] = Handler(
            codec=codec, runner=_runner()
        )
        assert handler.codec.factory is factory_fn
