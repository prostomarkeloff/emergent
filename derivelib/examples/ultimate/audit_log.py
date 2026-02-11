"""Audit logging — automatic mutation trail via WrappedTemplate.

audited(store) = DerivationT that wraps mutation handlers.
After success, writes AuditEntry to audit storage. Zero overhead on reads.

AuditEntry = timestamp + operation + entity_type + payload
Uses WrappedTemplate — the handler sees no difference.

    from examples.ultimate.audit_log import audited

    @derive(
        http_crud("/users", provider_node=Users)
            .chain(audited(audit_store))
    )
    @dataclass
    class User: ...
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, UTC

from kungfu import Ok, Result

from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider

from typing import TYPE_CHECKING

from derivelib import (
    DerivationT, Mutation,
    HandlerSpec, WrappedTemplate,
    serialize_op_fields, map_by_effect,
)
from derivelib._ctx import OperationHandler
from derivelib._effects import DerivationEffect
from derivelib._protocols import WrapperFn
from derivelib.axes.surface import DeriveOp

if TYPE_CHECKING:
    from derivelib._errors import DomainError


# ═══════════════════════════════════════════════════════════════════════════════
# AuditEntry — the audit record
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class AuditEntry:
    """One audit record. Stored in audit provider."""

    id: int = 0
    timestamp: str = ""
    operation: str = ""
    entity_type: str = ""
    payload: str = ""  # JSON-serialized snapshot


# ═══════════════════════════════════════════════════════════════════════════════
# Handler Wrapper — after-success logging
# ═══════════════════════════════════════════════════════════════════════════════


def _make_audit_wrapper(
    audit_store: MemoryRelationalProvider[AuditEntry],
    op_name: str,
) -> WrapperFn:
    """Build WrappedTemplate wrapper that logs on success.

        inner(op) -> result
        if Ok: write AuditEntry to store
        return result unchanged
    """

    def wrapper[EntityT](inner: OperationHandler[EntityT, DomainError], spec: HandlerSpec[EntityT]) -> OperationHandler[EntityT, DomainError]:
        async def audited_handler(op: object) -> Result[EntityT, DomainError]:
            result = await inner(op)
            if isinstance(result, Ok):
                entry = AuditEntry(
                    timestamp=datetime.now(UTC).isoformat(),
                    operation=op_name,
                    entity_type=spec.entity_name,
                    payload=serialize_op_fields(op, spec.non_identity_names),
                )
                await audit_store.insert(entry)
            return result

        return audited_handler

    return wrapper


# ═══════════════════════════════════════════════════════════════════════════════
# audited — DerivationT
# ═══════════════════════════════════════════════════════════════════════════════


def audited(
    audit_store: MemoryRelationalProvider[AuditEntry],
) -> DerivationT:
    """Add audit logging to mutation ops.

    Wraps handler templates with after-success audit write.
    Reads pass through untouched.

        .chain(audited(my_audit_store))
    """

    def _add(_eff: DerivationEffect, op: DeriveOp) -> DeriveOp:
        wrapped = WrappedTemplate(
            inner=op.handler_template,
            wrapper=_make_audit_wrapper(audit_store, op.name),
        )
        return replace(op, handler_template=wrapped)

    return map_by_effect({Mutation: _add})


__all__ = (
    "AuditEntry",
    "audited",
)
