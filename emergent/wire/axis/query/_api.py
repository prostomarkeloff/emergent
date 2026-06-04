"""API QuerySet — REST-ish API operations.

For querying external APIs with typed filters and pagination.

    @dataclass
    class User:
        id: Annotated[str, Identity, api.PathParam]
        name: Annotated[str, api.Filterable, api.Sortable]
        active: Annotated[bool, api.Filterable]

    users = api(User, key=lambda u: u.id)

    # List with filters
    q = users.list().filter(lambda u: u.active == True).page(1, per_page=20)
    result = await provider.fetch(q)

    # Get by ID
    q = users.get("user-123")
    user = await provider.fetch_one(q)
"""

from __future__ import annotations

import dataclasses as _dc
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Callable, Generic, TypeVar

if TYPE_CHECKING:
    from emergent.wire.axis.query._contexts import MemoryAPIContext, HTTPAPIContext

from emergent.wire.axis.query._contexts import ExplainContext, ExplainEntry
from emergent.wire.axis.query._expr import Expr
from emergent.wire.axis.query._proxy import (
    FieldProxy,
    OrderSpec,
    build_expr,
    build_order,
    EntityProxy,
)

# ─── Cross-compilable ops (from _relational) ─────────────────────────────────
# Filter, OrderBy, Select are now unified types that compile for ALL backends.
# Import them here and alias to old *Mod names for backward compatibility.
from emergent.wire.axis.query._relational import Filter, OrderBy, Select

# Backward compat aliases — existing code using FilterMod/OrderMod/SelectMod
# continues to work. These ARE the same types.
FilterMod = Filter
OrderMod = OrderBy
SelectMod = Select


K = TypeVar("K")
T = TypeVar("T")


# ─── Operations ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ListOp:
    """List resources."""
    pass

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(ExplainEntry(op="List"))


@dataclass(frozen=True, slots=True)
class GetOp(Generic[K]):
    """Get single resource by ID."""
    id: K

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(ExplainEntry(op="Get", fields=(("id", repr(self.id)),)))


@dataclass(frozen=True, slots=True)
class CreateOp(Generic[T]):
    """Create resource."""
    entity: T

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(ExplainEntry(op="Create", fields=(
            ("entity_type", type(self.entity).__name__),
        )))


@dataclass(frozen=True, slots=True)
class UpdateOp(Generic[K, T]):
    """Update resource."""
    id: K
    entity: T
    partial: bool = False  # PATCH vs PUT

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        method = "Patch" if self.partial else "Update"
        return ctx.add(ExplainEntry(op=method, fields=(("id", repr(self.id)),)))


@dataclass(frozen=True, slots=True)
class DeleteOp(Generic[K]):
    """Delete resource."""
    id: K

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(ExplainEntry(op="Delete", fields=(("id", repr(self.id)),)))


# ─── API-only Modifiers (self-compiling) ──────────────────────────────────────
# These have no relational equivalent — they stay here as API-specific mods.


@dataclass(frozen=True, slots=True)
class PageMod:
    """Page-based pagination."""

    page: int
    per_page: int

    def compile_memory_api(self, ctx: MemoryAPIContext) -> MemoryAPIContext:
        total = len(ctx.data)
        start = (self.page - 1) * self.per_page
        end = start + self.per_page
        return replace(ctx, data=ctx.data[start:end], total=total, has_more=end < total)

    def compile_http_api(self, ctx: HTTPAPIContext) -> HTTPAPIContext:
        ctx.apply_pagination(ctx.params, self)
        return ctx

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(ExplainEntry(op="Page", fields=(
            ("page", self.page), ("per_page", self.per_page),
        )))


@dataclass(frozen=True, slots=True)
class CursorMod:
    """Cursor-based pagination."""

    cursor: str
    limit: int

    def compile_memory_api(self, ctx: MemoryAPIContext) -> MemoryAPIContext:
        total = len(ctx.data)
        try:
            start = int(self.cursor)
        except (ValueError, TypeError):
            start = 0
        end = start + self.limit
        return replace(ctx, data=ctx.data[start:end], total=total, has_more=end < total)

    def compile_http_api(self, ctx: HTTPAPIContext) -> HTTPAPIContext:
        ctx.apply_pagination(ctx.params, self)
        return ctx

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(ExplainEntry(op="Cursor", fields=(
            ("cursor", self.cursor), ("limit", self.limit),
        )))


