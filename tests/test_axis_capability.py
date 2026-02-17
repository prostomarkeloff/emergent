"""Tests for emergent.wire.axis._capability helper functions."""

from pydantic.fields import FieldInfo as PydanticFieldInfo

from emergent.wire.axis._capability import (
    # Contexts — field-level
    OpenAPIContext,
    ArgparseContext,
    SQLAlchemyContext,
    PydanticContext,
    # Contexts — schema-level
    PydanticModelContext,
    OpenAPISchemaContext,
    SQLAlchemyTableContext,
    # Contexts — surface
    FastAPIRouteContext,
    TelegrinderHandlerContext,
    CLICommandContext,
    # Contexts — app-level
    FastAPIAppContext,
    # Spec types
    ExtraFieldSpec,
    ExtraColumnSpec,
    # Field-level helpers
    openapi_schema,
    argparse_arg,
    sqlalchemy_column,
    pydantic_metadata,
    pydantic_extra,
    pydantic_field,
    # Schema-level helpers
    pydantic_model,
    openapi_schema_level,
    sqlalchemy_table,
    # Surface helpers
    fastapi_route,
    telegrinder_handler,
    cli_command,
    # App-level helpers
    fastapi_app_middleware,
    # Combinator
    combine,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_pydantic_ctx(
    field_name: str = "x",
    field_type: type = int,
) -> PydanticContext:
    fi = PydanticFieldInfo.from_annotation(field_type)
    return PydanticContext(
        field_name=field_name,
        field_type=field_type,
        field_info=fi,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# openapi_schema
# ═══════════════════════════════════════════════════════════════════════════════


class TestOpenAPISchema:
    def test_fresh_ctx_adds_properties(self) -> None:
        ctx = OpenAPIContext(field_name="name", field_type=str)
        result = openapi_schema(ctx, description="A name", minLength=1)
        assert result.schema == {"description": "A name", "minLength": 1}
        assert result.field_name == "name"
        assert result.field_type is str

    def test_pre_populated_ctx_merges(self) -> None:
        ctx = OpenAPIContext(
            field_name="name",
            field_type=str,
            schema={"description": "old", "minLength": 1},
        )
        result = openapi_schema(ctx, description="new", maxLength=255)
        assert result.schema["description"] == "new"
        assert result.schema["minLength"] == 1
        assert result.schema["maxLength"] == 255

    def test_original_ctx_is_unchanged(self) -> None:
        ctx = OpenAPIContext(field_name="x", field_type=int, schema={"minimum": 0})
        openapi_schema(ctx, maximum=100)
        assert "maximum" not in ctx.schema


# ═══════════════════════════════════════════════════════════════════════════════
# argparse_arg
# ═══════════════════════════════════════════════════════════════════════════════


class TestArgparseArg:
    def test_fresh_ctx_adds_kwargs(self) -> None:
        ctx = ArgparseContext(field_name="count", field_type=int)
        result = argparse_arg(ctx, help="Number of items", default=1)
        assert result.kwargs["help"] == "Number of items"
        assert result.kwargs["default"] == 1

    def test_pre_populated_ctx_merges(self) -> None:
        ctx = ArgparseContext(
            field_name="count",
            field_type=int,
            kwargs={"help": "old help", "default": 0},
        )
        result = argparse_arg(ctx, help="new help", metavar="N")
        assert result.kwargs["help"] == "new help"
        assert result.kwargs["default"] == 0
        assert result.kwargs["metavar"] == "N"

    def test_original_ctx_is_unchanged(self) -> None:
        ctx = ArgparseContext(field_name="x", field_type=str, kwargs={"help": "old"})
        argparse_arg(ctx, help="new")
        assert ctx.kwargs["help"] == "old"


# ═══════════════════════════════════════════════════════════════════════════════
# sqlalchemy_column
# ═══════════════════════════════════════════════════════════════════════════════


class TestSQLAlchemyColumn:
    def test_fresh_ctx_adds_kwargs(self) -> None:
        ctx = SQLAlchemyContext(field_name="email", field_type=str)
        result = sqlalchemy_column(ctx, nullable=False, index=True)
        assert result.column_kwargs["nullable"] is False
        assert result.column_kwargs["index"] is True

    def test_pre_populated_ctx_merges(self) -> None:
        ctx = SQLAlchemyContext(
            field_name="email",
            field_type=str,
            column_kwargs={"nullable": True, "index": False},
        )
        result = sqlalchemy_column(ctx, nullable=False, unique=True)
        assert result.column_kwargs["nullable"] is False
        assert result.column_kwargs["index"] is False
        assert result.column_kwargs["unique"] is True

    def test_original_ctx_is_unchanged(self) -> None:
        ctx = SQLAlchemyContext(
            field_name="x", field_type=int, column_kwargs={"nullable": True}
        )
        sqlalchemy_column(ctx, nullable=False)
        assert ctx.column_kwargs["nullable"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# pydantic_metadata
# ═══════════════════════════════════════════════════════════════════════════════


class TestPydanticMetadata:
    def test_adds_items_to_empty_metadata(self) -> None:
        ctx = _make_pydantic_ctx()
        sentinel = object()
        result = pydantic_metadata(ctx, sentinel)
        assert sentinel in result.field_info.metadata

    def test_appends_multiple_items(self) -> None:
        ctx = _make_pydantic_ctx()
        a = object()
        b = object()
        result = pydantic_metadata(ctx, a, b)
        assert a in result.field_info.metadata
        assert b in result.field_info.metadata

    def test_original_field_info_not_mutated(self) -> None:
        ctx = _make_pydantic_ctx()
        original_meta_len = len(ctx.field_info.metadata)
        pydantic_metadata(ctx, object())
        assert len(ctx.field_info.metadata) == original_meta_len


# ═══════════════════════════════════════════════════════════════════════════════
# pydantic_extra
# ═══════════════════════════════════════════════════════════════════════════════


class TestPydanticExtra:
    def test_fresh_json_schema_extra(self) -> None:
        ctx = _make_pydantic_ctx()
        result = pydantic_extra(ctx, x_internal=True)
        extra: dict[str, str | int | float | bool | None] = result.field_info.json_schema_extra  # pyright: ignore[reportAssignmentType] - pydantic stubs expose dict[Unknown, Unknown] in the union, no way to narrow it without assignment
        assert isinstance(extra, dict)
        assert extra["x_internal"] is True

    def test_merges_into_existing_extra(self) -> None:
        ctx = _make_pydantic_ctx()
        ctx_with_extra = pydantic_extra(ctx, existing_key="old")
        result = pydantic_extra(ctx_with_extra, new_key="new")
        extra = result.field_info.json_schema_extra
        assert isinstance(extra, dict)
        assert extra["existing_key"] == "old"
        assert extra["new_key"] == "new"

    def test_original_field_info_not_mutated(self) -> None:
        ctx = _make_pydantic_ctx()
        pydantic_extra(ctx, key="value")
        assert ctx.field_info.json_schema_extra is None


# ═══════════════════════════════════════════════════════════════════════════════
# pydantic_field
# ═══════════════════════════════════════════════════════════════════════════════


class TestPydanticField:
    def test_generic_mutation_applied(self) -> None:
        ctx = _make_pydantic_ctx()

        def set_title(fi: PydanticFieldInfo) -> None:
            fi.title = "My Field"

        result = pydantic_field(ctx, set_title)
        assert result.field_info.title == "My Field"

    def test_original_field_info_not_mutated(self) -> None:
        ctx = _make_pydantic_ctx()

        def set_title(fi: PydanticFieldInfo) -> None:
            fi.title = "Mutated"

        pydantic_field(ctx, set_title)
        assert ctx.field_info.title is None


# ═══════════════════════════════════════════════════════════════════════════════
# pydantic_model
# ═══════════════════════════════════════════════════════════════════════════════


class TestPydanticModel:
    def test_set_title(self) -> None:
        ctx = PydanticModelContext(class_name="User")
        result = pydantic_model(ctx, title="User Model")
        assert result.title == "User Model"

    def test_set_description(self) -> None:
        ctx = PydanticModelContext(class_name="User")
        result = pydantic_model(ctx, description="A user")
        assert result.description == "A user"

    def test_set_is_abstract(self) -> None:
        ctx = PydanticModelContext(class_name="Base")
        result = pydantic_model(ctx, is_abstract=True)
        assert result.is_abstract is True

    def test_add_field_appends(self) -> None:
        ctx = PydanticModelContext(class_name="User")
        spec: ExtraFieldSpec[int] = ExtraFieldSpec(name="version", field_type=int, default=1)
        result = pydantic_model(ctx, add_field=spec)
        assert len(result.extra_fields) == 1
        assert result.extra_fields[0].name == "version"

    def test_no_args_preserves_ctx(self) -> None:
        ctx = PydanticModelContext(class_name="User", title="Old Title", is_abstract=False)
        result = pydantic_model(ctx)
        assert result.title == "Old Title"
        assert result.is_abstract is False


# ═══════════════════════════════════════════════════════════════════════════════
# openapi_schema_level
# ═══════════════════════════════════════════════════════════════════════════════


class TestOpenAPISchemaLevel:
    def test_fresh_ctx_adds_properties(self) -> None:
        ctx = OpenAPISchemaContext(class_name="User")
        result = openapi_schema_level(ctx, title="User", description="A user schema")
        assert result.schema == {"title": "User", "description": "A user schema"}

    def test_merges_with_existing(self) -> None:
        ctx = OpenAPISchemaContext(
            class_name="User", schema={"title": "Old", "x_custom": True}
        )
        result = openapi_schema_level(ctx, title="New", extra_prop="value")
        assert result.schema["title"] == "New"
        assert result.schema["x_custom"] is True
        assert result.schema["extra_prop"] == "value"


# ═══════════════════════════════════════════════════════════════════════════════
# sqlalchemy_table
# ═══════════════════════════════════════════════════════════════════════════════


class TestSQLAlchemyTable:
    def test_set_table_name(self) -> None:
        ctx = SQLAlchemyTableContext(class_name="User")
        result = sqlalchemy_table(ctx, table_name="users")
        assert result.table_name == "users"

    def test_set_is_abstract(self) -> None:
        ctx = SQLAlchemyTableContext(class_name="Base")
        result = sqlalchemy_table(ctx, is_abstract=True)
        assert result.is_abstract is True

    def test_add_constraint_appends(self) -> None:
        ctx = SQLAlchemyTableContext(class_name="User")
        result = sqlalchemy_table(ctx, add_constraint=("email", "user_id"))
        assert len(result.constraints) == 1
        assert result.constraints[0] == ("email", "user_id")

    def test_add_index_appends(self) -> None:
        ctx = SQLAlchemyTableContext(class_name="User")
        result = sqlalchemy_table(ctx, add_index=("created_at",))
        assert len(result.indexes) == 1

    def test_add_column_appends(self) -> None:
        ctx = SQLAlchemyTableContext(class_name="User")
        spec: ExtraColumnSpec[int] = ExtraColumnSpec(name="version", column_type=int)
        result = sqlalchemy_table(ctx, add_column=spec)
        assert len(result.extra_columns) == 1
        assert result.extra_columns[0].name == "version"

    def test_no_args_preserves_ctx(self) -> None:
        ctx = SQLAlchemyTableContext(class_name="User", table_name="users", is_abstract=False)
        result = sqlalchemy_table(ctx)
        assert result.table_name == "users"
        assert result.is_abstract is False


# ═══════════════════════════════════════════════════════════════════════════════
# fastapi_route
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastAPIRoute:
    def test_tags_append(self) -> None:
        ctx = FastAPIRouteContext(path="/users", method="GET", tags=("users",))
        result = fastapi_route(ctx, tags=("admin",))
        assert "users" in result.tags
        assert "admin" in result.tags

    def test_security_append(self) -> None:
        ctx = FastAPIRouteContext(path="/users", method="GET")
        scheme: dict[str, list[str]] = {"oauth2": ["read"]}
        result = fastapi_route(ctx, security=(scheme,))
        assert len(result.security) == 1
        assert result.security[0] == scheme

    def test_openapi_extra_fresh(self) -> None:
        ctx = FastAPIRouteContext(path="/users", method="GET")
        result = fastapi_route(ctx, openapi_extra={"x-custom": "value"})
        assert result.openapi_extra is not None
        assert result.openapi_extra["x-custom"] == "value"

    def test_openapi_extra_merges_existing(self) -> None:
        ctx = FastAPIRouteContext(
            path="/users",
            method="GET",
            openapi_extra={"x-old": "old"},
        )
        result = fastapi_route(ctx, openapi_extra={"x-new": "new"})
        assert result.openapi_extra is not None
        assert result.openapi_extra["x-old"] == "old"
        assert result.openapi_extra["x-new"] == "new"

    def test_summary_description_status_code(self) -> None:
        ctx = FastAPIRouteContext(path="/items", method="POST")
        result = fastapi_route(
            ctx, summary="Create item", description="Creates a new item", status_code=201
        )
        assert result.summary == "Create item"
        assert result.description == "Creates a new item"
        assert result.status_code == 201


# ═══════════════════════════════════════════════════════════════════════════════
# telegrinder_handler
# ═══════════════════════════════════════════════════════════════════════════════


class TestTelegrinderHandler:
    def test_all_fields(self) -> None:
        ctx = TelegrinderHandlerContext()
        result = telegrinder_handler(
            ctx,
            edit_message=True,
            answer_callback=True,
            answer_callback_text="Done!",
            answer_callback_show_alert=True,
            silent=True,
            parse_mode="HTML",
            link_preview_disabled=True,
            protect_content=True,
        )
        assert result.edit_message is True
        assert result.answer_callback is True
        assert result.answer_callback_text == "Done!"
        assert result.answer_callback_show_alert is True
        assert result.silent is True
        assert result.parse_mode == "HTML"
        assert result.link_preview_disabled is True
        assert result.protect_content is True

    def test_no_args_preserves_defaults(self) -> None:
        ctx = TelegrinderHandlerContext()
        result = telegrinder_handler(ctx)
        assert result.edit_message is False
        assert result.answer_callback is False
        assert result.parse_mode is None


# ═══════════════════════════════════════════════════════════════════════════════
# cli_command
# ═══════════════════════════════════════════════════════════════════════════════


class TestCLICommand:
    def test_all_fields(self) -> None:
        ctx = CLICommandContext(name="run")
        result = cli_command(
            ctx,
            help="Run the task",
            description="A detailed description",
            epilog="See docs for more info",
            hidden=True,
        )
        assert result.help == "Run the task"
        assert result.description == "A detailed description"
        assert result.epilog == "See docs for more info"
        assert result.hidden is True

    def test_no_args_preserves_defaults(self) -> None:
        ctx = CLICommandContext(name="build", help="Build it", hidden=False)
        result = cli_command(ctx)
        assert result.help == "Build it"
        assert result.hidden is False

    def test_name_is_preserved(self) -> None:
        ctx = CLICommandContext(name="deploy")
        result = cli_command(ctx, help="Deploy the app")
        assert result.name == "deploy"


# ═══════════════════════════════════════════════════════════════════════════════
# fastapi_app_middleware
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastAPIAppMiddleware:
    def test_appends_middleware(self) -> None:
        ctx = FastAPIAppContext()

        class DummyMiddleware:
            pass

        result = fastapi_app_middleware(ctx, DummyMiddleware, some_option=True)
        assert len(result.middleware) == 1
        cls, kwargs = result.middleware[0]
        assert cls is DummyMiddleware
        assert kwargs["some_option"] is True

    def test_appends_multiple_middleware(self) -> None:
        ctx = FastAPIAppContext()

        class MiddlewareA:
            pass

        class MiddlewareB:
            pass

        ctx_a = fastapi_app_middleware(ctx, MiddlewareA)
        ctx_b = fastapi_app_middleware(ctx_a, MiddlewareB, key="val")
        assert len(ctx_b.middleware) == 2
        assert ctx_b.middleware[0][0] is MiddlewareA
        assert ctx_b.middleware[1][0] is MiddlewareB

    def test_original_ctx_is_unchanged(self) -> None:
        ctx = FastAPIAppContext()

        class M:
            pass

        fastapi_app_middleware(ctx, M)
        assert len(ctx.middleware) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# combine
# ═══════════════════════════════════════════════════════════════════════════════


class TestCombine:
    def test_returns_tuple_of_capabilities(self) -> None:
        class CapA:
            ...

        class CapB:
            ...

        a = CapA()
        b = CapB()
        result = combine(a, b)  # type: ignore[arg-type]
        assert isinstance(result, tuple)
        assert result == (a, b)

    def test_empty_combine(self) -> None:
        result = combine()
        assert result == ()

    def test_single_capability(self) -> None:
        class CapA:
            ...

        a = CapA()
        result = combine(a)  # type: ignore[arg-type]
        assert result == (a,)
