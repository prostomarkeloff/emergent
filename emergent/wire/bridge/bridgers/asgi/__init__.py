"""ASGI bridger — capabilities for ASGI-based frameworks.

Works with: FastAPI, Starlette, Quart, and other ASGI frameworks.
"""

from emergent.wire.bridge.bridgers.asgi._capabilities import MountASGI

__all__ = ("MountASGI",)
