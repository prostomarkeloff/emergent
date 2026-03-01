"""Generic dialect infrastructure — transport-agnostic patterns.

Pattern = tuple[Op, ...] × TriggerGen × ProviderNode

Op = transport-agnostic operation descriptor (WHAT)
TriggerGen = transport-specific trigger factory (WHERE)
Dialect = generic Pattern from Op descriptors

Any pattern (CRUD, readonly, search, etc.) is a Dialect.
CRUD is just one set of Ops. Anyone can define their own.

    from derivelib._dialect import Op, dialect, HTTPTriggers

    LIST = Op("List", no_fields(), list_response(), FetchMany())
    GET = Op("Get", id_only(), entity_response(), FetchOneById())

    def http_readonly(path, provider_node):
        return dialect(LIST, GET, triggers=HTTPTriggers(path), provider_node=provider_node)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Protocol, runtime_checkable

from emergent.wire.axis.query import MutatingRelationalProvider
from emergent.wire.axis.schema.dialects.compose import Node as ComposeNode
from emergent.wire.axis.surface import Exposure, Trigger
from emergent.wire.axis.surface.capabilities import SurfaceCapability
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger, Method

from derivelib._derivation import Derivation, DerivationT
from derivelib._effects import DerivationEffect, has_effect
from derivelib._project import FieldProjection, ResponseSpec
from derivelib.axes.query import base_query, bind_provider
from derivelib.axes.schema import inspect_entity, require_identity
from derivelib.axes.surface import DeriveOp, HandlerTemplate


# ═══════════════════════════════════════════════════════════════════════════════
# Op — transport-agnostic operation descriptor
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Op:
    """Transport-agnostic operation descriptor.

    Describes WHAT an operation does (business logic),
    not WHERE it's exposed (transport).

    Effects classify the operation semantically. Transforms dispatch
    on effects via isinstance — open-world, anyone can add custom effects.

        from derivelib._effects import Read, Mutation, Creates

        LIST = Op("List", no_fields(), list_response(), FetchMany(), effects=(Read(),))
        CREATE = Op("Create", non_id(), entity_response(), InsertNew(), effects=(Creates(),))
    """

    name: str
    input_proj: FieldProjection
    output: ResponseSpec
    handler_template: HandlerTemplate
    capabilities: tuple[SurfaceCapability, ...] = ()
    extra_op_fields: tuple[tuple[str, type], ...] = ()
    extra_request_fields: tuple[tuple[str, type], ...] = ()
    effects: tuple[DerivationEffect, ...] = ()
    codec_factory: Callable[[type, type], Exposure] | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# TriggerGen — generic trigger factory
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class TriggerGen(Protocol):
    """Map (entity, Op) → Trigger. Transport-specific, pattern-agnostic.

    Implementations: HTTPTriggers, CLITriggers, or any custom trigger gen.
    """

    def __call__(self, entity: type, op: Op) -> Trigger | None: ...


# ═══════════════════════════════════════════════════════════════════════════════
# Generic Trigger Generators
# ═══════════════════════════════════════════════════════════════════════════════

# Route spec: (method, suffix)
# suffix is a string appended to base_path. Use {id} for identity fields.
#   True  → shorthand for "/{id}" (auto-built from entity Identity fields)
#   False → shorthand for "" (no suffix)
#   str   → literal suffix, e.g. "/{id}/submit"
type RouteSpec = tuple[Method, bool | str]

DEFAULT_REST_ROUTES: dict[str, RouteSpec] = {
    "List": ("GET", False),
    "Get": ("GET", True),
    "Create": ("POST", False),
    "Update": ("PUT", True),
    "Patch": ("PATCH", True),
    "Delete": ("DELETE", True),
}


@dataclass(frozen=True, slots=True)
class HTTPTriggers:
    """Generic HTTP trigger gen with REST defaults.

    Well-known ops (List, Get, Create, Update, Delete) get standard
    REST routes. Identity path params are built from entity's Identity
    fields (supports composite keys).

    Pass custom routes to override defaults or add new op mappings::

        HTTPTriggers("/api/users", routes={
            **DEFAULT_REST_ROUTES,
            "Search": ("POST", False),
        })

    String suffixes for full path control::

        HTTPTriggers("/api/orders", routes={
            **DEFAULT_REST_ROUTES,
            "Submit": ("POST", "/{id}/submit"),
            "Cancel": ("POST", "/{id}/cancel"),
            "Export": ("GET", "/export"),
        })
    """

    base_path: str
    routes: dict[str, RouteSpec] = field(default_factory=lambda: dict(DEFAULT_REST_ROUTES))

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
        # Unknown ops → POST /base/{name_lower}
        return HTTPRouteTrigger(method="POST", path=f"{path}/{op.name.lower()}")

    def _id_suffix(self, entity: type) -> str:
        """Build path suffix from entity's identity field names."""
        from emergent.wire.axis.schema import fields_with_capability
        from emergent.wire.axis.schema._universal import Identity

        id_triples = fields_with_capability(entity, Identity)
        if not id_triples:
            return "/{id}"
        return "/" + "/".join(f"{{{name}}}" for name, _, _ in id_triples)


