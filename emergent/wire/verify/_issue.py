from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Issue:
    """Single verification issue found during compile-time check."""

    field: str
    severity: Severity
    message: str


class VerificationError(Exception):
    """Raised by verify_raising when verification finds errors."""

    def __init__(self, message: str, issues: tuple[Issue, ...]) -> None:
        super().__init__(message)
        self.issues = issues
