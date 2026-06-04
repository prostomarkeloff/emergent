"""Telegrinder type compatibility — protocols for optional uninstalled dependency.

telegrinder is an optional dependency that may not be installed. These Protocol
types provide structural interfaces for static type checking. At runtime, the
real telegrinder types are used via try/except ImportError in each module.

This module NEVER uses Any. All protocols define the exact structural interface
needed by the emergent codebase.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nodnod import Scope


# ═══════════════════════════════════════════════════════════════════════════════
# Rule Protocols
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class ABCRule(Protocol):
    """Structural type for telegrinder's ABCRule.

    telegrinder is an optional dependency without type stubs.
    This protocol captures the interface used by the emergent codebase.
    """
    ...


class AndRule(Protocol):
    """Structural type for telegrinder's AndRule combinator."""

    def __init__(self, *rules: ABCRule) -> None: ...


class OrRule(Protocol):
    """Structural type for telegrinder's OrRule combinator."""

    def __init__(self, *rules: ABCRule) -> None: ...


# ═══════════════════════════════════════════════════════════════════════════════
# Command Protocol
# ═══════════════════════════════════════════════════════════════════════════════


class ArgumentProto(Protocol):
    """Structural type for telegrinder's Argument."""

    def __init__(
        self,
        name: str = ...,
        validators: list[type] | None = ...,
        optional: bool = ...,
        **kwargs: object,
    ) -> None: ...

    @property
    def name(self) -> str: ...


class CommandProto(Protocol):
    """Structural type for telegrinder's Command rule.

    Captures the attributes accessed in enhance_command_with_args and
    extract_command_info.
    """

    def __init__(
        self,
        names: frozenset[str] | str,
        *arguments: ArgumentProto,
        prefixes: tuple[str, ...] = ...,
        separator: str = ...,
        lazy: bool = ...,
        validate_mention: bool = ...,
        ignore_case: bool = ...,
    ) -> None: ...

    @property
    def names(self) -> frozenset[str]: ...

    @property
    def arguments(self) -> tuple[ArgumentProto, ...]: ...

    @property
    def prefixes(self) -> tuple[str, ...]: ...

    @property
    def separator(self) -> str: ...

    @property
    def lazy(self) -> bool: ...

    @property
    def validate_mention(self) -> bool: ...

    @property
    def ignore_case(self) -> bool: ...


# ═══════════════════════════════════════════════════════════════════════════════
# Context Protocol
# ═══════════════════════════════════════════════════════════════════════════════


class Context(Protocol):
    """Structural type for telegrinder's dispatch Context.

    Captures the interface used by the emergent codebase:
    - .get(key) for named value lookup
    - .per_event_scope for accessing the per-event nodnod Scope
    """

    def get(self, key: str) -> Any | None: ...

    @property
    def per_event_scope(self) -> Scope: ...


# ═══════════════════════════════════════════════════════════════════════════════
# Dispatch Protocol
# ═══════════════════════════════════════════════════════════════════════════════


class Dispatch(Protocol):
    """Structural type for telegrinder's Dispatch.

    Only __getattr__ is used (for accessing view attributes like .message).
    """
    ...


# ═══════════════════════════════════════════════════════════════════════════════
# Cute Types Protocol
# ═══════════════════════════════════════════════════════════════════════════════


class BaseCute(Protocol):
    """Structural type for telegrinder's BaseCute.

    Used in issubclass checks to detect cute type parameters.
    """
    ...


class CallbackQueryCute(Protocol):
    """Structural type for telegrinder's CallbackQueryCute.

    Captures the interface used by enrichers: answer(), edit_text().
    """

    async def answer(self, **kwargs: Any) -> Any: ...

    async def edit_text(self, **kwargs: Any) -> Any: ...


class MessageCute(Protocol):
    """Structural type for telegrinder's MessageCute."""
    ...


# ═══════════════════════════════════════════════════════════════════════════════
# API / Update Protocols
# ═══════════════════════════════════════════════════════════════════════════════


class API(Protocol):
    """Structural type for telegrinder's API."""

    async def send_message(self, **kwargs: Any) -> Any: ...


class Update(Protocol):
    """Structural type for telegrinder's Update."""

    @property
    def callback_query(self) -> Any: ...


__all__ = (
    "ABCRule",
    "AndRule",
    "OrRule",
    "ArgumentProto",
    "CommandProto",
    "Context",
    "Dispatch",
    "BaseCute",
    "CallbackQueryCute",
    "MessageCute",
    "API",
    "Update",
)
