"""Verification as compilation target — compile-time contradiction detection."""

from ._issue import Issue, Severity, VerificationError
from ._length import LENGTH_VERIFY_PHASE, LengthVerifyCompilable, LengthVerifyCtx
from ._numeric import NUMERIC_VERIFY_PHASE, NumericVerifyCompilable, NumericVerifyCtx
from ._semantics import (
    SEMANTICS_VERIFY_PHASE,
    SemanticsVerifyCompilable,
    SemanticsVerifyCtx,
)
from ._verify import VERIFY_PHASES, VERIFY_SCHEMA, verify, verify_raising

__all__ = [
    # Core types
    "Issue",
    "Severity",
    "VerificationError",
    # Top-level API
    "verify",
    "verify_raising",
    # Pre-built
    "VERIFY_SCHEMA",
    "VERIFY_PHASES",
    # Phases
    "NUMERIC_VERIFY_PHASE",
    "LENGTH_VERIFY_PHASE",
    "SEMANTICS_VERIFY_PHASE",
    # Contexts (for custom check functions or subclassing)
    "NumericVerifyCtx",
    "LengthVerifyCtx",
    "SemanticsVerifyCtx",
    # Protocols (for implementing on custom capabilities)
    "NumericVerifyCompilable",
    "LengthVerifyCompilable",
    "SemanticsVerifyCompilable",
]