@dataclass(frozen=True, slots=True)
class OffsetMod:
    """Offset-based pagination."""

    offset: int
    limit: int

    def compile_memory_api(self, ctx: MemoryAPIContext) -> MemoryAPIContext:
        total = len(ctx.data)
        end = self.offset + self.limit
        return replace(ctx, data=ctx.data[self.offset:end], total=total, has_more=end < total)

    def compile_http_api(self, ctx: HTTPAPIContext) -> HTTPAPIContext:
        ctx.apply_pagination(ctx.params, self)
        return ctx

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(ExplainEntry(op="Offset", fields=(
            ("offset", self.offset), ("limit", self.limit),
        )))


@dataclass(frozen=True, slots=True)
class SearchMod:
    """Full-text search."""

    query: str

    def compile_memory_api(self, ctx: MemoryAPIContext) -> MemoryAPIContext:
        search_lower = self.query.lower()
        result = [
            item for item in ctx.data
            if any(
                search_lower in str(getattr(item, f.name, "")).lower()
                for f in _dc.fields(item)
            )
        ]
        return replace(ctx, data=result)

    def compile_http_api(self, ctx: HTTPAPIContext) -> HTTPAPIContext:
        ctx.params["q"] = self.query
        return ctx

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(ExplainEntry(op="Search", fields=(("query", self.query),)))


@dataclass(frozen=True, slots=True)
class IncludeMod:
    """Include related resources.

    No compile_memory_api — memory doesn't support include.
    Skipped via open-world dispatch; memory provider adds handler
    override that raises TypeError (preserving current behavior).
    """

    relations: tuple[str, ...]

    def compile_http_api(self, ctx: HTTPAPIContext) -> HTTPAPIContext:
        ctx.params["include"] = ",".join(self.relations)
        return ctx

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(ExplainEntry(op="Include", fields=(
            ("relations", list(self.relations)),
        )))


# Union of all operations
APIOp = ListOp | GetOp[Any] | CreateOp[Any] | UpdateOp[Any, Any] | DeleteOp[Any]

# Union of all modifiers (Filter, OrderBy, Select are cross-compilable from _relational)
APIMod = Filter | OrderBy | PageMod | CursorMod | OffsetMod | Select | SearchMod | IncludeMod


