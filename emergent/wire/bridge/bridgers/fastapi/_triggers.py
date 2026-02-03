"""FastAPI trigger types and builders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NotRequired, TypedDict


class FastAPITriggerData(TypedDict):
    """FastAPI HTTP route trigger data."""

    method: str
    path: str
    name: NotRequired[str | None]
    operation_id: NotRequired[str | None]
    tags: NotRequired[list[str]]
    summary: NotRequired[str | None]
    deprecated: NotRequired[bool]


@dataclass(frozen=True, slots=True)
class FastAPITriggerBuilder:
    """TriggerBuilder for FastAPI -> HTTPRouteTrigger."""

    def build(self, data: FastAPITriggerData) -> object:
        """Convert FastAPI trigger data to HTTPRouteTrigger."""
        from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger, Method

        method_str = data["method"]
        method: Method
        match method_str:
            case "GET" | "POST" | "PUT" | "DELETE" | "PATCH":
                method = method_str
            case _:
                method = "GET"

        return HTTPRouteTrigger(method, data["path"])


__all__ = (
    "FastAPITriggerData",
    "FastAPITriggerBuilder",
)