@dataclass(frozen=True, slots=True)
class NestedHTTPTriggers:
    """Nested HTTP trigger gen: /parent_path/{scope}/child_segment/...

    Builds nested resource paths. Child identity suffix excludes scope fields
    (handles case where FK is also Identity in composite keys).

        NestedHTTPTriggers("/users", ("user_id",), "posts")
        # List:   GET    /users/{user_id}/posts
        # Get:    GET    /users/{user_id}/posts/{id}
        # Create: POST   /users/{user_id}/posts
        # Update: PUT    /users/{user_id}/posts/{id}
        # Delete: DELETE /users/{user_id}/posts/{id}
    """

    parent_path: str
    scope_fields: tuple[str, ...]
    child_segment: str
    routes: dict[str, RouteSpec] = field(default_factory=lambda: dict(DEFAULT_REST_ROUTES))

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
        """Child identity path params, excluding scope fields."""
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
    """Generic CLI trigger gen. Op name → prefix-name_lower command."""

    prefix: str

    def __call__(self, entity: type, op: Op) -> Trigger:
        return CLITrigger(command=f"{self.prefix}-{op.name.lower()}")


# ═══════════════════════════════════════════════════════════════════════════════
# Provider Fields
# ═══════════════════════════════════════════════════════════════════════════════


def _provider_fields(
    provider_node: type,
) -> tuple[tuple[str, type], tuple[str, type]]:
    """Create provider field pair: (op_field, request_field).

    Op field is plain type. Request field has compose.Node for runtime resolution.
    MutatingRelationalProvider is used unparameterized (concrete type resolved
    at runtime by compose.Node).
    """
    import typing

    op_field: tuple[str, type] = ("provider", MutatingRelationalProvider)
    # Build Annotated form dynamically to avoid pyright evaluating
    # the unparameterized generic.
    annotated_getitem = getattr(typing, "Annotated").__getitem__
    request_field: tuple[str, type] = (
        "provider",
        annotated_getitem((MutatingRelationalProvider, ComposeNode(provider_node))),
    )
    return op_field, request_field


# ═══════════════════════════════════════════════════════════════════════════════
# Pattern Protocol
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class Pattern(Protocol):
    """Pattern protocol — compilable derivation source.

    Dialect, ChainedPattern, and any custom pattern implement this.
    """

    def compile(self, entity: type) -> Derivation: ...


# ═══════════════════════════════════════════════════════════════════════════════
# Dialect — generic Pattern
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Dialect:
    """Generic pattern: ops × triggers → derivation.

    Pure data structure. compile() assembles preamble + DeriveOp steps.
    Use dialect() constructor for standard setup (schema + query + provider).

        # Direct construction (full control):
        Dialect(ops=my_ops, triggers=HTTPTriggers("/api"), preamble=(...,))

        # Smart constructor (standard setup):
        dialect(LIST, GET, triggers=HTTPTriggers("/api"), provider_node=X)
    """

    ops: tuple[Op, ...]
    triggers: TriggerGen
    capabilities: tuple[SurfaceCapability, ...] = ()
    preamble: Derivation = ()
    shared_op_fields: tuple[tuple[str, type], ...] = ()
    shared_request_fields: tuple[tuple[str, type], ...] = ()
    adapt: bool = True

    def chain(self, *transforms: DerivationT) -> ChainedPattern:
        """Chain DerivationT transforms after compile.

        Returns a new Pattern that compiles this dialect then applies transforms.

            http_crud("/api/users", P).chain(readonly(), paginated(20))
        """
        return ChainedPattern(self, transforms)

    def compile(self, entity: type) -> Derivation:
        from derivelib._derivation import Step

        steps: list[Step] = list(self.preamble)
        ops = self.ops
        if self.adapt:
            from derivelib.adapt import adapt_base_query, adapt_ops
            ops = adapt_ops(ops, entity)
            steps.append(adapt_base_query())
        for op in ops:
            trigger = self.triggers(entity, op)
            if trigger is None:
                continue
            derive_op = DeriveOp(
                name=op.name,
                input_proj=op.input_proj,
                output=op.output,
                handler_template=op.handler_template,
                trigger=trigger,
                capabilities=(*self.capabilities, *op.capabilities),
                extra_op_fields=(*op.extra_op_fields, *self.shared_op_fields),
                extra_request_fields=(
                    *op.extra_request_fields,
                    *self.shared_request_fields,
                ),
                codec_factory=op.codec_factory,
                effects=op.effects,
                source=op,
            )
            steps.append(derive_op)
        return tuple(steps)


