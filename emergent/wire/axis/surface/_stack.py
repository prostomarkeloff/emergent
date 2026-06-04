"""AppStack — composition of applications with prefix routing."""

from __future__ import annotations

from dataclasses import dataclass, field

from emergent.wire.axis.surface._app import Application


@dataclass(slots=True)
class AppStack:
    """Stack of applications with prefix routing.

    Enables nested command structures:

        main_app = application()  # scan, graph, doctor
        new_app = application()   # op, handler

        stack = (
            AppStack()
            .root(main_app)           # cli scan/graph/doctor
            .mount("new", new_app)    # cli new op/handler
        )

    Compilers (CLI, REST, etc.) understand AppStack and create
    appropriate nested routing.
    """

    root_app: Application = field(default_factory=Application)
    mounts: dict[str, Application | AppStack] = field(default_factory=dict)

    def root(self, app: Application) -> AppStack:
        """Set root application (top-level commands)."""
        return AppStack(
            root_app=Application(endpoints=(*self.root_app.endpoints, *app.endpoints)),
            mounts=self.mounts,
        )

    def mount(self, prefix: str, app: Application | AppStack) -> AppStack:
        """Mount application or stack under prefix."""
        return AppStack(root_app=self.root_app, mounts={**self.mounts, prefix: app})


def app_stack() -> AppStack:
    """Create a new AppStack."""
    return AppStack()
