"""Generic domain errors — shared across all derivation patterns.

Not CRUD-specific. Any pattern that works with entities
needs NotFound, AlreadyExists, InvalidData.

ProblemDetail follows RFC 9457 / RFC 7807 (Problem Details for HTTP APIs).

    from emergent.wire.derive._errors import NotFound, AlreadyExists

    return Error(NotFound(entity="User", id=42))

type URIs follow the pattern ``urn:emergent:error:<kind>`` — stable,
machine-readable identifiers that clients can match on. ``about:blank``
is only for generic HTTP errors with no further semantics (per RFC 9457 §4.2.1).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


# Identity values: {field_name: field_value}. Values are int | str in practice
# (int for auto-increment, str for UUID/slug). Mapping because read-only.
type IdentityMap = Mapping[str, int | str]

# Mutable result of ProblemDetail.to_dict() (built then conditionally extended).
type ProblemDict = dict[str, str | int]


@dataclass(frozen=True, slots=True)
class ProblemDetail:
    """RFC 9457 Problem Detail — generic error envelope.

    ``type``: URI identifying the problem TYPE (stable, same for all instances).
    ``title``: Human-readable, SAME for same ``type`` (never changes per-instance).
    ``status``: HTTP status code.
    ``detail``: Human-readable, specific to THIS occurrence.
    ``instance``: URI identifying THIS specific occurrence (optional, omit if not meaningful).
    """

    type: str
    title: str
    status: int
    detail: str
    instance: str | None = None

    @property
    def status_code(self) -> int:
        return self.status

    def to_dict(self) -> ProblemDict:
        """Serialize to JSON-compatible dict, omitting None fields."""
        d: ProblemDict = {
            "type": self.type,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
        }
        if self.instance is not None:
            d["instance"] = self.instance
        return d


@dataclass(frozen=True, slots=True)
class NotFound:
    """Entity not found by identity."""

    entity: str
    id: IdentityMap

    def to_problem(self) -> ProblemDetail:
        return ProblemDetail(
            type="urn:emergent:error:not-found",
            title="Not Found",
            status=404,
            detail=f"{self.entity} with id {self.id} not found",
        )


@dataclass(frozen=True, slots=True)
class AlreadyExists:
    """Entity with given identity already exists."""

    entity: str
    id: IdentityMap

    def to_problem(self) -> ProblemDetail:
        return ProblemDetail(
            type="urn:emergent:error:already-exists",
            title="Conflict",
            status=409,
            detail=f"{self.entity} with id {self.id} already exists",
        )


@dataclass(frozen=True, slots=True)
class InvalidData:
    """Entity data failed validation."""

    entity: str
    reason: str

    def to_problem(self) -> ProblemDetail:
        return ProblemDetail(
            type="urn:emergent:error:invalid-data",
            title="Unprocessable Entity",
            status=422,
            detail=f"Invalid {self.entity}: {self.reason}",
        )


DomainError = NotFound | AlreadyExists | InvalidData


@runtime_checkable
class HasToProblem(Protocol):
    """Protocol for custom error types that can convert to ProblemDetail.

    Implement this on custom domain errors to integrate with
    error capabilities (ErrorTransform, ProblemResponse).
    """

    def to_problem(self) -> ProblemDetail: ...

# RFC 9457 Problem Detail JSON Schema — shared by error caps and openapi.
type JSONSchemaValue = str | int | bool | Sequence[str] | Mapping[str, JSONSchemaValue]
type JSONSchema = Mapping[str, JSONSchemaValue]

PROBLEM_SCHEMA: JSONSchema = {
    "type": "object",
    "properties": {
        "type": {"type": "string"},
        "title": {"type": "string"},
        "status": {"type": "integer"},
        "detail": {"type": "string"},
        "instance": {"type": "string"},
    },
    "required": ["type", "title", "status"],
}


__all__ = (
    "IdentityMap",
    "ProblemDetail",
    "NotFound",
    "AlreadyExists",
    "InvalidData",
    "DomainError",
    "HasToProblem",
    "JSONSchema",
    "PROBLEM_SCHEMA",
)
