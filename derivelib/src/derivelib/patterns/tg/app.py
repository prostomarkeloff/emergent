"""TGApp — unified multi-part TG pattern coordinator.

One TGApp instance owns all TG sub-patterns for an application.
Shared key_node, theme, callback registry.

    tg = TGApp(key_node=UserId, theme=ru_theme)

    @derive(tg.flow("register", description="Sign up"))
    @dataclass
    class Registration:
        name: Annotated[str, TextInput("Name?")]

    @derive(tg.browse("tasks", provider_node=TaskStore))
    @dataclass
    class TaskCard:
        id: Annotated[int, Identity]

    @derive(tg.dashboard("roulette", description="Spin"))
    @dataclass
    class RouletteTable:
        id: Annotated[int, Identity]

    @derive(tg.settings("config"))
    @dataclass
    class BotConfig:
        volume: Annotated[int, Counter("Volume:")]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from nodnod.agent.base import Agent
    from telegrinder.bot.dispatch import Dispatch

    from emergent.graph._family import ScopeFamily
    from emergent.wire.axis.surface._app import Application
    from emergent.wire.compile._lifetime import Tier

from emergent.wire.axis.surface.capabilities._base import SurfaceCapability

from derivelib.patterns.tg.browse import TGBrowsePattern
from derivelib.patterns.tg.dashboard import TGDashboardPattern
from derivelib.patterns.tg.flow import LaunchMode, ShowMode, TGFlowPattern
from derivelib.patterns.tg.registry import CallbackRegistry, CommandEntry
from derivelib.patterns.tg.settings import TGSettingsPattern
from derivelib.patterns.tg.uilib.theme import (
    DEFAULT_THEME,
    UITheme,
    ActionUI,
    DisplayUI,
    ErrorUI,
    NavUI,
    SelectionUI,
)


@dataclass
class TGApp:
    """Unified multi-part TG pattern — the coordinator.

    Creates sub-patterns (flow, browse, dashboard, settings) with shared
    key_node + theme, and validates command/callback uniqueness eagerly.

    Attributes:
        key_node: nodnod node type for session routing (shared by all patterns).
        theme: UITheme for all sub-patterns.
        registry: CallbackRegistry tracking commands and callback prefixes.
    """

    key_node: type
    theme: UITheme = field(default_factory=lambda: DEFAULT_THEME)
    registry: CallbackRegistry = field(default_factory=CallbackRegistry)
    agent_cls: type[Agent] | None = None
    family: ScopeFamily[Tier] | None = None

    def compile(self, app: Application) -> Dispatch:
        """Compile wire Application to telegrinder Dispatch with scope family.

        Convenience — wraps telegrinder_compile with this TGApp's family.
        Auto-binds key_node to Request tier if family is provided.
        """
        from emergent.wire.compile.targets.telegrinder import telegrinder_compile

        return telegrinder_compile(app, family=self._build_family())

    def _build_family(self) -> ScopeFamily[Tier] | None:
        """Build final family: user family + key_node bound to Request."""
        if self.family is None:
            return None
        from emergent.wire.compile._lifetime import Request

        return self.family.bind(Request, self.key_node)

    def flow(
        self,
        command: str,
        *caps: SurfaceCapability,
        description: str | None = None,
        order: int = 100,
        show_mode: ShowMode = ShowMode.SEND,
        launch_mode: LaunchMode = LaunchMode.STANDARD,
    ) -> TGFlowPattern:
        """Create a flow sub-pattern.

        Flow callbacks use SHA256 hash — collision-resistant by construction.
        Only command uniqueness is validated here.
        """
        self.registry.register_command(command, "flow", description, order)
        return TGFlowPattern(
            command=command,
            key_node=self.key_node,
            capabilities=caps,
            description=description,
            order=order,
            show_mode=show_mode,
            launch_mode=launch_mode,
            theme=self.theme,
            agent_cls=self.agent_cls,
        )

    def browse(
        self,
        command: str,
        provider_node: type,
        *caps: SurfaceCapability,
        page_size: int = 5,
        empty_text: str = "Nothing found.",
        cb_prefix: str = "",
        description: str | None = None,
        order: int = 100,
    ) -> TGBrowsePattern:
        """Create a browse sub-pattern.

        Callback prefix defaults to command[:6]. Validated for uniqueness.
        """
        actual_prefix = cb_prefix or command[:6]
        self.registry.register_command(command, "browse", description, order)
        self.registry.register_callback(actual_prefix, "browse", command)
        return TGBrowsePattern(
            command=command,
            provider_node=provider_node,
            key_node=self.key_node,
            page_size=page_size,
            empty_text=empty_text,
            capabilities=caps,
            cb_prefix=actual_prefix,
            description=description,
            order=order,
            theme=self.theme,
            agent_cls=self.agent_cls,
        )

    def dashboard(
        self,
        command: str,
        *caps: SurfaceCapability,
        empty_text: str = "Nothing found.",
        cb_prefix: str = "",
        description: str | None = None,
        order: int = 100,
    ) -> TGDashboardPattern:
        """Create a dashboard sub-pattern.

        Callback prefix defaults to command[:6]. Validated for uniqueness.
        """
        actual_prefix = cb_prefix or command[:6]
        self.registry.register_command(command, "dashboard", description, order)
        self.registry.register_callback(actual_prefix, "dashboard", command)
        return TGDashboardPattern(
            command=command,
            key_node=self.key_node,
            empty_text=empty_text,
            capabilities=caps,
            cb_prefix=actual_prefix,
            description=description,
            order=order,
            theme=self.theme,
            agent_cls=self.agent_cls,
        )

    def settings(
        self,
        command: str,
        *caps: SurfaceCapability,
        description: str | None = None,
        order: int = 100,
    ) -> TGSettingsPattern:
        """Create a settings sub-pattern.

        Settings callbacks use SHA256 hash — collision-resistant like flow.
        Only command uniqueness is validated here.
        """
        self.registry.register_command(command, "settings", description, order)
        return TGSettingsPattern(
            command=command,
            key_node=self.key_node,
            capabilities=caps,
            description=description,
            order=order,
            theme=self.theme,
            agent_cls=self.agent_cls,
        )

    @property
    def commands(self) -> Sequence[CommandEntry]:
        """All registered commands, sorted by (order, command)."""
        return self.registry.commands


__all__ = (
    "TGApp",
    # UILib (re-exported for single-import convenience)
    "UITheme",
    "DEFAULT_THEME",
    "NavUI",
    "SelectionUI",
    "ActionUI",
    "DisplayUI",
    "ErrorUI",
)
