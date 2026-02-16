"""tg_flow widget protocol — self-contained flow widgets.

Each widget implements FlowWidget protocol:
- render(ctx) → (text, keyboard | None)
- handle_message(message, ctx) → WidgetResult
- handle_callback(value, ctx) → WidgetResult

Flow generator dispatches via protocol, not isinstance chains.
Adding a new widget = one new class, zero changes to flow.py.
"""

from __future__ import annotations

import calendar
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, time
from enum import Enum
from typing import TYPE_CHECKING, Protocol, TypeVar, runtime_checkable

from kungfu import Option, Some

from telegrinder.tools.keyboard import Button, InlineButton, InlineKeyboard, Keyboard

from derivelib.patterns.tg.uilib.theme import DEFAULT_THEME, UITheme
from derivelib.patterns.tg.uilib.keyboard import build_column_grid

if TYPE_CHECKING:
    from telegrinder.bot.cute_types.message import MessageCute

F = TypeVar("F", bound=Callable[..., object])


# ═══════════════════════════════════════════════════════════════════════════════
# Validation annotations
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class MinLen:
    """Minimum text length validation.

        name: Annotated[str, TextInput("Name:"), MinLen(2)]
    """

    length: int


@dataclass(frozen=True, slots=True)
class MaxLen:
    """Maximum text length validation.

        name: Annotated[str, TextInput("Name:"), MaxLen(50)]
    """

    length: int


@dataclass(frozen=True, slots=True)
class Pattern:
    r"""Regex pattern validation.

        date: Annotated[str, TextInput("Date YYYY-MM-DD:"), Pattern(r"^\\d{4}-\\d{2}-\\d{2}$")]
    """

    regex: str


def _validate_text(
    text: str,
    validators: tuple[MinLen | MaxLen | Pattern, ...],
    theme: UITheme = DEFAULT_THEME,
) -> str | None:
    """Run validators on text input. Returns error message or None."""
    for v in validators:
        if isinstance(v, MinLen) and len(text) < v.length:
            return theme.errors.too_short.format(v.length)
        if isinstance(v, MaxLen) and len(text) > v.length:
            return theme.errors.too_long.format(v.length)
        if isinstance(v, Pattern) and not re.match(v.regex, text):
            return theme.errors.invalid_format.format(v.regex)
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Widget context
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class WidgetContext:
    """Context passed to widget protocol methods.

    Provides the widget with all information it needs to render,
    validate, and handle interactions.
    """

    flow_name: str
    field_name: str
    current_value: Option[object]  # Some(v) | Nothing()
    base_type: type
    validators: tuple[MinLen | MaxLen | Pattern, ...]
    is_optional: bool
    flow_state: Mapping[str, object] = field(default_factory=dict)
    dynamic_options: Mapping[str, str] = field(default_factory=dict)
    theme: UITheme = field(default_factory=UITheme)

    def callback_data(self, value: str) -> str:
        """Build callback_data JSON for flow inline buttons."""
        return json.dumps({"flow": self.flow_name, "value": value})

    def typed_value[T](self, expected: type[T], default: T) -> T:
        """Extract current_value if it matches expected type, else default."""
        if isinstance(self.current_value, Some):
            raw = self.current_value.value
            if isinstance(raw, expected):
                return raw
        return default


# ═══════════════════════════════════════════════════════════════════════════════
# Result algebra
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Stay:
    """Re-render without advancing (Counter inc/dec, Multiselect toggle)."""

    new_value: object  # value to store in flow state


@dataclass(frozen=True, slots=True)
class Advance:
    """Store value and advance to next step."""

    value: object  # final value for this field
    summary: str  # e.g. "Selected: Admin", "Value: 5"


@dataclass(frozen=True, slots=True)
class Reject:
    """Input rejected. Shows error."""

    message: str


@dataclass(frozen=True, slots=True)
class NoOp:
    """No action (e.g. Counter noop button)."""


type WidgetResult = Stay | Advance | Reject | NoOp

type AnyKeyboard = InlineKeyboard | Keyboard

from derivelib.patterns.tg.uilib.helpers import (  # noqa: E402
    checked_keyboard,
    handle_checked_cb,
    handle_radio_cb,
    no_options_reject,
    no_options_text,
    option_keyboard,
    parse_selected,
    radio_keyboard,
    reject_text,
)


# ═══════════════════════════════════════════════════════════════════════════════
# FlowWidget protocol
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class FlowWidget(Protocol):
    """Protocol for self-contained flow widgets.

    Each widget encapsulates its own rendering, message handling,
    and callback handling. The flow generator dispatches via this
    protocol instead of isinstance chains.

    Matches wire's fold dispatch pattern: @runtime_checkable Protocol,
    dispatch via isinstance(item, FlowWidget).
    """

    @property
    def prompt(self) -> str: ...

    @property
    def needs_callback(self) -> bool: ...

    async def render(self, ctx: WidgetContext) -> tuple[str, AnyKeyboard | None]: ...

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult: ...

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult: ...


# ═══════════════════════════════════════════════════════════════════════════════
# Concrete widgets
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TextInput:
    """Collect text from user message.

        name: Annotated[str, TextInput("What's your name?")]
    """

    prompt: str

    @property
    def needs_callback(self) -> bool:
        return False

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        return self.prompt, None

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        match message.text:
            case Some(text):
                pass
            case _:
                return Reject(message=ctx.theme.errors.send_text)

        error = _validate_text(text, ctx.validators, ctx.theme)
        if error is not None:
            return Reject(message=f"Invalid: {error}. Try again:")

        value: str | int | float | bool = text
        if ctx.base_type is int:
            try:
                value = int(text)
            except ValueError:
                return Reject(message=ctx.theme.errors.send_number)
        elif ctx.base_type is float:
            try:
                value = float(text)
            except ValueError:
                return Reject(message=ctx.theme.errors.send_number)
        elif ctx.base_type is bool:
            value = text.lower() in ("yes", "true", "1", "y")

        return Advance(value=value, summary=text)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        return Reject(message=ctx.theme.errors.send_text)


@dataclass(frozen=True, slots=True)
class Inline:
    """Inline keyboard single selection.

    Options are passed as keyword arguments: key=display_label.
    Use ``columns`` to control buttons per row (default 1).

        role: Annotated[str, Inline("Choose role:", admin="Admin", user="User")]
        size: Annotated[str, Inline("Size:", columns=3, xs="XS", s="S", m="M", l="L")]
    """

    prompt: str
    columns: int = 1
    options: dict[str, str] = field(default_factory=lambda: dict[str, str]())

    def __init__(self, prompt: str, *, columns: int = 1, **options: str) -> None:
        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "options", options)

    @property
    def needs_callback(self) -> bool:
        return True

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        kb = option_keyboard(ctx, self.options, self.columns)
        return self.prompt, kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        return reject_text(ctx)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        if value not in self.options:
            return NoOp()
        label = self.options[value]
        return Advance(value=value, summary=f"Selected: {label}")


