"""Query compilation contexts — abstract backend interfaces for self-compiling ops.

Symmetric with compile-axis contexts (PydanticContext, OpenAPIContext, etc.):
contexts carry backend-specific logic as closures, ops transform contexts
through compile_*_query / compile_*_api protocol methods.

    # Memory relational: ops use evaluate() + getattr directly
    ctx = MemoryQueryContext(data=list(entities))
    result = fold(query.ops, ctx, MemoryQueryCompilable, "compile_memory_query")

    # SA relational: context carries closures that close over the SA model
    ctx = SAQueryContext(stmt=select(model), get_column=..., compile_expr=...)
    result = fold(query.ops, ctx, SAQueryCompilable, "compile_sa_query")

    # Memory API: mods transform list via fold
    ctx = MemoryAPIContext(data=list(entities))
    result = fold(query.mods, ctx, MemoryAPICompilable, "compile_memory_api")

    # HTTP API: mods accumulate params/body via closures
    ctx = HTTPAPIContext(params={}, body=None, ...)
    fold(query.mods, ctx, HTTPAPICompilable, "compile_http_api")

All dispatch via fold() from _core.py — same two-level dispatch as compile axis:
  1. handler map (priority) — backend overrides any op
  2. protocol (fallback) — op compiles itself
  3. skip (open-world) — unknown ops silently ignored

QueryPhase[Ctx] — reified fold spec, analogous to CompilationPhase[Ctx].
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy import Select, ColumnElement
    from emergent.wire.axis.query._api import PageMod, CursorMod, OffsetMod
    from emergent.wire.axis.query._proxy import OrderSpec

    # Select is invariant in _TP; we don't know the entity row type,
    # so Any is unavoidable here — consistent with SA's own stubs.
    _Stmt = Select[Any]
    _Col = ColumnElement[object]
    _BoolCol = ColumnElement[bool]
    _PaginationMod = PageMod | CursorMod | OffsetMod

from dataclasses import dataclass, replace
from typing import Protocol, runtime_checkable

from emergent.wire.axis.query._expr import Expr
from emergent.wire.compile._core import ItemHandler
from emergent.wire.compile._core import fold as _core_fold


# ═══════════════════════════════════════════════════════════════════════════════
# Memory Query Context
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class MemoryQueryContext:
    """Memory query compilation context — just the accumulating list.

    Ops use self.expr.evaluate(item) and getattr(item, field) directly.
    No closures or backend-specific imports needed.

        ctx = MemoryQueryContext(data=list(entities))
        result_ctx = filter_op.compile_memory_query(ctx)
        items = result_ctx.data
    """

    data: list[object]


# ═══════════════════════════════════════════════════════════════════════════════
# SA Query Context
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class SAQueryContext:
    """SQLAlchemy query compilation context — carries SA-specific logic as closures.

    No sqlalchemy imports leak into query ops. The SA provider constructs
    this context at init time, closing over self._compiled.model.

    Symmetric with compile-axis PydanticContext, OpenAPIContext, etc.:
    the context IS the abstract interface to the backend.

        ctx = SAQueryContext(
            stmt=select(model),
            get_column=lambda name: getattr(model, name),
            compile_expr=lambda expr: compile_expr(expr, compiled),
            asc=lambda col: col.asc(),
            desc=lambda col: col.desc(),
            join=...,
            window_func=...,
        )
    """

    # The accumulating SQL statement (SA Select at runtime)
    stmt: _Stmt

    # Field name → SA column expression
    get_column: Callable[[str], _Col]

    # Expr AST → SA boolean expression (for WHERE, HAVING, JOIN ON)
    compile_expr: Callable[[Expr], _BoolCol]

    # Column ordering
    asc: Callable[[_Col], _Col]
    desc: Callable[[_Col], _Col]

    # Join: (stmt, target_type, on_expr, kind, tablename) → new_stmt
    join: Callable[[_Stmt, type, Expr, str, str | None], _Stmt]

    # Window: WindowSpec → labeled SA column expression
    window_func: Callable[[object], _Col]

    # Select projection: (field_names,) → new select stmt with only those columns
    select_columns: Callable[[_Stmt, Sequence[str]], _Stmt]


# ═══════════════════════════════════════════════════════════════════════════════
# Compilation Protocols
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class MemoryQueryCompilable(Protocol):
    """Protocol for ops that can compile themselves for memory backend.

    Symmetric with PydanticCompilable, OpenAPICompilable, etc.
    Built-in ops (Filter, OrderBy, Limit, ...) implement this natively.
    Custom ops implement this to work with memory providers automatically.
    """

    def compile_memory_query(self, ctx: MemoryQueryContext) -> MemoryQueryContext: ...


@runtime_checkable
class SAQueryCompilable(Protocol):
    """Protocol for ops that can compile themselves for SQLAlchemy backend.

    Built-in ops implement this using SAQueryContext closures (no SA imports).
    Custom ops implement this to work with SA providers automatically.
    Handler maps can override any op's SA compilation.
    """

    def compile_sa_query(self, ctx: SAQueryContext) -> SAQueryContext: ...


# ═══════════════════════════════════════════════════════════════════════════════
# Memory API Context
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class MemoryAPIContext:
    """Memory API mod compilation context — list + pagination metadata.

    APIMods (FilterMod, OrderMod, PageMod, etc.) transform data via fold.
    Pagination mods record total/has_more before slicing — single pass
    replaces the two-method (_apply_mods + _apply_pagination) approach.

        ctx = MemoryAPIContext(data=list(entities))
        result = fold(query.mods, ctx, MemoryAPICompilable, "compile_memory_api")
        items = result.data
        total = result.total
    """

    data: list[object]
    total: int | None = None
    has_more: bool = False


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP API Context
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class HTTPAPIContext:
    """HTTP API mod compilation context — mutable accumulator with closures.

    APIMods populate params/body via fold. Closures abstract away
    FilterEncoding and Pagination strategies — mods never import httpx
    or strategy types.

    Not frozen — mutable dicts accumulated during fold. Per-request,
    never shared. Safe pattern for HTTP param building.

        ctx = HTTPAPIContext(
            params={}, body=None,
            encode_filter=lambda expr: encoding.encode(expr, entity, profile),
            apply_pagination=lambda params, mod: pagination.apply(params, mod),
            is_body_filter=isinstance(encoding, BodyFilters),
        )
        fold(query.mods, ctx, HTTPAPICompilable, "compile_http_api")
        # use ctx.params, ctx.body for the HTTP request
    """

    params: dict[str, object]
    body: dict[str, object] | None

    # Expr → filter params dict (closure over FilterEncoding + entity + profile)
    encode_filter: Callable[[Expr], dict[str, object]]

    # (params_dict, pagination_mod) → mutates params (closure over Pagination)
    apply_pagination: Callable[[dict[str, object], _PaginationMod], None]

    # True when FilterEncoding produces body, not query params
    is_body_filter: bool

    # OrderSpec sequence → order params dict
    # Provider configures param names/format (e.g. "sort", "order_by", "-field" vs "field:desc")
    encode_order: Callable[[Sequence[OrderSpec]], dict[str, object]] | None = None

    # int → limit params dict
    # Provider configures param name (e.g. "limit", "per_page", "max_results")
    encode_limit: Callable[[int], dict[str, object]] | None = None

    # field names → select/fields params dict
    # Provider configures param name/format (e.g. "fields", "select", "columns")
    encode_select: Callable[[Sequence[str]], dict[str, object]] | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# API Compilation Protocols
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class MemoryAPICompilable(Protocol):
    """Protocol for API mods that can compile themselves for memory backend."""

    def compile_memory_api(self, ctx: MemoryAPIContext) -> MemoryAPIContext: ...


@runtime_checkable
class HTTPAPICompilable(Protocol):
    """Protocol for API mods that can compile themselves for HTTP backend."""

    def compile_http_api(self, ctx: HTTPAPIContext) -> HTTPAPIContext: ...


# ═══════════════════════════════════════════════════════════════════════════════
# Memory KV Context
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class MemoryKVContext:
    """Memory KV compilation context — mutable, carries dict store + raw result.

    Ops mutate store directly and set result for the provider to wrap in Result.
    Mutable because KV ops have side effects (set, delete).

        ctx = MemoryKVContext(store=self._data)
        MEMORY_KV.fold([query.op], ctx)
        value = ctx.result  # raw value; provider wraps in Ok()
    """

    store: dict[object, object]
    result: object = None


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP KV Context
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class HTTPKVContext:
    """HTTP KV compilation context — mutable accumulator with closures.

    Ops populate method/path/params/body via closures that abstract away
    the HTTP API format. Same pattern as HTTPAPIContext.

    Closures provided by the KV provider at construction time:
      - encode_key: key → URL path segment
      - encode_pattern: pattern → query params
      - encode_value: (value, ttl) → request body

        ctx = HTTPKVContext(
            encode_key=lambda k: f"/kv/{k}",
            encode_pattern=lambda p: {"pattern": p},
            encode_value=lambda v, ttl: {"value": v, "ttl": ttl},
        )
        HTTP_KV.fold([query.op], ctx)
        # use ctx.method, ctx.path, ctx.params, ctx.body
    """

    # Request spec — accumulated by ops
    method: str = "GET"
    path: str = ""
    params: dict[str, object] | None = None
    body: dict[str, object] | None = None

    # key → URL path segment (closure over serialization)
    encode_key: Callable[[object], str] = lambda k: str(k)

    # pattern → query params dict (closure over pattern format)
    encode_pattern: Callable[[str], dict[str, object]] = lambda p: {"pattern": p}

    # (value, ttl | None) → request body dict (closure over serialization)
    encode_value: Callable[[object, int | None], dict[str, object]] = (
        lambda v, ttl: {"value": v, **({"ttl": ttl} if ttl is not None else {})}
    )


# ═══════════════════════════════════════════════════════════════════════════════
# KV Compilation Protocols
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class MemoryKVCompilable(Protocol):
    """Protocol for KV ops that can compile themselves for memory backend."""

    def compile_memory_kv(self, ctx: MemoryKVContext) -> MemoryKVContext: ...


@runtime_checkable
class HTTPKVCompilable(Protocol):
    """Protocol for KV ops that can compile themselves for HTTP backend."""

    def compile_http_kv(self, ctx: HTTPKVContext) -> HTTPKVContext: ...


# ═══════════════════════════════════════════════════════════════════════════════
# Explain Context — self-description phase (open-world, symmetric with verify)
# ═══════════════════════════════════════════════════════════════════════════════


type ExplainValue = str | int | float | bool | None | tuple[str, ...] | list[str]


@dataclass(frozen=True, slots=True)
class ExplainEntry:
    """One self-described step: op name + ordered (name, value) pairs.

    Values are scalar-or-simple-sequence — typed, JSON-serializable.
    Kept as a closed union to avoid Any while covering every explain
    payload actually produced by query ops.
    """

    op: str
    fields: tuple[tuple[str, ExplainValue], ...] = ()


@dataclass(frozen=True, slots=True)
class ExplainContext:
    """Accumulates ExplainEntry during a fold pass."""

    entries: tuple[ExplainEntry, ...] = ()

    def add(self, entry: ExplainEntry) -> ExplainContext:
        return replace(self, entries=(*self.entries, entry))


@runtime_checkable
class ExplainCompilable(Protocol):
    """Protocol — op self-describes into an ExplainContext.

    Every op (Filter, OrderBy, Limit, ...) that wants to appear in
    explain output implements this. Open-world: unknown ops silently
    skipped by fold. No external registry, no dispatch table.
    """

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext: ...


class AutoPrintable:
    """Mixin — default compile_explain via dataclass field reflection.

    Inherit for free per-field stringification:

        @dataclass(frozen=True, slots=True)
        class Limit(AutoPrintable):
            count: int

        # compile_explain auto-produces ExplainEntry("Limit", (("count", "10"),))

    Override compile_explain for custom format (Filter expr rendering,
    aggregate spec formatting, etc.).
    """

    __slots__ = ()

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        import dataclasses as _dc
        if not _dc.is_dataclass(self) or isinstance(self, type):
            return ctx.add(ExplainEntry(op=type(self).__name__))
        pairs = tuple(
            (f.name, str(getattr(self, f.name)))
            for f in _dc.fields(self)
        )
        return ctx.add(ExplainEntry(op=type(self).__name__, fields=pairs))


# ═══════════════════════════════════════════════════════════════════════════════
# QueryPhase — reified fold spec (analogous to CompilationPhase)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class QueryPhase[Ctx]:
    """Query-level fold phase descriptor — reified fold spec.

    Symmetric with CompilationPhase[Ctx] from compile/_phase.py.
    Bundles protocol + method + optional handler overrides.

    Unlike CompilationPhase, no initial factory — query contexts vary
    too much (list for memory, Select for SA, dict pair for HTTP).
    Caller provides initial context directly.

        result = MEMORY_RELATIONAL.fold(query.ops, MemoryQueryContext(data=...))
        result = MEMORY_API.fold(query.mods, MemoryAPIContext(data=...))
    """

    protocol: type
    method: str
    handlers: Mapping[type, ItemHandler[Ctx]] | None = None

    def fold(self, ops: Iterable[Any], initial: Ctx) -> Ctx:
        """Run fold() with this phase's protocol and handlers."""
        return _core_fold(ops, initial, self.protocol, self.method, self.handlers)

    def with_handler(
        self, op_type: type, handler: ItemHandler[Ctx]
    ) -> QueryPhase[Ctx]:
        """Return new phase with added/replaced handler. Immutable."""
        merged = {**(self.handlers or {}), op_type: handler}
        return replace(self, handlers=merged)

    def without_handler(self, op_type: type) -> QueryPhase[Ctx]:
        """Return new phase without handler for given type. Immutable."""
        if self.handlers is None:
            return self
        filtered = {k: v for k, v in self.handlers.items() if k is not op_type}
        return replace(self, handlers=filtered if filtered else None)


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-built QueryPhase Constants
# ═══════════════════════════════════════════════════════════════════════════════


