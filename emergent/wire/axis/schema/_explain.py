"""Schema explain — self-description of schema types.

Two layers:
  1. Dict-returning: schema_dict(), field_info_dict() — structured data for tools/analysis
  2. Human-readable: explain_schema(), explain_field() — formats from dicts

    from emergent.wire.axis.schema._explain import (
        schema_dict, explain_schema, DIALECT_BASES,
    )

    data = schema_dict(User)           # -> dict
    text = explain_schema(User)        # -> str (formats from schema_dict)

Open-world: unknown capability types get generic repr, never crash.
Dialect grouping: pass custom Mapping[str, type] for your own dialects.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

from emergent.wire.axis.schema._inspect import FieldInfo, inspect_type
from emergent.wire.axis.schema._universal import (
    SchemaAxisCapability,
    SchemaCapability,
    UniversalCapability,
    get_schema_meta,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _cap_repr(cap: SchemaAxisCapability) -> str:
    """Human-readable repr of a capability instance.

    Frozen dataclasses → show fields. Other → type name.
    """
    name = type(cap).__name__
    if dataclasses.is_dataclass(cap) and not isinstance(cap, type):
        fields = dataclasses.fields(cap)
        if not fields:
            return name
        parts: list[str] = []
        for f in fields:
            val = getattr(cap, f.name)
            if isinstance(val, type):
                parts.append(repr(val.__name__))
            else:
                parts.append(repr(val))
        return f"{name}({', '.join(parts)})"
    return name


def _cap_dict(cap: SchemaAxisCapability) -> dict[str, Any]:
    """Capability → structured dict."""
    d: dict[str, Any] = {"type": type(cap).__name__}
    if dataclasses.is_dataclass(cap) and not isinstance(cap, type):
        for f in dataclasses.fields(cap):
            val = getattr(cap, f.name)
            d[f.name] = val.__name__ if isinstance(val, type) else val
    return d


# ═══════════════════════════════════════════════════════════════════════════════
# Dialect Bases — default mapping of dialect names → base classes
# ═══════════════════════════════════════════════════════════════════════════════


def _build_dialect_bases() -> Mapping[str, type[SchemaAxisCapability]]:
    """Lazy-build dialect bases to avoid import errors for optional deps."""
    from emergent.wire.axis.schema.dialects.cli import CLICapability
    from emergent.wire.axis.schema.dialects.openapi import OpenAPICapability
    from emergent.wire.axis.schema.dialects.sql import SQLCapability
    from emergent.wire.axis.schema.dialects.tg import TelegramCapability
    from emergent.wire.axis.schema.dialects.compose import ComposeCapability
    from emergent.wire.axis.schema.dialects.pydantic import PydanticCapability
    from emergent.wire.axis.schema.dialects.api import APICapability
    from emergent.wire.axis.schema.dialects.query import QueryCapability

    return {
        "cli": CLICapability,
        "openapi": OpenAPICapability,
        "sql": SQLCapability,
        "tg": TelegramCapability,
        "compose": ComposeCapability,
        "pydantic": PydanticCapability,
        "api": APICapability,
        "query": QueryCapability,
    }


_DIALECT_BASES: Mapping[str, type[SchemaAxisCapability]] | None = None


def _get_dialect_bases() -> Mapping[str, type[SchemaAxisCapability]]:
    global _DIALECT_BASES
    if _DIALECT_BASES is None:
        _DIALECT_BASES = _build_dialect_bases()
    return _DIALECT_BASES


# ═══════════════════════════════════════════════════════════════════════════════
# Dict-returning layer — structured data
# ═══════════════════════════════════════════════════════════════════════════════


def field_info_dict(
    info: FieldInfo,
    dialects: Mapping[str, type[SchemaAxisCapability]] | None = None,
) -> dict[str, Any]:
    """One field's schema info as structured dict.

    Args:
        info: FieldInfo from inspect_type()
        dialects: Dialect name → base class mapping (default: built-in dialects)

    Returns:
        Dict with name, type, optional, default, universal caps, and per-dialect caps.
    """
    if dialects is None:
        dialects = _get_dialect_bases()

    d: dict[str, Any] = {
        "name": info.name,
        "type": info.base_type.__name__ if isinstance(info.base_type, type) else str(info.base_type),
        "optional": info.is_optional,
        "has_default": info.has_default,
    }

    # Universal capabilities
    universal = info.universal
    if universal:
        d["universal"] = [_cap_dict(c) for c in universal]

    # Per-dialect capabilities
    for dialect_name, base_cls in dialects.items():
        caps = info.dialect(base_cls)
        if caps:
            d[dialect_name] = [_cap_dict(c) for c in caps]

    return d


def schema_dict(
    cls: type,
    dialects: Mapping[str, type[SchemaAxisCapability]] | None = None,
) -> dict[str, Any]:
    """Full schema type as structured dict.

    Args:
        cls: Type to inspect (dataclass, Pydantic, TypedDict, NamedTuple)
        dialects: Dialect name → base class mapping (default: built-in dialects)

    Returns:
        Dict with class name, schema-level meta, and per-field info.

    Example:
        data = schema_dict(User)
        data["name"]        # "User"
        data["meta"]        # schema-level capabilities
        data["fields"]      # list of field dicts
    """
    if dialects is None:
        dialects = _get_dialect_bases()

    fields = inspect_type(cls)
    meta = get_schema_meta(cls)

    d: dict[str, Any] = {"name": cls.__name__}

    if meta:
        d["meta"] = [_cap_dict(c) for c in meta]

    d["fields"] = [field_info_dict(info, dialects) for info in fields.values()]

    return d


# ═══════════════════════════════════════════════════════════════════════════════
# Human-readable layer — formats from dicts
# ═══════════════════════════════════════════════════════════════════════════════


def explain_schema(
    cls: type,
    dialects: Mapping[str, type[SchemaAxisCapability]] | None = None,
) -> str:
    """Human-readable explanation of a schema type. Formats from schema_dict().

    Example:
        print(explain_schema(User))
        # === User ===
        #   [SchemaName("users"), Timestamps]
        #
        #   id (int):
        #     [Identity]
        #
        #   email (str):
        #     [Unique, MaxLen(255)]
        #     cli: Help("Email address")
    """
    data = schema_dict(cls, dialects)
    return _format_schema(data)


def explain_field(
    cls: type,
    field_name: str,
    dialects: Mapping[str, type[SchemaAxisCapability]] | None = None,
) -> str:
    """Human-readable explanation of a single field. Formats from field_info_dict().

    Example:
        print(explain_field(User, "email"))
        #   email (str):
        #     [Unique, MaxLen(255)]
        #     cli: Help("Email address")
    """
    if dialects is None:
        dialects = _get_dialect_bases()

    fields = inspect_type(cls)
    info = fields.get(field_name)
    if info is None:
        return f"(field '{field_name}' not found in {cls.__name__})"

    fd = field_info_dict(info, dialects)
    return _format_field(fd)


# ═══════════════════════════════════════════════════════════════════════════════
# Formatters (dict → str)
# ═══════════════════════════════════════════════════════════════════════════════


def _format_cap_short(cap_dict: dict[str, Any]) -> str:
    """Format a capability dict as short human-readable string."""
    name = cap_dict["type"]
    fields = {k: v for k, v in cap_dict.items() if k != "type"}
    if not fields:
        return name
    parts = ", ".join(repr(v) for v in fields.values())
    return f"{name}({parts})"


def _format_schema(data: dict[str, Any]) -> str:
    lines: list[str] = [f"=== {data['name']} ==="]

    # Schema-level meta
    meta = data.get("meta")
    if meta:
        cap_strs = [_format_cap_short(m) for m in meta]
        lines.append(f"  [{', '.join(cap_strs)}]")

    # Fields
    for fd in data.get("fields", []):
        lines.append("")
        lines.append(_format_field(fd))

    return "\n".join(lines)


def _format_field(fd: dict[str, Any]) -> str:
    lines: list[str] = []

    # Header: name (type) with optional/default markers
    type_str = fd["type"]
    suffix = ""
    if fd.get("has_default"):
        suffix = " = default"
    elif fd.get("optional"):
        suffix = " | None"
    lines.append(f"  {fd['name']} ({type_str}{suffix}):")

    # Universal capabilities
    universal = fd.get("universal")
    if universal:
        cap_strs = [_format_cap_short(c) for c in universal]
        lines.append(f"    [{', '.join(cap_strs)}]")

    # Per-dialect capabilities
    dialect_keys = [
        k for k in fd
        if k not in ("name", "type", "optional", "has_default", "universal")
    ]
    for dialect_name in dialect_keys:
        caps = fd[dialect_name]
        cap_strs = [_format_cap_short(c) for c in caps]
        lines.append(f"    {dialect_name}: {', '.join(cap_strs)}")

    return "\n".join(lines)


__all__ = (
    # Dict layer
    "schema_dict",
    "field_info_dict",
    # Human-readable layer
    "explain_schema",
    "explain_field",
)