# ─── QuerySet ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class APIQuerySet(Generic[K, T]):
    """API query — REST-ish operations.

    K = key type, T = entity type.
    Immutable. Each method returns new QuerySet.
    """

    entity: type[T]
    key_fn: Callable[[T], K] | None = None
    op: APIOp | None = None
    mods: tuple[APIMod, ...] = field(default_factory=tuple)

    def _with_op(self, op: APIOp) -> APIQuerySet[K, T]:
        return APIQuerySet(entity=self.entity, key_fn=self.key_fn, op=op, mods=self.mods)

    def _with_mod(self, mod: APIMod) -> APIQuerySet[K, T]:
        if isinstance(mod, (PageMod, CursorMod, OffsetMod)):
            # Pagination: last-wins — replace any existing pagination mod
            mods = tuple(m for m in self.mods if not isinstance(m, (PageMod, CursorMod, OffsetMod)))
        else:
            mods = self.mods
        return APIQuerySet(entity=self.entity, key_fn=self.key_fn, op=self.op, mods=(*mods, mod))

    # ─── CRUD Operations ─────────────────────────────────────────────────

    def list(self) -> APIQuerySet[K, T]:
        """List resources.

        Usage:
            users.list().filter(lambda u: u.active).page(1)
        """
        return self._with_op(ListOp())

    def get(self, id: K) -> APIQuerySet[K, T]:
        """Get single resource by ID.

        Usage:
            users.get("user-123")
        """
        return self._with_op(GetOp(id))

    def create(self, entity: T) -> APIQuerySet[K, T]:
        """Create resource.

        Usage:
            users.create(User(name="alice", ...))
        """
        return self._with_op(CreateOp(entity))

    def update(self, id: K, entity: T, *, partial: bool = False) -> APIQuerySet[K, T]:
        """Update resource.

        Usage:
            users.update("user-123", updated_user)
            users.update("user-123", partial_user, partial=True)  # PATCH
        """
        return self._with_op(UpdateOp(id, entity, partial))

    def delete(self, id: K) -> APIQuerySet[K, T]:
        """Delete resource.

        Usage:
            users.delete("user-123")
        """
        return self._with_op(DeleteOp(id))

    # ─── Modifiers (for list) ────────────────────────────────────────────

    def filter(self, predicate: Callable[[EntityProxy[T]], Expr]) -> APIQuerySet[K, T]:
        """Add filter.

        Usage:
            .filter(lambda u: u.active == True)
            .filter(lambda u: u.balance > 100)
        """
        expr = build_expr(self.entity, predicate)
        return self._with_mod(Filter(expr))

    def order_by(
        self, *order_fns: Callable[[EntityProxy[T]], FieldProxy | OrderSpec]
    ) -> APIQuerySet[K, T]:
        """Add ordering.

        Usage:
            .order_by(lambda u: u.name.asc())
            .order_by(lambda u: u.balance.desc())
        """
        specs = tuple(build_order(self.entity, fn) for fn in order_fns)
        return self._with_mod(OrderBy(specs))

    def page(self, page: int, per_page: int = 20) -> APIQuerySet[K, T]:
        """Page-based pagination.

        Usage:
            .page(1, per_page=50)
        """
        return self._with_mod(PageMod(page, per_page))

    def cursor(self, cursor: str, limit: int = 20) -> APIQuerySet[K, T]:
        """Cursor-based pagination.

        Usage:
            .cursor("eyJpZCI6MTIzfQ==", limit=50)
        """
        return self._with_mod(CursorMod(cursor, limit))

    def offset(self, offset: int, limit: int = 20) -> APIQuerySet[K, T]:
        """Offset-based pagination.

        Usage:
            .offset(100, limit=50)
        """
        return self._with_mod(OffsetMod(offset, limit))

    def select(self, *field_fns: Callable[[EntityProxy[T]], FieldProxy]) -> APIQuerySet[K, T]:
        """Select specific fields (sparse fieldsets).

        Usage:
            .select(lambda u: u.id, lambda u: u.name)
        """
        proxy = EntityProxy(self.entity)
        fields = tuple(fn(proxy).name for fn in field_fns)
        return self._with_mod(Select(fields))

    def search(self, query: str) -> APIQuerySet[K, T]:
        """Full-text search.

        Usage:
            .search("alice")
        """
        return self._with_mod(SearchMod(query))

    def include(self, *relations: str) -> APIQuerySet[K, T]:
        """Include related resources.

        Usage:
            .include("posts", "comments")
        """
        return self._with_mod(IncludeMod(relations))

    # ─── Introspection ───────────────────────────────────────────────────

    @property
    def filters(self) -> list[Expr]:
        """All filter expressions."""
        return [mod.expr for mod in self.mods if isinstance(mod, Filter)]

    @property
    def ordering(self) -> list[OrderSpec]:
        """All order specs."""
        result: list[OrderSpec] = []
        for mod in self.mods:
            if isinstance(mod, OrderBy):
                result.extend(mod.specs)
        return result

    @property
    def pagination(self) -> PageMod | CursorMod | OffsetMod | None:
        """Pagination modifier if set."""
        for mod in self.mods:
            if isinstance(mod, (PageMod, CursorMod, OffsetMod)):
                return mod
        return None

    @property
    def ops(self) -> tuple[APIMod, ...]:
        """Pipeline ops for fold compilation. Uniform access with RelationalQuerySet."""
        return self.mods


def api(entity: type[T], key: Callable[[T], K] | None = None) -> APIQuerySet[K, T]:
    """Create API QuerySet for entity.

    Usage:
        users = api(User, key=lambda u: u.id)
        q = users.list().filter(lambda u: u.active).page(1)

        # Without key (key-dependent ops like get/update/delete lose type info):
        q = api(User).list()
    """
    return APIQuerySet(entity=entity, key_fn=key)


__all__ = (
    # Operations
    "ListOp",
    "GetOp",
    "CreateOp",
    "UpdateOp",
    "DeleteOp",
    "APIOp",
    # Cross-compilable (from _relational)
    "Filter",
    "OrderBy",
    "Select",
    # Backward compat aliases
    "FilterMod",
    "OrderMod",
    "SelectMod",
    # API-only modifiers
    "PageMod",
    "CursorMod",
    "OffsetMod",
    "SearchMod",
    "IncludeMod",
    "APIMod",
    # QuerySet
    "APIQuerySet",
    "api",
)
