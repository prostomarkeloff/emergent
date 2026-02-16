"""UITheme — configurable UI strings for TG patterns.

All hardcoded icons, labels, error messages, and format patterns
extracted into frozen dataclasses with sensible defaults.

    from derivelib.patterns.tg.uilib import UITheme, ActionUI

    # Override just what you need — everything else keeps defaults
    theme = UITheme(action=ActionUI(done="Готово ✓", yes="Да", no="Нет"))
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class NavUI:
    """Navigation arrows and labels."""

    prev: str = "\u25c0"
    next: str = "\u25b6"
    prev_label: str = "\u25c0\ufe0f Prev"
    next_label: str = "Next \u25b6\ufe0f"
    back: str = "Back"
    back_arrow: str = "\u25c0 Back"


@dataclass(frozen=True, slots=True)
class SelectionUI:
    """State indicators for selection widgets."""

    checked: str = "\u2705"
    unchecked: str = "\u2b1c"
    radio_on: str = "\U0001f518"
    radio_off: str = "\u26aa"
    toggle_on: str = "\U0001f7e2"
    toggle_off: str = "\U0001f534"
    tab_active: str = "\U0001f518"
    tab_inactive: str = "\u26aa"


@dataclass(frozen=True, slots=True)
class ActionUI:
    """Button labels."""

    done: str = "Done \u2713"
    ok: str = "OK"
    yes: str = "Yes"
    no: str = "No"
    cancel: str = "Cancelled."
    remove_last: str = "Remove last"
    decrement: str = "\u2212"
    increment: str = "+"


@dataclass(frozen=True, slots=True)
class DisplayUI:
    """Formatting strings."""

    none_value: str = "(not set)"
    bool_true: str = "Yes"
    bool_false: str = "No"
    no_options: str = "(no options available)"
    entity_not_found: str = "Entity not found."
    disabled_date: str = "\u00b7"
    date_format: str = "%b %d, %Y"
    page_format: str = "{}/{}"


@dataclass(frozen=True, slots=True)
class ErrorUI:
    """Error and rejection messages.

    Static strings are used as-is. Format-string templates use ``.format()``.
    """

    use_buttons: str = "Please use the buttons above."
    use_button: str = "Please use the button above."
    send_text: str = "Please send a text message."
    send_photo: str = "Please send a photo."
    send_document: str = "Please send a document."
    send_location: str = "Please share a location."
    send_video: str = "Please send a video."
    send_voice: str = "Please send a voice message."
    send_contact: str = "Please use the Share Contact button."
    send_number: str = "Please enter a number."
    use_calendar: str = "Please use the calendar buttons above."
    use_time_picker: str = "Please use the time picker buttons above."
    use_slider: str = "Please use the slider buttons above."
    enter_pin: str = "Please enter all digits first."
    send_media: str = "Please send a photo, document, or video."
    select_days: str = "Please select at least one day."
    select_option: str = "Please select an option first."
    select_rating: str = "Please select a rating first."
    too_short: str = "Too short (min {} chars)"
    too_long: str = "Too long (max {} chars)"
    invalid_format: str = "Invalid format (expected {})"
    max_items: str = "Max {} items"
    min_select: str = "Select at least {}"
    range_error: str = "Must be between {} and {}."
    max_reached: str = "Maximum {} items reached. Press Done."
    min_required: str = "Please add at least {} items."


@dataclass(frozen=True, slots=True)
class UITheme:
    """Top-level theme container.

    Override sub-dataclasses to customize UI strings::

        theme = UITheme(action=ActionUI(done="Готово ✓"))
    """

    nav: NavUI = field(default_factory=NavUI)
    selection: SelectionUI = field(default_factory=SelectionUI)
    action: ActionUI = field(default_factory=ActionUI)
    display: DisplayUI = field(default_factory=DisplayUI)
    errors: ErrorUI = field(default_factory=ErrorUI)


DEFAULT_THEME = UITheme()


__all__ = (
    "NavUI",
    "SelectionUI",
    "ActionUI",
    "DisplayUI",
    "ErrorUI",
    "UITheme",
    "DEFAULT_THEME",
)
