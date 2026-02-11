"""Owner-scoped queries — pre-filter by authenticated identity.

Entities must have an owner_field (e.g., owner_id: str).
Operations are filtered to only access entities owned by the current user.

    from derivelib.authlib.owner import owner_scoped, OwnerContext

    @derive(
        http_crud("/posts", provider_node=Posts)
            .chain(require_auth(validate, BearerExtract()))
            .chain(owner_scoped(AuthUser, owner_field="author_id", identity_attr="name"))
    )
    @dataclass
    class Post:
        id: Annotated[int, Identity]
        author_id: str
        title: str

Mechanism:
1. Inject enricher reads identity from scope → injects OwnerContext
2. owner_field added as extra_op_field with compose.Retrieve(OwnerContext)
   → resolved from scope (NOT from request body)
3. Handler templates use scope_fields=(owner_field,) → pre-filter query
4. Creates: owner_field excluded from input (auto-set from identity)
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Annotated, TYPE_CHECKING

from nodnod import Scope

from derivelib._derivation import DerivationT, Step
from derivelib._effects import Creates, has_effect
from derivelib._project import ExcludeFromProjection

from .errors import AuthorizationFailed

if TYPE_CHECKING:
    from derivelib._protocols import HandlerTemplate


# ═══════════════════════════════════════════════════════════════════════════════
# OwnerContext — scope injection type
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class OwnerContext:
    """Owner ID extracted from authenticated identity. Scope injection type."""

    value: str | int


# ═══════════════════════════════════════════════════════════════════════════════
# owner_scoped — DerivationT
# ═══════════════════════════════════════════════════════════════════════════════


def owner_scoped(
    identity_type: type,
    owner_field: str = "owner_id",
    identity_attr: str = "id",
) -> DerivationT:
    """Pre-filter all ops by owner identity.

    Mechanism:
    1. Inject enricher reads identity from scope → injects OwnerContext
    2. owner_field added as extra_op_field with compose.Retrieve(OwnerContext)
       → resolved from scope (NOT from request body)
    3. Handler templates use scope_fields=(owner_field,) → pre-filter query
    4. Creates: owner_field excluded from input (auto-set from identity)

        .chain(owner_scoped(AuthUser, owner_field="author_id", identity_attr="name"))
    """
    from emergent.wire.axis.surface.enrichers._impl import Inject as InjectEnricher
    from emergent.wire.axis.schema.dialects.compose import Retrieve

    def _extract_owner(scope: Scope) -> OwnerContext:
        wrapper = scope.get(identity_type)
        if wrapper is None:
            raise AuthorizationFailed("authentication required for owner-scoped access")
        return OwnerContext(getattr(wrapper.value, identity_attr))

    inject_enricher = InjectEnricher(type=OwnerContext, factory=_extract_owner)

    # Annotated field type for extra_op_fields — resolved from scope, not request.
    # Retrieve(OwnerContext) tells compose to resolve from scope, not request body.
    owner_field_type = Annotated[str | int, Retrieve(OwnerContext)]

    def transform(steps: tuple[Step, ...]) -> tuple[Step, ...]:
        from derivelib.axes.surface import DeriveOp

        result: list[Step] = []
        for s in steps:
            if not isinstance(s, DeriveOp):
                result.append(s)
                continue

            # 1. Add inject enricher
            caps = (*s.capabilities, inject_enricher)

            # 2. Add owner_field as compose.Retrieve op field
            extra = (*s.extra_op_fields, (owner_field, owner_field_type))

            # 3. Add scope_fields to handler template
            tmpl = _add_scope_field(s.handler_template, owner_field)

            # 4. For creates: exclude owner_field from input (auto-set)
            proj = s.input_proj
            if has_effect(s.effects, Creates):
                proj = ExcludeFromProjection(inner=proj, names=(owner_field,))

            result.append(replace(s,
                capabilities=caps,
                extra_op_fields=extra,
                handler_template=tmpl,
                input_proj=proj,
            ))
        return tuple(result)

    return transform


def _add_scope_field(template: HandlerTemplate, field: str) -> HandlerTemplate:
    """Add scope_field to handler template (duck-typed).

    Handler templates are frozen dataclasses. We reconstruct via type()
    because HandlerTemplate is a Protocol — not a DataclassInstance for replace().
    """
    scope_fields: tuple[str, ...] | None = getattr(template, "scope_fields", None)
    if scope_fields is not None:
        return _reconstruct_template(template, scope_fields=(*scope_fields, field))
    inner: HandlerTemplate | None = getattr(template, "inner", None)
    if inner is not None:
        return _reconstruct_template(template, inner=_add_scope_field(inner, field))
    return template


def _reconstruct_template(
    template: HandlerTemplate,
    **overrides: tuple[str, ...] | HandlerTemplate,
) -> HandlerTemplate:
    """Reconstruct a handler template dataclass with field overrides."""
    dc_fields: dict[str, type] = getattr(template, "__dataclass_fields__", {})
    kwargs = {name: getattr(template, name) for name in dc_fields}
    kwargs.update(overrides)
    cls: type = type(template)
    return cls(**kwargs)


__all__ = (
    "OwnerContext",
    "owner_scoped",
)
