"""Multi-tenant isolation — scope-driven tenant filtering.

TenantId = scope injection type (extracted from request)
HeaderTenantExtract = ScopeEnricher reading X-Tenant-Id header
TenantFilter = ScopeEnricher that post-filters responses by tenant
tenant_scoped() = DerivationT that adds extractors + filter to ops

    from examples.ultimate.multi_tenant import tenant_scoped, HeaderTenantExtract

    @derive(
        http_crud("/items", provider_node=Items)
            .chain(tenant_scoped(HeaderTenantExtract()))
    )
    @dataclass
    class Item:
        id: Annotated[int, Identity]
        tenant_id: str
        name: str

Architecture note:
  annotate_handler() wraps handlers as (op) -> Any — single parameter.
  WrappedTemplate handlers therefore CANNOT access scope.
  ScopeEnrichers wrap the entire call chain and DO have scope access.
  So tenant filtering lives in enrichers, not handler wrappers.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, replace
from typing import Any

from nodnod import Scope

from emergent.wire.axis.surface.capabilities import ScopeEnricher, EnricherNext

from derivelib import Derivation, DerivationT, Step, Read, Mutation, has_effect, NotFound


# ═══════════════════════════════════════════════════════════════════════════════
# TenantId — scope injection type
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TenantId:
    """Tenant identifier extracted from transport. Scope injection type."""

    value: str


# ═══════════════════════════════════════════════════════════════════════════════
# Extractors
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class HeaderTenantExtract(ScopeEnricher):
    """HTTP: extract tenant from X-Tenant-Id header.

    Skips silently for non-HTTP scope.
    Always calls next — never fails.
    """

    header_name: str = "x-tenant-id"

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        try:
            import fastapi

            request = scope.get(fastapi.Request)
            if request is not None:
                tenant = request.value.headers.get(self.header_name, "")
                if tenant:
                    scope.inject(TenantId, TenantId(tenant))
        except ImportError:
            pass
        return await call(scope)


# ═══════════════════════════════════════════════════════════════════════════════
# TenantFilter — enricher that post-filters responses
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TenantFilter(ScopeEnricher):
    """Post-filter responses by tenant_id from scope.

    Wraps the entire call chain (enricher → core handler → response).
    After core returns, filters list items or rejects single entities
    that don't match the current tenant.

    Works because enrichers wrap core_handler(scope) → response,
    so they see the final converted response.
    """

    tenant_field: str = "tenant_id"

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R | NotFound:
        result: R = await call(scope)

        # No tenant in scope → return unfiltered
        tenant_wrapper = scope.get(TenantId)
        if tenant_wrapper is None:
            return result

        tid = tenant_wrapper.value.value  # wrapper.value = TenantId, .value = str

        # Response is a generated dataclass — use getattr
        # LIST response: has .items attribute (list of entities)
        items_raw = getattr(result, "items", None)
        if isinstance(items_raw, list):
            # getattr returns Unknown type, use Any to filter
            # No alternative: structural typing doesn't preserve list element types through getattr
            def _filter_by_tenant(items: Any, field: str, value: str) -> list[Any]:
                return [item for item in items if getattr(item, field, None) == value]

            filtered_items = _filter_by_tenant(items_raw, self.tenant_field, tid)
            # Replace items on the response (frozen dataclass → rebuild)
            if dataclasses.is_dataclass(result) and not isinstance(result, type):
                try:
                    data = {f.name: getattr(result, f.name) for f in dataclasses.fields(result)}
                    data["items"] = filtered_items
                    result = type(result)(**data)
                except (TypeError, AttributeError):
                    pass
            return result

        # GET response: single entity with tenant_id
        entity_tid = getattr(result, self.tenant_field, None)
        if entity_tid is not None and entity_tid != tid:
            entity_name = type(result).__name__.replace("Get", "").replace("Response", "")
            # Enricher protocol requires R, but returning error object is
            # wire's standard gating pattern — framework handles NotFound
            return NotFound(entity=entity_name, id={})

        return result


# ═══════════════════════════════════════════════════════════════════════════════
# tenant_scoped — DerivationT
# ═══════════════════════════════════════════════════════════════════════════════


def tenant_scoped(
    *extractors: ScopeEnricher,
    tenant_field: str = "tenant_id",
) -> DerivationT:
    """Add tenant isolation to all ops.

    Reads: post-filter by tenant_id from scope (via TenantFilter enricher).
    Creates/Mutations: add extractors to capabilities.

        .chain(tenant_scoped(HeaderTenantExtract()))
    """
    tenant_filter = TenantFilter(tenant_field=tenant_field)

    def transform(steps: Derivation) -> Derivation:
        from derivelib.axes.surface import DeriveOp

        result: list[Step] = []
        for s in steps:
            if isinstance(s, DeriveOp):
                if has_effect(s.effects, Read):
                    # Reads: add extractors + tenant filter enricher
                    s = replace(s, capabilities=(*s.capabilities, *extractors, tenant_filter))
                elif has_effect(s.effects, Mutation):
                    # Mutations: add extractors (tenant comes from request body)
                    s = replace(s, capabilities=(*s.capabilities, *extractors))
            result.append(s)
        return tuple(result)

    return transform


__all__ = (
    # Scope injection type
    "TenantId",
    # Extractors
    "HeaderTenantExtract",
    # Filter enricher
    "TenantFilter",
    # Transform
    "tenant_scoped",
)