@dataclass(frozen=True, slots=True)
class Confirm:
    """Yes/No inline keyboard.

        accept_tos: Annotated[bool, Confirm("Accept terms of service?")]
    """

    prompt: str
    yes_label: str = "Yes"
    no_label: str = "No"

    @property
    def needs_callback(self) -> bool:
        return True

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        kb = InlineKeyboard()
        kb.add(InlineButton(text=self.yes_label, callback_data=ctx.callback_data("yes")))
        kb.add(InlineButton(text=self.no_label, callback_data=ctx.callback_data("no")))
        return self.prompt, kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        return Reject(message=ctx.theme.errors.use_buttons)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        is_yes = value == "yes"
        label = self.yes_label if is_yes else self.no_label
        return Advance(value=is_yes, summary=f"Selected: {label}")


@dataclass(frozen=True, slots=True)
class Toggle:
    """One-tap boolean flip. Shows current state, tap to invert and advance.

    Unlike Confirm (which always asks "yes or no?"), Toggle shows the
    current value and flips it on tap. Ideal for settings.

        notifications: Annotated[bool, Toggle("Notifications")]
        dark_mode: Annotated[bool, Toggle("Dark mode", on="Enabled", off="Disabled")]
    """

    prompt: str
    on: str = "On"
    off: str = "Off"

    @property
    def needs_callback(self) -> bool:
        return True

    def _current(self, ctx: WidgetContext) -> bool:
        if isinstance(ctx.current_value, Some):
            raw: object = ctx.current_value.value
            if isinstance(raw, bool):
                return raw
        return False

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        current = self._current(ctx)
        icon = ctx.theme.selection.toggle_on if current else ctx.theme.selection.toggle_off
        label = self.on if current else self.off
        kb = InlineKeyboard()
        kb.add(InlineButton(
            text=f"{icon} {label}",
            callback_data=ctx.callback_data("toggle"),
        ))
        return self.prompt, kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        return Reject(message=ctx.theme.errors.use_button)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        if value == "toggle":
            current = self._current(ctx)
            new_val = not current
            label = self.on if new_val else self.off
            return Advance(value=new_val, summary=label)
        return NoOp()


@dataclass(frozen=True, slots=True)
class Counter:
    """Interactive +/- stepper for integer fields.

    Shows ``[−] [value] [+]`` inline keyboard with a Done button.
    User adjusts via buttons; Done finalizes and advances.

        amount: Annotated[int, Counter("How many?", min=1, max=100, step=5, default=10)]
    """

    prompt: str
    min: int = 0
    max: int = 999999
    step: int = 1
    default: int = 0

    @property
    def needs_callback(self) -> bool:
        return True

    def _current_value(self, ctx: WidgetContext) -> int:
        cv = ctx.current_value
        if isinstance(cv, Some):
            raw: object = cv.value
            if isinstance(raw, int):
                return raw
        return self.default

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        current = self._current_value(ctx)
        kb = InlineKeyboard()
        kb.add(InlineButton(text=ctx.theme.action.decrement, callback_data=ctx.callback_data("counter:dec")))
        kb.add(InlineButton(text=str(current), callback_data=ctx.callback_data("counter:noop")))
        kb.add(InlineButton(text=ctx.theme.action.increment, callback_data=ctx.callback_data("counter:inc")))
        kb.row()
        kb.add(InlineButton(text=ctx.theme.action.done, callback_data=ctx.callback_data("counter:done")))
        return self.prompt, kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        return reject_text(ctx)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        current = self._current_value(ctx)
        if value == "counter:inc":
            return Stay(new_value=min(current + self.step, self.max))
        elif value == "counter:dec":
            return Stay(new_value=max(current - self.step, self.min))
        elif value == "counter:done":
            return Advance(value=current, summary=f"Value: {current}")
        elif value == "counter:noop":
            return NoOp()
        return NoOp()


@dataclass(frozen=True, slots=True)
class Multiselect:
    """Toggle multiple items on/off with checkmarks.

    Shows options with ✅/⬜ prefix and a Done button.
    Selected keys stored as comma-separated string.

        tags: Annotated[str, Multiselect("Tags:", columns=2, python="Python", rust="Rust")]
    """

    prompt: str
    columns: int = 1
    min_selected: int = 0
    max_selected: int = 0  # 0 = unlimited
    options: dict[str, str] = field(default_factory=lambda: dict[str, str]())

    def __init__(
        self,
        prompt: str,
        *,
        columns: int = 1,
        min_selected: int = 0,
        max_selected: int = 0,
        **options: str,
    ) -> None:
        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "min_selected", min_selected)
        object.__setattr__(self, "max_selected", max_selected)
        object.__setattr__(self, "options", options)

    @property
    def needs_callback(self) -> bool:
        return True

    def _selected_set(self, ctx: WidgetContext) -> set[str]:
        return parse_selected(ctx)

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        selected = self._selected_set(ctx)
        kb = checked_keyboard(ctx, self.options, selected, self.columns)
        return self.prompt, kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        return reject_text(ctx)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        selected = self._selected_set(ctx)
        return handle_checked_cb(value, self.options, selected, ctx, "ms", self.min_selected, self.max_selected)


# ═══════════════════════════════════════════════════════════════════════════════
# Media widgets
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class PhotoInput:
    """Accept a photo from user.

        avatar: Annotated[str, PhotoInput("Send your avatar:")]

    Stores the file_id of the largest photo resolution.
    """

    prompt: str

    @property
    def needs_callback(self) -> bool:
        return False

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        return self.prompt, None

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        match message.photo:
            case Some(photos) if photos:
                file_id: str = photos[-1].file_id
                return Advance(value=file_id, summary="Photo uploaded")
            case _:
                return Reject(message=ctx.theme.errors.send_photo)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        return Reject(message=ctx.theme.errors.send_photo)


@dataclass(frozen=True, slots=True)
class DocumentInput:
    """Accept a document/file from user.

        resume: Annotated[str, DocumentInput("Upload your resume:")]

    Stores the file_id of the document.
    """

    prompt: str

    @property
    def needs_callback(self) -> bool:
        return False

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        return self.prompt, None

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        match message.document:
            case Some(doc):
                return Advance(value=doc.file_id, summary="Document uploaded")
            case _:
                return Reject(message=ctx.theme.errors.send_document)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        return Reject(message=ctx.theme.errors.send_document)


@dataclass(frozen=True, slots=True)
class LocationInput:
    """Accept a shared location from user.

        location: Annotated[tuple[float, float], LocationInput("Share your location:")]

    Stores (latitude, longitude) tuple.
    """

    prompt: str

    @property
    def needs_callback(self) -> bool:
        return False

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        return self.prompt, None

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        match message.location:
            case Some(loc):
                lat: float = loc.latitude
                lon: float = loc.longitude
                return Advance(
                    value=(lat, lon),
                    summary=f"Location: {lat:.4f}, {lon:.4f}",
                )
            case _:
                return Reject(message=ctx.theme.errors.send_location)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        return Reject(message=ctx.theme.errors.send_location)


