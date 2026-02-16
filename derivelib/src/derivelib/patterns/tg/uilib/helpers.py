"""Shared widget building blocks for built-in and third-party widgets.

Helpers extracted from repeated patterns across Inline, Radio, Multiselect,
Dynamic* widgets. Every built-in widget uses these — third-party widgets
get the same vocabulary.
"""

from __future__ import annotations

from collections.abc import Mapping

from kungfu import Some

from telegrinder.tools.keyboard import InlineButton, InlineKeyboard

from derivelib.patterns.tg.uilib.keyboard import build_column_grid
from derivelib.patterns.tg.widget import (
    Advance,
    NoOp,
    Reject,
    Stay,
    WidgetContext,
    WidgetResult,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Rejections
# ═══════════════════════════════════════════════════════════════════════════════


def reject_text(ctx: WidgetContext) -> Reject:
    """Reject with "use buttons" message."""
    return Reject(message=ctx.theme.errors.use_buttons)


def no_options_reject(ctx: WidgetContext) -> Reject:
    """Reject when dynamic options are empty."""
    if ctx.is_optional:
        return Reject(message="No options available. Send /skip to skip.")
    return Reject(message="No options available.")


# ═══════════════════════════════════════════════════════════════════════════════
# Text helpers
# ═══════════════════════════════════════════════════════════════════════════════


def no_options_text(ctx: WidgetContext, prompt: str) -> str:
    """Render text when dynamic options are empty."""
    hint = " Send /skip to continue." if ctx.is_optional else ""
    return f"{prompt}\n\n{ctx.theme.display.no_options}{hint}"


# ═══════════════════════════════════════════════════════════════════════════════
# Keyboard builders
# ═══════════════════════════════════════════════════════════════════════════════


def option_keyboard(
    ctx: WidgetContext,
    options: Mapping[str, str],
    columns: int = 1,
) -> InlineKeyboard:
    """Build a plain option grid keyboard."""
    kb = InlineKeyboard()
    items = [(label, ctx.callback_data(key)) for key, label in options.items()]
    build_column_grid(kb, items, columns)
    return kb


def radio_keyboard(
    ctx: WidgetContext,
    options: Mapping[str, str],
    selected: str,
    columns: int = 1,
    prefix: str = "radio",
) -> InlineKeyboard:
    """Build a radio-style keyboard with selection icons and Done button."""
    kb = InlineKeyboard()
    _sel = ctx.theme.selection
    items = [
        (
            f"{_sel.radio_on if key == selected else _sel.radio_off} {label}",
            ctx.callback_data(f"{prefix}:{key}"),
        )
        for key, label in options.items()
    ]
    build_column_grid(kb, items, columns)
    kb.add(InlineButton(
        text=ctx.theme.action.done,
        callback_data=ctx.callback_data(f"{prefix}:done"),
    ))
    return kb


def checked_keyboard(
    ctx: WidgetContext,
    options: Mapping[str, str],
    selected: set[str],
    columns: int = 1,
    prefix: str = "ms",
) -> InlineKeyboard:
    """Build a multiselect keyboard with check icons and Done button."""
    kb = InlineKeyboard()
    _sel = ctx.theme.selection
    items = [
        (
            f"{_sel.checked if key in selected else _sel.unchecked} {label}",
            ctx.callback_data(f"{prefix}:{key}"),
        )
        for key, label in options.items()
    ]
    build_column_grid(kb, items, columns)
    kb.add(InlineButton(
        text=ctx.theme.action.done,
        callback_data=ctx.callback_data(f"{prefix}:done"),
    ))
    return kb


# ═══════════════════════════════════════════════════════════════════════════════
# Callback handlers
# ═══════════════════════════════════════════════════════════════════════════════


def handle_radio_cb(
    value: str,
    options: Mapping[str, str],
    selected: str,
    ctx: WidgetContext,
    prefix: str = "radio",
) -> WidgetResult:
    """Handle radio callback: done -> Advance, key -> Stay."""
    done_key = f"{prefix}:done"
    if value == done_key:
        if not selected or selected not in options:
            return Reject(message=ctx.theme.errors.select_option)
        return Advance(value=selected, summary=f"Selected: {options[selected]}")
    tag = f"{prefix}:"
    if value.startswith(tag):
        key = value[len(tag):]
        if key in options:
            return Stay(new_value=key)
    return NoOp()


def handle_checked_cb(
    value: str,
    options: Mapping[str, str],
    selected: set[str],
    ctx: WidgetContext,
    prefix: str = "ms",
    min_selected: int = 0,
    max_selected: int = 0,
) -> WidgetResult:
    """Handle multiselect callback: toggle item, done -> Advance."""
    done_key = f"{prefix}:done"
    tag = f"{prefix}:"
    if value.startswith(tag) and value != done_key:
        key = value[len(tag):]
        if key not in options:
            return NoOp()
        toggled = set(selected)
        if key in toggled:
            toggled.discard(key)
        else:
            if max_selected > 0 and len(toggled) >= max_selected:
                return Reject(message=ctx.theme.errors.max_items.format(max_selected))
            toggled.add(key)
        return Stay(new_value=",".join(sorted(toggled)) if toggled else "")
    elif value == done_key:
        if min_selected > 0 and len(selected) < min_selected:
            return Reject(message=ctx.theme.errors.min_select.format(min_selected))
        final = ",".join(sorted(selected)) if selected else ""
        labels = [options.get(k, k) for k in sorted(selected)]
        summary = ", ".join(labels) if labels else "(none)"
        return Advance(value=final, summary=f"Selected: {summary}")
    return NoOp()


# ═══════════════════════════════════════════════════════════════════════════════
# Utilities
# ═══════════════════════════════════════════════════════════════════════════════


def parse_selected(ctx: WidgetContext) -> set[str]:
    """Parse comma-separated current_value into a set."""
    if isinstance(ctx.current_value, Some):
        raw = ctx.current_value.value
        if isinstance(raw, str) and raw:
            return set(raw.split(","))
    return set()


__all__ = (
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
