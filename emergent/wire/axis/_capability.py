"""Capability — ROOT type + compilation infrastructure for all axes.

    from emergent.wire.axis._capability import (
        # Root
        Capability,
        # Contexts
        PydanticContext, OpenAPIContext, ArgparseContext, SQLAlchemyContext,
        # Protocols
        PydanticCompilable, OpenAPICompilable, ArgparseCompilable, SQLAlchemyCompilable,
        # Helpers
        openapi_schema, argparse_arg, sqlalchemy_column,
        combine,
    )
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Generic, TYPE_CHECKING, Mapping, Protocol, Sequence, TypeVar, runtime_checkable

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo
    from sqlalchemy.sql.elements import ClauseElement


# ═══════════════════════════════════════════════════════════════════════════════
# Type Variables & Sentinels
# ═══════════════════════════════════════════════════════════════════════════════


CT = TypeVar('CT')  # Column type (SA type class)
FT = TypeVar('FT')  # Field type (Python type)


class _Unset:
    """Sentinel for fields without default values."""
    __slots__ = ()

    def __repr__(self) -> str:
        return "<UNSET>"


UNSET = _Unset()


# ═══════════════════════════════════════════════════════════════════════════════
# ROOT Capability
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class Capability(Protocol):
    """Root marker for all axis capabilities.

    All axis capabilities inherit from this Protocol:
        - schema.SchemaCapability
        - surface.SurfaceCapability
        - storage.StorageCapability
        - query.QueryCapability

    Protocol-based for structural typing and runtime checking.
    """
    ...


# ═══════════════════════════════════════════════════════════════════════════════
# JSON Schema Type (standard spec)
# ═══════════════════════════════════════════════════════════════════════════════


JsonSchemaValue = (
    str | int | float | bool | None
    | list["JsonSchemaValue"]
    | dict[str, "JsonSchemaValue"]
)
JsonSchemaDict = dict[str, JsonSchemaValue]

# Argparse accepts various types for kwargs (choices can be mixed types)
ArgparseKwargValue = (
    str | int | float | bool | None
    | Sequence[str] | Sequence[int] | Sequence[str | int | float | bool | None]
)


# ═══════════════════════════════════════════════════════════════════════════════
# Schema Axis Contexts (field-level)
# ═══════════════════════════════════════════════════════════════════════════════


def _empty_schema() -> JsonSchemaDict:
    return {}


def _empty_argparse_kwargs() -> dict[str, ArgparseKwargValue]:
    return {}


def _empty_column_kwargs() -> dict[str, str | int | bool | None]:
    return {}


@dataclass(frozen=True, slots=True)
class PydanticContext:
    """Pydantic compilation context — holds FieldInfo directly."""
    field_name: str
    field_type: type
    field_info: "FieldInfo"


@dataclass(frozen=True, slots=True)
class OpenAPIContext:
    """OpenAPI compilation context — holds JSON Schema dict."""
    field_name: str
    field_type: type
    schema: JsonSchemaDict = field(default_factory=_empty_schema)


@dataclass(frozen=True, slots=True)
class ArgparseContext:
    """Argparse compilation context — holds add_argument kwargs."""
    field_name: str
    field_type: type
    kwargs: Mapping[str, ArgparseKwargValue] = field(default_factory=_empty_argparse_kwargs)
    is_positional: bool = False
    arg_names: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class SQLAlchemyContext:
    """SQLAlchemy compilation context — holds Column config."""
    field_name: str
    field_type: type
    column_type: type | None = None
    column_kwargs: Mapping[str, str | int | bool | None] = field(default_factory=_empty_column_kwargs)


# ═══════════════════════════════════════════════════════════════════════════════
# Dialect-Specific Contexts (field-level)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class DeltaContext:
    """Delta dialect compilation context — accumulates delta field metadata."""
    field_name: str
    field_type: type
    delta_kind: str | None = None  # "numeric" | "string" | "collection"


@dataclass(frozen=True, slots=True)
class QuerySchemaContext:
    """Query dialect compilation context — accumulates query capabilities per field."""
    field_name: str
    field_type: type
    filterable: bool = False
    sortable: bool = False
    selectable: bool = False
    searchable: bool = False
    aggregatable: bool = False
    aggregate_functions: tuple[type, ...] = ()
    operators: tuple[type, ...] = ()
    json_queryable: bool = False
    array_queryable: bool = False
    full_text_indexed: bool = False
    fti_language: str = "english"


@dataclass(frozen=True, slots=True)
class ConstraintsContext:
    """Universal constraints compilation context — accumulates validation constraints per field."""
    field_name: str
    field_type: type
    min_length: int | None = None
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    exclusive_min: float | None = None
    exclusive_max: float | None = None
    multiple_of: float | None = None
    pattern: str | None = None
    choices: tuple[Any, ...] | None = None
    is_identity: bool = False
    is_unique: bool = False


# ═══════════════════════════════════════════════════════════════════════════════
# Schema-Level Spec Types (Generic)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ExtraColumnSpec(Generic[CT]):
    """Extra column specification for table-level context.

    CT — SQLAlchemy type class (Integer, DateTime, etc.).
    SA expressions (server_default, onupdate) typed via ClauseElement.

    Example::

        ExtraColumnSpec("version", Integer, nullable=False, default=1)
        ExtraColumnSpec("created_at", DateTime, server_default=func.now())
    """
    name: str
    column_type: type[CT]
    nullable: bool = True
    default: int | float | str | bool | None = None
    server_default: str | ClauseElement | None = None
    onupdate: str | ClauseElement | None = None


@dataclass(frozen=True, slots=True)
class ExtraFieldSpec(Generic[FT]):
    """Extra field specification for model-level context.

    FT — Python type of the field.

    Example::

        ExtraFieldSpec("version", int, 1)       # with default
        ExtraFieldSpec("name", str)              # no default (UNSET)
    """
    name: str
    field_type: type[FT]
    default: FT | _Unset = UNSET


# ═══════════════════════════════════════════════════════════════════════════════
# Schema Axis Contexts (schema-level)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class PydanticModelContext:
    """Pydantic model-level compilation context."""
    class_name: str
    title: str | None = None
    description: str | None = None
    is_abstract: bool = False
    extra_fields: tuple[ExtraFieldSpec[Any], ...] = ()


@dataclass(frozen=True, slots=True)
class OpenAPISchemaContext:
    """OpenAPI schema-level compilation context."""
    class_name: str
    schema: JsonSchemaDict = field(default_factory=_empty_schema)


@dataclass(frozen=True, slots=True)
class SQLAlchemyTableContext:
    """SQLAlchemy table-level compilation context."""
    class_name: str
    table_name: str | None = None
    is_abstract: bool = False
    constraints: tuple[tuple[str, ...], ...] = ()
    indexes: tuple[tuple[str, ...], ...] = ()
    extra_columns: tuple[ExtraColumnSpec[Any], ...] = ()


# ═══════════════════════════════════════════════════════════════════════════════
# Surface Axis Contexts
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FastAPIRouteContext:
    """FastAPI route configuration context."""
    path: str
    method: str
    tags: tuple[str, ...] = ()
    summary: str | None = None
    description: str | None = None
    deprecated: bool = False
    operation_id: str | None = None
    security: tuple[dict[str, list[str]], ...] = ()
    openapi_extra: dict[str, Any] | None = None
    status_code: int | None = None


@dataclass(frozen=True, slots=True)
class TelegrinderHandlerContext:
    """Telegrinder handler configuration context."""
    edit_message: bool = False
    answer_callback: bool = False
    answer_callback_text: str | None = None
    answer_callback_show_alert: bool = False
    silent: bool = False
    parse_mode: str | None = None
    link_preview_disabled: bool = False
    protect_content: bool = False


@dataclass(frozen=True, slots=True)
class CLICommandContext:
    """CLI command configuration context."""
    name: str
    help: str | None = None
    description: str | None = None
    epilog: str | None = None
    hidden: bool = False


# ═══════════════════════════════════════════════════════════════════════════════
# Request Build Context (compose.* dialect)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class RequestBuildContext:
    """Request field building context — describes HOW to resolve field value.

    Strategy fields are set by compose.* capabilities via compile_request_build().
    The compiler reads the folded context and executes the appropriate strategy.
    """
    field_name: str
    field_type: type
    compose_node: type | None = None
    compose_node_default: object | None = None
    compose_node_map: Callable[..., object] | None = None
    compose_optional_node: type | None = None
    compose_fallback_nodes: tuple[type, ...] | None = None
    compose_race_nodes: tuple[type, ...] | None = None
    compose_retrieve_type: type | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Telegrinder Input Context (tg.CommandArg)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TelegrinderInputContext:
    """Telegrinder command argument context.

    Set by tg.CommandArg via compile_telegrinder_input().
    The compiler reads the folded context and generates telegrinder Arguments.
    """
    field_name: str
    field_type: type
    is_command_arg: bool = False
    optional: bool = False
    greedy: bool = False


# ═══════════════════════════════════════════════════════════════════════════════
# Telegrinder Render Context (tg.Style, tg.Line, etc.)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TelegrinderRenderContext:
    """Telegrinder response rendering context.

    Set by tg.Style, tg.Line, tg.Skip, tg.Button, tg.Keyboard
    via compile_telegrinder_render(). The compiler reads the folded
    context and builds Telegram message formatting.
    """
    field_name: str
    field_type: type
    style: str | None = None
    style_language: str | None = None
    line_after: bool = True
    line_before: bool = False
    skip: bool = False
    button_callback: str | None = None
    button_url: str | None = None
    keyboard_columns: int | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Schema Axis Helpers (field-level)
# ═══════════════════════════════════════════════════════════════════════════════


def openapi_schema(ctx: OpenAPIContext, **kwargs: JsonSchemaValue) -> OpenAPIContext:
    """Add JSON Schema properties — direct dict merge."""
    merged: JsonSchemaDict = {**ctx.schema, **kwargs}
    return replace(ctx, schema=merged)


def argparse_arg(
    ctx: ArgparseContext,
    **kwargs: ArgparseKwargValue,
) -> ArgparseContext:
    """Add argparse kwargs — direct dict merge."""
    merged: dict[str, ArgparseKwargValue] = {**ctx.kwargs, **kwargs}
    return replace(ctx, kwargs=merged)


def sqlalchemy_column(ctx: SQLAlchemyContext, **kwargs: str | int | bool | None) -> SQLAlchemyContext:
    """Add Column kwargs — direct dict merge."""
    merged: dict[str, str | int | bool | None] = {**ctx.column_kwargs, **kwargs}
    return replace(ctx, column_kwargs=merged)


def pydantic_metadata(ctx: PydanticContext, *items: object) -> PydanticContext:
    """Append items to Pydantic FieldInfo.metadata — immutable context update."""
    fi = copy.deepcopy(ctx.field_info)
    fi.metadata.extend(items)
    return replace(ctx, field_info=fi)


def pydantic_extra(ctx: PydanticContext, **extra: object) -> PydanticContext:
    """Merge into Pydantic FieldInfo.json_schema_extra — immutable context update."""
    fi = copy.deepcopy(ctx.field_info)
    existing = dict(fi.json_schema_extra) if fi.json_schema_extra else {}
    existing.update(extra)
    fi.json_schema_extra = existing
    return replace(ctx, field_info=fi)


def pydantic_field(ctx: PydanticContext, mutate: Callable[["FieldInfo"], None]) -> PydanticContext:
    """Generic pydantic FieldInfo mutation — immutable context update."""
    fi = copy.deepcopy(ctx.field_info)
    mutate(fi)
    return replace(ctx, field_info=fi)


# ═══════════════════════════════════════════════════════════════════════════════
# Schema-Level Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def pydantic_model(
    ctx: PydanticModelContext,
    *,
    title: str | None = None,
    description: str | None = None,
    is_abstract: bool | None = None,
    add_field: ExtraFieldSpec[Any] | None = None,
) -> PydanticModelContext:
    """Modify Pydantic model context."""
    return replace(
        ctx,
        title=title if title is not None else ctx.title,
        description=description if description is not None else ctx.description,
        is_abstract=is_abstract if is_abstract is not None else ctx.is_abstract,
        extra_fields=(*ctx.extra_fields, add_field) if add_field else ctx.extra_fields,
    )


def openapi_schema_level(ctx: OpenAPISchemaContext, **kwargs: JsonSchemaValue) -> OpenAPISchemaContext:
    """Add schema-level JSON Schema properties."""
    merged: JsonSchemaDict = {**ctx.schema, **kwargs}
    return replace(ctx, schema=merged)


def sqlalchemy_table(
    ctx: SQLAlchemyTableContext,
    *,
    table_name: str | None = None,
    is_abstract: bool | None = None,
    add_constraint: tuple[str, ...] | None = None,
    add_index: tuple[str, ...] | None = None,
    add_column: ExtraColumnSpec[Any] | None = None,
) -> SQLAlchemyTableContext:
    """Modify SQLAlchemy table context."""
    return replace(
        ctx,
        table_name=table_name if table_name is not None else ctx.table_name,
        is_abstract=is_abstract if is_abstract is not None else ctx.is_abstract,
        constraints=(*ctx.constraints, add_constraint) if add_constraint else ctx.constraints,
        indexes=(*ctx.indexes, add_index) if add_index else ctx.indexes,
        extra_columns=(*ctx.extra_columns, add_column) if add_column else ctx.extra_columns,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Surface Axis Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def fastapi_route(
    ctx: FastAPIRouteContext,
    *,
    tags: tuple[str, ...] | None = None,
    summary: str | None = None,
    description: str | None = None,
    deprecated: bool | None = None,
    operation_id: str | None = None,
    security: tuple[dict[str, list[str]], ...] | None = None,
    status_code: int | None = None,
    openapi_extra: dict[str, Any] | None = None,
) -> FastAPIRouteContext:
    """Modify FastAPI route configuration."""
    merged_extra = ctx.openapi_extra
    if openapi_extra is not None:
        if merged_extra is None:
            merged_extra = dict(openapi_extra)
        else:
            merged_extra = {**merged_extra, **openapi_extra}

    return replace(
        ctx,
        tags=(*ctx.tags, *tags) if tags else ctx.tags,
        summary=summary if summary is not None else ctx.summary,
        description=description if description is not None else ctx.description,
        deprecated=deprecated if deprecated is not None else ctx.deprecated,
        operation_id=operation_id if operation_id is not None else ctx.operation_id,
        security=(*ctx.security, *security) if security else ctx.security,
        status_code=status_code if status_code is not None else ctx.status_code,
        openapi_extra=merged_extra,
    )


def telegrinder_handler(
    ctx: TelegrinderHandlerContext,
    *,
    edit_message: bool | None = None,
    answer_callback: bool | None = None,
    answer_callback_text: str | None = None,
    answer_callback_show_alert: bool | None = None,
    silent: bool | None = None,
    parse_mode: str | None = None,
    link_preview_disabled: bool | None = None,
    protect_content: bool | None = None,
) -> TelegrinderHandlerContext:
    """Modify Telegrinder handler configuration."""
    return replace(
        ctx,
        edit_message=edit_message if edit_message is not None else ctx.edit_message,
        answer_callback=answer_callback if answer_callback is not None else ctx.answer_callback,
        answer_callback_text=answer_callback_text if answer_callback_text is not None else ctx.answer_callback_text,
        answer_callback_show_alert=answer_callback_show_alert if answer_callback_show_alert is not None else ctx.answer_callback_show_alert,
        silent=silent if silent is not None else ctx.silent,
        parse_mode=parse_mode if parse_mode is not None else ctx.parse_mode,
        link_preview_disabled=link_preview_disabled if link_preview_disabled is not None else ctx.link_preview_disabled,
        protect_content=protect_content if protect_content is not None else ctx.protect_content,
    )


def cli_command(
    ctx: CLICommandContext,
    *,
    help: str | None = None,
    description: str | None = None,
    epilog: str | None = None,
    hidden: bool | None = None,
) -> CLICommandContext:
    """Modify CLI command configuration."""
    return replace(
        ctx,
        help=help if help is not None else ctx.help,
        description=description if description is not None else ctx.description,
        epilog=epilog if epilog is not None else ctx.epilog,
        hidden=hidden if hidden is not None else ctx.hidden,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Compilation Protocols (field-level)
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class PydanticCompilable(Protocol):
    """Capability that compiles to Pydantic FieldInfo."""

    def compile_pydantic(self, ctx: PydanticContext) -> PydanticContext:
        ...


@runtime_checkable
class OpenAPICompilable(Protocol):
    """Capability that compiles to OpenAPI schema."""

    def compile_openapi(self, ctx: OpenAPIContext) -> OpenAPIContext:
        ...


@runtime_checkable
class ArgparseCompilable(Protocol):
    """Capability that compiles to argparse configuration."""

    def compile_argparse(self, ctx: ArgparseContext) -> ArgparseContext:
        ...


@runtime_checkable
class SQLAlchemyCompilable(Protocol):
    """Capability that compiles to SQLAlchemy Column configuration."""

    def compile_sqlalchemy(self, ctx: SQLAlchemyContext) -> SQLAlchemyContext:
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Compilation Protocols (dialect-specific field-level)
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class DeltaCompilable(Protocol):
    """Capability that compiles to delta field metadata."""

    def compile_delta(self, ctx: DeltaContext) -> DeltaContext:
        ...


@runtime_checkable
class QuerySchemaCompilable(Protocol):
    """Capability that compiles to query schema metadata."""

    def compile_query_schema(self, ctx: QuerySchemaContext) -> QuerySchemaContext:
        ...


@runtime_checkable
class ConstraintsCompilable(Protocol):
    """Capability that compiles to universal validation constraints."""

    def compile_constraints(self, ctx: ConstraintsContext) -> ConstraintsContext:
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Compilation Protocols (schema-level)
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class PydanticModelCompilable(Protocol):
    """Capability that compiles to Pydantic model configuration."""

    def compile_pydantic_model(self, ctx: PydanticModelContext) -> PydanticModelContext:
        ...


@runtime_checkable
class OpenAPISchemaCompilable(Protocol):
    """Capability that compiles to OpenAPI schema-level configuration."""

    def compile_openapi_schema(self, ctx: OpenAPISchemaContext) -> OpenAPISchemaContext:
        ...


@runtime_checkable
class SQLAlchemyTableCompilable(Protocol):
    """Capability that compiles to SQLAlchemy table configuration."""

    def compile_sqlalchemy_table(self, ctx: SQLAlchemyTableContext) -> SQLAlchemyTableContext:
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Surface Axis Compilation Protocols
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class FastAPICompilable(Protocol):
    """Capability that compiles to FastAPI route configuration."""

    def compile_fastapi(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext:
        ...


@runtime_checkable
class TelegrinderCompilable(Protocol):
    """Capability that compiles to Telegrinder handler configuration."""

    def compile_telegrinder(self, ctx: TelegrinderHandlerContext) -> TelegrinderHandlerContext:
        ...


@runtime_checkable
class CLICompilable(Protocol):
    """Capability that compiles to CLI command configuration."""

    def compile_cli(self, ctx: CLICommandContext) -> CLICommandContext:
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Request Build Protocol (compose.* dialect)
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class RequestBuildCompilable(Protocol):
    """Capability that compiles to request field building strategy."""

    def compile_request_build(self, ctx: RequestBuildContext) -> RequestBuildContext:
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Telegrinder Input Protocol (tg.CommandArg)
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class TelegrinderInputCompilable(Protocol):
    """Capability that compiles to telegrinder command argument config."""

    def compile_telegrinder_input(self, ctx: TelegrinderInputContext) -> TelegrinderInputContext:
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Telegrinder Render Protocol (tg.Style, tg.Line, etc.)
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class TelegrinderRenderCompilable(Protocol):
    """Capability that compiles to telegrinder response rendering config."""

    def compile_telegrinder_render(self, ctx: TelegrinderRenderContext) -> TelegrinderRenderContext:
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Application-Level Contexts (global middleware, app config)
# ═══════════════════════════════════════════════════════════════════════════════


def _empty_middleware() -> tuple[tuple[type, Mapping[str, object]], ...]:
    return ()


@dataclass(frozen=True, slots=True)
class FastAPIAppContext:
    """FastAPI application-level configuration.

    Used by FastAPIAppCompilable capabilities to configure
    application-wide middleware. CORS is just middleware too.

    Example::

        @dataclass(frozen=True, slots=True)
        class CORS(SurfaceCapability):
            origins: tuple[str, ...]

            def compile_fastapi_app(self, ctx: FastAPIAppContext) -> FastAPIAppContext:
                from starlette.middleware.cors import CORSMiddleware
                return fastapi_app_middleware(
                    ctx,
                    CORSMiddleware,
                    allow_origins=list(self.origins),
                )
    """

    middleware: tuple[tuple[type, Mapping[str, object]], ...] = field(
        default_factory=_empty_middleware
    )


@dataclass(frozen=True, slots=True)
class TelegrinderBotContext:
    """Telegrinder bot-level configuration."""

    error_handler: object | None = None
    parse_mode: str | None = None


@dataclass(frozen=True, slots=True)
class CLIAppContext:
    """CLI application-level configuration."""

    prog: str | None = None
    description: str | None = None
    epilog: str | None = None


@dataclass(frozen=True, slots=True)
class HandlerRuntimeContext:
    """Pre-folded handler runtime context — enrichers + response transforms."""
    enrichers: tuple[Any, ...] = ()
    response_transforms: tuple[Any, ...] = ()


# ═══════════════════════════════════════════════════════════════════════════════
# Application-Level Compilation Protocols
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class FastAPIAppCompilable(Protocol):
    """Capability that compiles to FastAPI application configuration.

    Used for global middleware, CORS, etc.

    Example::

        @dataclass(frozen=True, slots=True)
        class CORS(SurfaceCapability):
            origins: tuple[str, ...]

            def compile_fastapi_app(self, ctx: FastAPIAppContext) -> FastAPIAppContext:
                return replace(ctx, cors=CORSSpec(allow_origins=self.origins))
    """

    def compile_fastapi_app(self, ctx: FastAPIAppContext) -> FastAPIAppContext:
        ...


@runtime_checkable
class TelegrinderBotCompilable(Protocol):
    """Capability that compiles to Telegrinder bot configuration."""

    def compile_telegrinder_bot(self, ctx: TelegrinderBotContext) -> TelegrinderBotContext:
        ...


@runtime_checkable
class CLIAppCompilable(Protocol):
    """Capability that compiles to CLI application configuration."""

    def compile_cli_app(self, ctx: CLIAppContext) -> CLIAppContext:
        ...


@runtime_checkable
class HandlerRuntimeCompilable(Protocol):
    """Capability that contributes to handler runtime context (enrichers, transforms)."""

    def compile_handler_runtime(self, ctx: HandlerRuntimeContext) -> HandlerRuntimeContext:
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Application-Level Context Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def fastapi_app_middleware(
    ctx: FastAPIAppContext,
    middleware_cls: type,
    **kwargs: object,
) -> FastAPIAppContext:
    """Add middleware to FastAPI app context.

    Example::

        # CORS is just middleware
        ctx = fastapi_app_middleware(
            ctx,
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["GET", "POST"],
        )
    """
    return replace(
        ctx,
        middleware=(*ctx.middleware, (middleware_cls, kwargs)),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Combinator
# ═══════════════════════════════════════════════════════════════════════════════


def combine(*caps: Capability) -> tuple[Capability, ...]:
    """Combine capabilities into tuple for Annotated.

    Purely syntactic sugar — Annotated already accepts multiple args.
    """
    return caps


__all__ = (
    # Root
    "Capability",
    # Type variables & sentinels
    "CT",
    "FT",
    "_Unset",
    "UNSET",
    # Spec types (generic)
    "ExtraColumnSpec",
    "ExtraFieldSpec",
    # JSON Schema types
    "JsonSchemaValue",
    "JsonSchemaDict",
    # Argparse types
    "ArgparseKwargValue",
    # Schema axis field-level contexts
    "PydanticContext",
    "OpenAPIContext",
    "ArgparseContext",
    "SQLAlchemyContext",
    # Schema axis field-level helpers
    "openapi_schema",
    "argparse_arg",
    "sqlalchemy_column",
    "pydantic_metadata",
    "pydantic_extra",
    "pydantic_field",
    # Schema axis schema-level contexts
    "PydanticModelContext",
    "OpenAPISchemaContext",
    "SQLAlchemyTableContext",
    # Schema axis schema-level helpers
    "pydantic_model",
    "openapi_schema_level",
    "sqlalchemy_table",
    # Surface axis route-level contexts
    "FastAPIRouteContext",
    "TelegrinderHandlerContext",
    "CLICommandContext",
    # Request build context
    "RequestBuildContext",
    # Telegrinder input/render contexts
    "TelegrinderInputContext",
    "TelegrinderRenderContext",
    # Surface axis route-level helpers
    "fastapi_route",
    "telegrinder_handler",
    "cli_command",
    # Surface axis application-level contexts
    "FastAPIAppContext",
    "TelegrinderBotContext",
    "CLIAppContext",
    # Surface axis application-level helpers
    "fastapi_app_middleware",
    # Dialect-specific field-level contexts
    "DeltaContext",
    "QuerySchemaContext",
    "ConstraintsContext",
    # Dialect-specific field-level protocols
    "DeltaCompilable",
    "QuerySchemaCompilable",
    "ConstraintsCompilable",
    # Schema axis field-level protocols
    "PydanticCompilable",
    "OpenAPICompilable",
    "ArgparseCompilable",
    "SQLAlchemyCompilable",
    # Schema axis schema-level protocols
    "PydanticModelCompilable",
    "OpenAPISchemaCompilable",
    "SQLAlchemyTableCompilable",
    # Surface axis route-level protocols
    "FastAPICompilable",
    "TelegrinderCompilable",
    "CLICompilable",
    # Request build protocol
    "RequestBuildCompilable",
    # Telegrinder input/render protocols
    "TelegrinderInputCompilable",
    "TelegrinderRenderCompilable",
    # Surface axis application-level protocols
    "FastAPIAppCompilable",
    "TelegrinderBotCompilable",
    "CLIAppCompilable",
    # Handler runtime
    "HandlerRuntimeContext",
    "HandlerRuntimeCompilable",
    # Combinators
    "combine",
)
