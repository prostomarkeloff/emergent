"""Compiler core — axes context and common types.

Functional compiler infrastructure. Axes passed explicitly, no global state.

    from emergent.wire.compile import Axes, compile_handler

    axes = Axes.default()
    handler = compile_handler(handler, axes, my_wrapper)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol, TypeVar, TYPE_CHECKING

from emergent.wire.axis.schema import inspect_dataclass, FieldInfo

if TYPE_CHECKING:
    from nodnod import Scope
from emergent.wire.axis.schema import (
    MinLen,
    MaxLen,
    Min,
    Max,
    Pattern,
    OneOf,
    Identity,
    Unique,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Scope Setup Protocol
# ═══════════════════════════════════════════════════════════════════════════════


class ScopeSetup(Protocol):
    """Protocol for framework-specific scope setup.

    Each framework injects its own types into nodnod Scope.
    This abstracts the setup so adapters can share code.

    Example:
        class FastAPIScopeSetup:
            def __init__(self, request: Request, pydantic_types: set[type]):
                self.request = request
                self.pydantic_types = pydantic_types

            async def setup(self, scope: Scope) -> None:
                scope.inject(Request, self.request)
                # ... pydantic handling
    """

    async def setup(self, scope: Scope) -> None:
        """Inject framework-specific types into scope."""
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Axes Context
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Axes:
    """Multi-axis context for compilation.

    Passed explicitly to all compiler functions.
    No global state, easy to test.

    Attributes:
        schema: Function to inspect dataclass fields with capabilities.
    """

    schema: Callable[[type], dict[str, FieldInfo]]

    @classmethod
    def default(cls) -> Axes:
        """Create default axes with standard introspection."""
        return cls(schema=inspect_dataclass)


# ═══════════════════════════════════════════════════════════════════════════════
# Field Constraint Extraction
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FieldConstraints:
    """Extracted constraints from schema capabilities.

    Universal representation that any framework can use.
    """

    min_length: int | None = None
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    pattern: str | None = None
    choices: tuple[Any, ...] | None = None
    is_identity: bool = False
    is_unique: bool = False
    is_optional: bool = False


def extract_constraints(info: FieldInfo) -> FieldConstraints:
    """Extract universal constraints from FieldInfo.

    Pure function: FieldInfo → FieldConstraints
    """
    min_length: int | None = None
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    pattern: str | None = None
    choices: tuple[Any, ...] | None = None
    is_identity = False
    is_unique = False

    for cap in info.universal:
        match cap:
            case MinLen(value=v):
                min_length = v
            case MaxLen(value=v):
                max_length = v
            case Min(value=v):
                min_value = v
            case Max(value=v):
                max_value = v
            case Pattern(regex=r):
                pattern = r
            case OneOf(values=vs):
                choices = vs
            case Identity():
                is_identity = True
            case Unique():
                is_unique = True
            case _:
                pass  # Other capabilities ignored

    return FieldConstraints(
        min_length=min_length,
        max_length=max_length,
        min_value=min_value,
        max_value=max_value,
        pattern=pattern,
        choices=choices,
        is_identity=is_identity,
        is_unique=is_unique,
        is_optional=info.is_optional,
    )


def extract_all_constraints(
    cls: type, axes: Axes
) -> dict[str, tuple[type, FieldConstraints]]:
    """Extract constraints for all fields of a dataclass.

    Returns: {field_name: (base_type, constraints)}
    """
    fields = axes.schema(cls)
    return {
        name: (info.base_type, extract_constraints(info))
        for name, info in fields.items()
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Handler Wrapper Type
# ═══════════════════════════════════════════════════════════════════════════════

T = TypeVar("T")

# Wrapper transforms async handler into framework-specific artifact
Wrapper = Callable[[Callable[..., Any]], T]


# ═══════════════════════════════════════════════════════════════════════════════
# Unified Compile Loop
# ═══════════════════════════════════════════════════════════════════════════════


# Standard codec types to scan for
STANDARD_CODECS: tuple[type, ...] = ()  # Will be set after imports


def scan_all_codecs[T](
    app: Any,
    trigger_type: type[T],
    register: Callable[[T, Any], None],
) -> None:
    """Scan app for all standard codec types and register handlers.

    Unified compile loop that all adapters can use.

    Args:
        app: Wire Application
        trigger_type: Trigger type to scan for
        register: Function (trigger, handler) -> None

    Example:
        def register(trigger: HTTPRouteTrigger, handler: Handler[Any]) -> None:
            register_handler(fapi, trigger, handler, axes)

        scan_all_codecs(app, HTTPRouteTrigger, register)
    """
    from emergent.wire.axis.surface._scan import scan
    from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec
    from emergent.wire.axis.surface.codecs.stateful import StatefulCodec
    from emergent.wire.axis.surface.codecs.immediate import (
        ImmediateCodec,
        ImmediateFactoryCodec,
    )

    codec_types = (
        RequestResponseCodec,
        StatefulCodec,
        ImmediateCodec,
        ImmediateFactoryCodec,
    )

    for codec_type in codec_types:
        for trigger, handler in scan(app, trigger_type, codec_type):
            register(trigger, handler)


__all__ = (
    "ScopeSetup",
    "Axes",
    "FieldConstraints",
    "extract_constraints",
    "extract_all_constraints",
    "Wrapper",
    "scan_all_codecs",
)
