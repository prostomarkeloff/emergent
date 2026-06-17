"""Generic error-handling capabilities — ResponseTransform pipeline.

Not CRUD-specific. Any pattern producing DomainError can use these.

    ErrorTransform: calls response.to_problem() if available
    ProblemResponse: wraps ProblemDetail in JSONResponse with status code
    ERROR_CAPS: standard (ErrorTransform, ProblemResponse) tuple

    from emergent.wire.derive._error_caps import ERROR_CAPS
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TYPE_CHECKING, runtime_checkable

from emergent.wire.axis.surface.capabilities import SurfaceCapability
from emergent.wire.axis.surface.transforms import ResponseTransform

from emergent.wire.derive._errors import PROBLEM_SCHEMA as _PROBLEM_SCHEMA

if TYPE_CHECKING:
    from emergent.wire.axis._capability import FastAPIRouteContext


@runtime_checkable
class _HasToProblem(Protocol):
    # Any — return is a domain-specific problem envelope, structurally opaque here.
    def to_problem(self) -> Any: ...


@runtime_checkable
class _ProblemLike(Protocol):
    # Any — status_code / to_dict() values are framework-opaque at this boundary.
    status_code: Any

    def to_dict(self) -> Any: ...


@dataclass(frozen=True, slots=True)
class ErrorTransform(ResponseTransform):
    """Calls response.to_problem() if available, passes through otherwise."""

    def apply_response(self, response: Any) -> Any:
        if isinstance(response, _HasToProblem) and callable(response.to_problem):
            return response.to_problem()
        return response


@dataclass(frozen=True, slots=True)
class ProblemResponse(ResponseTransform):
    """Wraps ProblemDetail in JSONResponse per RFC 9457.

    Uses ``to_dict()`` to serialize — omits None fields (e.g. ``instance``
    when not set). This ensures the response body matches PROBLEM_SCHEMA.
    """

    media_type: str = "application/problem+json"

    def apply_response(self, response: Any) -> Any:
        if (
            isinstance(response, _ProblemLike)
            and callable(response.to_dict)
            and response.status_code is not None
        ):
            try:
                from starlette.responses import JSONResponse
            except ImportError:
                return response

            return JSONResponse(
                status_code=response.status_code,
                content=response.to_dict(),
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
