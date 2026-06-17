"""Trigger generators — map (entity, Op) -> Trigger.

Transport-specific, pattern-agnostic. Implementations: HTTPTriggers, CLITriggers.

    from emergent.wire.derive._trigger import HTTPTriggers, CLITriggers, TriggerGen
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable, TYPE_CHECKING

from emergent.wire.axis.surface import Trigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger, Method

if TYPE_CHECKING:
    from emergent.wire.derive._opspec import Op


@runtime_checkable
class TriggerGen(Protocol):
    """Map (entity, Op) -> Trigger. Transport-specific, pattern-agnostic."""

    def __call__(self, entity: type, op: Op) -> Trigger | None: ...


# Route spec: (method, suffix)
# True -> "/{id}" (auto from Identity fields), False -> "" (no suffix), str -> literal
type RouteSpec = tuple[Method, bool | str]
type RouteMap = dict[str, RouteSpec]

DEFAULT_REST_ROUTES: RouteMap = {
    "List": ("GET", False),
    "Get": ("GET", True),
    "Create": ("POST", False),
    "Update": ("PUT", True),
    "Patch": ("PATCH", True),
    "Delete": ("DELETE", True),
    "Upsert": ("PUT", False),
}


@dataclass(frozen=True, slots=True)
class HTTPTriggers:
    """Generic HTTP trigger gen with REST defaults.

    Well-known ops get standard REST routes. Identity path params
    are built from entity's Identity fields (supports composite keys).

        HTTPTriggers("/api/users")
        HTTPTriggers("/api/users", routes={**DEFAULT_REST_ROUTES, "Search": ("POST", False)})
    """

    base_path: str
    routes: RouteMap = field(default_factory=lambda: dict(DEFAULT_REST_ROUTES))

    def __call__(self, entity: type, op: Op) -> Trigger:
        path = self.base_path.rstrip("/")
        if op.name in self.routes:
            method, spec = self.routes[op.name]
            if spec is True:
                suffix = self._id_suffix(entity)
            elif spec is False:
                suffix = ""
            else:
                suffix = spec
            return HTTPRouteTrigger(method=method, path=path + suffix)
        return HTTPRouteTrigger(method="POST", path=f"{path}/{op.name.lower()}")

    def _id_suffix(self, entity: type) -> str:
        from emergent.wire.axis.schema import fields_with_capability
        from emergent.wire.axis.schema._universal import Identity

        id_triples = fields_with_capability(entity, Identity)
        if not id_triples:
            return "/{id}"
        return "/" + "/".join(f"{{{name}}}" for name, _, _ in id_triples)


@dataclass(frozen=True, slots=True)
class NestedHTTPTriggers:
    """Nested HTTP trigger gen: /parent_path/{scope}/child_segment/...

        NestedHTTPTriggers("/users", ("user_id",), "posts")
        # List: GET /users/{user_id}/posts
        # Get:  GET /users/{user_id}/posts/{id}
    """

    parent_path: str
    scope_fields: tuple[str, ...]
    child_segment: str
    routes: RouteMap = field(default_factory=lambda: dict(DEFAULT_REST_ROUTES))

    def __call__(self, entity: type, op: Op) -> Trigger:
        prefix = self.parent_path.rstrip("/")
        for name in self.scope_fields:
            prefix += f"/{{{name}}}"
        child_path = f"{prefix}/{self.child_segment}"

        if op.name in self.routes:
            method, spec = self.routes[op.name]
            if spec is True:
                suffix = self._child_id_suffix(entity)
            elif spec is False:
                suffix = ""
            else:
                suffix = spec
            return HTTPRouteTrigger(method=method, path=child_path + suffix)
        return HTTPRouteTrigger(method="POST", path=f"{child_path}/{op.name.lower()}")

    def _child_id_suffix(self, entity: type) -> str:
        from emergent.wire.axis.schema import fields_with_capability
        from emergent.wire.axis.schema._universal import Identity

        scope_set = set(self.scope_fields)
        id_triples = fields_with_capability(entity, Identity)
        child_ids = [(n, i, c) for n, i, c in id_triples if n not in scope_set]
        if not child_ids:
            return ""
        return "/" + "/".join(f"{{{name}}}" for name, _, _ in child_ids)


@dataclass(frozen=True, slots=True)
class CLITriggers:
    """Generic CLI trigger gen. Op name -> prefix-name_lower command."""

    prefix: str

    def __call__(self, entity: type, op: Op) -> Trigger:
        return CLITrigger(command=f"{self.prefix}-{op.name.lower()}")


# ═══════════════════════════════════════════════════════════════════════════════
# Compositional Trigger Wrappers
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FilteredTriggerGen:
    """Conditionally skip ops by name.

        FilteredTriggerGen(HTTPTriggers("/api"), only_ops=frozenset({"List", "Get"}))
        FilteredTriggerGen(HTTPTriggers("/api"), exclude_ops=frozenset({"Delete"}))
    """

    inner: TriggerGen
    only_ops: frozenset[str] | None = None
    exclude_ops: frozenset[str] | None = None

    def __call__(self, entity: type, op: Op) -> Trigger | None:
        if self.only_ops is not None and op.name not in self.only_ops:
            return None
        if self.exclude_ops is not None and op.name in self.exclude_ops:
            return None
        return self.inner(entity, op)


@dataclass(frozen=True, slots=True)
class PrefixedTriggerGen:
    """Prefix HTTP paths on generated triggers.

        PrefixedTriggerGen(HTTPTriggers("/users"), prefix="/v2")
        # List: GET /v2/users
    """

    inner: TriggerGen
    prefix: str

    def __call__(self, entity: type, op: Op) -> Trigger | None:
        trigger = self.inner(entity, op)
        if trigger is None:
            return None
        if isinstance(trigger, HTTPRouteTrigger):
            return HTTPRouteTrigger(
                method=trigger.method, path=self.prefix + trigger.path
            )
        return trigger


@dataclass(frozen=True, slots=True)
class MultiTriggerGen:
    """Multiple triggers per op — generates one OpSpec per trigger.

        MultiTriggerGen(HTTPTriggers("/api/users"), CLITriggers("user"))
    """

    generators: tuple[TriggerGen, ...]

    def __call__(self, entity: type, op: Op) -> tuple[Trigger, ...]:
        return tuple(
            t for g in self.generators
            if (t := g(entity, op)) is not None
        )


__all__ = (
    "TriggerGen",
    "RouteSpec",
    "DEFAULT_REST_ROUTES",
    "HTTPTriggers",
    "NestedHTTPTriggers",
    "CLITriggers",
    "FilteredTriggerGen",
    "PrefixedTriggerGen",
    "MultiTriggerGen",
)
