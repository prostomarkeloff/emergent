"""
Graph — computation graphs with auto-parallelization.

    from emergent import graph as G

    @G.node
    class FetchUser:
        @classmethod
        async def __compose__(cls, order: Order, db: Database) -> FetchUser:
            return cls(await db.get_user(order.user_id))

    result = await G.compose(FetchUser, order, db)
"""

from nodnod import scalar_node as node

from emergent.graph._run import (
    TypedScope,
    Run,
    run,
    compose,
)
from emergent.graph._compiled import (
    CompiledRun,
    Compiled,
    graph,
)
from emergent.graph._visualize import (
    to_mermaid,
    to_tree,
    to_text,
    to_ascii,
    visualize,
    get_layers,
    get_dependencies,
)

__all__ = (
    "node",
    "TypedScope",
    "run",
    "Run",
    "compose",
    "graph",
    "Compiled",
    "CompiledRun",
    # Visualization
    "to_mermaid",
    "to_tree",
    "to_text",
    "to_ascii",
    "visualize",
    "get_layers",
    "get_dependencies",
)
