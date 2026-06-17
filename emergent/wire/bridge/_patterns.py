"""Bridge capability patterns — reusable compositions.

Like schema._patterns for common capability tuples.

    from emergent.wire.bridge import patterns

    wire_app = build_application(
        app,
        capabilities=patterns.SKIP_DEPRECATED,
    )
"""

from __future__ import annotations

from typing import Any

from emergent.wire.bridge._capabilities import (
    BridgeCapability,
    SkipByName,
    SkipDeprecated,
    WrapAsDelegate,
    WrapAsync,
)


type DependsMap = dict[Any, Any]


# ═══════════════════════════════════════════════════════════════════════════════
# Skip Patterns
# ═══════════════════════════════════════════════════════════════════════════════


# Skip deprecated handlers
SKIP_DEPRECATED: tuple[BridgeCapability, ...] = (SkipDeprecated(),)

# Skip internal/private handlers (names starting with _)
SKIP_PRIVATE: tuple[BridgeCapability, ...] = (SkipByName(pattern=r"^_.*"),)

# Skip deprecated and private
SKIP_INTERNAL: tuple[BridgeCapability, ...] = (
    SkipDeprecated(),
    SkipByName(pattern=r"^_.*"),
)


# ═══════════════════════════════════════════════════════════════════════════════
# Wrapper Patterns
# ═══════════════════════════════════════════════════════════════════════════════


# Ensure all handlers are async
ASYNC_ALL: tuple[BridgeCapability, ...] = (WrapAsync(),)

# Wrap all handlers as delegate (THIN — preserve signature)
DELEGATE_ALL: tuple[BridgeCapability, ...] = (WrapAsDelegate(),)


# ═══════════════════════════════════════════════════════════════════════════════
# Combined Patterns
# ═══════════════════════════════════════════════════════════════════════════════


# Clean extraction — skip deprecated/private, wrap as delegate
CLEAN: tuple[BridgeCapability, ...] = (
    SkipDeprecated(),
    SkipByName(pattern=r"^_.*"),
    WrapAsDelegate(),
)


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI Patterns (for convenience import)
# ═══════════════════════════════════════════════════════════════════════════════


def fastapi_default() -> tuple[BridgeCapability, ...]:
    """FastAPI default capabilities — type inference + delegate wrapping."""
    from emergent.wire.bridge.bridgers.fastapi import InferFromFastAPI

    return (
        InferFromFastAPI(),
        WrapAsDelegate(),
    )


def fastapi_with_depends(
    depends_map: DependsMap,
) -> tuple[BridgeCapability, ...]:
    """FastAPI with Depends() mapping."""
    from emergent.wire.bridge.bridgers.fastapi import InferFromFastAPI, MapDepends

    return (
        InferFromFastAPI(),
        MapDepends(depends_map=depends_map),
        WrapAsDelegate(),
    )


__all__ = (
    # Skip patterns
    "SKIP_DEPRECATED",
    "SKIP_PRIVATE",
    "SKIP_INTERNAL",
    # Wrapper patterns
    "ASYNC_ALL",
    "DELEGATE_ALL",
    # Combined
    "CLEAN",
    # FastAPI builders
    "fastapi_default",
    "fastapi_with_depends",
)
