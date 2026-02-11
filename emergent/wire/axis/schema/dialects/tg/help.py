"""Telegram help generation — schema-level capabilities.

Two approaches supported:

1. Decorators (simple cases):
    @tg.help.command("Create account", order=1)
    @dataclass
    class RegisterRequest: ...

2. Explicit in generate_help_from_command_rules (i18n, overrides decorators):
    generate_help_from_command_rules(
        app,
        get_description=lambda cls: i18n.t(f"cmd.{cls.__name__}"),
        order=[RegisterRequest, LoginRequest],
    )

Explicit parameters always override decorators.
"""

from dataclasses import dataclass, replace
from typing import Protocol, runtime_checkable

from emergent.wire.axis.schema._universal import (
    SchemaCapability,
    schema_meta,
)


@dataclass(frozen=True, slots=True)
class TgHelpContext:
    """Fold context for Telegram help metadata."""
    description: str | None = None
    order: int = 100
    hidden: bool = False


@runtime_checkable
class TgHelpCompilable(Protocol):
    """Protocol for schema-level capabilities that contribute to TG help."""

    def compile_tg_help(self, ctx: TgHelpContext) -> TgHelpContext:
        ...


@dataclass(frozen=True, slots=True)
class Command(SchemaCapability):
    """Help metadata for a Telegram command.

    Attributes:
        description: Human-readable description for /help
        order: Sort order in help list (lower = first)
        hidden: If True, hide from /help output
    """
    description: str | None = None
    order: int = 100
    hidden: bool = False

    def compile_tg_help(self, ctx: TgHelpContext) -> TgHelpContext:
        return replace(ctx, description=self.description, order=self.order, hidden=self.hidden)


def command(description: str, *, order: int = 100):
    """Decorator shortcut for Command capability.

    Example:
        @tg.help.command("Create new account", order=1)
        @dataclass
        class RegisterRequest:
            ...
    """
    return schema_meta(Command(description=description, order=order))


def hidden():
    """Decorator to hide command from help.

    Example:
        @tg.help.hidden()
        @dataclass
        class DebugRequest:
            ...
    """
    return schema_meta(Command(hidden=True))


def get_command(cls: type) -> Command:
    """Get Command capability from request class via fold_schema."""
    from emergent.wire.compile._core import fold_schema
    ctx = fold_schema(cls, TgHelpContext(), TgHelpCompilable, "compile_tg_help")
    return Command(description=ctx.description, order=ctx.order, hidden=ctx.hidden)


def is_hidden(cls: type) -> bool:
    """Check if request class is hidden from help."""
    return get_command(cls).hidden


__all__ = (
    "Command",
    "command",
    "hidden",
    "get_command",
    "is_hidden",
)
