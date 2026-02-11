"""Approval flow — state machine dialect.

Transition = (name, from_states, to_state)
approval_flow() = dialect with validated state transitions.

NOT CRUD — shows derive handles arbitrary business patterns.
Each transition = one validated endpoint.

    from examples.ultimate.approval_flow import approval_flow, Transition

    @derive(
        approval_flow(
            "/articles", provider_node=Articles, state_field="status",
            transitions=(
                Transition("submit",  ("draft",), "pending"),
                Transition("approve", ("pending",), "published"),
                Transition("reject",  ("pending",), "draft"),
            ),
        ),
    )
    @dataclass
    class Article: ...
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from kungfu import Ok, Error, Result

from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

from derivelib import (
    exposure, SurfaceCtx, Derivation, DerivationT, Step,
    InvalidData, dict_converter,
    fetch_by_identity, id_path, not_found_error, provider_field,
)
from derivelib.axes.schema import inspect_entity, require_identity
from derivelib._protocols import HasProvider
from derivelib.patterns.crud import CRUDErrorTransform, ProblemResponse

if TYPE_CHECKING:
    from derivelib._errors import DomainError


# ═══════════════════════════════════════════════════════════════════════════════
# Transition DSL
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Transition:
    """One state transition: name + valid from_states + target to_state.

        Transition("submit",  ("draft",), "pending")
        Transition("approve", ("pending",), "approved")
        Transition("cancel",  ("draft", "pending"), "cancelled")
    """

    name: str
    from_states: tuple[str, ...]
    to_state: str


_APPROVAL_CAPS = (CRUDErrorTransform(), ProblemResponse())


# ═══════════════════════════════════════════════════════════════════════════════
# Surface Steps — create + transition endpoints
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ApprovalCreateStep:
    """Create entity with initial state. Derives from entity schema."""

    base_path: str
    state_field: str
    initial_state: str
    provider_node: type

    def derive_surface[EntityT](self, ctx: SurfaceCtx[EntityT]) -> SurfaceCtx[EntityT]:
        schema = ctx.schema
        entity = schema.entity
        id_names = schema.identity_names()
        non_id = schema.non_identity_fields()
        sf, init = self.state_field, self.initial_state

        # Exclude state field + optional/defaulted fields (server-managed)
        user_fields = {
            name: info for name, info in non_id.items()
            if name != sf and not (info.is_optional and info.has_default)
        }
        fields = {f.name: f.base_type for f in user_fields.values()}
        fields["provider"] = provider_field(self.provider_node)
        names = list(user_fields.keys())

        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            d = {n: getattr(op, n) for n in names}
            for name in id_names:
                d[name] = 0
            d[sf] = init
            return Ok(await op.provider.insert(entity(**d)))

        resp_fields: dict[str, type] = {n: info.base_type for n, info in schema.identity_fields.items()}
        resp_fields[sf] = str
        return ctx.add_exposure(
            exposure("create", entity)
            .request(**fields).response(**resp_fields)
            .response_converter(dict_converter)
            .caps(*_APPROVAL_CAPS)
            .handler(handler).trigger(HTTPRouteTrigger("POST", f"{self.base_path}/create"))
        )


@dataclass(frozen=True, slots=True)
class ApprovalTransitionStep:
    """One state transition endpoint. Validates current state before allowing."""

    base_path: str
    transition: Transition
    state_field: str
    provider_node: type

    def derive_surface[EntityT](self, ctx: SurfaceCtx[EntityT]) -> SurfaceCtx[EntityT]:
        schema = ctx.schema
        entity = schema.entity
        id_names = schema.identity_names()
        non_id_names = tuple(schema.non_identity_fields().keys())
        tr, sf = self.transition, self.state_field

        async def handler(op: HasProvider[EntityT]) -> Result[Any, DomainError]:
            obj = await fetch_by_identity(op.provider, entity, op, id_names)
            if obj is None:
                return not_found_error(entity.__name__, op, id_names)
            cur = getattr(obj, sf)
            if cur not in tr.from_states:
                return Error(InvalidData(entity=entity.__name__, reason=f"cannot '{tr.name}': state is '{cur}', need {tr.from_states}"))
            updated = entity(**{
                **{name: getattr(obj, name) for name in (*id_names, *non_id_names)},
                sf: tr.to_state,
            })
            await op.provider.update(updated)
            return Ok({sf: tr.to_state})

        req_fields = {n: info.base_type for n, info in schema.identity_fields.items()}
        req_fields["provider"] = provider_field(self.provider_node)
        return ctx.add_exposure(
            exposure(tr.name, entity)
            .request(**req_fields)
            .response(**{sf: str})
            .response_converter(dict_converter)
            .caps(*_APPROVAL_CAPS)
            .handler(handler).trigger(HTTPRouteTrigger("POST", f"{self.base_path}/{id_path(id_names)}/{tr.name}"))
        )


@dataclass(frozen=True, slots=True)
class ApprovalStatusStep:
    """GET endpoint returning current state of an entity."""

    base_path: str
    state_field: str
    provider_node: type

    def derive_surface[EntityT](self, ctx: SurfaceCtx[EntityT]) -> SurfaceCtx[EntityT]:
        schema = ctx.schema
        entity = schema.entity
        id_names = schema.identity_names()
        sf = self.state_field

        async def handler(op: HasProvider[EntityT]) -> Result[Any, DomainError]:
            obj = await fetch_by_identity(op.provider, entity, op, id_names)
            if obj is None:
                return not_found_error(entity.__name__, op, id_names)
            return Ok({sf: getattr(obj, sf)})

        req_fields = {n: info.base_type for n, info in schema.identity_fields.items()}
        req_fields["provider"] = provider_field(self.provider_node)
        return ctx.add_exposure(
            exposure("status", entity)
            .request(**req_fields)
            .response(**{sf: str})
            .response_converter(dict_converter)
            .caps(*_APPROVAL_CAPS)
            .handler(handler).trigger(HTTPRouteTrigger("GET", f"{self.base_path}/{id_path(id_names)}/status"))
        )


# ═══════════════════════════════════════════════════════════════════════════════
# approval_flow — dialect (pattern)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ApprovalFlowPattern:
    """State machine pattern: transitions -> validated endpoints.

    Compiles to: create + N transitions + status endpoint.
    """

    base_path: str
    provider_node: type
    state_field: str
    transitions: tuple[Transition, ...]

    def compile(self, entity: type) -> Derivation:
        init = self.transitions[0].from_states[0] if self.transitions else "draft"
        return (
            inspect_entity(), require_identity(),
            ApprovalCreateStep(self.base_path, self.state_field, init, self.provider_node),
            *(
                ApprovalTransitionStep(self.base_path, tr, self.state_field, self.provider_node)
                for tr in self.transitions
            ),
            ApprovalStatusStep(self.base_path, self.state_field, self.provider_node),
        )


def approval_flow(
    path: str,
    provider_node: type,
    *,
    state_field: str = "status",
    transitions: tuple[Transition, ...],
) -> ApprovalFlowPattern:
    """Approval flow dialect — state machine as validated endpoints.

        approval_flow(
            "/articles", provider_node=Articles, state_field="status",
            transitions=(
                Transition("submit",  ("draft",), "pending"),
                Transition("approve", ("pending",), "published"),
            ),
        )
    """
    return ApprovalFlowPattern(path, provider_node, state_field, transitions)


def exclude_managed_fields(
    *fields: str,
) -> DerivationT:
    """Exclude server-managed fields from CRUD input projections.

    Chain on CRUD ops to exclude fields managed by other concerns
    (e.g., status managed by approval_flow, deleted_at by soft_delete).

        .chain(exclude_managed_fields("status"))
    """
    from derivelib import ExcludeFromProjection, Mutation, has_effect

    def transform(steps: Derivation) -> Derivation:
        from derivelib.axes.surface import DeriveOp

        result: list[Step] = []
        for s in steps:
            if isinstance(s, DeriveOp) and has_effect(s.effects, Mutation):
                excluded = ExcludeFromProjection(s.input_proj, fields)
                result.append(replace(s, input_proj=excluded))
            else:
                result.append(s)
        return tuple(result)

    return transform


__all__ = (
    # DSL
    "Transition",
    # Pattern
    "ApprovalFlowPattern",
    "approval_flow",
    # Helpers
    "exclude_managed_fields",
)