MEMORY_RELATIONAL: QueryPhase[MemoryQueryContext] = QueryPhase(
    protocol=MemoryQueryCompilable,
    method="compile_memory_query",
)

SA_RELATIONAL: QueryPhase[SAQueryContext] = QueryPhase(
    protocol=SAQueryCompilable,
    method="compile_sa_query",
)

MEMORY_API: QueryPhase[MemoryAPIContext] = QueryPhase(
    protocol=MemoryAPICompilable,
    method="compile_memory_api",
)

HTTP_API: QueryPhase[HTTPAPIContext] = QueryPhase(
    protocol=HTTPAPICompilable,
    method="compile_http_api",
)

MEMORY_KV: QueryPhase[MemoryKVContext] = QueryPhase(
    protocol=MemoryKVCompilable,
    method="compile_memory_kv",
)

HTTP_KV: QueryPhase[HTTPKVContext] = QueryPhase(
    protocol=HTTPKVCompilable,
    method="compile_http_kv",
)


EXPLAIN_QUERY: QueryPhase[ExplainContext] = QueryPhase(
    protocol=ExplainCompilable,
    method="compile_explain",
)


# ═══════════════════════════════════════════════════════════════════════════════
# QueryCompilation — multi-phase query compilation result
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class QueryCompilation:
    """Result of multi-phase query compilation.

    Typed access by QueryPhase constant:

        result = compiler.compile(ops, {MEMORY_RELATIONAL: ctx, HTTP_API: http_ctx})
        memory_ctx = result[MEMORY_RELATIONAL]  # MemoryQueryContext
        http_ctx = result[HTTP_API]              # HTTPAPIContext
    """

    _contexts: dict[type, object]

    def __getitem__[Ctx](self, phase: QueryPhase[Ctx]) -> Ctx:
        ctx = self._contexts.get(phase.protocol)
        if ctx is None:
            raise KeyError(f"No context for protocol {phase.protocol.__name__}")
        return ctx

    def get[Ctx](self, phase: QueryPhase[Ctx]) -> Ctx | None:
        """Get context for phase, or None if not compiled."""
        return self._contexts.get(phase.protocol)

    def __contains__(self, phase: QueryPhase[Any]) -> bool:
        return phase.protocol in self._contexts


