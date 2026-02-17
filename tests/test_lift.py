"""Tests for emergent/lift.py.

Covers:
1. from_result(Ok(42))  — unwrap and verify value
2. from_result(Error("x")) — unwrap error
3. from_awaitable()    — success path (async fn that returns value)
4. from_awaitable()    — exception caught by on_error
"""

from __future__ import annotations

import pytest
from kungfu import Error, LazyCoroResult, Ok, Result

from emergent.lift import from_awaitable, from_result


class TestFromResultOk:
    @pytest.mark.asyncio
    async def test_ok_value_is_preserved(self) -> None:
        ok_result: Result[int, str] = Ok(42)
        lazy: LazyCoroResult[int, str] = from_result(ok_result)
        result: Ok[int] | Error[str] = await lazy
        assert isinstance(result, Ok)
        assert result.value == 42

    @pytest.mark.asyncio
    async def test_ok_with_string_value(self) -> None:
        ok_result: Result[str, str] = Ok("hello")
        lazy: LazyCoroResult[str, str] = from_result(ok_result)
        result: Ok[str] | Error[str] = await lazy
        assert isinstance(result, Ok)
        assert result.value == "hello"


class TestFromResultError:
    @pytest.mark.asyncio
    async def test_error_is_preserved(self) -> None:
        err_result: Result[int, str] = Error("x")
        lazy: LazyCoroResult[int, str] = from_result(err_result)
        result: Ok[int] | Error[str] = await lazy
        assert isinstance(result, Error)
        assert result.error == "x"

    @pytest.mark.asyncio
    async def test_error_with_int_payload(self) -> None:
        err_result: Result[str, int] = Error(404)
        lazy: LazyCoroResult[str, int] = from_result(err_result)
        result: Ok[str] | Error[int] = await lazy
        assert isinstance(result, Error)
        assert result.error == 404


class TestFromAwaitableSuccess:
    @pytest.mark.asyncio
    async def test_success_path_returns_ok(self) -> None:
        async def async_fn() -> int:
            return 99

        lazy = from_awaitable(async_fn, on_error=lambda e: str(e))
        result = await lazy
        assert isinstance(result, Ok)
        assert result.value == 99

    @pytest.mark.asyncio
    async def test_success_path_with_string_return(self) -> None:
        async def async_fn() -> str:
            return "done"

        lazy = from_awaitable(async_fn, on_error=lambda e: repr(e))
        result = await lazy
        assert isinstance(result, Ok)
        assert result.value == "done"


class TestFromAwaitableError:
    @pytest.mark.asyncio
    async def test_exception_is_caught_by_on_error(self) -> None:
        async def async_fn() -> int:
            raise ValueError("boom")

        lazy = from_awaitable(async_fn, on_error=lambda e: f"caught: {e}")
        result = await lazy
        assert isinstance(result, Error)
        assert result.error == "caught: boom"

    @pytest.mark.asyncio
    async def test_on_error_receives_original_exception(self) -> None:
        exc = RuntimeError("failure")

        captured: list[Exception] = []

        def on_error(e: Exception) -> str:
            captured.append(e)
            return "error"

        async def async_fn() -> str:
            raise exc

        lazy = from_awaitable(async_fn, on_error=on_error)
        result = await lazy
        assert isinstance(result, Error)
        assert result.error == "error"
        assert len(captured) == 1
        assert captured[0] is exc
