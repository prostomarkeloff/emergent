"""Compose dialect — nodnod node composition directives.

Tells compiler how to compose field values from nodnod nodes.
Any compiler with nodnod integration reads these.

    from emergent.wire.axis.schema.dialects import compose

    @dataclass
    class TelegramBalanceRequest:
        chat_id: Annotated[int, compose.Node(ChatId)]

        def to_auth(self) -> TelegramIdentity:
            return TelegramIdentity(chat_id=self.chat_id)
"""

from dataclasses import dataclass, replace
from typing import Any, Callable, TypeVar, TYPE_CHECKING

from emergent.wire.axis.schema._universal import SchemaAxisCapability

if TYPE_CHECKING:
    from emergent.wire.axis._capability import RequestBuildContext


T = TypeVar("T")


class ComposeCapability(SchemaAxisCapability):
    """Base for nodnod composition capabilities."""

    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Node Composition
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Node(ComposeCapability):
    """Compose field value from nodnod node.

    Example:
        chat_id: Annotated[int, compose.Node(ChatId)]
        user: Annotated[User, compose.Node(UserNode, default=guest)]
    """
    node_type: type
    default: Any = None
    map: Callable[[Any], Any] | None = None

    def compile_request_build(self, ctx: "RequestBuildContext") -> "RequestBuildContext":
        return replace(ctx,
            compose_node=self.node_type,
            compose_node_default=self.default,
            compose_node_map=self.map,
        )


@dataclass(frozen=True, slots=True)
class Optional(ComposeCapability):
    """Compose node, wrap in Option (Nothing if fails).

    Example:
        admin: Annotated[Option[AdminUser], compose.Optional(AdminNode)]
    """
    node_type: type

    def compile_request_build(self, ctx: "RequestBuildContext") -> "RequestBuildContext":
        return replace(ctx, compose_optional_node=self.node_type)


@dataclass(frozen=True, slots=True)
class Fallback(ComposeCapability):
    """Fallback chain — first successful node wins (SequentialEither).

    Example:
        user: Annotated[User, compose.Fallback(CachedUser, DBUser, GuestUser)]
    """

    node_types: tuple[type, ...]

    def __init__(self, *node_types: type) -> None:
        object.__setattr__(self, "node_types", node_types)

    def compile_request_build(self, ctx: "RequestBuildContext") -> "RequestBuildContext":
        return replace(ctx, compose_fallback_nodes=self.node_types)


@dataclass(frozen=True, slots=True)
class Race(ComposeCapability):
    """Concurrent race — fastest node wins (ConcurrentEither).

    Example:
        data: Annotated[Data, compose.Race(API1, API2, API3)]
    """
    node_types: tuple[type, ...]

    def __init__(self, *node_types: type) -> None:
        object.__setattr__(self, "node_types", node_types)

    def compile_request_build(self, ctx: "RequestBuildContext") -> "RequestBuildContext":
        return replace(ctx, compose_race_nodes=self.node_types)


# ═══════════════════════════════════════════════════════════════════════════════
# Scope Retrieval
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Retrieve(ComposeCapability):
    """Retrieve value directly from scope by type (no composition).

    Renamed from Inject to clarify this READS from scope.
    (enricher.Inject WRITES to scope)

    Example:
        auth_user: Annotated[AuthUser, compose.Retrieve(AuthUser)]
    """

    from_type: type

    def compile_request_build(self, ctx: "RequestBuildContext") -> "RequestBuildContext":
        return replace(ctx, compose_retrieve_type=self.from_type)


__all__ = (
    "ComposeCapability",
    # Node composition
    "Node",
    "Optional",
    "Fallback",
    "Race",
    # Scope retrieval
    "Retrieve",
)
