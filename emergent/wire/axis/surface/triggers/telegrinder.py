"""Telegrinder trigger — expose endpoints as Telegram bot handlers."""

from __future__ import annotations

from dataclasses import dataclass

from emergent.wire._telegrinder_compat import ABCRule
from emergent.wire.axis._explain import ExplainContext, ExplainNode


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

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        fields: tuple[tuple[str, str | list[str]], ...] = (("view", self.view),)
        if self.rules:
            fields = (*fields, ("rules", [type(r).__name__ for r in self.rules]))
        return ctx.add(ExplainNode("TelegrinderTrigger", fields))


# Backward compatibility alias
TelegrindTrigger = TelegrinderTrigger
