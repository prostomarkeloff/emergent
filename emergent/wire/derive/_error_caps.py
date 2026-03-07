"""Generic error-handling capabilities — ResponseTransform pipeline.

Not CRUD-specific. Any pattern producing DomainError can use these.

    ErrorTransform: calls response.to_problem() if available
    ProblemResponse: wraps ProblemDetail in JSONResponse with status code
    ERROR_CAPS: standard (ErrorTransform, ProblemResponse) tuple

    from emergent.wire.derive._error_caps import ERROR_CAPS
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from emergent.wire.axis.surface.capabilities import SurfaceCapability
from emergent.wire.axis.surface.transforms import ResponseTransform

from emergent.wire.derive._errors import PROBLEM_SCHEMA as _PROBLEM_SCHEMA

if TYPE_CHECKING:
    from emergent.wire.axis._capability import FastAPIRouteContext


@dataclass(frozen=True, slots=True)
class ErrorTransform(ResponseTransform):
    """Calls response.to_problem() if available, passes through otherwise."""

    def apply_response(self, response: object) -> object:
        to_problem = getattr(response, "to_problem", None)
        if callable(to_problem):
            return to_problem()
        return response


@dataclass(frozen=True, slots=True)
class ProblemResponse(ResponseTransform):
    """Wraps ProblemDetail (status_code + dataclass fields) in JSONResponse."""

    media_type: str = "application/problem+json"

    def apply_response(self, response: object) -> object:
        status_code = getattr(response, "status_code", None)
        dc_fields: dict[str, type] | None = getattr(response, "__dataclass_fields__", None)
        if status_code is not None and dc_fields is not None:
            try:
                from starlette.responses import JSONResponse
            except ImportError:
                return response

            content = {name: getattr(response, name) for name in dc_fields}
            return JSONResponse(
                status_code=status_code,
                content=content,
                media_type=self.media_type,
            )
        return response

    def compile_fastapi_route(
        self, ctx: FastAPIRouteContext
    ) -> FastAPIRouteContext:
        from dataclasses import replace

        error_responses = {
            "404": {
                "description": "Resource not found",
                "content": {self.media_type: {"schema": _PROBLEM_SCHEMA}},
            },
            "409": {
                "description": "Resource conflict",
                "content": {self.media_type: {"schema": _PROBLEM_SCHEMA}},
            },
            "422": {
                "description": "Validation error",
                "content": {self.media_type: {"schema": _PROBLEM_SCHEMA}},
            },
        }

        existing = dict(ctx.openapi_extra) if ctx.openapi_extra else {}
        existing_responses = existing.get("responses", {})
        merged_responses = {**error_responses, **existing_responses}
        new_extra = {**existing, "responses": merged_responses}

        return replace(ctx, openapi_extra=new_extra)


ERROR_CAPS: tuple[SurfaceCapability, ...] = (ErrorTransform(), ProblemResponse())


__all__ = (
    "ErrorTransform",
    "ProblemResponse",
    "ERROR_CAPS",
)