# ═══════════════════════════════════════════════════════════════════════════════
# Radio — stateful single-select with Done
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Radio:
    """Single-select with visible selection state and Done button.

    Like Inline but user can change selection before confirming.

        role: Annotated[str, Radio("Role:", admin="Admin", user="User")]
    """

    prompt: str
    columns: int = 1
    options: dict[str, str] = field(default_factory=lambda: dict[str, str]())

    def __init__(self, prompt: str, *, columns: int = 1, **options: str) -> None:
        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "options", options)

    @property
    def needs_callback(self) -> bool:
        return True

    def _selected(self, ctx: WidgetContext) -> str:
        return ctx.typed_value(str, "")

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        kb = radio_keyboard(ctx, self.options, self._selected(ctx), self.columns)
        return self.prompt, kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        return reject_text(ctx)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        return handle_radio_cb(value, self.options, self._selected(ctx), ctx)


# ═══════════════════════════════════════════════════════════════════════════════
# DatePicker — calendar date selection
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class DatePicker:
    """Calendar-based date picker.

    Three views: month grid (default day view), month selector, year nav.

        deadline: Annotated[date, DatePicker("When?", min_date=date.today())]
    """

    prompt: str
    min_date: date | None = None
    max_date: date | None = None

    @property
    def needs_callback(self) -> bool:
        return True

    def _view_state(self, ctx: WidgetContext) -> dict[str, int | str]:
        cv = ctx.current_value
        if isinstance(cv, Some):
            raw: object = cv.value
            if isinstance(raw, dict):
                return raw  # type: ignore[return-value]
        today = date.today()
        return {"year": today.year, "month": today.month, "view": "day"}

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        vs = self._view_state(ctx)
        view = str(vs.get("view", "day"))
        year = int(vs.get("year", date.today().year))
        month = int(vs.get("month", date.today().month))

        kb = InlineKeyboard()

        if view == "day":
            month_name = calendar.month_name[month]
            kb.add(InlineButton(text=ctx.theme.nav.prev, callback_data=ctx.callback_data("dp:pm")))
            kb.add(InlineButton(text=f"{month_name} {year}", callback_data=ctx.callback_data("dp:mv")))
            kb.add(InlineButton(text=ctx.theme.nav.next, callback_data=ctx.callback_data("dp:nm")))
            kb.row()

            for day_name in ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"):
                kb.add(InlineButton(text=day_name, callback_data=ctx.callback_data("dp:noop")))
            kb.row()

            for week in calendar.monthcalendar(year, month):
                for day_num in week:
                    if day_num == 0:
                        kb.add(InlineButton(text=" ", callback_data=ctx.callback_data("dp:noop")))
                    else:
                        d = date(year, month, day_num)
                        enabled = True
                        if self.min_date is not None and d < self.min_date:
                            enabled = False
                        if self.max_date is not None and d > self.max_date:
                            enabled = False
                        if enabled:
                            kb.add(InlineButton(
                                text=str(day_num),
                                callback_data=ctx.callback_data(f"dp:d:{d.isoformat()}"),
                            ))
                        else:
                            kb.add(InlineButton(
                                text=ctx.theme.display.disabled_date,
                                callback_data=ctx.callback_data("dp:noop"),
                            ))
                kb.row()

        elif view == "month":
            kb.add(InlineButton(text=ctx.theme.nav.prev, callback_data=ctx.callback_data("dp:py")))
            kb.add(InlineButton(text=str(year), callback_data=ctx.callback_data("dp:noop")))
            kb.add(InlineButton(text=ctx.theme.nav.next, callback_data=ctx.callback_data("dp:ny")))
            kb.row()

            for row_start in range(1, 13, 3):
                for m in range(row_start, row_start + 3):
                    name = calendar.month_abbr[m]
                    kb.add(InlineButton(
                        text=name,
                        callback_data=ctx.callback_data(f"dp:m:{m}"),
                    ))
                kb.row()

        return self.prompt, kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        return Reject(message=ctx.theme.errors.use_calendar)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        vs = self._view_state(ctx)
        year = int(vs.get("year", date.today().year))
        month = int(vs.get("month", date.today().month))

        if value == "dp:pm":
            month -= 1
            if month < 1:
                month, year = 12, year - 1
            return Stay(new_value={"year": year, "month": month, "view": "day"})
        elif value == "dp:nm":
            month += 1
            if month > 12:
                month, year = 1, year + 1
            return Stay(new_value={"year": year, "month": month, "view": "day"})
        elif value == "dp:py":
            return Stay(new_value={"year": year - 1, "month": month, "view": "month"})
        elif value == "dp:ny":
            return Stay(new_value={"year": year + 1, "month": month, "view": "month"})
        elif value == "dp:mv":
            return Stay(new_value={"year": year, "month": month, "view": "month"})
        elif value.startswith("dp:m:"):
            m = int(value[5:])
            return Stay(new_value={"year": year, "month": m, "view": "day"})
        elif value.startswith("dp:d:"):
            d = date.fromisoformat(value[5:])
            return Advance(value=d, summary=d.strftime(ctx.theme.display.date_format))
        elif value == "dp:noop":
            return NoOp()
        return NoOp()


