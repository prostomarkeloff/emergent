"""Entry point for cross-compiled CLI.

Run:
    python -m examples.cross_compile notes-list
    python -m examples.cross_compile notes-create "Title" "Content"
    python -m examples.cross_compile state
"""

from examples.cross_compile.bridge import cli_parser
from emergent.wire.compile.targets.cli import cli_run

if __name__ == "__main__":
    cli_run(cli_parser)
