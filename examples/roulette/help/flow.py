"""Help response — immediate codec, no domain layer."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HelpResponse:
    """Help response for Telegram."""
    text: str

    def __str__(self) -> str:
        return self.text
