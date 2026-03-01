from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from emergent.wire.compile._phase import CompilationPhase

from ._issue import Issue, Severity


@dataclass(frozen=True, slots=True)
class SemanticsVerifyCtx:
    """Accumulated semantic flags for one field."""

    field_name: str
    field_type: type
    is_read_only: bool = False
    is_write_only: bool = False
    is_computed: bool = False
    is_immutable: bool = False
    is_sensitive: bool = False
    is_identity: bool = False
    is_unique: bool = False
    is_nullable: bool = False

    def check(self) -> tuple[Issue, ...]:
        issues: list[Issue] = []
        f = self.field_name

        # ReadOnly + WriteOnly = inaccessible
        if self.is_read_only and self.is_write_only:
            issues.append(Issue(
                f, Severity.ERROR,
                "ReadOnly + WriteOnly — field is inaccessible",
            ))

        # Computed + WriteOnly = nonsense (Computed implies read-only)
        if self.is_computed and self.is_write_only:
            issues.append(Issue(
                f, Severity.ERROR,
                "Computed + WriteOnly — computed is read-only by definition",
            ))

        # Identity + Nullable
        if self.is_identity and self.is_nullable:
            issues.append(Issue(
                f, Severity.WARNING,
                "Identity + Nullable — primary key should not be nullable",
            ))

        # Unique + Nullable
        if self.is_unique and self.is_nullable:
            issues.append(Issue(
                f, Severity.WARNING,
                "Unique + Nullable — multiple NULLs may bypass unique constraint",
            ))

        # Identity + Computed
        if self.is_identity and self.is_computed:
            issues.append(Issue(
                f, Severity.WARNING,
                "Identity + Computed — ID depends on runtime computation",
            ))

        return tuple(issues)


@runtime_checkable
class SemanticsVerifyCompilable(Protocol):
    def compile_verify_semantics(self, ctx: SemanticsVerifyCtx) -> SemanticsVerifyCtx: ...


def _semantics_initial(name: str, field_type: type) -> SemanticsVerifyCtx:
    return SemanticsVerifyCtx(field_name=name, field_type=field_type)


SEMANTICS_VERIFY_PHASE = CompilationPhase(
    SemanticsVerifyCtx, SemanticsVerifyCompilable, _semantics_initial,
)
