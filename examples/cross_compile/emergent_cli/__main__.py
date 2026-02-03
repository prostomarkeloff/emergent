"""Entry point for emergent CLI.

Run:
    python -m examples.cross_compile.emergent_cli hello
"""

from examples.cross_compile.emergent_cli.app import cli_parser
from emergent.wire.compile.targets.cli import cli_run

if __name__ == "__main__":
    cli_run(cli_parser)
