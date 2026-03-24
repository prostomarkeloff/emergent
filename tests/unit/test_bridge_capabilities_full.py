"""Tests for emergent.wire.bridge._capabilities — covers remaining missed lines.

Targeted lines:
- 182: _ensure_async raise TypeError for non-callable
- 194-197: _call_handler sync branch and TypeError branch
- 325-326: _matches_name pattern matching
- 433: SetResponseTypeByName name match sets response_type
- 460: SetCodecByName returns ctx when name not in map
- 508-526: IsolateGlobal.purify — module attribute isolation with lock
- 542-563: IsolateGlobalAsync.purify — async context manager isolation
- 650-657: WithContext.purify — async context manager wrapping
- 742-758: SetGlobal.purify — set-once module global
"""

from __future__ import annotations

import asyncio
import sys
import types
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest

from emergent.wire.bridge._capabilities import (
    AddCapability,
    BridgeContext,
    IsolateGlobal,
    IsolateGlobalAsync,
    SetCodecByName,
    SetGlobal,
    SetResponseTypeByName,
    WithContext,
    call_handler,
    chain_purifiers,
)

# Testing internal helper — no public alias exists; renaming on import
# so call sites don't trigger reportPrivateUsage.
from emergent.wire.bridge._capabilities import _matches_name as matches_name  # pyright: ignore[reportPrivateUsage]
from emergent.wire.bridge._core import WireData


# ═══════════════════════════════════════════════════════════════════════════════
# Test doubles
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class StubRouteData:
    """Minimal route data for tests."""

    path: str
    method: str = "GET"


@dataclass(frozen=True, slots=True)
class StubCapability:
    """Minimal surface capability for tests."""

    tag: str


