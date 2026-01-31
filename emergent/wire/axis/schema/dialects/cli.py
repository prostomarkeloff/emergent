"""CLI dialect — CLI-specific capabilities for argparse generation.

These are IGNORED by other compilers (FastAPI, Pydantic, etc.)

    from emergent.wire.axis.schema.dialects import cli

    @dataclass
    class Register:
        login: Annotated[str, MinLen(3), cli.Help("Username to register")]
        verbose: Annotated[bool, cli.Flag("--verbose", "-v")]
        output: Annotated[str, cli.Choices("json", "yaml", "text")]
"""

from dataclasses import dataclass

from emergent.wire.axis.schema._universal import Capability


class CLICapability(Capability):
    """Base for CLI-specific capabilities."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Help & Documentation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Help(CLICapability):
    """Help text for argument.

    Example:
        login: Annotated[str, cli.Help("Username to register")]
    """
    text: str


@dataclass(frozen=True, slots=True)
class Metavar(CLICapability):
    """Metavar for argument display.

    Example:
        file: Annotated[str, cli.Metavar("FILE")]
        # Shows: --file FILE
    """
    name: str


# ═══════════════════════════════════════════════════════════════════════════════
# Argument Naming
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Flag(CLICapability):
    """Explicit flag name(s) for optional argument.

    Example:
        verbose: Annotated[bool, cli.Flag("--verbose", "-v")]
        output: Annotated[str, cli.Flag("-o", "--output")]
    """
    names: tuple[str, ...]

    def __init__(self, *names: str) -> None:
        object.__setattr__(self, "names", names)


@dataclass(frozen=True, slots=True)
class Positional(CLICapability):
    """Mark as positional argument with optional custom name.

    Example:
        file: Annotated[str, cli.Positional("input_file")]
    """
    name: str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Value Constraints
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Choices(CLICapability):
    """Allowed values for argument.

    Example:
        format: Annotated[str, cli.Choices("json", "yaml", "text")]
    """
    values: tuple[str, ...]

    def __init__(self, *values: str) -> None:
        object.__setattr__(self, "values", values)


@dataclass(frozen=True, slots=True)
class Nargs(CLICapability):
    """Number of arguments to consume.

    Example:
        files: Annotated[list[str], cli.Nargs("+")]  # one or more
        items: Annotated[list[str], cli.Nargs("*")]  # zero or more
        pair: Annotated[list[str], cli.Nargs(2)]     # exactly 2
    """
    count: str | int  # "+", "*", "?", or int


# ═══════════════════════════════════════════════════════════════════════════════
# Actions
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Action(CLICapability):
    """Argparse action.

    Example:
        verbose: Annotated[int, cli.Action("count")]  # -v -v -v → 3
        no_cache: Annotated[bool, cli.Action("store_false")]
    """
    action: str


@dataclass(frozen=True, slots=True)
class Append(CLICapability):
    """Append action — collect multiple values.

    Example:
        includes: Annotated[list[str], cli.Append()]
        # --include foo --include bar → ["foo", "bar"]
    """
    pass


@dataclass(frozen=True, slots=True)
class Count(CLICapability):
    """Count action — count occurrences.

    Example:
        verbose: Annotated[int, cli.Count()]
        # -v -v -v → 3
    """
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Environment & Defaults
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Env(CLICapability):
    """Read default from environment variable.

    Example:
        token: Annotated[str, cli.Env("API_TOKEN")]
    """
    var: str


@dataclass(frozen=True, slots=True)
class Required(CLICapability):
    """Mark optional argument as required.

    Example:
        config: Annotated[str, cli.Flag("--config"), cli.Required()]
    """
    pass


__all__ = (
    "CLICapability",
    # Help
    "Help",
    "Metavar",
    # Naming
    "Flag",
    "Positional",
    # Values
    "Choices",
    "Nargs",
    # Actions
    "Action",
    "Append",
    "Count",
    # Environment
    "Env",
    "Required",
)
