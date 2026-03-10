"""Tests for derivelib.patterns.methods — method-level triggers and MethodsPattern."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from kungfu import Ok, Result

from emergent.wire.axis.schema import Identity
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

from derivelib._derive import derive, derive_endpoints
from derivelib import DomainError
from derivelib.patterns.methods import (
    MethodsPattern,
    TRIGGER_ENTRIES_ATTR,
    command,
    delete,
    get,
    method,
    methods,
    patch,
    post,
    put,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Calling conventions: @classmethod, @staticmethod, plain
# ═══════════════════════════════════════════════════════════════════════════════


class TestClassmethod:
    def test_classmethod_preserved(self) -> None:
        @dataclass
        class SVC:
            @classmethod
            @post("/test")
            async def create(cls) -> Result[int, DomainError]:
                return Ok(1)

        raw = SVC.__dict__["create"]
        assert isinstance(raw, classmethod)

    def test_classmethod_trigger_entries(self) -> None:
        @dataclass
        class SVC:
            @classmethod
            @post("/test")
            async def create(cls) -> Result[int, DomainError]:
                return Ok(1)

        raw = SVC.__dict__["create"]
        fn = raw.__func__
        entries = getattr(fn, TRIGGER_ENTRIES_ATTR, [])
        assert len(entries) == 1
        assert isinstance(entries[0].trigger, HTTPRouteTrigger)

    def test_classmethod_multi_trigger(self) -> None:
        @dataclass
        class SVC:
            @classmethod
            @post("/api/create")
            @command("create-item")
            async def create(cls) -> Result[int, DomainError]:
                return Ok(1)

        raw = SVC.__dict__["create"]
        fn = raw.__func__
        entries = getattr(fn, TRIGGER_ENTRIES_ATTR, [])
        assert len(entries) == 2


class TestStaticmethod:
    def test_staticmethod_preserved(self) -> None:
        @dataclass
        class SVC:
            @staticmethod
            @post("/test")
            async def health() -> Result[str, DomainError]:
                return Ok("ok")

        raw = SVC.__dict__["health"]
        assert isinstance(raw, staticmethod)

    def test_staticmethod_trigger_entries(self) -> None:
        @dataclass
        class SVC:
            @staticmethod
            @post("/test")
            async def health() -> Result[str, DomainError]:
                return Ok("ok")

        raw = SVC.__dict__["health"]
        fn = raw.__func__
        entries = getattr(fn, TRIGGER_ENTRIES_ATTR, [])
        assert len(entries) == 1


class TestPlainMethod:
    def test_plain_method_not_wrapped(self) -> None:
        @dataclass
        class SVC:
            @post("/test")
            async def action(self) -> Result[int, DomainError]:
                return Ok(1)

        raw = SVC.__dict__["action"]
        assert not isinstance(raw, classmethod)
        assert not isinstance(raw, staticmethod)

    def test_plain_method_trigger_entries(self) -> None:
        @dataclass
        class SVC:
            @post("/test")
            async def action(self, x: int) -> Result[int, DomainError]:
                return Ok(x)

        raw = SVC.__dict__["action"]
        entries = getattr(raw, TRIGGER_ENTRIES_ATTR, [])
        assert len(entries) == 1

    def test_plain_function_no_self(self) -> None:
        @dataclass
        class SVC:
            @post("/test")
            async def action(x: int) -> Result[int, DomainError]:
                return Ok(x)

        raw = SVC.__dict__["action"]
        assert not isinstance(raw, classmethod)
        entries = getattr(raw, TRIGGER_ENTRIES_ATTR, [])
        assert len(entries) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP aliases
# ═══════════════════════════════════════════════════════════════════════════════


class TestHTTPAliases:
    def test_post(self) -> None:
        @dataclass
        class SVC:
            @classmethod
            @post("/test")
            async def create(cls) -> Result[int, DomainError]:
                return Ok(1)

        fn = SVC.__dict__["create"].__func__
        entries = getattr(fn, TRIGGER_ENTRIES_ATTR, [])
        assert isinstance(entries[0].trigger, HTTPRouteTrigger)
        assert entries[0].trigger.method == "POST"

    def test_get(self) -> None:
        @dataclass
        class SVC:
            @classmethod
            @get("/test")
            async def list_all(cls) -> Result[list, DomainError]:
                return Ok([])

        fn = SVC.__dict__["list_all"].__func__
        assert getattr(fn, TRIGGER_ENTRIES_ATTR, [])[0].trigger.method == "GET"

    def test_put(self) -> None:
        @dataclass
        class SVC:
            @classmethod
            @put("/test")
            async def update(cls) -> Result[int, DomainError]:
                return Ok(1)

        fn = SVC.__dict__["update"].__func__
        assert getattr(fn, TRIGGER_ENTRIES_ATTR, [])[0].trigger.method == "PUT"

    def test_delete(self) -> None:
        @dataclass
        class SVC:
            @classmethod
            @delete("/test")
            async def remove(cls) -> Result[bool, DomainError]:
                return Ok(True)

        fn = SVC.__dict__["remove"].__func__
        assert getattr(fn, TRIGGER_ENTRIES_ATTR, [])[0].trigger.method == "DELETE"

    def test_patch(self) -> None:
        @dataclass
        class SVC:
            @classmethod
            @patch("/test")
            async def partial_update(cls) -> Result[int, DomainError]:
                return Ok(1)

        fn = SVC.__dict__["partial_update"].__func__
        assert getattr(fn, TRIGGER_ENTRIES_ATTR, [])[0].trigger.method == "PATCH"


# ═══════════════════════════════════════════════════════════════════════════════
# CLI alias
# ═══════════════════════════════════════════════════════════════════════════════


class TestCommandAlias:
    def test_cli_trigger(self) -> None:
        @dataclass
        class SVC:
            @classmethod
            @command("do-stuff")
            async def do_stuff(cls) -> Result[int, DomainError]:
                return Ok(1)

        fn = SVC.__dict__["do_stuff"].__func__
        entries = getattr(fn, TRIGGER_ENTRIES_ATTR, [])
        assert isinstance(entries[0].trigger, CLITrigger)


# ═══════════════════════════════════════════════════════════════════════════════
# MethodsPattern — end-to-end via derive_endpoints
# ═══════════════════════════════════════════════════════════════════════════════


class TestMethodsPattern:
    def test_single_method(self) -> None:
        @dataclass
        class SVC:
            id: Annotated[int, Identity]

            @classmethod
            @post("/api/create")
            async def create(cls) -> Result[int, DomainError]:
                return Ok(1)

        endpoints = derive_endpoints(SVC, methods)
        total = sum(len(ep.exposures) for ep in endpoints)
        assert total == 1

    def test_two_methods(self) -> None:
        @dataclass
        class SVC:
            id: Annotated[int, Identity]

            @classmethod
            @post("/api/create")
            async def create(cls) -> Result[int, DomainError]:
                return Ok(1)

            @classmethod
            @get("/api/list")
            async def list_all(cls) -> Result[list, DomainError]:
                return Ok([])

        endpoints = derive_endpoints(SVC, methods)
        total = sum(len(ep.exposures) for ep in endpoints)
        assert total == 2

    def test_all_three_conventions(self) -> None:
        @dataclass
        class SVC:
            id: Annotated[int, Identity]

            @classmethod
            @post("/api/create")
            async def create(cls) -> Result[int, DomainError]:
                return Ok(1)

            @staticmethod
            @get("/api/health")
            async def health() -> Result[str, DomainError]:
                return Ok("ok")

            @post("/api/do")
            async def do_thing(self, x: int) -> Result[int, DomainError]:
                return Ok(x)

        endpoints = derive_endpoints(SVC, methods)
        total = sum(len(ep.exposures) for ep in endpoints)
        assert total == 3

    def test_skips_private_methods(self) -> None:
        @dataclass
        class SVC:
            id: Annotated[int, Identity]

            @classmethod
            @post("/api/create")
            async def create(cls) -> Result[int, DomainError]:
                return Ok(1)

            async def _internal(self) -> None:
                pass

        endpoints = derive_endpoints(SVC, methods)
        total = sum(len(ep.exposures) for ep in endpoints)
        assert total == 1

    def test_multiple_triggers_per_method(self) -> None:
        @dataclass
        class SVC:
            id: Annotated[int, Identity]

            @classmethod
            @post("/api/create")
            @command("create")
            async def create(cls) -> Result[int, DomainError]:
                return Ok(1)

        endpoints = derive_endpoints(SVC, methods)
        total = sum(len(ep.exposures) for ep in endpoints)
        assert total == 2

    def test_default_methods_has_error_caps(self) -> None:
        assert len(methods.capabilities) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# End-to-end
# ═══════════════════════════════════════════════════════════════════════════════


class TestMethodsEndToEnd:
    def test_classmethod_compile_to_endpoints(self) -> None:
        @dataclass
        class SVC:
            id: Annotated[int, Identity]

            @classmethod
            @post("/api/create")
            async def create(cls, name: str) -> Result[int, DomainError]:
                return Ok(1)

        endpoints = derive_endpoints(SVC, methods)
        total = sum(len(ep.exposures) for ep in endpoints)
        assert total > 0

    def test_staticmethod_compile_to_endpoints(self) -> None:
        @dataclass
        class SVC:
            id: Annotated[int, Identity]

            @staticmethod
            @post("/api/health")
            async def health() -> Result[str, DomainError]:
                return Ok("ok")

        endpoints = derive_endpoints(SVC, methods)
        total = sum(len(ep.exposures) for ep in endpoints)
        assert total > 0

    def test_mixed_conventions_compile(self) -> None:
        @dataclass
        class SVC:
            id: Annotated[int, Identity]

            @classmethod
            @post("/api/create")
            async def create(cls, name: str) -> Result[int, DomainError]:
                return Ok(1)

            @staticmethod
            @get("/api/health")
            async def health() -> Result[str, DomainError]:
                return Ok("ok")

            @post("/api/action")
            async def action(self, x: int) -> Result[int, DomainError]:
                return Ok(x)

        endpoints = derive_endpoints(SVC, methods)
        total = sum(len(ep.exposures) for ep in endpoints)
        assert total == 3
