"""Callback and command registry for TG pattern coordination.

Ensures no two patterns claim the same command or callback prefix.
Used by TGApp to validate at pattern-creation time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True, slots=True)
class CommandEntry:
    """Registered command with metadata for /help generation."""

    command: str
    pattern_kind: str
    description: str | None = None
    order: int = 100


@dataclass(frozen=True, slots=True)
class CallbackNamespace:
    """Registered callback prefix — must be globally unique."""

    prefix: str
    pattern_kind: str
    command: str


class CallbackCollision(ValueError):
    """Raised when two patterns claim the same callback prefix."""


class CommandCollision(ValueError):
    """Raised when two patterns claim the same command."""


@dataclass
class CallbackRegistry:
    """Compile-time registry for TG commands and callback prefixes.

    Mutable — TGApp calls register methods as patterns are created.
    Validates uniqueness eagerly: collision = immediate error.
    """

    _commands: dict[str, CommandEntry] = field(default_factory=lambda: dict[str, CommandEntry]())
    _callbacks: dict[str, CallbackNamespace] = field(default_factory=lambda: dict[str, CallbackNamespace]())

    def register_command(
        self,
        command: str,
        pattern_kind: str,
        description: str | None = None,
        order: int = 100,
    ) -> None:
        """Register a /command. Raises CommandCollision on duplicate."""
        if command in self._commands:
            existing = self._commands[command]
            raise CommandCollision(
                f"Command /{command} already registered "
                f"by {existing.pattern_kind} pattern"
            )
        self._commands[command] = CommandEntry(
            command=command,
            pattern_kind=pattern_kind,
            description=description,
            order=order,
        )

    def register_callback(
        self,
        prefix: str,
        pattern_kind: str,
        command: str,
    ) -> None:
        """Register a callback prefix. Raises CallbackCollision on duplicate."""
        if prefix in self._callbacks:
            existing = self._callbacks[prefix]
            raise CallbackCollision(
                f"Callback prefix '{prefix}' collision: "
                f"/{existing.command} ({existing.pattern_kind}) "
                f"vs /{command} ({pattern_kind})"
            )
        self._callbacks[prefix] = CallbackNamespace(
            prefix=prefix,
            pattern_kind=pattern_kind,
            command=command,
        )

    @property
    def commands(self) -> Sequence[CommandEntry]:
        """All registered commands, sorted by (order, command)."""
        return sorted(
            self._commands.values(),
            key=lambda c: (c.order, c.command),
        )

    @property
    def callback_namespaces(self) -> Sequence[CallbackNamespace]:
        """All registered callback namespaces."""
        return list(self._callbacks.values())


__all__ = (
    "CallbackCollision",
    "CallbackNamespace",
    "CallbackRegistry",
    "CommandCollision",
    "CommandEntry",
)
