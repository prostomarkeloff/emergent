"""Tests for the CLI surface dialect capabilities.

Covers Help, Description, Epilog, and Hidden capabilities from
emergent.wire.axis.surface.dialects.cli.
"""

from __future__ import annotations

import pytest

from emergent.wire.axis._capability import CLICommandContext
from emergent.wire.axis.surface.dialects import cli as cli_cmd


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def fresh_ctx() -> CLICommandContext:
    return CLICommandContext(name="test")


@pytest.fixture()
def populated_ctx() -> CLICommandContext:
    return CLICommandContext(
        name="test",
        help="old help",
        description="old description",
        epilog="old epilog",
        hidden=False,
    )


# ─── Help ─────────────────────────────────────────────────────────────────────


def test_help_sets_help_on_fresh_ctx(fresh_ctx: CLICommandContext) -> None:
    result = cli_cmd.Help("List all users").compile_cli(fresh_ctx)

    assert result.help == "List all users"
    assert result.name == "test"
    assert result.description is None
    assert result.epilog is None
    assert result.hidden is False


def test_help_overwrites_existing_help(populated_ctx: CLICommandContext) -> None:
    result = cli_cmd.Help("new help").compile_cli(populated_ctx)

    assert result.help == "new help"
    # other fields are carried over unchanged
    assert result.description == "old description"
    assert result.epilog == "old epilog"
    assert result.hidden is False


def test_help_does_not_mutate_original_ctx(fresh_ctx: CLICommandContext) -> None:
    cli_cmd.Help("some text").compile_cli(fresh_ctx)

    assert fresh_ctx.help is None


# ─── Description ─────────────────────────────────────────────────────────────


def test_description_sets_description_on_fresh_ctx(fresh_ctx: CLICommandContext) -> None:
    result = cli_cmd.Description("Long description here").compile_cli(fresh_ctx)

    assert result.description == "Long description here"
    assert result.name == "test"
    assert result.help is None
    assert result.epilog is None
    assert result.hidden is False


def test_description_overwrites_existing_description(populated_ctx: CLICommandContext) -> None:
    result = cli_cmd.Description("new description").compile_cli(populated_ctx)

    assert result.description == "new description"
    assert result.help == "old help"
    assert result.epilog == "old epilog"
    assert result.hidden is False


def test_description_does_not_mutate_original_ctx(fresh_ctx: CLICommandContext) -> None:
    cli_cmd.Description("text").compile_cli(fresh_ctx)

    assert fresh_ctx.description is None


# ─── Epilog ───────────────────────────────────────────────────────────────────


def test_epilog_sets_epilog_on_fresh_ctx(fresh_ctx: CLICommandContext) -> None:
    result = cli_cmd.Epilog("Examples:\n  my-tool users").compile_cli(fresh_ctx)

    assert result.epilog == "Examples:\n  my-tool users"
    assert result.name == "test"
    assert result.help is None
    assert result.description is None
    assert result.hidden is False


def test_epilog_overwrites_existing_epilog(populated_ctx: CLICommandContext) -> None:
    result = cli_cmd.Epilog("new epilog").compile_cli(populated_ctx)

    assert result.epilog == "new epilog"
    assert result.help == "old help"
    assert result.description == "old description"
    assert result.hidden is False


def test_epilog_does_not_mutate_original_ctx(fresh_ctx: CLICommandContext) -> None:
    cli_cmd.Epilog("text").compile_cli(fresh_ctx)

    assert fresh_ctx.epilog is None


# ─── Hidden ───────────────────────────────────────────────────────────────────


def test_hidden_sets_hidden_true_on_fresh_ctx(fresh_ctx: CLICommandContext) -> None:
    result = cli_cmd.Hidden().compile_cli(fresh_ctx)

    assert result.hidden is True
    assert result.name == "test"
    assert result.help is None
    assert result.description is None
    assert result.epilog is None


def test_hidden_sets_hidden_true_on_populated_ctx(populated_ctx: CLICommandContext) -> None:
    result = cli_cmd.Hidden().compile_cli(populated_ctx)

    assert result.hidden is True
    assert result.help == "old help"
    assert result.description == "old description"
    assert result.epilog == "old epilog"


def test_hidden_does_not_mutate_original_ctx(fresh_ctx: CLICommandContext) -> None:
    cli_cmd.Hidden().compile_cli(fresh_ctx)

    assert fresh_ctx.hidden is False


# ─── CLICommandContext frozen immutability ─────────────────────────────────────


def test_cli_command_context_is_frozen() -> None:
    ctx = CLICommandContext(name="immutable")
    with pytest.raises((AttributeError, TypeError)):
        ctx.help = "should fail"  # type: ignore[misc]
