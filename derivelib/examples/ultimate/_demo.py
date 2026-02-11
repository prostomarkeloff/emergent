"""ultimate demo — one entity, seven concerns, zero boilerplate.

Article with: CRUD + audit + tenant isolation + soft delete +
realtime events + approval flow + auth (from authlib).

    cd derivelib && PYTHONPATH=src:.. uv run python -m examples.ultimate

    # 1. create article (sets tenant from header, initial status=draft)
    curl -X POST http://localhost:8000/articles \
         -H 'Content-Type: application/json' \
         -H 'X-Tenant-Id: acme' \
         -d '{"tenant_id":"acme","title":"hello","body":"world"}'

    # 2. list articles (filtered by tenant)
    curl http://localhost:8000/articles -H 'X-Tenant-Id: acme'

    # 3. soft-delete article (sets deleted_at, doesn't remove)
    curl -X DELETE http://localhost:8000/articles/1 -H 'X-Tenant-Id: acme'

    # 4. list again (deleted article filtered out)
    curl http://localhost:8000/articles -H 'X-Tenant-Id: acme'

    # 5. restore soft-deleted article
    curl -X DELETE http://localhost:8000/articles/1/restore -H 'X-Tenant-Id: acme'

    # 6. submit for approval (draft -> pending)
    curl -X POST http://localhost:8000/articles/1/submit

    # 7. approve (pending -> published)
    curl -X POST http://localhost:8000/articles/1/approve

    # 8. check status
    curl http://localhost:8000/articles/1/status

    # 9. bulk import
    curl -X POST http://localhost:8000/articles/import \
         -H 'Content-Type: application/json' \
         -d '{"items":[{"tenant_id":"acme","title":"a","body":"b"},{"tenant_id":"acme","title":"c","body":"d"}]}'

    # 10. bulk export
    curl http://localhost:8000/articles/export
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from nodnod import scalar_node

from emergent.wire.axis.query import MutatingRelationalProvider, SequenceNextId
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
from emergent.wire.axis.schema import Identity

from derivelib import derive, build_application_from_decorated
from derivelib.patterns.crud import http_crud, LIST, GET, CREATE, UPDATE, DELETE

from . import (
    AuditEntry,
    audited,
    HeaderTenantExtract,
    tenant_scoped,
    soft_delete,
    EventBus,
    with_events,
    Transition,
    approval_flow,
    exclude_managed_fields,
    with_import_export,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Providers
# ═══════════════════════════════════════════════════════════════════════════════


_articles: MemoryRelationalProvider[Article] = MemoryRelationalProvider(
    key_fn=lambda x: x.id, next_id=SequenceNextId(),
)
_audit: MemoryRelationalProvider[AuditEntry] = MemoryRelationalProvider(
    key_fn=lambda x: x.id, next_id=SequenceNextId(),
)


@scalar_node
class Articles:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider[Article]:
        return _articles


# ═══════════════════════════════════════════════════════════════════════════════
# Event Bus
# ═══════════════════════════════════════════════════════════════════════════════


event_bus = EventBus()


# ═══════════════════════════════════════════════════════════════════════════════
# Entity — one decorator, seven concerns
# ═══════════════════════════════════════════════════════════════════════════════


@derive(
    http_crud(
        "/articles", provider_node=Articles,
        ops=(LIST, GET, CREATE, UPDATE, DELETE),
    ).chain(
        audited(_audit),
        tenant_scoped(HeaderTenantExtract()),
        soft_delete(),
        exclude_managed_fields("status"),
        with_events(event_bus, channel="articles"),
        with_import_export(),
    ),
    approval_flow(
        "/articles", provider_node=Articles, state_field="status",
        transitions=(
            Transition("submit", ("draft",), "pending"),
            Transition("approve", ("pending",), "published"),
            Transition("reject", ("pending",), "draft"),
            Transition("archive", ("published",), "archived"),
        ),
    ),
)
@dataclass
class Article:
    id: Annotated[int, Identity]
    tenant_id: str = ""
    title: str = ""
    body: str = ""
    status: str = "draft"
    deleted_at: str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Build
# ═══════════════════════════════════════════════════════════════════════════════


app = build_application_from_decorated(Article)

from emergent.wire.compile import targets  # noqa: E402

fastapi_app = targets.fastapi.compile(app)