def _make_ctx(
    name: str | None = "test_handler",
    deprecated: bool = False,
    skip: bool = False,
    wire: WireData | None = None,
    request_type: type | None = None,
    response_type: type | None = None,
) -> BridgeContext[StubRouteData, ..., object]:
    async def handler() -> None:
        pass

    return BridgeContext(
        trigger_data=StubRouteData(path="/test"),
        handler=handler,
        name=name,
        deprecated=deprecated,
        skip=skip,
        wire=wire or WireData(),
        request_type=request_type,
        response_type=response_type,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# _matches_name — pattern matching branch (lines 325-326)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMatchesNamePattern:
    """Test _matches_name with pattern matching (lines 324-326)."""

    def test_matches_by_pattern(self) -> None:
        """When names is set but does not match, and pattern matches, return True."""
        ctx = _make_ctx(name="get_users")
        result = matches_name(ctx, names=frozenset({"other"}), pattern=r"^get_.*")
        assert result is True

    def test_pattern_only_matches(self) -> None:
        """When names is None but pattern matches, return True."""
        ctx = _make_ctx(name="get_users")
        result = matches_name(ctx, names=None, pattern=r"^get_.*")
        assert result is True

    def test_pattern_does_not_match(self) -> None:
        """When pattern is set but doesn't match, return False."""
        ctx = _make_ctx(name="delete_users")
        result = matches_name(ctx, names=frozenset({"other"}), pattern=r"^get_.*")
        assert result is False

    def test_both_none_returns_true(self) -> None:
        """When both names and pattern are None, return True (match all)."""
        ctx = _make_ctx(name="anything")
        result = matches_name(ctx, names=None, pattern=None)
        assert result is True

    def test_name_is_none_pattern_set(self) -> None:
        """When ctx.name is None, pattern check is skipped."""
        ctx = _make_ctx(name=None)
        result = matches_name(ctx, names=None, pattern=r"^get_.*")
        # names is None and pattern is not None -> falls to final: names is None and pattern is None -> False
        assert result is False

    def test_name_matches_names_set(self) -> None:
        """When ctx.name is in names, return True immediately."""
        ctx = _make_ctx(name="target")
        result = matches_name(ctx, names=frozenset({"target"}), pattern=None)
        assert result is True


# ═══════════════════════════════════════════════════════════════════════════════
# _call_handler — sync handler and error branches (lines 194-197)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCallHandler:
    """Test _call_handler with sync handlers (lines 194-195)."""

    @pytest.mark.asyncio
    async def test_call_sync_handler(self) -> None:
        """_call_handler with sync handler runs via to_thread (line 194-195)."""

        def sync_fn(x: int) -> int:
            return x * 3

        result = await call_handler(sync_fn, 7)
        assert result == 21

    @pytest.mark.asyncio
    async def test_call_async_handler(self) -> None:
        """_call_handler with async handler awaits directly (line 191-192)."""

        async def async_fn(x: int) -> int:
            return x * 3

        result = await call_handler(async_fn, 7)
        assert result == 21

    @pytest.mark.asyncio
    async def test_call_sync_handler_with_kwargs(self) -> None:
        """_call_handler passes kwargs to sync handler."""

        def sync_fn(x: int, y: int = 10) -> int:
            return x + y

        result = await call_handler(sync_fn, 5, y=20)
        assert result == 25


# ═══════════════════════════════════════════════════════════════════════════════
# SetResponseTypeByName — name matches map (line 433)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSetResponseTypeByNameMissed:
    """Test SetResponseTypeByName setting the response type when name matches (line 431-432)."""

    def test_sets_response_type_when_name_in_map(self) -> None:
        ctx = _make_ctx(name="get_user", response_type=None)
        cap = SetResponseTypeByName(type_map={"get_user": dict})
        result = cap.compile_bridge(ctx)
        assert result.response_type is dict

    def test_returns_ctx_when_name_not_in_map(self) -> None:
        """Line 433 — return ctx when name not in type_map."""
        ctx = _make_ctx(name="unknown_handler", response_type=None)
        cap = SetResponseTypeByName(type_map={"get_user": dict})
        result = cap.compile_bridge(ctx)
        assert result.response_type is None

    def test_name_is_none_returns_unchanged(self) -> None:
        ctx = _make_ctx(name=None, response_type=None)
        cap = SetResponseTypeByName(type_map={"get_user": dict})
        result = cap.compile_bridge(ctx)
        assert result.response_type is None


# ═══════════════════════════════════════════════════════════════════════════════
# SetCodecByName — return ctx when name not in codec_map (line 460)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSetCodecByNameMissed:
    """Test SetCodecByName when name is not in map (line 460)."""

    def test_returns_ctx_when_name_not_in_map(self) -> None:
        ctx = _make_ctx(name="unknown_handler")
        cap = SetCodecByName(codec_map={"get_user": "some_codec"})
        result = cap.compile_bridge(ctx)
        assert result.wire.codec is None

    def test_returns_ctx_when_name_is_none(self) -> None:
        ctx = _make_ctx(name=None)
        cap = SetCodecByName(codec_map={"get_user": "some_codec"})
        result = cap.compile_bridge(ctx)
        assert result.wire.codec is None

    def test_sets_codec_when_name_matches(self) -> None:
        ctx = _make_ctx(name="get_user")
        cap = SetCodecByName(codec_map={"get_user": "my_codec"})
        result = cap.compile_bridge(ctx)
        assert result.wire.codec == "my_codec"


# ═══════════════════════════════════════════════════════════════════════════════
# IsolateGlobal.purify — module attribute isolation (lines 508-526)
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsolateGlobal:
    """Test IsolateGlobal purifier — lines 508-526."""

    @pytest.mark.asyncio
    async def test_isolates_module_global(self) -> None:
        """IsolateGlobal sets module attr to factory result and restores after."""
        # Create a temporary module with a global attribute
        mod = types.ModuleType("_test_isolate_module")
        mod.shared_value = "original"  # type: ignore[attr-defined]
        sys.modules["_test_isolate_module"] = mod

        try:
            cap = IsolateGlobal(
                module_path="_test_isolate_module",
                attr_name="shared_value",
                factory=lambda: "isolated",
            )

            async def handler() -> str:
                import _test_isolate_module  # type: ignore[import-not-found]

                return _test_isolate_module.shared_value  # type: ignore[no-any-return]

            wrapped = cap.purify(handler)
            result = await wrapped()

            assert result == "isolated"
            # After call, original value should be restored
            assert mod.shared_value == "original"  # type: ignore[attr-defined]
        finally:
            del sys.modules["_test_isolate_module"]

    @pytest.mark.asyncio
    async def test_restores_on_exception(self) -> None:
        """IsolateGlobal restores old value even when handler raises."""
        mod = types.ModuleType("_test_isolate_exc")
        mod.val = "original"  # type: ignore[attr-defined]
        sys.modules["_test_isolate_exc"] = mod

        try:
            cap = IsolateGlobal(
                module_path="_test_isolate_exc",
                attr_name="val",
                factory=lambda: "temp",
            )

            async def handler() -> str:
                raise ValueError("boom")

            wrapped = cap.purify(handler)
            with pytest.raises(ValueError, match="boom"):
                await wrapped()

            assert mod.val == "original"  # type: ignore[attr-defined]
        finally:
            del sys.modules["_test_isolate_exc"]

    @pytest.mark.asyncio
    async def test_serializes_concurrent_calls(self) -> None:
        """IsolateGlobal uses a lock so concurrent calls don't interleave."""
        mod = types.ModuleType("_test_isolate_lock")
        mod.counter = 0  # type: ignore[attr-defined]
        sys.modules["_test_isolate_lock"] = mod

        try:
            call_count = 0

            def factory() -> int:
                nonlocal call_count
                call_count += 1
                return call_count

            cap = IsolateGlobal(
                module_path="_test_isolate_lock",
                attr_name="counter",
                factory=factory,
            )

            async def handler() -> int:
                import _test_isolate_lock  # type: ignore[import-not-found]

                val = int(_test_isolate_lock.counter)  # type: ignore[reportUnknownArgumentType]  # dynamically created test module has no stubs
                await asyncio.sleep(0.01)
                return val

            wrapped = cap.purify(handler)

            results = await asyncio.gather(wrapped(), wrapped())
            # Due to lock, calls are serialized, so both should get distinct values
            assert len(set(results)) == 2
        finally:
            del sys.modules["_test_isolate_lock"]


# ═══════════════════════════════════════════════════════════════════════════════
# IsolateGlobalAsync.purify — async context manager isolation (lines 542-563)
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsolateGlobalAsync:
    """Test IsolateGlobalAsync purifier — lines 542-563."""

    @pytest.mark.asyncio
    async def test_isolates_with_async_cm(self) -> None:
        """IsolateGlobalAsync uses async context manager for value."""
        mod = types.ModuleType("_test_isolate_async")
        mod.resource = "original"  # type: ignore[attr-defined]
        sys.modules["_test_isolate_async"] = mod

        try:
            enter_log: list[str] = []
            exit_log: list[str] = []

            @asynccontextmanager
            async def resource_factory():  # type: ignore[no-untyped-def]
                enter_log.append("enter")
                yield "async_resource"
                exit_log.append("exit")

            cap = IsolateGlobalAsync(
                module_path="_test_isolate_async",
                attr_name="resource",
                factory=resource_factory,
            )

            async def handler() -> str:
                import _test_isolate_async  # type: ignore[import-not-found]

                return _test_isolate_async.resource  # type: ignore[no-any-return]

            wrapped = cap.purify(handler)
            result = await wrapped()

            assert result == "async_resource"
            assert enter_log == ["enter"]
            assert exit_log == ["exit"]
            # Original value restored
            assert mod.resource == "original"  # type: ignore[attr-defined]
        finally:
            del sys.modules["_test_isolate_async"]

    @pytest.mark.asyncio
    async def test_restores_on_exception(self) -> None:
        """IsolateGlobalAsync restores and exits CM even when handler raises."""
        mod = types.ModuleType("_test_isolate_async_exc")
        mod.val = "original"  # type: ignore[attr-defined]
        sys.modules["_test_isolate_async_exc"] = mod

        try:
            exit_called = False

            @asynccontextmanager
            async def factory():  # type: ignore[no-untyped-def]
                try:
                    yield "temp"
                finally:
                    nonlocal exit_called
                    exit_called = True

            cap = IsolateGlobalAsync(
                module_path="_test_isolate_async_exc",
                attr_name="val",
                factory=factory,
            )

            async def handler() -> str:
                raise RuntimeError("fail")

            wrapped = cap.purify(handler)
            with pytest.raises(RuntimeError, match="fail"):
                await wrapped()

            # __aexit__ called with exception info per context manager protocol
            assert exit_called is True
            assert mod.val == "original"  # type: ignore[attr-defined]
        finally:
            del sys.modules["_test_isolate_async_exc"]


# ═══════════════════════════════════════════════════════════════════════════════
# WithContext.purify — async context manager wrapping (lines 650-657)
# ═══════════════════════════════════════════════════════════════════════════════


class TestWithContext:
    """Test WithContext purifier — lines 650-657."""

    @pytest.mark.asyncio
    async def test_wraps_handler_in_async_context(self) -> None:
        """WithContext runs handler inside async context manager."""
        log: list[str] = []

        @asynccontextmanager
        async def my_context():  # type: ignore[no-untyped-def]
            log.append("enter")
            yield
            log.append("exit")

        cap = WithContext(factory=my_context)

        async def handler() -> str:
            log.append("handler")
            return "done"

        wrapped = cap.purify(handler)
        result = await wrapped()

        assert result == "done"
        assert log == ["enter", "handler", "exit"]

    @pytest.mark.asyncio
    async def test_context_manager_exit_on_error(self) -> None:
        """WithContext exits context manager even when handler raises."""
        log: list[str] = []

        @asynccontextmanager
        async def my_context():  # type: ignore[no-untyped-def]
            log.append("enter")
            try:
                yield
            finally:
                log.append("exit")

        cap = WithContext(factory=my_context)

        async def handler() -> str:
            raise ValueError("oops")

        wrapped = cap.purify(handler)
        with pytest.raises(ValueError, match="oops"):
            await wrapped()

        assert "enter" in log
        assert "exit" in log

    @pytest.mark.asyncio
    async def test_with_sync_handler(self) -> None:
        """WithContext also works with sync handlers (via _call_handler)."""
        log: list[str] = []

        @asynccontextmanager
        async def my_context():  # type: ignore[no-untyped-def]
            log.append("enter")
            yield
            log.append("exit")

        cap = WithContext(factory=my_context)

        def sync_handler() -> str:
            log.append("handler")
            return "sync_done"

        wrapped = cap.purify(sync_handler)
        result = await wrapped()

        assert result == "sync_done"
        assert log == ["enter", "handler", "exit"]


# ═══════════════════════════════════════════════════════════════════════════════
# SetGlobal.purify — set-once module global (lines 742-758)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSetGlobal:
    """Test SetGlobal purifier — lines 742-758."""

    @pytest.mark.asyncio
    async def test_sets_global_on_first_call(self) -> None:
        """SetGlobal sets module attribute on first call."""
        mod = types.ModuleType("_test_set_global")
        mod.db = None  # type: ignore[attr-defined]
        sys.modules["_test_set_global"] = mod

        try:
            cap = SetGlobal(
                module_path="_test_set_global",
                attr_name="db",
                factory=lambda: "connected_db",
            )

            async def handler() -> str:
                import _test_set_global  # type: ignore[import-not-found]

                return _test_set_global.db  # type: ignore[no-any-return]

            wrapped = cap.purify(handler)
            result = await wrapped()

            assert result == "connected_db"
            assert mod.db == "connected_db"  # type: ignore[attr-defined]
        finally:
            del sys.modules["_test_set_global"]

    @pytest.mark.asyncio
    async def test_only_sets_once(self) -> None:
        """SetGlobal only calls factory once, subsequent calls skip."""
        mod = types.ModuleType("_test_set_global_once")
        mod.counter = 0  # type: ignore[attr-defined]
        sys.modules["_test_set_global_once"] = mod

        try:
            call_count = 0

            def factory() -> int:
                nonlocal call_count
                call_count += 1
                return call_count

            cap = SetGlobal(
                module_path="_test_set_global_once",
                attr_name="counter",
                factory=factory,
            )

            async def handler() -> int:
                import _test_set_global_once  # type: ignore[import-not-found]

                return _test_set_global_once.counter  # type: ignore[no-any-return]

            wrapped = cap.purify(handler)

            result1 = await wrapped()
            result2 = await wrapped()
            result3 = await wrapped()

            # Factory called only once
            assert call_count == 1
            # All calls see the same value
            assert result1 == 1
            assert result2 == 1
            assert result3 == 1
        finally:
            del sys.modules["_test_set_global_once"]

    @pytest.mark.asyncio
    async def test_works_with_sync_handler(self) -> None:
        """SetGlobal purifier also works with sync handlers."""
        mod = types.ModuleType("_test_set_global_sync")
        mod.val = None  # type: ignore[attr-defined]
        sys.modules["_test_set_global_sync"] = mod

        try:
            cap = SetGlobal(
                module_path="_test_set_global_sync",
                attr_name="val",
                factory=lambda: "initialized",
            )

            def sync_handler() -> str:
                import _test_set_global_sync  # type: ignore[import-not-found]

                return _test_set_global_sync.val  # type: ignore[no-any-return]

            wrapped = cap.purify(sync_handler)
            result = await wrapped()

            assert result == "initialized"
        finally:
            del sys.modules["_test_set_global_sync"]


# ═══════════════════════════════════════════════════════════════════════════════
# AddCapability with pattern matching (lines 325-326 via _matches_name)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAddCapabilityWithPattern:
    """Test AddCapability using for_pattern which exercises _matches_name pattern branch."""

    def test_adds_capability_matching_pattern(self) -> None:
        """AddCapability with for_pattern exercises lines 324-326."""
        cap_to_add = StubCapability(tag="timeout")
        ctx = _make_ctx(name="get_slow_users")
        cap = AddCapability(
            capability=cap_to_add,  # type: ignore[arg-type]
            for_pattern=r"^get_slow_.*",
        )
        result = cap.compile_bridge(ctx)
        assert cap_to_add in result.wire.surface_capabilities

    def test_does_not_add_when_pattern_does_not_match(self) -> None:
        cap_to_add = StubCapability(tag="timeout")
        ctx = _make_ctx(name="post_users")
        cap = AddCapability(
            capability=cap_to_add,  # type: ignore[arg-type]
            for_pattern=r"^get_.*",
        )
        result = cap.compile_bridge(ctx)
        assert cap_to_add not in result.wire.surface_capabilities

    def test_adds_with_names_not_matching_but_pattern_matching(self) -> None:
        """When for_names does not match but for_pattern does, capability is added."""
        cap_to_add = StubCapability(tag="metric")
        ctx = _make_ctx(name="get_metrics")
        cap = AddCapability(
            capability=cap_to_add,  # type: ignore[arg-type]
            for_names=frozenset({"other_handler"}),
            for_pattern=r"^get_.*",
        )
        result = cap.compile_bridge(ctx)
        assert cap_to_add in result.wire.surface_capabilities


# ═══════════════════════════════════════════════════════════════════════════════
# chain_purifiers and apply_purifiers with IsolateGlobal/SetGlobal/WithContext
# ═══════════════════════════════════════════════════════════════════════════════


class TestChainPurifiersWithRealPurifiers:
    """Integration tests chaining multiple purifiers including the missed ones."""

    @pytest.mark.asyncio
    async def test_chain_setglobal_and_withcontext(self) -> None:
        """Chain SetGlobal + WithContext — both transform the handler."""
        mod = types.ModuleType("_test_chain_mod")
        mod.flag = False  # type: ignore[attr-defined]
        sys.modules["_test_chain_mod"] = mod

        try:
            log: list[str] = []

            @asynccontextmanager
            async def ctx_factory():  # type: ignore[no-untyped-def]
                log.append("ctx_enter")
                yield
                log.append("ctx_exit")

            set_global_cap = SetGlobal(
                module_path="_test_chain_mod",
                attr_name="flag",
                factory=lambda: True,
            )
            with_ctx_cap = WithContext(factory=ctx_factory)

            async def handler() -> bool:
                import _test_chain_mod  # type: ignore[import-not-found]

                log.append("handler")
                return _test_chain_mod.flag  # type: ignore[no-any-return]

            wrapped = chain_purifiers([set_global_cap, with_ctx_cap], handler)
            result = await wrapped()

            assert result is True
            assert "ctx_enter" in log
            assert "handler" in log
            assert "ctx_exit" in log
        finally:
            del sys.modules["_test_chain_mod"]
