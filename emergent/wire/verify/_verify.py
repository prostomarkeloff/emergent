from __future__ import annotations

from typing import Any

from emergent.wire.compile._core import Axes
from emergent.wire.compile._phase import CompilationPhase, SchemaCompiler

from ._issue import Issue, Severity, VerificationError
from ._length import LENGTH_VERIFY_PHASE
from ._numeric import NUMERIC_VERIFY_PHASE
from ._semantics import SEMANTICS_VERIFY_PHASE

VERIFY_PHASES: tuple[CompilationPhase[Any], ...] = (
    NUMERIC_VERIFY_PHASE,
    LENGTH_VERIFY_PHASE,
    SEMANTICS_VERIFY_PHASE,
)

VERIFY_SCHEMA = SchemaCompiler(phases=VERIFY_PHASES)


def verify(
    *entities: type,
    axes: Axes | None = None,
    phases: tuple[CompilationPhase[Any], ...] = VERIFY_PHASES,
) -> tuple[Issue, ...]:
    """Compile entities with verify phases and collect issues.

    Each verify context must have a ``check() -> tuple[Issue, ...]`` method.
    """
    _axes = axes or Axes.default()
    compiler = SchemaCompiler(phases=phases)
    issues: list[Issue] = []
    for entity in entities:
        ec = compiler.compile(entity, _axes)
        for fc in ec:
            for phase in phases:
                ctx = fc[phase]
                issues.extend(ctx.check())
    return tuple(issues)


def verify_raising(
    *entities: type,
    axes: Axes | None = None,
    phases: tuple[CompilationPhase[Any], ...] = VERIFY_PHASES,
) -> None:
    """Verify entities and raise on errors. Convenience for fail-fast at import time."""
    issues = verify(*entities, axes=axes, phases=phases)
    errors = tuple(i for i in issues if i.severity is Severity.ERROR)
    if errors:
        msg = "\n".join(f"  {e.field}: {e.message}" for e in errors)
        raise VerificationError(f"Verification failed:\n{msg}", issues=errors)