# ═══════════════════════════════════════════════════════════════════════════════
# ScrollingInline — paginated option selection
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ScrollingInline:
    """Paginated inline selection for large option sets.

        category: Annotated[str, ScrollingInline("Category:", page_size=6, **many_options)]
    """

    prompt: str
    columns: int = 1
    page_size: int = 6
    options: dict[str, str] = field(default_factory=lambda: dict[str, str]())

    def __init__(
        self,
        prompt: str,
        *,
        columns: int = 1,
        page_size: int = 6,
        **options: str,
    ) -> None:
        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "page_size", page_size)
        object.__setattr__(self, "options", options)

    @property
    def needs_callback(self) -> bool:
        return True

    def _current_page(self, ctx: WidgetContext) -> int:
        cv = ctx.current_value
        if isinstance(cv, Some):
            raw: object = cv.value
            if isinstance(raw, int):
                return raw
        return 0

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        page = self._current_page(ctx)
        keys = list(self.options.keys())
        total = len(keys)
        total_pages = max(1, (total + self.page_size - 1) // self.page_size)
        page = min(page, total_pages - 1)

        start = page * self.page_size
        end = min(start + self.page_size, total)
        page_keys = keys[start:end]

        kb = InlineKeyboard()
        items = [(self.options[key], ctx.callback_data(key)) for key in page_keys]
        build_column_grid(kb, items, self.columns)

        if total_pages > 1:
            if page > 0:
                kb.add(InlineButton(text=ctx.theme.nav.prev, callback_data=ctx.callback_data("si:prev")))
            kb.add(InlineButton(
                text=ctx.theme.display.page_format.format(page + 1, total_pages),
                callback_data=ctx.callback_data("si:noop"),
            ))
            if page < total_pages - 1:
                kb.add(InlineButton(text=ctx.theme.nav.next, callback_data=ctx.callback_data("si:next")))
            kb.row()

        return self.prompt, kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        return reject_text(ctx)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        if value == "si:prev":
            page = self._current_page(ctx)
            return Stay(new_value=max(0, page - 1))
        elif value == "si:next":
            page = self._current_page(ctx)
            total_pages = max(1, (len(self.options) + self.page_size - 1) // self.page_size)
            return Stay(new_value=min(page + 1, total_pages - 1))
        elif value == "si:noop":
            return NoOp()
        elif value in self.options:
            return Advance(value=value, summary=f"Selected: {self.options[value]}")
        return NoOp()


# ═══════════════════════════════════════════════════════════════════════════════
# Case — conditional text display
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Case:
    """Display variant text based on a previously collected field value.

    Renders text from ``variants`` based on the value of ``selector`` field
    in the current flow state. Shows an OK button to advance.

        status_msg: Annotated[str, Case("status", active="You're active!", archived="Archived.")]
    """

    selector: str
    options: dict[str, str] = field(default_factory=lambda: dict[str, str]())

    def __init__(self, selector: str, **options: str) -> None:
        object.__setattr__(self, "selector", selector)
        object.__setattr__(self, "options", options)

    @property
    def prompt(self) -> str:
        return ""

    @property
    def needs_callback(self) -> bool:
        return True

    def _resolve_text(self, ctx: WidgetContext) -> str:
        state_val = ctx.flow_state.get(self.selector)
        return self.options.get(str(state_val), "")

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        text = self._resolve_text(ctx) or "(no variant matched)"
        kb = InlineKeyboard()
        kb.add(InlineButton(text=ctx.theme.action.ok, callback_data=ctx.callback_data("case:ok")))
        return text, kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        text = self._resolve_text(ctx)
        return Advance(value=text, summary=text or "(none)")

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        if value == "case:ok":
            text = self._resolve_text(ctx)
            return Advance(value=text, summary=text or "(none)")
        return NoOp()


# ═══════════════════════════════════════════════════════════════════════════════
# EnumInline — auto-generate options from Python Enum
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class EnumInline:
    """Inline keyboard auto-generated from Python Enum.

    Reads members from the field's base type (must be an Enum subclass).
    Labels default to member name (title-cased, underscores → spaces).

        class Priority(Enum):
            HIGH = "high"
            MEDIUM = "medium"
            LOW = "low"

        priority: Annotated[Priority, EnumInline("Priority:")]
    """

    prompt: str
    columns: int = 1

    @property
    def needs_callback(self) -> bool:
        return True

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        enum_cls = ctx.base_type
        if not (isinstance(enum_cls, type) and issubclass(enum_cls, Enum)):
            raise TypeError(
                f"EnumInline requires an Enum subclass as field type, got {enum_cls!r}. "
                f"Use `field: Annotated[MyEnum, EnumInline(...)]`."
            )
        kb = InlineKeyboard()
        items = [
            (m.name.replace("_", " ").title(), ctx.callback_data(str(m.value)))
            for m in enum_cls
        ]
        build_column_grid(kb, items, self.columns)
        return self.prompt, kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        return reject_text(ctx)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        enum_cls = ctx.base_type
        if not (isinstance(enum_cls, type) and issubclass(enum_cls, Enum)):
            return NoOp()
        for m in enum_cls:
            if str(m.value) == value:
                return Advance(
                    value=m,
                    summary=f"Selected: {m.name.replace('_', ' ').title()}",
                )
        return NoOp()


# ═══════════════════════════════════════════════════════════════════════════════
# Rating — star / number rating
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Rating:
    """Star rating selection.

    Shows number buttons 1..max_stars. Tapping a number previews stars.
    Confirm button finalizes.

        satisfaction: Annotated[int, Rating("Rate your experience:")]
        quality: Annotated[int, Rating("Quality:", max_stars=10, filled="●", empty="○")]
    """

    prompt: str
    max_stars: int = 5
    filled: str = "\u2605"
    empty: str = "\u2606"

    @property
    def needs_callback(self) -> bool:
        return True

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        current = ctx.typed_value(int, 0)
        if current > 0:
            stars = self.filled * current + self.empty * (self.max_stars - current)
            text = f"{self.prompt}\n\n{stars}"
        else:
            text = self.prompt
        kb = InlineKeyboard()
        for i in range(1, self.max_stars + 1):
            label = self.filled if i <= current else str(i)
            kb.add(InlineButton(text=label, callback_data=ctx.callback_data(f"rate:{i}")))
        kb.row()
        if current > 0:
            kb.add(InlineButton(
                text=f"Confirm {self.filled * current}",
                callback_data=ctx.callback_data("rate:done"),
            ))
        return text, kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        return reject_text(ctx)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        if value == "rate:done":
            current = ctx.typed_value(int, 0)
            if current == 0:
                return Reject(message=ctx.theme.errors.select_rating)
            return Advance(
                value=current,
                summary=f"{self.filled * current} ({current}/{self.max_stars})",
            )
        if value.startswith("rate:"):
            try:
                n = int(value[5:])
            except ValueError:
                return NoOp()
            if 1 <= n <= self.max_stars:
                return Stay(new_value=n)
        return NoOp()


# ═══════════════════════════════════════════════════════════════════════════════
# TimePicker — hour:minute selection
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TimePicker:
    """Time selection — select hour, then minute.

        meeting: Annotated[time, TimePicker("Meeting time:", min_hour=9, max_hour=18)]
    """

    prompt: str
    min_hour: int = 0
    max_hour: int = 23
    step_minutes: int = 15

    @property
    def needs_callback(self) -> bool:
        return True

    def _view_state(self, ctx: WidgetContext) -> dict[str, int | str]:
        if isinstance(ctx.current_value, Some):
            raw = ctx.current_value.value
            if isinstance(raw, dict):
                return raw  # type: ignore[return-value]
        return {"view": "hour"}

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        vs = self._view_state(ctx)
        view = str(vs.get("view", "hour"))
        kb = InlineKeyboard()

        if view == "hour":
            items = [
                (f"{h:02d}", ctx.callback_data(f"tp:h:{h}"))
                for h in range(self.min_hour, self.max_hour + 1)
            ]
            build_column_grid(kb, items, 6)
            return f"{self.prompt}\n\nSelect hour:", kb

        elif view == "minute":
            hour = int(vs.get("hour", 0))
            items = [
                (f":{m:02d}", ctx.callback_data(f"tp:m:{m}"))
                for m in range(0, 60, self.step_minutes)
            ]
            build_column_grid(kb, items, 4)
            kb.add(InlineButton(
                text=ctx.theme.nav.back_arrow, callback_data=ctx.callback_data("tp:back"),
            ))
            return f"{self.prompt}\n\n{hour:02d}:__ \u2014 select minutes:", kb

        return self.prompt, kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        return Reject(message=ctx.theme.errors.use_time_picker)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        if value.startswith("tp:h:"):
            h = int(value[5:])
            return Stay(new_value={"view": "minute", "hour": h})
        elif value.startswith("tp:m:"):
            vs = self._view_state(ctx)
            h = int(vs.get("hour", 0))
            m = int(value[5:])
            return Advance(value=time(h, m), summary=f"{h:02d}:{m:02d}")
        elif value == "tp:back":
            return Stay(new_value={"view": "hour"})
        return NoOp()


# ═══════════════════════════════════════════════════════════════════════════════
# NumberInput — quick-select buttons + text fallback
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class NumberInput:
    """Numeric input with optional quick-select shortcut buttons.

    Shows shortcut buttons (if provided) AND accepts typed numbers.

        amount: Annotated[int, NumberInput("Amount:", shortcuts=(10, 50, 100, 500))]
        price: Annotated[float, NumberInput("Price:", min=0.01, max=9999.99)]
    """

    prompt: str
    min: int | float = 0
    max: int | float = 999999
    shortcuts: tuple[int | float, ...] = ()

    @property
    def needs_callback(self) -> bool:
        return bool(self.shortcuts)

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        if not self.shortcuts:
            return self.prompt, None
        kb = InlineKeyboard()
        items = [
            (str(int(v)) if isinstance(v, float) and v == int(v) else str(v),
             ctx.callback_data(f"num:{v}"))
            for v in self.shortcuts
        ]
        build_column_grid(kb, items, 4)
        return f"{self.prompt}\n\nQuick select or type a number:", kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        match message.text:
            case Some(text):
                text = text.strip()
            case _:
                return Reject(message=ctx.theme.errors.send_number)
        try:
            value: int | float = int(text) if ctx.base_type is int else float(text)
        except ValueError:
            return Reject(message=ctx.theme.errors.send_number)
        if value < self.min or value > self.max:
            return Reject(message=ctx.theme.errors.range_error.format(self.min, self.max))
        return Advance(value=value, summary=str(value))

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        if value.startswith("num:"):
            try:
                n: int | float = int(value[4:]) if ctx.base_type is int else float(value[4:])
            except ValueError:
                return NoOp()
            return Advance(value=n, summary=str(n))
        return NoOp()


# ═══════════════════════════════════════════════════════════════════════════════
# VideoInput / VoiceInput — media type parity
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class VideoInput:
    """Accept a video from user.

        demo: Annotated[str, VideoInput("Send a demo video:")]

    Stores the file_id of the video.
    """

    prompt: str

    @property
    def needs_callback(self) -> bool:
        return False

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        return self.prompt, None

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        match message.video:
            case Some(video):
                return Advance(value=video.file_id, summary="Video uploaded")
            case _:
                return Reject(message=ctx.theme.errors.send_video)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        return Reject(message=ctx.theme.errors.send_video)


@dataclass(frozen=True, slots=True)
class VoiceInput:
    """Accept a voice message from user.

        feedback: Annotated[str, VoiceInput("Record your feedback:")]

    Stores the file_id of the voice message.
    """

    prompt: str

    @property
    def needs_callback(self) -> bool:
        return False

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        return self.prompt, None

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        match message.voice:
            case Some(voice):
                return Advance(value=voice.file_id, summary="Voice message recorded")
            case _:
                return Reject(message=ctx.theme.errors.send_voice)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        return Reject(message=ctx.theme.errors.send_voice)


# ═══════════════════════════════════════════════════════════════════════════════
# ContactInput — Telegram native contact sharing
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ContactInput:
    """Accept Telegram contact share from user.

    Uses Telegram's native contact sharing via reply keyboard.
    The keyboard auto-hides after the user taps it (one_time).

        phone: Annotated[str, ContactInput("Please share your phone number:")]

    Stores the phone_number string.
    """

    prompt: str
    button_text: str = "\U0001f4f1 Share Contact"

    @property
    def needs_callback(self) -> bool:
        return False

    async def render(
        self, ctx: WidgetContext,
    ) -> tuple[str, Keyboard | None]:
        kb = (
            Keyboard()
            .add(Button(self.button_text, request_contact=True))
            .resize()
            .one_time()
        )
        return self.prompt, kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        match message.contact:
            case Some(contact):
                phone: str = contact.phone_number
                return Advance(value=phone, summary=f"Phone: {phone}")
            case _:
                return Reject(message=ctx.theme.errors.send_contact)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        return Reject(message=ctx.theme.errors.send_contact)


# ═══════════════════════════════════════════════════════════════════════════════
# ListBuilder — collect variable-length list
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ListBuilder:
    """Collect a variable-length list of text items.

    Each text message adds an item. Done button finalizes.
    Uses Stay to accumulate items without advancing.

        tags: Annotated[list[str], ListBuilder("Add tags one by one:", min=1, max=10)]

    Requires flow.py Stay handling in from_message (added in this version).
    """

    prompt: str
    min: int = 0
    max: int = 100

    @property
    def needs_callback(self) -> bool:
        return True

    def _items(self, ctx: WidgetContext) -> list[str]:
        if isinstance(ctx.current_value, Some):
            raw = ctx.current_value.value
            if isinstance(raw, list):
                return list(raw)
        return []

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        items = self._items(ctx)
        lines = [self.prompt]
        if items:
            lines.append("")
            for i, item in enumerate(items, 1):
                lines.append(f"  {i}. {item}")
            lines.append(f"\nSend a message to add ({len(items)}/{self.max}):")
        kb = InlineKeyboard()
        if len(items) >= self.min and items:
            kb.add(InlineButton(
                text=f"Done ({len(items)} items)",
                callback_data=ctx.callback_data("lb:done"),
            ))
        if items:
            kb.add(InlineButton(
                text=ctx.theme.action.remove_last,
                callback_data=ctx.callback_data("lb:undo"),
            ))
        return "\n".join(lines), kb if items else None

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        match message.text:
            case Some(text):
                pass
            case _:
                return Reject(message=ctx.theme.errors.send_text)
        items = self._items(ctx)
        if self.max > 0 and len(items) >= self.max:
            return Reject(message=ctx.theme.errors.max_reached.format(self.max))
        error = _validate_text(text, ctx.validators, ctx.theme)
        if error is not None:
            return Reject(message=f"Invalid: {error}. Try again:")
        items.append(text)
        return Stay(new_value=items)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        items = self._items(ctx)
        if value == "lb:done":
            if len(items) < self.min:
                return Reject(message=ctx.theme.errors.min_required.format(self.min))
            preview = ", ".join(items[:3])
            if len(items) > 3:
                preview += "..."
            return Advance(value=items, summary=f"{len(items)} items: {preview}")
        elif value == "lb:undo":
            if items:
                items.pop()
            return Stay(new_value=items)
        return NoOp()


# ═══════════════════════════════════════════════════════════════════════════════
# Slider — visual range selection
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Slider:
    """Visual range slider with progress bar.

    Renders a progress bar in text and control buttons in inline keyboard.
    Fine and coarse step buttons, optional preset shortcuts.

        volume: Annotated[int, Slider("Volume:", max=100, step=5, big_step=25)]
        brightness: Annotated[int, Slider("Brightness:", presets=(0, 25, 50, 75, 100))]
    """

    prompt: str
    min: int = 0
    max: int = 100
    step: int = 1
    big_step: int = 10
    default: int = 0
    presets: tuple[int, ...] = ()
    bar_width: int = 10
    filled: str = "\u2588"
    empty: str = "\u2591"

    @property
    def needs_callback(self) -> bool:
        return True

    def _current(self, ctx: WidgetContext) -> int:
        return ctx.typed_value(int, self.default)

    def _bar(self, value: int) -> str:
        if self.max == self.min:
            ratio = 1.0
        else:
            ratio = (value - self.min) / (self.max - self.min)
        filled_count = round(ratio * self.bar_width)
        return self.filled * filled_count + self.empty * (self.bar_width - filled_count)

    def _clamp(self, value: int) -> int:
        return max(self.min, min(value, self.max))

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        current = self._current(ctx)
        bar = self._bar(current)
        text = f"{self.prompt}\n\n{bar} {current}"

        kb = InlineKeyboard()
        # Fine/coarse control row
        kb.add(InlineButton(text=ctx.theme.nav.prev, callback_data=ctx.callback_data("sl:left")))
        kb.add(InlineButton(
            text=f"{ctx.theme.action.decrement}{self.big_step}",
            callback_data=ctx.callback_data("sl:dec"),
        ))
        kb.add(InlineButton(text=str(current), callback_data=ctx.callback_data("sl:noop")))
        kb.add(InlineButton(
            text=f"{ctx.theme.action.increment}{self.big_step}",
            callback_data=ctx.callback_data("sl:inc"),
        ))
        kb.add(InlineButton(text=ctx.theme.nav.next, callback_data=ctx.callback_data("sl:right")))
        kb.row()

        # Preset row
        if self.presets:
            for p in self.presets:
                kb.add(InlineButton(text=str(p), callback_data=ctx.callback_data(f"sl:p:{p}")))
            kb.row()

        # Done
        kb.add(InlineButton(text=ctx.theme.action.done, callback_data=ctx.callback_data("sl:done")))
        return text, kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        return reject_text(ctx)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        current = self._current(ctx)
        if value == "sl:left":
            return Stay(new_value=self._clamp(current - self.step))
        elif value == "sl:right":
            return Stay(new_value=self._clamp(current + self.step))
        elif value == "sl:dec":
            return Stay(new_value=self._clamp(current - self.big_step))
        elif value == "sl:inc":
            return Stay(new_value=self._clamp(current + self.big_step))
        elif value.startswith("sl:p:"):
            try:
                p = int(value[5:])
            except ValueError:
                return NoOp()
            return Stay(new_value=self._clamp(p))
        elif value == "sl:done":
            return Advance(value=current, summary=f"{self._bar(current)} {current}")
        elif value == "sl:noop":
            return NoOp()
        return NoOp()


# ═══════════════════════════════════════════════════════════════════════════════
# PinInput — digit-by-digit code entry via numpad
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class PinInput:
    """PIN/code entry with numpad keyboard.

    Shows masked or visible digits and a 3x4 numpad.
    User taps digits, backspace to delete, confirm when complete.

        pin: Annotated[str, PinInput("Enter PIN:")]
        code: Annotated[str, PinInput("Verification code:", length=6, secret=False)]
    """

    prompt: str
    length: int = 4
    mask: str = "\u25cf"
    empty_dot: str = "\u25cb"
    secret: bool = True

    @property
    def needs_callback(self) -> bool:
        return True

    def _digits(self, ctx: WidgetContext) -> str:
        return ctx.typed_value(str, "")

    def _display(self, digits: str) -> str:
        entered = len(digits)
        if self.secret:
            return " ".join(
                self.mask if i < entered else self.empty_dot
                for i in range(self.length)
            )
        return " ".join(
            digits[i] if i < entered else self.empty_dot
            for i in range(self.length)
        )

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        digits = self._digits(ctx)
        display = self._display(digits)
        text = f"{self.prompt}\n\n{display}"

        kb = InlineKeyboard()
        # Row 1-3: 1-9
        for row_start in (1, 4, 7):
            for d in range(row_start, row_start + 3):
                kb.add(InlineButton(text=str(d), callback_data=ctx.callback_data(f"pin:{d}")))
            kb.row()
        # Row 4: ⌫ 0 ✓
        kb.add(InlineButton(text="\u232b", callback_data=ctx.callback_data("pin:del")))
        kb.add(InlineButton(text="0", callback_data=ctx.callback_data("pin:0")))
        kb.add(InlineButton(text=ctx.theme.action.done, callback_data=ctx.callback_data("pin:ok")))
        return text, kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        return reject_text(ctx)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        digits = self._digits(ctx)
        if value == "pin:del":
            if digits:
                return Stay(new_value=digits[:-1])
            return NoOp()
        elif value == "pin:ok":
            if len(digits) < self.length:
                return Reject(message=ctx.theme.errors.enter_pin)
            return Advance(value=digits, summary=self.mask * self.length if self.secret else digits)
        elif value.startswith("pin:"):
            digit = value[4:]
            if digit.isdigit() and len(digits) < self.length:
                return Stay(new_value=digits + digit)
        return NoOp()


# ═══════════════════════════════════════════════════════════════════════════════
# MediaGroupInput — collect multiple media files
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class MediaGroupInput:
    """Collect multiple photos, documents, or videos.

    User sends media one by one. Done button finalizes.
    Stores list of file_id strings.

        photos: Annotated[list[str], MediaGroupInput("Send photos:", max=10)]
        files: Annotated[list[str], MediaGroupInput("Upload files:", accept="document")]
        media: Annotated[list[str], MediaGroupInput("Send media:", accept="any")]
    """

    prompt: str
    min: int = 1
    max: int = 10
    accept: str = "photo"  # "photo", "document", "video", "any"

    @property
    def needs_callback(self) -> bool:
        return True

    def _items(self, ctx: WidgetContext) -> list[str]:
        if isinstance(ctx.current_value, Some):
            raw = ctx.current_value.value
            if isinstance(raw, list):
                return list(raw)
        return []

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        items = self._items(ctx)
        count = len(items)
        if count > 0:
            text = f"{self.prompt}\n\n\U0001f4ce {count}/{self.max} files added"
        else:
            text = self.prompt
        kb = InlineKeyboard()
        if count >= self.min and items:
            kb.add(InlineButton(
                text=f"{ctx.theme.action.done} ({count})",
                callback_data=ctx.callback_data("mg:done"),
            ))
        if items:
            kb.add(InlineButton(
                text=ctx.theme.action.remove_last,
                callback_data=ctx.callback_data("mg:undo"),
            ))
        return text, kb if items else None

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        items = self._items(ctx)
        if self.max > 0 and len(items) >= self.max:
            return Reject(message=ctx.theme.errors.max_reached.format(self.max))
        file_id: str | None = None
        if self.accept in ("photo", "any"):
            match message.photo:
                case Some(photos) if photos:
                    file_id = photos[-1].file_id
        if file_id is None and self.accept in ("document", "any"):
            match message.document:
                case Some(doc):
                    file_id = doc.file_id
        if file_id is None and self.accept in ("video", "any"):
            match message.video:
                case Some(vid):
                    file_id = vid.file_id
        if file_id is None:
            return Reject(message=ctx.theme.errors.send_media)
        items.append(file_id)
        return Stay(new_value=items)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        items = self._items(ctx)
        if value == "mg:done":
            if len(items) < self.min:
                return Reject(message=ctx.theme.errors.min_required.format(self.min))
            return Advance(value=items, summary=f"{len(items)} files")
        elif value == "mg:undo":
            if items:
                items.pop()
            return Stay(new_value=items)
        return NoOp()


# ═══════════════════════════════════════════════════════════════════════════════
# TimeSlotPicker — select from available time slots grouped by date
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TimeSlotPicker:
    """Select a time slot from dynamically-provided options, grouped by date.

    Options come from @options as ``dict[str, str]`` where keys contain
    a date part (ISO format before 'T'). Slots are grouped by date with
    headers.

        slot: Annotated[str, TimeSlotPicker("Choose appointment:")]

        @classmethod
        @options("slot")
        async def load_slots(cls, db) -> dict[str, str]:
            return {"2024-01-15T10:00": "10:00", "2024-01-15T14:00": "14:00", ...}
    """

    prompt: str
    columns: int = 3
    date_format: str = "%a %b %d"

    @property
    def needs_callback(self) -> bool:
        return True

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        opts = ctx.dynamic_options
        if not opts:
            return no_options_text(ctx, self.prompt), None
        # Group by date part (before T)
        groups: dict[str, list[tuple[str, str]]] = {}
        for key, label in opts.items():
            date_part = key.split("T")[0] if "T" in key else ""
            groups.setdefault(date_part, []).append((key, label))
        kb = InlineKeyboard()
        for date_key, slots in groups.items():
            # Date header
            if date_key:
                try:
                    d = date.fromisoformat(date_key)
                    header = d.strftime(self.date_format)
                except ValueError:
                    header = date_key
                kb.add(InlineButton(
                    text=f"\u2014 {header} \u2014",
                    callback_data=ctx.callback_data("ts:noop"),
                ))
                kb.row()
            items = [(label, ctx.callback_data(f"ts:{key}")) for key, label in slots]
            build_column_grid(kb, items, self.columns)
        return self.prompt, kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        if not ctx.dynamic_options:
            return no_options_reject(ctx)
        return reject_text(ctx)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        if value == "ts:noop":
            return NoOp()
        if value.startswith("ts:"):
            key = value[3:]
            opts = ctx.dynamic_options
            if key in opts:
                return Advance(value=key, summary=f"Selected: {opts[key]}")
        return NoOp()


# ═══════════════════════════════════════════════════════════════════════════════
# RecurrencePicker — recurring schedule (weekdays + time)
# ═══════════════════════════════════════════════════════════════════════════════

_WEEKDAY_NAMES: tuple[str, ...] = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True, slots=True)
class RecurrencePicker:
    """Pick a recurring schedule: weekdays + time.

    Multi-step widget: select days → select hour → select minutes.
    Returns string like ``"0,2,4@10:30"`` (weekday indices + time).

        schedule: Annotated[str, RecurrencePicker("Publication schedule:")]
    """

    prompt: str
    min_hour: int = 0
    max_hour: int = 23
    step_minutes: int = 15

    @property
    def needs_callback(self) -> bool:
        return True

    def _state(self, ctx: WidgetContext) -> dict[str, str | int]:
        if isinstance(ctx.current_value, Some):
            raw = ctx.current_value.value
            if isinstance(raw, dict):
                return raw  # type: ignore[return-value]
        return {"view": "days", "days": ""}

    def _selected_days(self, st: dict[str, str | int]) -> set[str]:
        days_str = str(st.get("days", ""))
        if days_str:
            return set(days_str.split(","))
        return set()

    def _day_summary(self, selected: set[str]) -> str:
        return ", ".join(_WEEKDAY_NAMES[int(d)] for d in sorted(selected))

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        st = self._state(ctx)
        view = str(st.get("view", "days"))
        selected = self._selected_days(st)

        kb = InlineKeyboard()

        if view == "days":
            _sel = ctx.theme.selection
            for i, day in enumerate(_WEEKDAY_NAMES):
                icon = _sel.checked if str(i) in selected else _sel.unchecked
                kb.add(InlineButton(
                    text=f"{icon} {day}",
                    callback_data=ctx.callback_data(f"rc:d:{i}"),
                ))
            kb.row()
            if selected:
                kb.add(InlineButton(
                    text=f"{ctx.theme.nav.next} Next",
                    callback_data=ctx.callback_data("rc:next"),
                ))
            return f"{self.prompt}\n\nSelect days:", kb

        elif view == "hour":
            items = [
                (f"{h:02d}", ctx.callback_data(f"rc:h:{h}"))
                for h in range(self.min_hour, self.max_hour + 1)
            ]
            build_column_grid(kb, items, 6)
            kb.add(InlineButton(
                text=ctx.theme.nav.back_arrow,
                callback_data=ctx.callback_data("rc:back:days"),
            ))
            return f"{self.prompt}\n\n{self._day_summary(selected)}\nSelect hour:", kb

        elif view == "minute":
            hour = int(st.get("hour", 0))
            items = [
                (f":{m:02d}", ctx.callback_data(f"rc:m:{m}"))
                for m in range(0, 60, self.step_minutes)
            ]
            build_column_grid(kb, items, 4)
            kb.add(InlineButton(
                text=ctx.theme.nav.back_arrow,
                callback_data=ctx.callback_data("rc:back:hour"),
            ))
            return (
                f"{self.prompt}\n\n{self._day_summary(selected)} at {hour:02d}:__",
                kb,
            )

        return self.prompt, kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        return reject_text(ctx)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        st = self._state(ctx)
        selected = self._selected_days(st)

        if value.startswith("rc:d:"):
            day = value[5:]
            if day in selected:
                selected.discard(day)
            else:
                selected.add(day)
            new_days = ",".join(sorted(selected)) if selected else ""
            return Stay(new_value={**st, "days": new_days})

        elif value == "rc:next":
            if not selected:
                return Reject(message=ctx.theme.errors.select_days)
            return Stay(new_value={**st, "view": "hour"})

        elif value.startswith("rc:h:"):
            h = int(value[5:])
            return Stay(new_value={**st, "view": "minute", "hour": h})

        elif value.startswith("rc:m:"):
            m = int(value[5:])
            hour = int(st.get("hour", 0))
            summary = f"{self._day_summary(selected)} at {hour:02d}:{m:02d}"
            final = f"{','.join(sorted(selected))}@{hour:02d}:{m:02d}"
            return Advance(value=final, summary=summary)

        elif value == "rc:back:days":
            return Stay(new_value={**st, "view": "days"})

        elif value == "rc:back:hour":
            return Stay(new_value={**st, "view": "hour"})

        return NoOp()


# ═══════════════════════════════════════════════════════════════════════════════
# SummaryReview — review all collected fields before confirming
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class SummaryReview:
    """Show all collected field values for review before submission.

    Reads ``ctx.flow_state`` to display a formatted summary. User confirms
    or (if with_back enabled) goes back to edit.

    Labels are passed as keyword arguments: ``field_name="Display Label"``.
    Fields without a label are auto-titled from the field name.

        review: Annotated[bool, SummaryReview(name="Name", email="Email", role="Role")]
    """

    labels: dict[str, str] = field(default_factory=lambda: dict[str, str]())

    def __init__(self, **labels: str) -> None:
        object.__setattr__(self, "labels", labels)

    @property
    def prompt(self) -> str:
        return ""

    @property
    def needs_callback(self) -> bool:
        return True

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        lines: list[str] = []
        for field_name, value in ctx.flow_state.items():
            if value is None or field_name == ctx.field_name:
                continue
            label = self.labels.get(field_name, field_name.replace("_", " ").title())
            lines.append(f"  {label}: {value}")
        text = "Review your answers:\n\n" + "\n".join(lines) if lines else "(no data)"
        kb = InlineKeyboard()
        kb.add(InlineButton(
            text=ctx.theme.action.done,
            callback_data=ctx.callback_data("sr:ok"),
        ))
        return text, kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        return reject_text(ctx)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        if value == "sr:ok":
            return Advance(value=True, summary="Confirmed")
        return NoOp()


# ═══════════════════════════════════════════════════════════════════════════════
# Dynamic widgets — options resolved at render time via @options
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class DynamicInline:
    """Inline keyboard with options loaded dynamically via @options.

    Options come from ``ctx.dynamic_options`` — populated by the flow
    generator from the entity's ``@options("field_name")`` method.

        project: Annotated[str, DynamicInline("Select project:")]

        @classmethod
        @options("project")
        async def load_projects(cls, db: ...) -> dict[str, str]:
            projects = await db.fetch_many(...)
            return {str(p.id): p.name for p in projects}
    """

    prompt: str
    columns: int = 1

    @property
    def needs_callback(self) -> bool:
        return True

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        opts = ctx.dynamic_options
        if not opts:
            return no_options_text(ctx, self.prompt), None
        kb = option_keyboard(ctx, opts, self.columns)
        return self.prompt, kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        if not ctx.dynamic_options:
            return no_options_reject(ctx)
        return reject_text(ctx)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        opts = ctx.dynamic_options
        if value not in opts:
            return NoOp()
        return Advance(value=value, summary=f"Selected: {opts[value]}")


@dataclass(frozen=True, slots=True)
class DynamicRadio:
    """Radio selection with dynamic options via @options.

    Like Radio but options are loaded at render time.

        category: Annotated[str, DynamicRadio("Select category:")]

        @classmethod
        @options("category")
        async def load_categories(cls, db: ...) -> dict[str, str]: ...
    """

    prompt: str
    columns: int = 1

    @property
    def needs_callback(self) -> bool:
        return True

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        opts = ctx.dynamic_options
        if not opts:
            return no_options_text(ctx, self.prompt), None
        selected = ctx.typed_value(str, "")
        kb = radio_keyboard(ctx, opts, selected, self.columns, "dr")
        return self.prompt, kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        if not ctx.dynamic_options:
            return no_options_reject(ctx)
        return reject_text(ctx)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        opts = ctx.dynamic_options
        selected = ctx.typed_value(str, "")
        return handle_radio_cb(value, opts, selected, ctx, "dr")


@dataclass(frozen=True, slots=True)
class DynamicMultiselect:
    """Multiselect with dynamic options via @options.

    Like Multiselect but options are loaded at render time.

        tags: Annotated[str, DynamicMultiselect("Select tags:")]

        @classmethod
        @options("tags")
        async def load_tags(cls, db: ...) -> dict[str, str]: ...
    """

    prompt: str
    columns: int = 1
    min_selected: int = 0
    max_selected: int = 0

    @property
    def needs_callback(self) -> bool:
        return True

    def _selected_set(self, ctx: WidgetContext) -> set[str]:
        return parse_selected(ctx)

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        opts = ctx.dynamic_options
        if not opts:
            return no_options_text(ctx, self.prompt), None
        selected = self._selected_set(ctx)
        kb = checked_keyboard(ctx, opts, selected, self.columns, "dms")
        return self.prompt, kb

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult:
        if not ctx.dynamic_options:
            return no_options_reject(ctx)
        return reject_text(ctx)

    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult:
        opts = ctx.dynamic_options
        selected = self._selected_set(ctx)
        return handle_checked_cb(value, opts, selected, ctx, "dms", self.min_selected, self.max_selected)


# ═══════════════════════════════════════════════════════════════════════════════
# @options decorator — marks a method as dynamic options provider
# ═══════════════════════════════════════════════════════════════════════════════


OPTIONS_ENTRIES_ATTR = "__options_entries__"

_DYNAMIC_WIDGETS = (DynamicInline, DynamicRadio, DynamicMultiselect)


@dataclass(frozen=True, slots=True)
class _OptionsEntry:
    """An @options entry attached to an entity method."""

    field_name: str


def options(field_name: str) -> Callable[[F], F]:
    """Mark a classmethod as the dynamic options provider for a flow field.

    The method must return ``dict[str, str]`` (key → display label).
    It can accept compose.Node DI parameters — same mechanism as finish().

        @classmethod
        @options("project")
        async def load_projects(
            cls,
            db: Annotated[Provider, compose.Node(Projects)],
        ) -> dict[str, str]:
            projects = await db.fetch_many(...)
            return {str(p.id): p.name for p in projects}
    """
    entry = _OptionsEntry(field_name)

    def decorator(fn: F) -> F:
        entries: list[_OptionsEntry] = getattr(fn, OPTIONS_ENTRIES_ATTR, [])
        entries.append(entry)
        setattr(fn, OPTIONS_ENTRIES_ATTR, entries)
        return fn

    return decorator


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════


__all__ = (
    # Theme
    "UITheme",
    "DEFAULT_THEME",
    # Validation
    "MinLen",
    "MaxLen",
    "Pattern",
    # Context
    "WidgetContext",
    # Result algebra
    "Stay",
    "Advance",
    "Reject",
    "NoOp",
    # Protocol
    "FlowWidget",
    "AnyKeyboard",
    # Concrete widgets
    "TextInput",
    "Inline",
    "Confirm",
    "Counter",
    "Multiselect",
    # Media widgets
    "PhotoInput",
    "DocumentInput",
    "LocationInput",
    "VideoInput",
    "VoiceInput",
    # Contact
    "ContactInput",
    # Toggle
    "Toggle",
    # Stateful selection
    "Radio",
    "DatePicker",
    "ScrollingInline",
    # Enum
    "EnumInline",
    # Rating
    "Rating",
    # Time
    "TimePicker",
    # Number
    "NumberInput",
    # List
    "ListBuilder",
    # Slider
    "Slider",
    # PinInput
    "PinInput",
    # MediaGroupInput
    "MediaGroupInput",
    # TimeSlotPicker
    "TimeSlotPicker",
    # RecurrencePicker
    "RecurrencePicker",
    # SummaryReview
    "SummaryReview",
    # Dynamic options
    "DynamicInline",
    "DynamicRadio",
    "DynamicMultiselect",
    "options",
    "OPTIONS_ENTRIES_ATTR",
    # Conditional
    "Case",
    # Widget helpers (from uilib.helpers)
    "reject_text",
    "no_options_reject",
    "no_options_text",
    "option_keyboard",
    "radio_keyboard",
    "checked_keyboard",
    "handle_radio_cb",
    "handle_checked_cb",
    "parse_selected",
)
