"""CLI adapter — functional compiler for argparse.

    from emergent.wire.compiler import Axes, cli_compile

    axes = Axes.default()
    parser = cli_compile(wire_app, axes, prog="my-tool")
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from emergent.wire._handler import Handler
from emergent.wire._scan import scan, scan_stack, StackView
from emergent.wire.axis.surface._app import Application
from emergent.wire.axis.surface._stack import AppStack
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec
from emergent.wire.axis.surface.codecs.stateful import StatefulCodec, get_transitions
from emergent.wire.axis.surface.codecs.resolve import get_method_params
from emergent.wire.axis.surface.triggers.cli import CLITrigger

from emergent.wire.compiler._core import Axes
from emergent.wire.compiler._rrc import execute_rrc
from emergent.wire.compiler._stateful import (
    execute_stateful_turn,
    execute_stateful_done,
)
from emergent.wire.compiler._generate import to_argparse_args, ArgSpec


# ═══════════════════════════════════════════════════════════════════════════════
# Request Construction
# ═══════════════════════════════════════════════════════════════════════════════


def construct_request(req_cls: type, ns: argparse.Namespace) -> Any:
    """Construct request from namespace."""
    from typing import get_type_hints

    hints = get_type_hints(req_cls)
    ns_dict = vars(ns)
    kwargs = {k: v for k, v in ns_dict.items() if k in hints}
    return req_cls(**kwargs)


# ═══════════════════════════════════════════════════════════════════════════════
# RRC Handler
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_rrc_cli(
    handler: Handler[RequestResponseCodec],
    axes: Axes,
) -> tuple[list[ArgSpec], Any]:
    """Wrap RRC handler for CLI.

    Returns: (arg_specs, async_handler)
    """
    req_cls = handler.codec.request
    arg_specs = to_argparse_args(req_cls, axes)

    async def _handler(ns: argparse.Namespace) -> str:
        request = construct_request(req_cls, ns)
        response = await execute_rrc(handler, request)
        return str(response)

    return (arg_specs, _handler)


# ═══════════════════════════════════════════════════════════════════════════════
# Stateful Handler
# ═══════════════════════════════════════════════════════════════════════════════


def _prompt_value(name: str, type_hint: type) -> Any:
    """Prompt user for value."""
    try:
        raw = input(f"{name}: ").strip()
        if not raw:
            return None
        if type_hint is int:
            return int(raw)
        if type_hint is float:
            return float(raw)
        if type_hint is bool:
            return raw.lower() in ("true", "yes", "1", "y")
        return raw
    except (ValueError, EOFError, KeyboardInterrupt):
        return None


def _compose_cli_param(
    name: str,
    original_type: type,
    compose_type: type,
    cli_args: dict[str, Any],
) -> Any:
    """Compose single CLI param."""
    from emergent.wire.axis.surface.codecs.resolve import wrap

    # From CLI args
    if name in cli_args and cli_args[name] is not None:
        return wrap(original_type, True, cli_args[name])

    # Prompt
    raw = _prompt_value(name, compose_type)
    if raw is not None:
        return wrap(original_type, True, raw)

    return wrap(original_type, False, "no input")


def wrap_stateful_cli(
    handler: Handler[StatefulCodec],
    axes: Axes,
) -> Any:
    """Wrap StatefulCodec for CLI (interactive)."""
    codec = handler.codec
    transitions = get_transitions(codec.flow)

    async def _handler(ns: argparse.Namespace) -> str:
        cli_args = {k: v for k, v in vars(ns).items() if not k.startswith("_")}
        state = codec.flow()

        while True:
            # Use first transition for CLI
            method = transitions[0] if transitions else None
            if method is None:
                raise RuntimeError("No transitions defined")

            params = get_method_params(method)
            composed = {
                name: _compose_cli_param(name, orig, comp, cli_args)
                for name, (orig, comp) in params.items()
            }

            new_state, response, is_terminal = await execute_stateful_turn(
                handler, state, method, composed
            )

            if not is_terminal:
                state = new_state
                if response is not None:
                    print(response)
                continue

            # Done
            _, rejection, final = await execute_stateful_done(handler, new_state)
            if rejection is not None:
                return str(rejection)
            return str(final)

    return _handler


# ═══════════════════════════════════════════════════════════════════════════════
# Registration
# ═══════════════════════════════════════════════════════════════════════════════


def register_rrc(
    subparsers: Any,
    trigger: CLITrigger,
    handler: Handler[RequestResponseCodec],
    axes: Axes,
) -> None:
    """Register RRC as subcommand."""
    arg_specs, async_handler = wrap_rrc_cli(handler, axes)

    sub = subparsers.add_parser(trigger.command, help=trigger.description)
    for spec in arg_specs:
        if spec.is_positional:
            sub.add_argument(spec.name, **spec.kwargs)
        else:
            sub.add_argument(spec.name, dest=spec.dest, **spec.kwargs)

    sub.set_defaults(_handler=async_handler)


def register_stateful(
    subparsers: Any,
    trigger: CLITrigger,
    handler: Handler[StatefulCodec],
    axes: Axes,
) -> None:
    """Register Stateful as subcommand."""
    async_handler = wrap_stateful_cli(handler, axes)

    sub = subparsers.add_parser(trigger.command, help=trigger.description)
    sub.set_defaults(_handler=async_handler)


def register_handler(
    subparsers: Any,
    trigger: CLITrigger,
    handler: Handler[Any],
    axes: Axes,
) -> None:
    """Register handler based on codec type."""
    if isinstance(handler.codec, RequestResponseCodec):
        register_rrc(subparsers, trigger, handler, axes)
    elif isinstance(handler.codec, StatefulCodec):
        register_stateful(subparsers, trigger, handler, axes)


# ═══════════════════════════════════════════════════════════════════════════════
# Compilation
# ═══════════════════════════════════════════════════════════════════════════════


def cli_compile(
    app: Application,
    axes: Axes | None = None,
    prog: str = "cli",
) -> argparse.ArgumentParser:
    """Compile wire Application to argparse parser."""
    axes = axes or Axes.default()
    parser = argparse.ArgumentParser(prog=prog)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for trigger, handler in scan(app, CLITrigger, RequestResponseCodec):
        register_rrc(subparsers, trigger, handler, axes)

    for trigger, handler in scan(app, CLITrigger, StatefulCodec):
        register_stateful(subparsers, trigger, handler, axes)

    return parser


def cli_compile_stack(
    stack: AppStack,
    axes: Axes | None = None,
    prog: str = "cli",
) -> argparse.ArgumentParser:
    """Compile AppStack to argparse with nested subcommands."""
    axes = axes or Axes.default()
    parser = argparse.ArgumentParser(prog=prog)
    subparsers = parser.add_subparsers(dest="command", required=True)

    view = scan_stack(stack, CLITrigger)

    def build_tree(sp: Any, v: StackView[CLITrigger], depth: int = 0) -> None:
        for trigger, handler in v.root:
            register_handler(sp, trigger, handler, axes)

        for prefix, child in v.mounts.items():
            sub = sp.add_parser(prefix, help=f"{prefix} commands")
            nested_sp = sub.add_subparsers(
                dest=f"{'_' * depth}subcommand_{prefix}",
                required=True,
            )
            if isinstance(child, StackView):
                build_tree(nested_sp, child, depth + 1)
            else:
                for trigger, handler in child:
                    register_handler(nested_sp, trigger, handler, axes)

    build_tree(subparsers, view)
    return parser


def cli_run(parser: argparse.ArgumentParser, args: list[str] | None = None) -> int:
    """Run CLI: parse args, execute handler, print output."""
    import sys

    parsed = parser.parse_args(args)
    handler = getattr(parsed, "_handler", None)

    if handler is None:
        parser.print_help()
        return 1

    try:
        output = asyncio.run(handler(parsed))
        print(output)
        return 0
    except KeyboardInterrupt:
        print("\nAborted.")
        return 130
    except Exception as e:
        print(f"{e}", file=sys.stderr)
        return 1


__all__ = (
    "cli_compile",
    "cli_compile_stack",
    "cli_run",
    "wrap_rrc_cli",
    "wrap_stateful_cli",
    "register_handler",
)
