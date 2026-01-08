"""
emergent — compositional patterns for Python backends.

    from emergent import saga as S   # Distributed transactions
    from emergent import cache as C  # Multi-tier caching
    from emergent import graph as G  # Computation graphs
"""

from emergent import saga
from emergent import cache
from emergent import graph
from emergent import lift
from emergent._types import (
    Lazy,
    Pure,
    Fallible,
    NodeId,
    LCR,
    NoError,
)

__version__ = "0.1.0"

__all__ = (
    "saga",
    "cache",
    "graph",
    "lift",
    "Lazy",
    "Pure",
    "Fallible",
    "NodeId",
    "LCR",
    "NoError",
)
