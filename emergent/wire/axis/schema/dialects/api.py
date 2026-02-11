"""API dialect — schema annotations for REST-ish APIs.

Supports multiple API profiles for different backends:

    class InternalAPI: ...
    class PartnerAPI: ...

    @dataclass
    class User:
        id: Annotated[str, Identity,
            api.profile(InternalAPI).path_param(),       # /users/{id}
            api.profile(PartnerAPI).query_param("uid"),  # ?uid=...
        ]
        name: Annotated[str,
            api.profile(InternalAPI).filterable().sortable(),
            api.profile(PartnerAPI).filterable(),
        ]

Provider reads annotations for its profile, ignores others.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, TypeVar

from emergent.wire.axis.schema._universal import SchemaAxisCapability


P = TypeVar("P")  # Profile type


class APICapability(SchemaAxisCapability):
    """Base for API-specific capabilities."""

    pass


# ─── Profile-Scoped Annotations ──────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ProfileConfig(APICapability):
    """Configuration for a specific API profile.

    Immutable builder — chain methods return new ProfileConfig via replace().

    Usage:
        api.profile(InternalAPI).path_param()
        api.profile(InternalAPI).filterable().sortable()
    """
    profile: type
    is_path_param: bool = False
    query_param_name: str | None = None  # param name if query param
    filterable: bool = False
    sortable: bool = False
    selectable: bool = False
    searchable: bool = False
    operators: tuple[str, ...] = ()  # allowed filter operators

    def path_param(self) -> ProfileConfig:
        """Mark as path parameter: /resource/{id}"""
        return replace(self, is_path_param=True)

    def query_param(self, name: str | None = None) -> ProfileConfig:
        """Mark as query parameter: ?name=value

        If name is None, uses field name.
        """
        return replace(self, query_param_name=name or "")

    def with_filterable(self, operators: tuple[str, ...] = ()) -> ProfileConfig:
        """Mark as filterable field.

        Operators: "eq", "ne", "gt", "gte", "lt", "lte", "in", "contains"
        Empty = only equality.
        """
        return replace(
            self, filterable=True,
            operators=operators if operators else self.operators,
        )

    def with_sortable(self) -> ProfileConfig:
        """Mark as sortable field."""
        return replace(self, sortable=True)

    def with_selectable(self) -> ProfileConfig:
        """Mark as selectable (sparse fieldsets)."""
        return replace(self, selectable=True)

    def with_searchable(self) -> ProfileConfig:
        """Mark as participating in full-text search."""
        return replace(self, searchable=True)

    def build(self) -> ProfileConfig:
        """No-op for backward compatibility."""
        return self


def profile(profile_type: type[P]) -> ProfileConfig:
    """Start building annotations for a specific API profile.

    Returns an immutable ProfileConfig — chain methods return new instances.

    Usage:
        api.profile(InternalAPI).path_param()
        api.profile(PartnerAPI).query_param("user_id").with_filterable()
    """
    return ProfileConfig(profile=profile_type)


# ─── Profile-Agnostic Annotations (shortcuts for single-API cases) ───────────


@dataclass(frozen=True, slots=True)
class PathParam(APICapability):
    """Field used in URL path: /users/{id}

    Profile-agnostic version. Use api.profile(X).path_param() for multi-API.
    """
    pass


@dataclass(frozen=True, slots=True)
class QueryParam(APICapability):
    """Field used as query parameter.

    Profile-agnostic version.
    """
    name: str | None = None  # None = use field name


@dataclass(frozen=True, slots=True)
class Filterable(APICapability):
    """Field can be filtered on.

    Profile-agnostic version.
    """
    operators: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Sortable(APICapability):
    """Field can be sorted on.

    Profile-agnostic version.
    """
    pass


@dataclass(frozen=True, slots=True)
class Selectable(APICapability):
    """Field can be selected (sparse fieldsets).

    Profile-agnostic version.
    """
    pass


@dataclass(frozen=True, slots=True)
class Searchable(APICapability):
    """Field participates in full-text search.

    Profile-agnostic version.
    """
    pass


# ─── Response Shape ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ResponseData(APICapability):
    """Path to data array in response JSON.

    Usage at class level (not field):
        ResponseData("data.users")  # {"data": {"users": [...]}}
    """
    path: str
    profile: type | None = None  # None = all profiles


@dataclass(frozen=True, slots=True)
class ResponseTotal(APICapability):
    """Path to total count in response JSON."""
    path: str
    profile: type | None = None


@dataclass(frozen=True, slots=True)
class ResponseCursor(APICapability):
    """Path to pagination cursor in response JSON."""
    path: str
    profile: type | None = None


# ─── Utility ─────────────────────────────────────────────────────────────────


def get_profile_config(
    annotations: tuple[Any, ...],
    target_profile: type,
) -> ProfileConfig | None:
    """Extract ProfileConfig for specific profile from annotations."""
    for ann in annotations:
        if isinstance(ann, ProfileConfig) and ann.profile is target_profile:
            return ann
    return None


def get_any_config(annotations: tuple[Any, ...]) -> ProfileConfig | None:
    """Extract first ProfileConfig from annotations (for single-API case)."""
    for ann in annotations:
        if isinstance(ann, ProfileConfig):
            return ann
    return None


__all__ = (
    # Base
    "APICapability",
    # Profile-scoped
    "ProfileConfig",
    "profile",
    # Profile-agnostic
    "PathParam",
    "QueryParam",
    "Filterable",
    "Sortable",
    "Selectable",
    "Searchable",
    # Response shape
    "ResponseData",
    "ResponseTotal",
    "ResponseCursor",
    # Utility
    "get_profile_config",
    "get_any_config",
)
