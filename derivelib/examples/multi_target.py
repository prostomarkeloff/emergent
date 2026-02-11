"""One entity. Every target.

Same dataclass compiles to HTTP REST API and CLI tool.
Add a TG trigger and you get a Telegram bot too.

    uv run python -m derivelib.examples.multi_target http
    uv run python -m derivelib.examples.multi_target cli product-create laptop 999.99
    uv run python -m derivelib.examples.multi_target cli product-list
"""

from __future__ import annotations

from dataclasses import dataclass  # noqa: I001
from typing import Annotated

from emergent.wire.axis.schema import Identity

from derivelib import derive, build_application_from_decorated, memory_node
from derivelib.patterns.crud import http_crud, cli_crud


# --- provider ---

Store = memory_node()


# --- one definition, two projections ---

@derive(
    http_crud("/products", provider_node=Store),
    cli_crud("product", provider_node=Store),
)
@dataclass
class Product:
    id: Annotated[int, Identity]
    name: str
    price: float
    in_stock: bool = True


app = build_application_from_decorated(Product)

from emergent.wire.compile import targets  # noqa: E402
from emergent.wire.compile.targets.cli import TYPED_CLI  # noqa: E402

if __name__ == "__main__":
    import sys

    from derivelib import endpoint_count
    n = endpoint_count(app)
    mode = sys.argv[1] if len(sys.argv) > 1 else "http"

    if mode == "http":
        fastapi_app = targets.fastapi.compile(app)
        print(f"\n  1 dataclass -> {n} exposures (HTTP + CLI)")
        print("  curl http://localhost:8000/products\n")
        import uvicorn
        uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)

    elif mode == "cli":
        parser = targets.cli.cli_compile(app, prog="shop", compiler=TYPED_CLI)
        exit_code = targets.cli.cli_run(parser, sys.argv[2:])
        sys.exit(exit_code)

    else:
        print("Usage: python -m derivelib.examples.multi_target {http|cli} [args]")