# ═══════════════════════════════════════════════════════════════════════════════
# QueryCompiler — composable query compiler (free algebra on free algebras)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class QueryCompiler:
    """Composable query compiler — compile ops through multiple phases.

    Analogous to SchemaCompiler from compile/_phase.py.
    Bundles QueryPhases. The ops are a free algebra (Level 1).
    The phases are a free algebra (Level 2).
    The compiler IS the free algebra on free algebras.

    Algebraic operations (keyed by protocol type):
        compiler_a + compiler_b     # left-biased union (idempotent)
        compiler_a | compiler_b     # right-biased merge (override)
        compiler_a - compiler_b     # restriction (remove phases)
        compiler_a & compiler_b     # intersection
        phase in compiler           # membership by protocol
        compiler[protocol_type]     # lookup by protocol type

    Example::

        DEBUGGABLE_HTTP = HTTP_COMPILER + MEMORY_COMPILER
        result = DEBUGGABLE_HTTP.compile(
            query.ops,
            {MEMORY_RELATIONAL: MemoryQueryContext(data=...), HTTP_API: http_ctx},
        )
        memory_result = result[MEMORY_RELATIONAL]
        http_result = result[HTTP_API]
    """

    phases: tuple[QueryPhase[Any], ...]

    def compile(
        self,
        ops: Iterable[Any],
        initials: Mapping[type, Any],
    ) -> QueryCompilation:
        """Compile ops through ALL phases. Each phase folds independently.

        initials: mapping from protocol type → initial context.
        Ops are materialized once (as tuple) and reused across phases.
        """
        ops_tuple = tuple(ops)
        contexts: dict[type, Any] = {}
        for phase in self.phases:
            ctx = initials[phase.protocol]
            contexts[phase.protocol] = phase.fold(ops_tuple, ctx)
        return QueryCompilation(contexts)

    # ─── Phase management ─────────────────────────────────────────────

    def with_phase(self, phase: QueryPhase[Any]) -> QueryCompiler:
        """Add phase. Raises ValueError if protocol already present."""
        if any(p.protocol is phase.protocol for p in self.phases):
            raise ValueError(
                f"Protocol {phase.protocol.__name__} already present — "
                f"use | for override"
            )
        return replace(self, phases=(*self.phases, phase))

    def without_phase(self, phase: QueryPhase[Any] | type) -> QueryCompiler:
        """Remove by protocol type. Accepts phase or bare protocol type."""
        key = phase.protocol if isinstance(phase, QueryPhase) else phase
        return replace(self, phases=tuple(p for p in self.phases if p.protocol is not key))

    # ─── Algebraic operations (keyed by protocol) ─────────────────────

    def __add__(self, other: QueryCompiler | QueryPhase[Any]) -> QueryCompiler:
        """Left-biased union. Idempotent: A + A == A."""
        if isinstance(other, QueryPhase):
            other = QueryCompiler(phases=(other,))
        seen = {p.protocol for p in self.phases}
        extra = tuple(p for p in other.phases if p.protocol not in seen)
        return QueryCompiler(phases=(*self.phases, *extra))

    def __radd__(self, other: QueryPhase[Any]) -> QueryCompiler:
        return QueryCompiler(phases=(other,)) + self

    def __or__(self, other: QueryCompiler | QueryPhase[Any]) -> QueryCompiler:
        """Right-biased merge. Other's phases override self's by protocol."""
        if isinstance(other, QueryPhase):
            other = QueryCompiler(phases=(other,))
        override = {p.protocol: p for p in other.phases}
        self_keys = {p.protocol for p in self.phases}
        result = [override.get(p.protocol, p) for p in self.phases]
        for p in other.phases:
            if p.protocol not in self_keys:
                result.append(p)
        return QueryCompiler(phases=tuple(result))

    def __ror__(self, other: QueryPhase[Any]) -> QueryCompiler:
        return QueryCompiler(phases=(other,)) | self

    def __sub__(self, other: QueryCompiler | QueryPhase[Any] | type) -> QueryCompiler:
        """Restriction — remove by protocol type."""
        if isinstance(other, QueryCompiler):
            remove_keys: set[type] = {p.protocol for p in other.phases}
        elif isinstance(other, QueryPhase):
            remove_keys = {other.protocol}
        else:
            remove_keys = {other}
        return QueryCompiler(phases=tuple(p for p in self.phases if p.protocol not in remove_keys))

    def __and__(self, other: QueryCompiler) -> QueryCompiler:
        """Intersection by protocol. Self's versions retained."""
        other_keys = {p.protocol for p in other.phases}
        return QueryCompiler(phases=tuple(p for p in self.phases if p.protocol in other_keys))

    def __contains__(self, item: QueryPhase[Any] | type) -> bool:
        """Membership by protocol. Accepts QueryPhase or bare protocol type."""
        if isinstance(item, QueryPhase):
            return any(p.protocol is item.protocol for p in self.phases)
        return any(p.protocol is item for p in self.phases)

    def __len__(self) -> int:
        return len(self.phases)

    def __iter__(self):
        return iter(self.phases)

    def __bool__(self) -> bool:
        return len(self.phases) > 0

    def __getitem__(self, protocol: type) -> QueryPhase[Any]:
        """Lookup phase by protocol type. Raises KeyError if not found."""
        for p in self.phases:
            if p.protocol is protocol:
                return p
        raise KeyError(protocol)


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-built QueryCompiler Constants
# ═══════════════════════════════════════════════════════════════════════════════

