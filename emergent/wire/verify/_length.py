from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from emergent.wire.compile._phase import CompilationPhase

from ._issue import Issue, Severity


@dataclass(frozen=True, slots=True)
class LengthVerifyCtx:
    """Accumulated length constraints for one field."""

    field_name: str
    field_type: type
    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None

    def check(self) -> tuple[Issue, ...]:
        issues: list[Issue] = []
        f = self.field_name

        # MinLen > MaxLen
        if self.min_length is not None and self.max_length is not None:
            if self.min_length > self.max_length:
                issues.append(Issue(
                    f, Severity.ERROR,
                    f"MinLen({self.min_length}) > MaxLen({self.max_length})",
                ))

        # MaxLen == 0
        if self.max_length is not None and self.max_length == 0:
            issues.append(Issue(
                f, Severity.WARNING,
                "MaxLen(0) — field cannot contain any characters",
            ))

        return tuple(issues)


@runtime_checkable
class LengthVerifyCompilable(Protocol):
    def compile_verify_length(self, ctx: LengthVerifyCtx) -> LengthVerifyCtx: ...


def _length_initial(name: str, field_type: type) -> LengthVerifyCtx:
    return LengthVerifyCtx(field_name=name, field_type=field_type)


LENGTH_VERIFY_PHASE = CompilationPhase(
    LengthVerifyCtx, LengthVerifyCompilable, _length_initial,
)
