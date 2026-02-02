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

from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from emergent.wire.axis.schema._universal import Capability


T = TypeVar("T")


class ComposeCapability(Capability):
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


@dataclass(frozen=True, slots=True)
class Optional(ComposeCapability):
    """Compose node, wrap in Option (Nothing if fails).

    Example:
        admin: Annotated[Option[AdminUser], compose.Optional(AdminNode)]
    """
    node_type: type


@dataclass(frozen=True, slots=True)
class Either(ComposeCapability):
    """Fallback chain — first successful node wins (SequentialEither).

    Example:
        user: Annotated[User, compose.Either(CachedUser, DBUser, GuestUser)]
    """
    node_types: tuple[type, ...]

    def __init__(self, *node_types: type) -> None:
        object.__setattr__(self, "node_types", node_types)


@dataclass(frozen=True, slots=True)
class Race(ComposeCapability):
    """Concurrent race — fastest node wins (ConcurrentEither).

    Example:
        data: Annotated[Data, compose.Race(API1, API2, API3)]
    """
    node_types: tuple[type, ...]

    def __init__(self, *node_types: type) -> None:
        object.__setattr__(self, "node_types", node_types)


# ═══════════════════════════════════════════════════════════════════════════════
# Scope Injection
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Inject(ComposeCapability):
    """Inject value directly from scope (no composition).

    Example:
        auth_user: Annotated[AuthUser, compose.Inject(AuthUser)]
    """
    inject_type: type


__all__ = (
    "ComposeCapability",
    # Node composition
    "Node",
    "Optional",
    "Either",
    "Race",
    # Injection
    "Inject",
)
