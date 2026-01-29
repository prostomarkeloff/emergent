"""
CLI integration for emergent.wire.

    from emergent.wire.contrib import cli

    parser = cli.from_application(app, prog="my-tool")
    cli.run_parser(parser)
"""

from ._impls._cli import (
    compile_to_argparse,
    add_endpoint_to_parser,
    from_application,
    from_app_stack,
    run_parser,
)

__all__ = (
    "compile_to_argparse",
    "add_endpoint_to_parser",
    "from_application",
    "from_app_stack",
    "run_parser",
)
