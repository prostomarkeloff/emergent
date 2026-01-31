"""API QuerySet — REST-ish API operations.

For querying external APIs with typed filters and pagination.

    @dataclass
    class User:
        id: Annotated[str, Identity, api.PathParam]
        name: Annotated[str, api.Filterable, api.Sortable]
        active: Annotated[bool, api.Filterable]

    users = api(User)

    # List with filters
    q = users.list().filter(lambda u: u.active == True).page(1, per_page=20)
    result = await provider.fetch(q)

    # Get by ID
    q = users.get("user-123")
    user = await provider.fetch_one(q)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Generic, TypeVar

from emergent.wire.axis.query._expr import Expr
from emergent.wire.axis.query._proxy import (
    FieldProxy,
    OrderSpec,
    build_expr,
    build_order,
    EntityProxy,
)


T = TypeVar("T")


# ─── Operations ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ListOp:
    """List resources."""
    pass


@dataclass(frozen=True, slots=True)
class GetOp:
    """Get single resource by ID."""
    id: Any


@dataclass(frozen=True, slots=True)
class CreateOp:
    """Create resource."""
    entity: Any


@dataclass(frozen=True, slots=True)
class UpdateOp:
    """Update resource."""
    id: Any
    entity: Any
    partial: bool = False  # PATCH vs PUT


@dataclass(frozen=True, slots=True)
class DeleteOp:
    """Delete resource."""
    id: Any


# Filter/pagination modifiers
@dataclass(frozen=True, slots=True)
class FilterMod:
    """Filter modifier."""
    expr: Expr


@dataclass(frozen=True, slots=True)
class OrderMod:
    """Order modifier."""
    specs: tuple[OrderSpec, ...]


@dataclass(frozen=True, slots=True)
class PageMod:
    """Page-based pagination."""
    page: int
    per_page: int


@dataclass(frozen=True, slots=True)
class CursorMod:
    """Cursor-based pagination."""
    cursor: str
    limit: int


@dataclass(frozen=True, slots=True)
class OffsetMod:
    """Offset-based pagination."""
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class SelectMod:
    """Field selection (sparse fieldsets)."""
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SearchMod:
    """Full-text search."""
    query: str


@dataclass(frozen=True, slots=True)
class IncludeMod:
    """Include related resources."""
    relations: tuple[str, ...]


# Union of all operations
APIOp = ListOp | GetOp | CreateOp | UpdateOp | DeleteOp

# Union of all modifiers
APIMod = FilterMod | OrderMod | PageMod | CursorMod | OffsetMod | SelectMod | SearchMod | IncludeMod


# ─── QuerySet ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class APIQuerySet(Generic[T]):
    """API query — REST-ish operations.

    Immutable. Each method returns new QuerySet.
    """

    entity: type[T]
    op: APIOp | None = None
    mods: tuple[APIMod, ...] = field(default_factory=tuple)

    def _with_op(self, op: APIOp) -> APIQuerySet[T]:
        return APIQuerySet(entity=self.entity, op=op, mods=self.mods)

    def _with_mod(self, mod: APIMod) -> APIQuerySet[T]:
        return APIQuerySet(entity=self.entity, op=self.op, mods=(*self.mods, mod))

    # ─── CRUD Operations ─────────────────────────────────────────────────

    def list(self) -> APIQuerySet[T]:
        """List resources.

        Usage:
            users.list().filter(lambda u: u.active).page(1)
        """
        return self._with_op(ListOp())

    def get(self, id: Any) -> APIQuerySet[T]:
        """Get single resource by ID.

        Usage:
            users.get("user-123")
        """
        return self._with_op(GetOp(id))

    def create(self, entity: T) -> APIQuerySet[T]:
        """Create resource.

        Usage:
            users.create(User(name="alice", ...))
        """
        return self._with_op(CreateOp(entity))

    def update(self, id: Any, entity: T, *, partial: bool = False) -> APIQuerySet[T]:
        """Update resource.

        Usage:
            users.update("user-123", updated_user)
            users.update("user-123", partial_user, partial=True)  # PATCH
        """
        return self._with_op(UpdateOp(id, entity, partial))

    def delete(self, id: Any) -> APIQuerySet[T]:
        """Delete resource.

        Usage:
            users.delete("user-123")
        """
        return self._with_op(DeleteOp(id))

    # ─── Modifiers (for list) ────────────────────────────────────────────

    def filter(self, predicate: Callable[[EntityProxy[T]], Expr]) -> APIQuerySet[T]:
        """Add filter.

        Usage:
            .filter(lambda u: u.active == True)
            .filter(lambda u: u.balance > 100)
        """
        expr = build_expr(self.entity, predicate)
        return self._with_mod(FilterMod(expr))

    def order_by(
        self, *order_fns: Callable[[EntityProxy[T]], FieldProxy | OrderSpec]
    ) -> APIQuerySet[T]:
        """Add ordering.

        Usage:
            .order_by(lambda u: u.name.asc())
            .order_by(lambda u: u.balance.desc())
        """
        specs = tuple(build_order(self.entity, fn) for fn in order_fns)
        return self._with_mod(OrderMod(specs))

    def page(self, page: int, per_page: int = 20) -> APIQuerySet[T]:
        """Page-based pagination.

        Usage:
            .page(1, per_page=50)
        """
        return self._with_mod(PageMod(page, per_page))

    def cursor(self, cursor: str, limit: int = 20) -> APIQuerySet[T]:
        """Cursor-based pagination.

        Usage:
            .cursor("eyJpZCI6MTIzfQ==", limit=50)
        """
        return self._with_mod(CursorMod(cursor, limit))

    def offset(self, offset: int, limit: int = 20) -> APIQuerySet[T]:
        """Offset-based pagination.

        Usage:
            .offset(100, limit=50)
        """
        return self._with_mod(OffsetMod(offset, limit))

    def select(self, *field_fns: Callable[[T], FieldProxy]) -> APIQuerySet[T]:
        """Select specific fields (sparse fieldsets).

        Usage:
            .select(lambda u: u.id, lambda u: u.name)
        """
        proxy = EntityProxy(self.entity)
        fields = tuple(fn(proxy).name for fn in field_fns)  # type: ignore
        return self._with_mod(SelectMod(fields))

    def search(self, query: str) -> APIQuerySet[T]:
        """Full-text search.

        Usage:
            .search("alice")
        """
        return self._with_mod(SearchMod(query))

    def include(self, *relations: str) -> APIQuerySet[T]:
        """Include related resources.

        Usage:
            .include("posts", "comments")
        """
        return self._with_mod(IncludeMod(relations))

    # ─── Introspection ───────────────────────────────────────────────────

    @property
    def filters(self) -> list[Expr]:
        """All filter expressions."""
        return [mod.expr for mod in self.mods if isinstance(mod, FilterMod)]

    @property
    def ordering(self) -> list[OrderSpec]:
        """All order specs."""
        result: list[OrderSpec] = []
        for mod in self.mods:
            if isinstance(mod, OrderMod):
                result.extend(mod.specs)
        return result

    @property
    def pagination(self) -> PageMod | CursorMod | OffsetMod | None:
        """Pagination modifier if set."""
        for mod in self.mods:
            if isinstance(mod, (PageMod, CursorMod, OffsetMod)):
                return mod
        return None


def api(entity: type[T]) -> APIQuerySet[T]:
    """Create API QuerySet for entity.

    Usage:
        users = api(User)
        q = users.list().filter(lambda u: u.active).page(1)
    """
    return APIQuerySet(entity=entity)


__all__ = (
    # Operations
    "ListOp",
    "GetOp",
    "CreateOp",
    "UpdateOp",
    "DeleteOp",
    "APIOp",
    # Modifiers
    "FilterMod",
    "OrderMod",
    "PageMod",
    "CursorMod",
    "OffsetMod",
    "SelectMod",
    "SearchMod",
    "IncludeMod",
    "APIMod",
    # QuerySet
    "APIQuerySet",
    "api",
)
