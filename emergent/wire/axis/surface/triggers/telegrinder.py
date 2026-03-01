"""Telegrinder trigger — expose endpoints as Telegram bot handlers."""

from __future__ import annotations

from dataclasses import dataclass

from emergent.wire._telegrinder_compat import ABCRule


@dataclass(frozen=True, slots=True)
class TelegrinderTrigger:
    """Trigger for telegrinder bot handler.

    Rules filter which Telegram updates match this endpoint.
    The view specifies which ViewBox attribute to register on
    (message, callback_query, etc.).

        from telegrinder.bot.rules import Command

        trigger = TelegrinderTrigger(Command("start"), view="message")

    Rules are variadic to match telegrinder's decorator syntax::

        # telegrinder native:
        @dp.message(Command("start"), Text("/hello"))
        async def handler(...): ...

        # wire equivalent:
        TelegrinderTrigger(Command("start"), Text("/hello"), view="message")
    """

    rules: tuple["ABCRule", ...]
    view: str = "message"

    def __init__(self, *rules: "ABCRule", view: str = "message") -> None:
        object.__setattr__(self, "rules", rules)
        object.__setattr__(self, "view", view)


# Backward compatibility alias
TelegrindTrigger = TelegrinderTrigger
