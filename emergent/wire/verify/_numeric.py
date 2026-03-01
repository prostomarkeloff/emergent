from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from emergent.wire.compile._phase import CompilationPhase

from ._issue import Issue, Severity


@dataclass(frozen=True, slots=True)
class NumericVerifyCtx:
    """Accumulated numeric constraints for one field."""

    field_name: str
    field_type: type
    lower_bound: float | None = None
    upper_bound: float | None = None
    exclusive_lower: float | None = None
    exclusive_upper: float | None = None
    multiple_of: float | None = None

    def check(self) -> tuple[Issue, ...]:
        issues: list[Issue] = []
        f = self.field_name

        # Min > Max
        if self.lower_bound is not None and self.upper_bound is not None:
            if self.lower_bound > self.upper_bound:
                issues.append(Issue(
                    f, Severity.ERROR,
                    f"Min({self.lower_bound}) > Max({self.upper_bound})",
                ))

        # ExclusiveMin >= ExclusiveMax
        if self.exclusive_lower is not None and self.exclusive_upper is not None:
            if self.exclusive_lower >= self.exclusive_upper:
                issues.append(Issue(
                    f, Severity.ERROR,
                    f"ExclusiveMin({self.exclusive_lower}) >= ExclusiveMax({self.exclusive_upper})",
                ))

        # Min >= ExclusiveMax → empty range
        if self.lower_bound is not None and self.exclusive_upper is not None:
            if self.lower_bound >= self.exclusive_upper:
                issues.append(Issue(
                    f, Severity.ERROR,
                    f"Min({self.lower_bound}) >= ExclusiveMax({self.exclusive_upper}) — empty range",
                ))

        # ExclusiveMin >= Max → empty range
        if self.exclusive_lower is not None and self.upper_bound is not None:
            if self.exclusive_lower >= self.upper_bound:
                issues.append(Issue(
                    f, Severity.ERROR,
                    f"ExclusiveMin({self.exclusive_lower}) >= Max({self.upper_bound}) — empty range",
                ))

        return tuple(issues)


@runtime_checkable
class NumericVerifyCompilable(Protocol):
    def compile_verify_numeric(self, ctx: NumericVerifyCtx) -> NumericVerifyCtx: ...


def _numeric_initial(name: str, field_type: type) -> NumericVerifyCtx:
    return NumericVerifyCtx(field_name=name, field_type=field_type)


NUMERIC_VERIFY_PHASE = CompilationPhase(
    NumericVerifyCtx, NumericVerifyCompilable, _numeric_initial,
)
