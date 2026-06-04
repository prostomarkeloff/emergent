"""Auth capabilities — SchemaCapabilities for auth gating.

All auth transforms expressed as DeriveModifiable capabilities.

    @schema_meta(
        http_crud("/api/posts", Posts),
        Authenticated(BearerExtract(), TokenValidate(AuthUser, lookup)),
        RoleRequired(AuthUser, "admin", role_getter, effect=Mutation),
        OwnerScoped(AuthUser, owner_field="author_id", identity_attr="name"),
    )
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from nodnod import Scope

from emergent.wire.axis.schema._universal import SchemaCapability
from emergent.wire.axis.surface.capabilities import EnricherNext, ScopeEnricher, SurfaceCapability

from .errors import AuthorizationFailed
from .openapi import AuthOpenAPI
from .validate import TokenValidate

if TYPE_CHECKING:
    from emergent.wire.derive._ctx import DeriveCtx
    from emergent.wire.derive._opspec import OpSpec
    from emergent.wire.derive._codegen import AnnotationValue

type RoleMap = dict[str, str]
type RequestFieldMap = dict[str, AnnotationValue]


# ═══════════════════════════════════════════════════════════════════════════════
# Authenticated — auth gating on specs by effect
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Authenticated(SchemaCapability):
    """Add auth enricher chain to ops matching a given effect.

    Enricher chain: extractors -> validate -> handler.

        Authenticated(BearerExtract(), TokenValidate(AuthUser, lookup))
        Authenticated(BearerExtract(), validate, effect=Mutation)
    """

    extractors: tuple[ScopeEnricher, ...]
    validate: TokenValidate
    effect: type | None = None
    openapi: AuthOpenAPI = AuthOpenAPI()

    def __init__(
        self,
        *extractors: ScopeEnricher,
        validate: TokenValidate | None = None,
        effect: type | None = None,
        openapi: AuthOpenAPI = AuthOpenAPI(),
    ):
        # Last extractor that is TokenValidate becomes the validator
        found_validate = validate
        actual_extractors: list[ScopeEnricher] = []
        for ext in extractors:
            if isinstance(ext, TokenValidate):
                found_validate = ext
            else:
                actual_extractors.append(ext)
        if found_validate is None:
            raise ValueError("Authenticated requires a TokenValidate enricher")
        object.__setattr__(self, "extractors", tuple(actual_extractors))
        object.__setattr__(self, "validate", found_validate)
        object.__setattr__(self, "effect", effect)
        object.__setattr__(self, "openapi", openapi)

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        from emergent.wire.derive._effects import Public, has_effect

        all_caps: tuple[SurfaceCapability, ...] = (
            *self.extractors,
            self.validate,
            self.openapi,
        )

        new_specs: list[OpSpec] = []
        for s in ctx.specs:
            if has_effect(s.effects, Public):
                new_specs.append(s)
                continue
            if self.effect is not None and not has_effect(s.effects, self.effect):
                new_specs.append(s)
                continue
            new_specs.append(
                replace(s, capabilities=(*s.capabilities, *all_caps))
            )
        return replace(ctx, specs=tuple(new_specs))


# ═══════════════════════════════════════════════════════════════════════════════
# RequireRole — enricher
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class RequireRole(ScopeEnricher):
    """Enricher: reject if identity doesn't have required role.

        RequireRole(AuthUser, frozenset({"admin"}), lambda u: u.roles)
    """

    identity_type: type
    roles: frozenset[str]
    role_getter: Callable[..., set[str]]

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        wrapper = scope.get(self.identity_type)
        if wrapper is None:
            raise AuthorizationFailed("not authenticated")
        user_roles = self.role_getter(wrapper.value)
        if not self.roles & user_roles:
            raise AuthorizationFailed(f"requires one of: {self.roles}")
        return await call(scope)


# ═══════════════════════════════════════════════════════════════════════════════
# RoleRequired — SchemaCapability
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class RoleRequired(SchemaCapability):
    """Add role-check enricher to ops.

        RoleRequired(AuthUser, "admin", lambda u: u.roles)
        RoleRequired(AuthUser, "editor", lambda u: u.roles, effect=Mutation)
    """

    identity_type: type
    role: str
    role_getter: Callable[..., set[str]]
    effect: type | None = None

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        enricher = RequireRole(
            self.identity_type, frozenset({self.role}), self.role_getter
        )
        return ctx.add_spec_capability(enricher, self.effect)


# ═══════════════════════════════════════════════════════════════════════════════
# AuthorizeOps — per-operation role gating
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class AuthorizeOps(SchemaCapability):
    """Per-operation role gating via op name -> role mapping.

        AuthorizeOps(AuthUser, {"Delete": "admin", "Create": "editor"}, lambda u: u.roles)
    """

    identity_type: type
    role_map: RoleMap
    role_getter: Callable[..., set[str]]
    strict: bool = True

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        new_specs: list[OpSpec] = []
        for s in ctx.specs:
            if s.name in self.role_map:
                enricher = RequireRole(
                    self.identity_type,
                    frozenset({self.role_map[s.name]}),
                    self.role_getter,
                )
                new_specs.append(
                    replace(s, capabilities=(*s.capabilities, enricher))
                )
            elif self.strict:
                raise ValueError(
                    f"AuthorizeOps: operation {s.name!r} has no role mapping. "
                    f"Add it to role_map or use strict=False to skip unmapped operations."
                )
            else:
                new_specs.append(s)
        return replace(ctx, specs=tuple(new_specs))


# ═══════════════════════════════════════════════════════════════════════════════
# OwnerContext + OwnerScoped
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class OwnerContext:
    """Owner ID extracted from authenticated identity. Scope injection type."""

    value: str | int


@dataclass(frozen=True, slots=True)
class OwnerScoped(SchemaCapability):
    """Pre-filter all ops by owner identity.

    Mechanism:
    1. Inject enricher reads identity -> injects OwnerContext
    2. owner_field added as extra_op_field with Retrieve(OwnerContext)
    3. Handler templates use scope_fields -> pre-filter query
    4. Creates: owner_field excluded from input (auto-set from identity)

        OwnerScoped(AuthUser, owner_field="author_id", identity_attr="name")
    """

    identity_type: type
    owner_field: str = "owner_id"
    identity_attr: str = "id"

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        from emergent.wire.axis.schema.dialects.compose import Retrieve
        from emergent.wire.axis.surface.enrichers._impl import Inject as InjectEnricher
        from emergent.wire.derive._codegen import AnnotationValue
        from emergent.wire.derive._effects import Creates, has_effect

        identity_type = self.identity_type
        identity_attr = self.identity_attr
        owner_field = self.owner_field

        def _extract_owner(scope: Scope) -> OwnerContext:
            wrapper = scope.get(identity_type)
            if wrapper is None:
                raise AuthorizationFailed(
                    "authentication required for owner-scoped access"
                )
            return OwnerContext(getattr(wrapper.value, identity_attr))

        inject_enricher = InjectEnricher(type=OwnerContext, factory=_extract_owner)
        owner_value_type = ctx.fields.get(owner_field, None)
        base_owner_type = owner_value_type.base_type if owner_value_type is not None else str | int
        # Build Annotated type at runtime — Annotated is a special form that pyright
        # doesn't model as type/UnionType/GenericAlias.
        import typing as _typing
        _annotated_getitem: Callable[..., AnnotationValue] = _typing.Annotated.__getitem__
        owner_request_type: AnnotationValue = _annotated_getitem((base_owner_type, Retrieve(OwnerContext)))

        new_specs: list[OpSpec] = []
        for s in ctx.specs:
            caps = (*s.capabilities, inject_enricher)
            extra_op_fields = tuple(
                field for field in s.extra_op_fields if field[0] != owner_field
            )
            extra_request_fields = tuple(
                field for field in s.extra_request_fields if field[0] != owner_field
            )

            input_fields = dict(s.input_fields)
            request_fields: RequestFieldMap = dict(s.request_fields)
            if has_effect(s.effects, Creates):
                input_fields.pop(owner_field, None)
                request_fields.pop(owner_field, None)
            elif owner_field in request_fields:
                request_fields[owner_field] = owner_request_type

            if owner_field not in input_fields:
                extra_op_fields = (*extra_op_fields, (owner_field, base_owner_type))

            if owner_field not in request_fields:
                extra_request_fields = (
                    *extra_request_fields,
                    (owner_field, owner_request_type),
                )

            new_specs.append(
                replace(
                    s,
                    capabilities=caps,
                    extra_op_fields=extra_op_fields,
                    extra_request_fields=extra_request_fields,
                    scope_fields=(
                        s.scope_fields
                        if owner_field in s.scope_fields
                        else (*s.scope_fields, owner_field)
                    ),
                    input_fields=input_fields,
                    request_fields=request_fields,
                )
            )
        return replace(ctx, specs=tuple(new_specs))


__all__ = (
    "Authenticated",
    "RequireRole",
    "RoleRequired",
    "AuthorizeOps",
    "OwnerContext",
    "OwnerScoped",
)
