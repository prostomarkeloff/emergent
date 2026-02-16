"""uilib — Unified configurable UI for TG patterns."""

from .theme import (
    NavUI,
    SelectionUI,
    ActionUI,
    DisplayUI,
    ErrorUI,
    UITheme,
    DEFAULT_THEME,
)

from .keyboard import (
    build_column_grid,
    build_nav_keyboard,
)

__all__ = (
    "NavUI",
    "SelectionUI",
    "ActionUI",
    "DisplayUI",
    "ErrorUI",
    "UITheme",
    "DEFAULT_THEME",
    "build_column_grid",
    "build_nav_keyboard",
)
