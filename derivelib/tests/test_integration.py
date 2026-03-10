"""Integration tests — full pipeline from @derive to compiled application."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Annotated

from kungfu import Error, Ok, Result

from emergent.wire.axis.query import MutatingRelationalProvider, relational
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
from emergent.wire.axis.schema import Identity
from emergent.wire.axis.schema.dialects import compose

from derivelib import (
    build_application_from_decorated,
    derive,
    derive_endpoints,
    endpoint_count,
    memory_node,
)
from derivelib import DomainError, InvalidData
from derivelib.patterns.crud import CREATE, GET, LIST, http_crud
from derivelib.patterns.methods import get, methods, post
from derivelib.transforms import readonly, without_delete


class _Node:
    pass


_MethodsStore = memory_node()
_HybridBoard = memory_node()


# ═══════════════════════════════════════════════════════════════════════════════
# Pure CRUD
# ═══════════════════════════════════════════════════════════════════════════════


class TestPureCrud:
    def test_six_endpoints(self) -> None:
        @dataclass
        class Item:
            id: Annotated[int, Identity]
            name: str
            price: float

        endpoints = derive_endpoints(
            Item, http_crud("/api/items", provider_node=_Node)
        )
        assert len(endpoints) == 1
        assert len(endpoints[0].exposures) == 6

    def test_selected_ops(self) -> None:
        @dataclass
        class Item:
            id: Annotated[int, Identity]
            name: str

        endpoints = derive_endpoints(
            Item, http_crud("/api/items", provider_node=_Node, ops=(LIST, GET, CREATE))
        )
        assert len(endpoints[0].exposures) == 3

    def test_readonly_chain(self) -> None:
        @dataclass
        class Item:
            id: Annotated[int, Identity]
            name: str

        pattern = http_crud("/api/items", provider_node=_Node).chain(readonly())
        endpoints = derive_endpoints(Item, pattern)
        assert len(endpoints[0].exposures) == 2

    def test_without_delete_chain(self) -> None:
        @dataclass
        class Item:
            id: Annotated[int, Identity]
            name: str

        pattern = http_crud("/api/items", provider_node=_Node).chain(without_delete())
        endpoints = derive_endpoints(Item, pattern)
        assert len(endpoints[0].exposures) == 5


# ═══════════════════════════════════════════════════════════════════════════════
# Pure Methods
# ═══════════════════════════════════════════════════════════════════════════════


@derive(methods)
@dataclass
class _OrderService:
    @post("/api/orders")
    async def create(
        cls,
        db: Annotated[MemoryRelationalProvider, compose.Node(_MethodsStore)],
        customer: str,
    ) -> Result[int, DomainError]:
        return Ok(1)

    @get("/api/orders")
    async def list_all(
        cls,
        db: Annotated[MemoryRelationalProvider, compose.Node(_MethodsStore)],
    ) -> Result[list, DomainError]:
        return Ok([])


class TestPureMethods:
    def test_methods_endpoints(self) -> None:
        app = build_application_from_decorated(_OrderService)
        assert endpoint_count(app) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# CRUD + Methods (hybrid)
# ═══════════════════════════════════════════════════════════════════════════════


@derive(
    http_crud("/bounties", provider_node=_HybridBoard, ops=(LIST, GET, CREATE)),
    methods,
)
@dataclass
class _Bounty:
    id: Annotated[int, Identity]
    title: str
    reward: int
    status: str = "open"

    @classmethod
    @post("/bounties/{bounty_id}/claim")
    async def claim(
        cls,
        db: Annotated[MutatingRelationalProvider[_Bounty], compose.Node(_HybridBoard)],
        bounty_id: int,
    ) -> Result[_Bounty, DomainError]:
        return Ok(_Bounty(id=bounty_id, title="t", reward=0, status="claimed"))


class TestHybrid:
    def test_crud_plus_methods(self) -> None:
        app = build_application_from_decorated(_Bounty)
        # 3 CRUD + 1 method
        assert endpoint_count(app) == 4


# ═══════════════════════════════════════════════════════════════════════════════
# Multiple entities
# ═══════════════════════════════════════════════════════════════════════════════


class TestMultipleEntities:
    def test_two_entities(self) -> None:
        @derive(http_crud("/api/users", provider_node=_Node))
        @dataclass
        class UserEntity:
            id: Annotated[int, Identity]
            name: str

        @derive(http_crud("/api/posts", provider_node=_Node))
        @dataclass
        class PostEntity:
            id: Annotated[int, Identity]
            title: str

        app = build_application_from_decorated(UserEntity, PostEntity)
        assert endpoint_count(app) == 12  # 6 + 6
