"""
Entry point.

Run: uv run python -m examples.full_stack.main
"""

import asyncio
from examples.full_stack.cli import run_cli


if __name__ == "__main__":
    asyncio.run(run_cli())

