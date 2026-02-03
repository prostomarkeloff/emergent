"""Extraction validation — verify extraction completeness.

FRAMEWORK-AGNOSTIC — validates generic extraction metadata.
Dependency-specific validation is done by capabilities.

    from emergent.wire.bridge._validate import validate_extraction

    report = validate_extraction(ctx, analysis)
    if not report.is_valid:
        for error in report.errors:
            print(f"Error: {error}")
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from emergent.wire.bridge._analyze import HandlerAnalysis
from emergent.wire.bridge._capabilities import BridgeContext


# ═══════════════════════════════════════════════════════════════════════════════
# Data Types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ExtractionReport:
    """Validation report for a single handler extraction."""

    handler_name: str
    is_valid: bool
    unmapped_depends: tuple[str, ...]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0


@dataclass(frozen=True, slots=True)
class ExtractionSummary:
    """Summary of all extraction validations."""

    total: int
    valid: int
    invalid: int
    reports: tuple[ExtractionReport, ...]
    all_unmapped: frozenset[str]

    @property
    def is_all_valid(self) -> bool:
        return self.invalid == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Validation Functions
# ═══════════════════════════════════════════════════════════════════════════════


def validate_extraction[T, **P, R](
    ctx: BridgeContext[T, P, R],
    analysis: HandlerAnalysis,
) -> ExtractionReport:
    """Validate that extraction is complete.

    FRAMEWORK-AGNOSTIC — checks only generic extraction state:
    - Codec is set
    - No obvious errors

    For dependency-specific validation (Depends(), globals, etc.),
    use specialized validation capabilities.

    Args:
        ctx: Bridge context after capability application
        analysis: Handler analysis

    Returns:
        ExtractionReport with validation results
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Check codec is set
    if ctx.wire.codec is None and not ctx.skip:
        errors.append("No codec set — use WrapAsDelegate or SetCodecByName")

    # Check for generator functions (may have issues)
    if analysis.is_generator:
        warnings.append("Handler is a generator — may need special handling")

    # Determine validity
    is_valid = len(errors) == 0

    return ExtractionReport(
        handler_name=analysis.name,
        is_valid=is_valid,
        unmapped_depends=(),  # Capabilities provide this
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def validate_analysis_only(
    analysis: HandlerAnalysis,
) -> ExtractionReport:
    """Validate handler analysis without full context.

    FRAMEWORK-AGNOSTIC — checks only generic handler properties.
    Useful for pre-validation before extraction.

    Args:
        analysis: Handler analysis

    Returns:
        ExtractionReport
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Check for generator functions
    if analysis.is_generator:
        warnings.append("Handler is a generator — may need special handling")

    is_valid = len(errors) == 0

    return ExtractionReport(
        handler_name=analysis.name,
        is_valid=is_valid,
        unmapped_depends=(),  # Capabilities provide this
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def validate_all(
    analyses: Sequence[HandlerAnalysis],
) -> ExtractionSummary:
    """Validate multiple handler analyses.

    FRAMEWORK-AGNOSTIC — checks only generic handler properties.

    Args:
        analyses: Sequence of handler analyses

    Returns:
        ExtractionSummary with all reports
    """
    reports: list[ExtractionReport] = []

    for analysis in analyses:
        report = validate_analysis_only(analysis)
        reports.append(report)

    valid_count = sum(1 for r in reports if r.is_valid)
    invalid_count = len(reports) - valid_count

    return ExtractionSummary(
        total=len(reports),
        valid=valid_count,
        invalid=invalid_count,
        reports=tuple(reports),
        all_unmapped=frozenset(),  # Capabilities provide this
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Formatting Utilities
# ═══════════════════════════════════════════════════════════════════════════════


def format_report(report: ExtractionReport) -> str:
    """Format extraction report as string.

    Args:
        report: Report to format

    Returns:
        Human-readable string
    """
    lines: list[str] = []
    status = "✅ VALID" if report.is_valid else "❌ INVALID"
    lines.append(f"{report.handler_name}: {status}")

    if report.unmapped_depends:
        lines.append(f"  Unmapped: {', '.join(report.unmapped_depends)}")

    for warning in report.warnings:
        lines.append(f"  ⚠️  {warning}")

    for error in report.errors:
        lines.append(f"  ❌ {error}")

    return "\n".join(lines)


def format_summary(summary: ExtractionSummary) -> str:
    """Format extraction summary as string.

    Args:
        summary: Summary to format

    Returns:
        Human-readable string
    """
    lines: list[str] = []
    lines.append(f"Extraction Summary: {summary.valid}/{summary.total} valid")

    if summary.all_unmapped:
        lines.append(f"All unmapped: {', '.join(sorted(summary.all_unmapped))}")

    lines.append("")

    for report in summary.reports:
        if not report.is_valid or report.has_warnings:
            lines.append(format_report(report))
            lines.append("")

    return "\n".join(lines)


__all__ = (
    # Data types
    "ExtractionReport",
    "ExtractionSummary",
    # Validation
    "validate_extraction",
    "validate_analysis_only",
    "validate_all",
    # Formatting
    "format_report",
    "format_summary",
)
