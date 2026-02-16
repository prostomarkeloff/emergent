"""Telegram trigger aliases — tg_command, tg_callback, tg_delegate.

tg_command and tg_callback are thin wrappers around method() that create
TelegrindTrigger with the appropriate telegrinder rules.

tg_delegate creates a DelegateCodec exposure — full telegrinder access
with compose.Node DI still working. Use for one-off interactive UI
that doesn't fit patterns.

    from derivelib.patterns.tg.methods import tg_command, tg_callback, tg_delegate

    @derive(methods)
    @dataclass
    class MyBot:
        @classmethod
        @tg_command("start")
        async def start(cls, ...) -> Result[str, DomainError]: ...

        @classmethod
        @tg_callback(MoveCard)
        async def move(cls, data: MoveCard) -> Result[str, DomainError]: ...

        @classmethod
        @tg_delegate("comments")
        async def show_comments(cls, message: MessageCute, db: ...) -> None: ...
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar, get_type_hints

from telegrinder.bot.rules.abc import ABCRule
from telegrinder.tools.serialization.abc import ModelType
from telegrinder.bot.rules.command import Command
from telegrinder.bot.rules.payload import PayloadModelRule

from emergent.wire.axis.surface import Exposure
from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger

from derivelib._ctx import SurfaceCtx
from derivelib.patterns.methods import method

F = TypeVar("F", bound=Callable[..., object])

DELEGATE_ENTRIES_ATTR = "__delegate_entries__"


# ═══════════════════════════════════════════════════════════════════════════════
# Delegate entry — parallel to _TriggerEntry but produces DelegateCodec
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class _DelegateEntry:
    """A delegate trigger attached to a method — produces DelegateCodec."""

    trigger: TelegrindTrigger
    capabilities: tuple[SurfaceCapability, ...]
    description: str | None = None
    order: int = 100


# ═══════════════════════════════════════════════════════════════════════════════
# TG command — alias for method(TelegrindTrigger(Command(name)))
# ═══════════════════════════════════════════════════════════════════════════════


def tg_command(
    name: str,
    *caps: SurfaceCapability,
    description: str | None = None,
    order: int = 100,
) -> Callable[[F], F]:
    """Telegram /command trigger.

    Equivalent to ``method(TelegrindTrigger(Command(name)), *caps)``.

        @classmethod
        @tg_command("start", description="Start the bot", order=1)
        async def start(cls) -> Result[str, DomainError]:
            return Ok("Hello!")
    """
    return method(TelegrindTrigger(Command(name)), *caps, description=description, order=order)


# ═══════════════════════════════════════════════════════════════════════════════
# TG callback — PayloadModelRule or string template
# ═══════════════════════════════════════════════════════════════════════════════


def tg_callback(
    model: type[ModelType],
    *caps: SurfaceCapability,
) -> Callable[[F], F]:
    """Telegram callback_query trigger with typed payload model.

    Uses telegrinder's PayloadModelRule for type-safe callback_data matching.
    The model should be a dataclass or msgspec.Struct.

        @dataclass
        class MoveCard:
            card_id: int
            target_column_id: int

        @classmethod
        @tg_callback(MoveCard)
        async def move(cls, data: MoveCard) -> Result[str, DomainError]: ...
    """
    trigger = TelegrindTrigger(PayloadModelRule(model), view="callback_query")
    return method(trigger, *caps)


# ═══════════════════════════════════════════════════════════════════════════════
# TG delegate — DelegateCodec escape hatch
# ═══════════════════════════════════════════════════════════════════════════════


def tg_delegate(
    *rules: ABCRule,
    caps: tuple[SurfaceCapability, ...] = (),
    view: str = "message",
    description: str | None = None,
    order: int = 100,
) -> Callable[[F], F]:
    """Telegram delegate — full telegrinder access via DelegateCodec.

    The handler receives raw telegrinder types (MessageCute, CallbackQueryCute)
    and has full control. compose.Node DI still works.

    Accepts raw telegrinder rules for maximum flexibility::

        @classmethod
        @tg_delegate(Command("comments"), description="Show comments")
        async def show_comments(cls, message: MessageCute, db: ...) -> None:
            await message.answer("Comments:", reply_markup=kb.get_markup())

        @classmethod
        @tg_delegate(PayloadModelRule(CommentCB), view="callback_query")
        async def handle_cb(cls, cb: CallbackQueryCute, data: CommentCB) -> None: ...

    Args:
        *rules: Telegrinder rules (e.g. Command("start"), PayloadModelRule(Model)).
        caps: Surface capabilities.
        view: Telegrinder view to register on ("message" or "callback_query").
        description: Help description for /help generation.
        order: Sort order for /help generation.
    """
    trigger = TelegrindTrigger(*rules, view=view)
    entry = _DelegateEntry(trigger, caps, description=description, order=order)

    def decorator(fn: F) -> F:
        entries: list[_DelegateEntry] = getattr(fn, DELEGATE_ENTRIES_ATTR, [])
        entries.append(entry)
        setattr(fn, DELEGATE_ENTRIES_ATTR, entries)
        return fn

    return decorator


# ═══════════════════════════════════════════════════════════════════════════════
# ExposeDelegateMethod — surface step for delegate methods
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ExposeDelegateMethod:
    """Wrap method as DelegateCodec exposure.

    Unlike ExposeMethod (which builds RRC), this preserves the original
    handler signature. The telegrinder compiler calls the handler directly
    with compose.Node DI resolution.
    """

    service: type
    method_name: str
    trigger: TelegrindTrigger
    capabilities: tuple[SurfaceCapability, ...]
    description: str | None = None
    order: int = 100

    def derive_surface[EntityT](self, ctx: SurfaceCtx[EntityT]) -> SurfaceCtx[EntityT]:
        raw_attr = inspect.getattr_static(self.service, self.method_name)

        if isinstance(raw_attr, staticmethod):
            # getattr returns the unwrapped function with correct annotations
            handler = getattr(self.service, self.method_name)
        elif isinstance(raw_attr, classmethod):
            # getattr returns bound classmethod (cls already bound)
            bound = getattr(self.service, self.method_name)

            async def handler(*args: object, **kwargs: object) -> object:  # noqa: E501 — unavoidable: generic forwarding wrapper
                return await bound(*args, **kwargs)

            # Copy type hints without cls for DI resolution
            hints = get_type_hints(bound, include_extras=True)
            handler.__annotations__ = {
                k: v for k, v in hints.items() if k != "cls"
            }
            object.__setattr__(
                handler, "__signature__", inspect.signature(bound),
            )
        else:
            # Plain method: self is always None
            method_fn = getattr(self.service, self.method_name)

            async def handler(*args: object, **kwargs: object) -> object:  # noqa: E501 — unavoidable: generic forwarding wrapper
                return await method_fn(None, *args, **kwargs)

            hints = get_type_hints(method_fn, include_extras=True)
            handler.__annotations__ = {
                k: v for k, v in hints.items() if k != "self"
            }
            sig = inspect.signature(method_fn)
            object.__setattr__(
                handler,
                "__signature__",
                sig.replace(
                    parameters=[
                        p for n, p in sig.parameters.items() if n != "self"
                    ],
                ),
            )

        caps: tuple[SurfaceCapability, ...] = self.capabilities
        if self.description is not None:
            from emergent.wire.axis.surface.dialects.telegram import HelpMeta
            caps = (*caps, HelpMeta(description=self.description, order=self.order))

        codec = DelegateCodec(handler=handler)
        exposure = Exposure(
            trigger=self.trigger,
            codec=codec,
            capabilities=tuple(caps),
        )

        # DelegateCodec bypasses the ops runner — create sentinel operation
        from derivelib._codegen import create_sentinel_operation

        op_type, op_handler = create_sentinel_operation(
            f"{self.service.__name__}{self.method_name.title()}DelegateOp",
        )
        return ctx.add_operation((op_type, op_handler, exposure))


__all__ = (
    # Decorators
    "tg_command",
    "tg_callback",
    "tg_delegate",
    # Step
    "ExposeDelegateMethod",
    # Entry (for MethodsPattern integration)
    "_DelegateEntry",
    "DELEGATE_ENTRIES_ATTR",
)
