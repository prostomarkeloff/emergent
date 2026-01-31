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

from dataclasses import dataclass
from typing import Any, TypeVar


P = TypeVar("P")  # Profile type


# ─── Profile-Scoped Annotations ──────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ProfileConfig:
    """Configuration for a specific API profile.

    Created via api.profile(ProfileType).method() chain.
    """
    profile: type
    path_param: bool = False
    query_param: str | None = None  # param name if query param
    filterable: bool = False
    sortable: bool = False
    selectable: bool = False
    searchable: bool = False
    operators: tuple[str, ...] = ()  # allowed filter operators


class ProfileBuilder:
    """Builder for profile-scoped annotations.

    Usage:
        api.profile(InternalAPI).path_param().filterable()
    """

    __slots__ = ("profile_type", "_config")

    def __init__(self, profile_type: type) -> None:
        self.profile_type = profile_type
        self._config: dict[str, Any] = {"profile": profile_type}

    def path_param(self) -> ProfileConfig:
        """Mark as path parameter: /resource/{id}"""
        self._config["path_param"] = True
        return ProfileConfig(**self._config)

    def query_param(self, name: str | None = None) -> ProfileConfig:
        """Mark as query parameter: ?name=value

        If name is None, uses field name.
        """
        self._config["query_param"] = name or ""  # empty string = use field name
        return ProfileConfig(**self._config)

    def filterable(self, operators: tuple[str, ...] = ()) -> ProfileBuilder:
        """Mark as filterable field.

        Operators: "eq", "ne", "gt", "gte", "lt", "lte", "in", "contains"
        Empty = only equality.
        """
        self._config["filterable"] = True
        if operators:
            self._config["operators"] = operators
        return self

    def sortable(self) -> ProfileBuilder:
        """Mark as sortable field."""
        self._config["sortable"] = True
        return self

    def selectable(self) -> ProfileBuilder:
        """Mark as selectable (sparse fieldsets)."""
        self._config["selectable"] = True
        return self

    def searchable(self) -> ProfileBuilder:
        """Mark as participating in full-text search."""
        self._config["searchable"] = True
        return self

    def build(self) -> ProfileConfig:
        """Finalize configuration."""
        return ProfileConfig(**self._config)

    # Allow using builder directly as annotation (auto-builds)
    def __hash__(self) -> int:
        return hash(self.build())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ProfileBuilder):
            return self.build() == other.build()
        return False


def profile(profile_type: type[P]) -> ProfileBuilder:
    """Start building annotations for a specific API profile.

    Usage:
        api.profile(InternalAPI).path_param()
        api.profile(PartnerAPI).query_param("user_id").filterable()
    """
    return ProfileBuilder(profile_type)


# ─── Profile-Agnostic Annotations (shortcuts for single-API cases) ───────────


@dataclass(frozen=True, slots=True)
class PathParam:
    """Field used in URL path: /users/{id}

    Profile-agnostic version. Use api.profile(X).path_param() for multi-API.
    """
    pass


@dataclass(frozen=True, slots=True)
class QueryParam:
    """Field used as query parameter.

    Profile-agnostic version.
    """
    name: str | None = None  # None = use field name


@dataclass(frozen=True, slots=True)
class Filterable:
    """Field can be filtered on.

    Profile-agnostic version.
    """
    operators: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Sortable:
    """Field can be sorted on.

    Profile-agnostic version.
    """
    pass


@dataclass(frozen=True, slots=True)
class Selectable:
    """Field can be selected (sparse fieldsets).

    Profile-agnostic version.
    """
    pass


@dataclass(frozen=True, slots=True)
class Searchable:
    """Field participates in full-text search.

    Profile-agnostic version.
    """
    pass


# ─── Response Shape ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ResponseData:
    """Path to data array in response JSON.

    Usage at class level (not field):
        ResponseData("data.users")  # {"data": {"users": [...]}}
    """
    path: str
    profile: type | None = None  # None = all profiles


@dataclass(frozen=True, slots=True)
class ResponseTotal:
    """Path to total count in response JSON."""
    path: str
    profile: type | None = None


@dataclass(frozen=True, slots=True)
class ResponseCursor:
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
        if isinstance(ann, ProfileBuilder) and ann.profile_type is target_profile:
            return ann.build()
    return None


def get_any_config(annotations: tuple[Any, ...]) -> ProfileConfig | None:
    """Extract first ProfileConfig from annotations (for single-API case)."""
    for ann in annotations:
        if isinstance(ann, ProfileConfig):
            return ann
        if isinstance(ann, ProfileBuilder):
            return ann.build()
    return None


__all__ = (
    # Profile-scoped
    "ProfileConfig",
    "ProfileBuilder",
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