@dataclass(frozen=True, slots=True)
class ChainedPattern:
    """Pattern with post-compile transforms. Satisfies Pattern protocol.

    Created by Dialect.chain() or ChainedPattern.chain().
    Applies DerivationT transforms to the compiled derivation steps.

        pattern = http_crud("/users", P).chain(readonly())
        steps = pattern.compile(User)  # compile → then transform
    """

    inner: Pattern
    transforms: tuple[DerivationT, ...]

    def compile(self, entity: type) -> Derivation:
        steps = self.inner.compile(entity)
        for t in self.transforms:
            steps = t(steps)
        return steps

    def chain(self, *transforms: DerivationT) -> ChainedPattern:
        """Chain additional transforms."""
        return ChainedPattern(self, transforms)


def dialect(
    *ops: Op,
    triggers: TriggerGen,
    provider_node: type,
    capabilities: tuple[SurfaceCapability, ...] = (),
) -> Dialect:
    """Build a Dialect with standard setup (schema + query + provider).

        my_dialect = dialect(
            LIST, GET, COUNT,
            triggers=HTTPTriggers("/api/users"),
            provider_node=UserProvider,
        )
    """
    preamble = (
        inspect_entity(),
        require_identity(),
        bind_provider(provider_node),
        base_query(),
    )
    prov_op, prov_req = _provider_fields(provider_node)
    return Dialect(
        ops=ops,
        triggers=triggers,
        capabilities=capabilities,
        preamble=preamble,
        shared_op_fields=(prov_op,),
        shared_request_fields=(prov_req,),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Op Transforms
# ═══════════════════════════════════════════════════════════════════════════════


def with_caps(
    ops: tuple[Op, ...],
    *caps: SurfaceCapability,
    effect: type[DerivationEffect] | None = None,
) -> tuple[Op, ...]:
    """Add capabilities to ops, optionally filtered by effect type.

        # Add to all ops:
        with_caps(ALL_CRUD_OPS, CORSCap())

        # Add only to mutations:
        with_caps(ALL_CRUD_OPS, AuthCap(), effect=Mutation)
    """
    if effect is None:
        return tuple(
            replace(op, capabilities=(*op.capabilities, *caps)) for op in ops
        )
    return tuple(
        replace(op, capabilities=(*op.capabilities, *caps))
        if has_effect(op.effects, effect)
        else op
        for op in ops
    )


def select_ops(ops: tuple[Op, ...], *targets: Op) -> tuple[Op, ...]:
    """Select ops by identity.

        from derivelib.patterns.crud import LIST, GET, ALL_CRUD_OPS
        read_only = select_ops(ALL_CRUD_OPS, LIST, GET)
    """
    return tuple(op for op in ops if any(op is t for t in targets))


def exclude_ops(ops: tuple[Op, ...], *targets: Op) -> tuple[Op, ...]:
    """Exclude ops by identity.

        from derivelib.patterns.crud import DELETE, ALL_CRUD_OPS
        no_delete = exclude_ops(ALL_CRUD_OPS, DELETE)
    """
    return tuple(op for op in ops if not any(op is t for t in targets))


def by_effect(ops: tuple[Op, ...], *effect_types: type[DerivationEffect]) -> tuple[Op, ...]:
    """Filter ops by effect types.

        from derivelib._effects import Mutation, Read

        mutations = by_effect(ALL_CRUD_OPS, Mutation)
        reads = by_effect(ALL_CRUD_OPS, Read)
    """
    return tuple(
        op for op in ops
        if any(has_effect(op.effects, et) for et in effect_types)
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = (
    # Core
    "Op",
    "TriggerGen",
    "Dialect",
    "ChainedPattern",
    # Trigger generators
    "RouteSpec",
    "DEFAULT_REST_ROUTES",
    "HTTPTriggers",
    "NestedHTTPTriggers",
    "CLITriggers",
    # Smart constructor
    "dialect",
    # Provider fields
    "_provider_fields",
    # Op transforms
    "with_caps",
    "select_ops",
    "exclude_ops",
    "by_effect",
)
