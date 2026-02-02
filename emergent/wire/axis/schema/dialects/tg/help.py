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

from dataclasses import dataclass

from emergent.wire.axis.schema._universal import (
    SchemaCapability,
    schema_meta,
    get_schema_capability,
)


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
    """Get Command capability from request class."""
    cap = get_schema_capability(cls, Command)
    if isinstance(cap, Command):
        return cap
    return Command()


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
