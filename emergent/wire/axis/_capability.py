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

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Mapping, Protocol, Sequence, runtime_checkable

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo


# ═══════════════════════════════════════════════════════════════════════════════
# ROOT Capability
# ═══════════════════════════════════════════════════════════════════════════════


class Capability:
    """Root for all axis capabilities."""
    pass


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


@dataclass(frozen=True, slots=True)
class SQLAlchemyContext:
    """SQLAlchemy compilation context — holds Column config."""
    field_name: str
    field_type: type
    column_type: type | None = None
    column_kwargs: Mapping[str, str | int | bool | None] = field(default_factory=_empty_column_kwargs)


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


@dataclass(frozen=True, slots=True)
class TelegrinderHandlerContext:
    """Telegrinder handler configuration context."""
    edit_message: bool = False
    answer_callback: bool = False
    answer_callback_text: str | None = None
    answer_callback_show_alert: bool = False
    silent: bool = False


@dataclass(frozen=True, slots=True)
class CLICommandContext:
    """CLI command configuration context."""
    name: str
    help: str | None = None
    description: str | None = None
    epilog: str | None = None


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


# ═══════════════════════════════════════════════════════════════════════════════
# Schema-Level Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def pydantic_model(
    ctx: PydanticModelContext,
    *,
    title: str | None = None,
    description: str | None = None,
    is_abstract: bool | None = None,
) -> PydanticModelContext:
    """Modify Pydantic model context."""
    return replace(
        ctx,
        title=title if title is not None else ctx.title,
        description=description if description is not None else ctx.description,
        is_abstract=is_abstract if is_abstract is not None else ctx.is_abstract,
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
) -> SQLAlchemyTableContext:
    """Modify SQLAlchemy table context."""
    return replace(
        ctx,
        table_name=table_name if table_name is not None else ctx.table_name,
        is_abstract=is_abstract if is_abstract is not None else ctx.is_abstract,
        constraints=(*ctx.constraints, add_constraint) if add_constraint else ctx.constraints,
        indexes=(*ctx.indexes, add_index) if add_index else ctx.indexes,
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
) -> FastAPIRouteContext:
    """Modify FastAPI route configuration."""
    return replace(
        ctx,
        tags=(*ctx.tags, *tags) if tags else ctx.tags,
        summary=summary if summary is not None else ctx.summary,
        description=description if description is not None else ctx.description,
        deprecated=deprecated if deprecated is not None else ctx.deprecated,
        operation_id=operation_id if operation_id is not None else ctx.operation_id,
        security=(*ctx.security, *security) if security else ctx.security,
    )


def telegrinder_handler(
    ctx: TelegrinderHandlerContext,
    *,
    edit_message: bool | None = None,
    answer_callback: bool | None = None,
    answer_callback_text: str | None = None,
    answer_callback_show_alert: bool | None = None,
    silent: bool | None = None,
) -> TelegrinderHandlerContext:
    """Modify Telegrinder handler configuration."""
    return replace(
        ctx,
        edit_message=edit_message if edit_message is not None else ctx.edit_message,
        answer_callback=answer_callback if answer_callback is not None else ctx.answer_callback,
        answer_callback_text=answer_callback_text if answer_callback_text is not None else ctx.answer_callback_text,
        answer_callback_show_alert=answer_callback_show_alert if answer_callback_show_alert is not None else ctx.answer_callback_show_alert,
        silent=silent if silent is not None else ctx.silent,
    )


def cli_command(
    ctx: CLICommandContext,
    *,
    help: str | None = None,
    description: str | None = None,
    epilog: str | None = None,
) -> CLICommandContext:
    """Modify CLI command configuration."""
    return replace(
        ctx,
        help=help if help is not None else ctx.help,
        description=description if description is not None else ctx.description,
        epilog=epilog if epilog is not None else ctx.epilog,
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
    # Surface axis application-level protocols
    "FastAPIAppCompilable",
    "TelegrinderBotCompilable",
    "CLIAppCompilable",
    # Combinators
    "combine",
)
