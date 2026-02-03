"""WebSocket trigger — bidirectional connections.

    endpoint(runner).expose(
        WebSocketTrigger("/ws/game"),
        delegate(game_handler),
        Auth(),
    )
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WebSocketTrigger:
    """WebSocket connection endpoint.

    Attributes:
        path: URL path for WebSocket endpoint.
        name: Optional name for the endpoint.

    Example::

        async def chat_handler(websocket: WebSocket, user: AuthUser):
            await websocket.accept()
            async for message in websocket.iter_text():
                await websocket.send_text(f"Echo: {message}")

        endpoint(runner).expose(
            WebSocketTrigger("/ws/chat"),
            delegate(chat_handler),
            Auth(),
        )
    """

    path: str
    name: str | None = None


__all__ = ("WebSocketTrigger",)