MEMORY_RELATIONAL_COMPILER: QueryCompiler = QueryCompiler(phases=(MEMORY_RELATIONAL,))
SA_COMPILER: QueryCompiler = QueryCompiler(phases=(SA_RELATIONAL,))
MEMORY_API_COMPILER: QueryCompiler = QueryCompiler(phases=(MEMORY_API,))
HTTP_COMPILER: QueryCompiler = QueryCompiler(phases=(HTTP_API,))
MEMORY_KV_COMPILER: QueryCompiler = QueryCompiler(phases=(MEMORY_KV,))
HTTP_KV_COMPILER: QueryCompiler = QueryCompiler(phases=(HTTP_KV,))


__all__ = (
    # Relational contexts
    "MemoryQueryContext",
    "SAQueryContext",
    "_Stmt",
    # API contexts
    "MemoryAPIContext",
    "HTTPAPIContext",
    # KV contexts
    "MemoryKVContext",
    "HTTPKVContext",
    # Relational protocols
    "MemoryQueryCompilable",
    "SAQueryCompilable",
    # API protocols
    "MemoryAPICompilable",
    "HTTPAPICompilable",
    # KV protocols
    "MemoryKVCompilable",
    "HTTPKVCompilable",
    # QueryPhase
    "QueryPhase",
    # Pre-built phases
    "MEMORY_RELATIONAL",
    "SA_RELATIONAL",
    "MEMORY_API",
    "HTTP_API",
    "MEMORY_KV",
    "HTTP_KV",
    # QueryCompiler
    "QueryCompilation",
    "QueryCompiler",
    # Pre-built compilers
    "MEMORY_RELATIONAL_COMPILER",
    "SA_COMPILER",
    "MEMORY_API_COMPILER",
    "HTTP_COMPILER",
    "MEMORY_KV_COMPILER",
    "HTTP_KV_COMPILER",
)
