"""ultimate — seven composable transforms, boilerplate is dead.

    from examples.ultimate import (
        # Audit
        AuditEntry, audited,
        # Multi-tenant
        TenantId, HeaderTenantExtract, tenant_scoped,
        # Soft delete
        soft_delete,
        # Realtime
        Event, EventBus, with_events,
        # Approval flow
        Transition, approval_flow,
        # Import/export
        with_import_export,
        # Versioning
        versioned, exclude_fields,
    )
"""

from .audit_log import AuditEntry, audited
from .multi_tenant import TenantId, HeaderTenantExtract, TenantFilter, tenant_scoped  # noqa: F401
from .soft_delete import soft_delete
from .realtime import Event, EventBus, with_events
from .approval_flow import Transition, approval_flow, exclude_managed_fields
from .import_export import with_import_export
from .versioned_api import versioned, exclude_fields

__all__ = (
    # Audit
    "AuditEntry",
    "audited",
    # Multi-tenant
    "TenantId",
    "HeaderTenantExtract",
    "TenantFilter",
    "tenant_scoped",
    # Soft delete
    "soft_delete",
    # Realtime
    "Event",
    "EventBus",
    "with_events",
    # Approval flow
    "Transition",
    "approval_flow",
    "exclude_managed_fields",
    # Import/export
    "with_import_export",
    # Versioning
    "versioned",
    "exclude_fields",
)
