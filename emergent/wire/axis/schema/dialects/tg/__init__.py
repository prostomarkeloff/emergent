"""Telegram dialect — formatting for Telegram targets.

Only formatting/structure. Text comes from Response data (i18n is your problem).

    from emergent.wire.axis.schema.dialects import tg

    @dataclass
    class BetResponse:
        result: Annotated[str, tg.Bold()]      # "✅ Won!" — already translated
        number: Annotated[int, tg.Code()]      # `7`
        payout: Annotated[int, tg.Bold()]      # *100*
"""

from dataclasses import dataclass
from typing import Literal

from emergent.wire.axis.schema._universal import SchemaAxisCapability


class TelegramCapability(SchemaAxisCapability):
    """Base for Telegram-specific capabilities."""

    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Text Style
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Style(TelegramCapability):
    """Text formatting style.

    Example:
        title: Annotated[str, tg.Style("bold")]
        code: Annotated[str, tg.Style("code")]
        secret: Annotated[str, tg.Style("spoiler")]
    """
    value: Literal["bold", "italic", "code", "pre", "strike", "underline", "spoiler"]
    language: str | None = None  # For "pre" only


# Shortcuts
def Bold() -> Style:
    return Style("bold")

def Italic() -> Style:
    return Style("italic")

def Code() -> Style:
    return Style("code")

def Pre(language: str | None = None) -> Style:
    return Style("pre", language=language)

def Strike() -> Style:
    return Style("strike")

def Spoiler() -> Style:
    return Style("spoiler")


# ═══════════════════════════════════════════════════════════════════════════════
# Layout
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Line(TelegramCapability):
    """Line break control.

    Example:
        title: Annotated[str, tg.Line()]  # newline after
        inline_label: Annotated[str, tg.Line(after=False)]  # no newline
    """
    after: bool = True
    before: bool = False


@dataclass(frozen=True, slots=True)
class Skip(TelegramCapability):
    """Skip this field in Telegram output.

    Example:
        internal_id: Annotated[str, tg.Skip()]
    """
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Command Arguments
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class CommandArg(TelegramCapability):
    """Mark field as command argument for /command parsing.

    Compiler generates telegrinder Argument from this.

    Example:
        @dataclass
        class RegisterRequest:
            login: Annotated[str, tg.CommandArg()]
            password: Annotated[str, tg.CommandArg()]

        # /register alice secret → login="alice", password="secret"

    For capturing rest of line (with spaces):
        @dataclass
        class CreateRequest:
            description: Annotated[str, tg.CommandArg(greedy=True)]

        # /create a game about numbers → description="a game about numbers"
    """
    optional: bool = False
    greedy: bool = False  # If True, captures rest of line (enables lazy mode)


# ═══════════════════════════════════════════════════════════════════════════════
# Buttons
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Button(TelegramCapability):
    """Inline keyboard button. Text comes from field value.

    Example:
        # Field value = button text
        action_btn: Annotated[str, tg.Button(callback="do:action")]
        link_btn: Annotated[str, tg.Button(url="https://...")]
    """
    callback: str | None = None
    url: str | None = None


@dataclass(frozen=True, slots=True)
class Keyboard(TelegramCapability):
    """Group nested buttons into keyboard.

    Example:
        buttons: Annotated[ButtonGroup, tg.Keyboard(columns=2)]
    """
    columns: int = 1


# Subdialects
from emergent.wire.axis.schema.dialects.tg import help


__all__ = (
    "TelegramCapability",
    # Style
    "Style",
    "Bold",
    "Italic",
    "Code",
    "Pre",
    "Strike",
    "Spoiler",
    # Layout
    "Line",
    "Skip",
    # Command
    "CommandArg",
    # Buttons
    "Button",
    "Keyboard",
    # Subdialects
    "help",
)
