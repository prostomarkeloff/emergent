"""Shared keyboard builder helpers for TG patterns."""

from __future__ import annotations

from collections.abc import Sequence

from telegrinder.tools.keyboard import InlineButton, InlineKeyboard

from derivelib.patterns.tg.uilib.theme import UITheme


def build_column_grid(
    kb: InlineKeyboard,
    items: Sequence[tuple[str, str]],
    columns: int,
) -> None:
    """Add items to keyboard in a column grid layout.

    Args:
        kb: Keyboard to add buttons to.
        items: (text, callback_data) pairs.
        columns: Buttons per row before wrapping.
    """
    col_count = 0
    for text, cb_data in items:
        kb.add(InlineButton(text=text, callback_data=cb_data))
        col_count += 1
        if col_count >= columns:
            kb.row()
            col_count = 0
    if col_count > 0:
        kb.row()


def build_nav_keyboard(
    browse_name: str,
    page: int,
    total_pages: int,
    entity_ids: Sequence[int],
    actions: Sequence[_ActionLike],
    *,
    theme: UITheme,
    view_filters: Sequence[_FilterLike] = (),
    active_filter: str = "",
) -> InlineKeyboard:
    """Build navigation + action inline keyboard.

    Args:
        browse_name: Short identifier for callback routing.
        page: Current page (0-indexed).
        total_pages: Total number of pages.
        entity_ids: IDs of entities on current page.
        actions: Action entries with label, method_name, row attrs.
        theme: UITheme for configurable strings.
        view_filters: Optional filter tab definitions.
        active_filter: Currently active filter key.
    """
    from derivelib.patterns.tg.browse import BrowseCB

    kb = InlineKeyboard()

    # Tab row (if filters exist)
    if view_filters:
        for vf in view_filters:
            prefix = theme.selection.tab_active if vf.key == active_filter else theme.selection.tab_inactive
            kb.add(InlineButton(
                text=f"{prefix} {vf.label}",
                callback_data=BrowseCB(b=browse_name, a=f"_tab_{vf.key}", p=0),
            ))
        kb.row()

    # Navigation row (hidden when single page)
    if total_pages > 1:
        if page > 0:
            kb.add(InlineButton(
                text=theme.nav.prev_label,
                callback_data=BrowseCB(b=browse_name, a="prev", p=page - 1),
            ))
        kb.add(InlineButton(
            text=theme.display.page_format.format(page + 1, total_pages),
            callback_data=BrowseCB(b=browse_name, a="noop", p=page),
        ))
        if page < total_pages - 1:
            kb.add(InlineButton(
                text=theme.nav.next_label,
                callback_data=BrowseCB(b=browse_name, a="next", p=page + 1),
            ))
        kb.row()

    # Action rows — grouped by row number, one set per entity
    for eid in entity_ids:
        if actions:
            for row_num in sorted(set(act.row for act in actions)):
                for act in actions:
                    if act.row == row_num:
                        kb.add(InlineButton(
                            text=act.label,
                            callback_data=BrowseCB(b=browse_name, a=act.method_name, e=eid),
                        ))
                kb.row()

    return kb


# ═══════════════════════════════════════════════════════════════════════════════
# Structural protocols for action/filter entries (avoid circular imports)
# ═══════════════════════════════════════════════════════════════════════════════


from typing import Protocol, runtime_checkable


@runtime_checkable
class _ActionLike(Protocol):
    """Structural match for browse._ActionEntry."""

    @property
    def label(self) -> str: ...

    @property
    def method_name(self) -> str: ...

    @property
    def row(self) -> int: ...


@runtime_checkable
class _FilterLike(Protocol):
    """Structural match for browse._ViewFilter."""

    @property
    def label(self) -> str: ...

    @property
    def key(self) -> str: ...


__all__ = (
    "build_column_grid",
    "build_nav_keyboard",
)
