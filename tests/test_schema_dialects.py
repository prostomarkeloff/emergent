"""Tests for emergent.wire.axis.schema.dialects — all dialect capabilities."""

import dataclasses
from dataclasses import dataclass, FrozenInstanceError
from typing import Annotated, Callable

import pytest

from emergent.wire.axis._capability import (
    ArgparseContext,
    OpenAPIContext,
    SQLAlchemyContext,
    SQLAlchemyTableContext,
    PydanticModelContext,
    ExtraColumnSpec,
    ExtraFieldSpec,
)


# ═══════════════════════════════════════════════════════════════════════════════
# SQL Dialect
# ═══════════════════════════════════════════════════════════════════════════════


class TestSQLDialect:
    def test_index(self):
        from emergent.wire.axis.schema.dialects.sql import Index

        cap = Index("idx_email")
        ctx = SQLAlchemyContext(field_name="email", field_type=str)
        result = cap.compile_sqlalchemy(ctx)
        assert result.column_kwargs["index"] is True

    def test_index_unique(self):
        from emergent.wire.axis.schema.dialects.sql import Index

        cap = Index("idx_email", unique=True)
        ctx = SQLAlchemyContext(field_name="email", field_type=str)
        result = cap.compile_sqlalchemy(ctx)
        assert result.column_kwargs["unique"] is True

    def test_type_override(self):
        from emergent.wire.axis.schema.dialects.sql import Type

        cap = Type("TEXT")
        ctx = SQLAlchemyContext(field_name="bio", field_type=str)
        result = cap.compile_sqlalchemy(ctx)
        assert result.column_type == "TEXT"

    def test_server_default(self):
        from emergent.wire.axis.schema.dialects.sql import ServerDefault

        cap = ServerDefault("CURRENT_TIMESTAMP")
        ctx = SQLAlchemyContext(field_name="created_at", field_type=str)
        result = cap.compile_sqlalchemy(ctx)
        assert result.column_kwargs["server_default"] == "CURRENT_TIMESTAMP"

    def test_on_update(self):
        from emergent.wire.axis.schema.dialects.sql import OnUpdate

        cap = OnUpdate("CURRENT_TIMESTAMP")
        ctx = SQLAlchemyContext(field_name="updated_at", field_type=str)
        result = cap.compile_sqlalchemy(ctx)
        assert result.column_kwargs["onupdate"] == "CURRENT_TIMESTAMP"

    def test_check(self):
        from emergent.wire.axis.schema.dialects.sql import Check

        cap = Check("age >= 0", name="ck_age")
        assert cap.expression == "age >= 0"
        assert cap.name == "ck_age"

    def test_primary_key(self):
        from emergent.wire.axis.schema.dialects.sql import PrimaryKey

        cap = PrimaryKey(autoincrement=True)
        ctx = SQLAlchemyContext(field_name="id", field_type=int)
        result = cap.compile_sqlalchemy(ctx)
        assert result.column_kwargs["primary_key"] is True
        assert result.column_kwargs["autoincrement"] is True

    def test_foreign_key(self):
        from emergent.wire.axis.schema.dialects.sql import ForeignKey

        cap = ForeignKey("teams.id", ondelete="SET NULL")
        ctx = SQLAlchemyContext(field_name="team_id", field_type=int)
        result = cap.compile_sqlalchemy(ctx)
        assert result.column_kwargs["fk_target"] == "teams.id"
        assert result.column_kwargs["fk_ondelete"] == "SET NULL"

    def test_table_name_compile(self):
        from emergent.wire.axis.schema.dialects.sql import TableName

        cap = TableName("user_accounts")
        ctx = SQLAlchemyTableContext(class_name="User")
        result = cap.compile_sqlalchemy_table(ctx)
        assert result.table_name == "user_accounts"

    def test_composite_defined_in_sql(self):
        """CompositeUnique/CompositeIndex are now defined in sql dialect as SQLCapability."""
        from emergent.wire.axis.schema.dialects.sql import (
            CompositeUnique,
            CompositeIndex,
            SQLCapability,
        )

        assert issubclass(CompositeUnique, SQLCapability)
        assert issubclass(CompositeIndex, SQLCapability)

    def test_fulltext_marker(self):
        from emergent.wire.axis.schema.dialects.sql import FullText

        ft = FullText()
        assert isinstance(ft, FullText)  # just a marker

    def test_hierarchy(self):
        from emergent.wire.axis.schema.dialects.sql import SQLCapability, Index
        from emergent.wire.axis.schema._universal import SchemaAxisCapability

        assert issubclass(SQLCapability, SchemaAxisCapability)
        assert issubclass(Index, SQLCapability)


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic Dialect
# ═══════════════════════════════════════════════════════════════════════════════


class TestPydanticDialect:
    def test_strict(self):
        from emergent.wire.axis.schema.dialects.pydantic import Strict
        from pydantic.fields import FieldInfo as PydFieldInfo

        cap = Strict()
        from emergent.wire.axis._capability import PydanticContext

        fi = PydFieldInfo(annotation=str)
        ctx = PydanticContext(field_name="email", field_type=str, field_info=fi)
        result = cap.compile_pydantic(ctx)
        assert len(result.field_info.metadata) > 0

    def test_coerce(self):
        from emergent.wire.axis.schema.dialects.pydantic import Coerce
        from pydantic.fields import FieldInfo as PydFieldInfo

        cap = Coerce()
        from emergent.wire.axis._capability import PydanticContext

        fi = PydFieldInfo(annotation=int)
        ctx = PydanticContext(field_name="count", field_type=int, field_info=fi)
        result = cap.compile_pydantic(ctx)
        assert len(result.field_info.metadata) > 0

    def test_alias_path(self):
        from emergent.wire.axis.schema.dialects.pydantic import AliasPath

        cap = AliasPath("data", "user", 0)
        assert cap.path == ("data", "user", 0)

    def test_exclude(self):
        from emergent.wire.axis.schema.dialects.pydantic import Exclude
        from pydantic.fields import FieldInfo as PydFieldInfo
        from emergent.wire.axis._capability import PydanticContext

        cap = Exclude()
        fi = PydFieldInfo(annotation=str)
        ctx = PydanticContext(field_name="internal", field_type=str, field_info=fi)
        result = cap.compile_pydantic(ctx)
        assert result.field_info.exclude is True

    def test_include(self):
        from emergent.wire.axis.schema.dialects.pydantic import Include
        from pydantic.fields import FieldInfo as PydFieldInfo
        from emergent.wire.axis._capability import PydanticContext

        cap = Include()
        fi = PydFieldInfo(annotation=str)
        ctx = PydanticContext(field_name="public", field_type=str, field_info=fi)
        result = cap.compile_pydantic(ctx)
        assert result.field_info.exclude is False

    def test_no_alias_class(self):
        """pydantic.Alias was removed (universal Alias covers it)."""
        from emergent.wire.axis.schema.dialects import pydantic as pyd

        assert not hasattr(pyd, "Alias")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI Dialect
# ═══════════════════════════════════════════════════════════════════════════════


class TestCLIDialect:
    def test_help(self):
        from emergent.wire.axis.schema.dialects.cli import Help

        cap = Help("Username")
        ctx = ArgparseContext(field_name="login", field_type=str)
        result = cap.compile_argparse(ctx)
        assert result.kwargs["help"] == "Username"

    def test_metavar(self):
        from emergent.wire.axis.schema.dialects.cli import Metavar

        cap = Metavar("FILE")
        ctx = ArgparseContext(field_name="file", field_type=str)
        result = cap.compile_argparse(ctx)
        assert result.kwargs["metavar"] == "FILE"

    def test_flag(self):
        from emergent.wire.axis.schema.dialects.cli import Flag

        cap = Flag("--verbose", "-v")
        assert cap.names == ("--verbose", "-v")
        ctx = ArgparseContext(field_name="verbose", field_type=bool)
        result = cap.compile_argparse(ctx)
        assert result.arg_names == ("--verbose", "-v")

    def test_positional(self):
        from emergent.wire.axis.schema.dialects.cli import Positional

        cap = Positional()
        ctx = ArgparseContext(field_name="file", field_type=str)
        result = cap.compile_argparse(ctx)
        assert result.is_positional is True

    def test_positional_with_name(self):
        from emergent.wire.axis.schema.dialects.cli import Positional

        cap = Positional("input_file")
        ctx = ArgparseContext(field_name="file", field_type=str)
        result = cap.compile_argparse(ctx)
        assert result.is_positional is True
        assert result.field_name == "input_file"

    def test_choices(self):
        from emergent.wire.axis.schema.dialects.cli import Choices

        cap = Choices("json", "yaml", "text")
        assert cap.values == ("json", "yaml", "text")
        ctx = ArgparseContext(field_name="format", field_type=str)
        result = cap.compile_argparse(ctx)
        assert result.kwargs["choices"] == ["json", "yaml", "text"]

    def test_nargs(self):
        from emergent.wire.axis.schema.dialects.cli import Nargs

        cap = Nargs("+")
        ctx = ArgparseContext(field_name="files", field_type=list)
        result = cap.compile_argparse(ctx)
        assert result.kwargs["nargs"] == "+"

    def test_action(self):
        from emergent.wire.axis.schema.dialects.cli import Action

        cap = Action("count")
        ctx = ArgparseContext(field_name="verbose", field_type=int)
        result = cap.compile_argparse(ctx)
        assert result.kwargs["action"] == "count"

    def test_append(self):
        from emergent.wire.axis.schema.dialects.cli import Append

        cap = Append()
        ctx = ArgparseContext(field_name="include", field_type=list)
        result = cap.compile_argparse(ctx)
        assert result.kwargs["action"] == "append"

    def test_count(self):
        from emergent.wire.axis.schema.dialects.cli import Count

        cap = Count()
        ctx = ArgparseContext(field_name="verbose", field_type=int)
        result = cap.compile_argparse(ctx)
        assert result.kwargs["action"] == "count"
        assert result.kwargs["default"] == 0

    def test_required(self):
        from emergent.wire.axis.schema.dialects.cli import Required

        cap = Required()
        ctx = ArgparseContext(field_name="config", field_type=str)
        result = cap.compile_argparse(ctx)
        assert result.kwargs["required"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# API Dialect
# ═══════════════════════════════════════════════════════════════════════════════


class TestAPIDialect:
    def test_profile_config_immutable(self):
        from emergent.wire.axis.schema.dialects.api import profile, ProfileConfig

        class InternalAPI:
            pass

        p = profile(InternalAPI)
        assert isinstance(p, ProfileConfig)
        assert p.profile is InternalAPI

    def test_profile_chain(self):
        from emergent.wire.axis.schema.dialects.api import profile

        class API:
            pass

        p = (
            profile(API)
            .path_param()
        )
        assert p.is_path_param is True

    def test_profile_query_param(self):
        from emergent.wire.axis.schema.dialects.api import profile

        class API:
            pass

        p = profile(API).query_param("uid")
        assert p.query_param_name == "uid"

    def test_profile_filterable_sortable(self):
        from emergent.wire.axis.schema.dialects.api import profile

        class API:
            pass

        p = profile(API).with_filterable(("eq", "in")).with_sortable()
        assert p.filterable is True
        assert p.sortable is True
        assert p.operators == ("eq", "in")

    def test_profile_selectable_searchable(self):
        from emergent.wire.axis.schema.dialects.api import profile

        class API:
            pass

        p = profile(API).with_selectable().with_searchable()
        assert p.selectable is True
        assert p.searchable is True

    def test_get_profile_config(self):
        from emergent.wire.axis.schema.dialects.api import (
            profile,
            get_profile_config,
        )

        class A:
            pass

        class B:
            pass

        pa = profile(A).path_param()
        pb = profile(B).query_param("uid")
        configs = (pa, pb)

        assert get_profile_config(configs, A) is pa
        assert get_profile_config(configs, B) is pb
        assert get_profile_config(configs, int) is None  # type: ignore[arg-type]

    def test_get_any_config(self):
        from emergent.wire.axis.schema.dialects.api import profile, get_any_config

        class API:
            pass

        p = profile(API).path_param()
        result = get_any_config((p,))
        assert result is p

    def test_profile_agnostic_types(self):
        from emergent.wire.axis.schema.dialects.api import (
            PathParam,
            QueryParam,
            Filterable,
            Sortable,
            Selectable,
            Searchable,
        )

        assert PathParam() is not None
        assert QueryParam(name="q") is not None
        assert Filterable(operators=("eq",)) is not None
        assert Sortable() is not None
        assert Selectable() is not None
        assert Searchable() is not None

    def test_response_shape(self):
        from emergent.wire.axis.schema.dialects.api import (
            ResponseData,
            ResponseTotal,
            ResponseCursor,
        )

        rd = ResponseData(path="data.users")
        assert rd.path == "data.users"
        assert rd.profile is None

        rt = ResponseTotal(path="meta.total")
        assert rt.path == "meta.total"

        rc = ResponseCursor(path="meta.cursor")
        assert rc.path == "meta.cursor"

    def test_build_noop(self):
        from emergent.wire.axis.schema.dialects.api import profile

        class API:
            pass

        p = profile(API).path_param().build()
        assert p.is_path_param is True


# ═══════════════════════════════════════════════════════════════════════════════
# OpenAPI Dialect
# ═══════════════════════════════════════════════════════════════════════════════


class TestOpenAPIDialect:
    def test_format(self):
        from emergent.wire.axis.schema.dialects.openapi import Format

        cap = Format("email")
        ctx = OpenAPIContext(field_name="email", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["format"] == "email"

    def test_content_media_type(self):
        from emergent.wire.axis.schema.dialects.openapi import ContentMediaType

        cap = ContentMediaType("image/png")
        ctx = OpenAPIContext(field_name="data", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["contentMediaType"] == "image/png"

    def test_content_encoding(self):
        from emergent.wire.axis.schema.dialects.openapi import ContentEncoding

        cap = ContentEncoding("base64")
        ctx = OpenAPIContext(field_name="data", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["contentEncoding"] == "base64"

    def test_title(self):
        from emergent.wire.axis.schema.dialects.openapi import Title

        cap = Title("User Email")
        ctx = OpenAPIContext(field_name="email", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["title"] == "User Email"

    def test_description(self):
        from emergent.wire.axis.schema.dialects.openapi import Description

        cap = Description("The user's email")
        ctx = OpenAPIContext(field_name="email", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["description"] == "The user's email"

    def test_examples(self):
        from emergent.wire.axis.schema.dialects.openapi import Examples

        cap = Examples("alice@example.com", "bob@example.com")
        assert cap.values == ("alice@example.com", "bob@example.com")
        ctx = OpenAPIContext(field_name="email", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["examples"] == ["alice@example.com", "bob@example.com"]

    def test_default(self):
        from emergent.wire.axis.schema.dialects.openapi import Default

        cap = Default("draft")
        ctx = OpenAPIContext(field_name="status", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["default"] == "draft"


# ═══════════════════════════════════════════════════════════════════════════════
# Telegram Dialect
# ═══════════════════════════════════════════════════════════════════════════════


class TestTelegramDialect:
    def test_style(self):
        from emergent.wire.axis.schema.dialects.tg import Style

        s = Style("bold")
        assert s.value == "bold"
        assert s.language is None

    def test_shortcuts(self):
        from emergent.wire.axis.schema.dialects.tg import (
            Bold,
            Italic,
            Code,
            Pre,
            Strike,
            Spoiler,
        )

        assert Bold().value == "bold"
        assert Italic().value == "italic"
        assert Code().value == "code"
        assert Pre().value == "pre"
        assert Pre("python").language == "python"
        assert Strike().value == "strike"
        assert Spoiler().value == "spoiler"

    def test_line(self):
        from emergent.wire.axis.schema.dialects.tg import Line

        l = Line()
        assert l.after is True
        assert l.before is False

        l2 = Line(after=False, before=True)
        assert l2.after is False
        assert l2.before is True

    def test_skip(self):
        from emergent.wire.axis.schema.dialects.tg import Skip
        from emergent.wire.axis._capability import TelegrinderRenderContext

        cap = Skip()
        ctx = TelegrinderRenderContext(field_name="internal", field_type=str)
        result = cap.compile_telegrinder_render(ctx)
        assert result.skip is True

    def test_command_arg(self):
        from emergent.wire.axis.schema.dialects.tg import CommandArg

        ca = CommandArg()
        assert ca.optional is False
        assert ca.greedy is False

        ca2 = CommandArg(optional=True, greedy=True)
        assert ca2.optional is True
        assert ca2.greedy is True

    def test_button(self):
        from emergent.wire.axis.schema.dialects.tg import Button

        b = Button(callback="do:action")
        assert b.callback == "do:action"
        assert b.url is None

    def test_keyboard(self):
        from emergent.wire.axis.schema.dialects.tg import Keyboard

        k = Keyboard(columns=2)
        assert k.columns == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Compose Dialect
# ═══════════════════════════════════════════════════════════════════════════════


class TestComposeDialect:
    def test_node(self):
        from emergent.wire.axis.schema.dialects.compose import Node

        class ChatId:
            pass

        n = Node(node_type=ChatId)
        assert n.node_type is ChatId
        assert n.default is None
        assert n.map is None

    def test_optional(self):
        from emergent.wire.axis.schema.dialects.compose import Optional

        class AdminNode:
            pass

        o = Optional(node_type=AdminNode)
        assert o.node_type is AdminNode

    def test_fallback(self):
        from emergent.wire.axis.schema.dialects.compose import Fallback

        class A:
            pass

        class B:
            pass

        f = Fallback(A, B)
        assert f.node_types == (A, B)

    def test_race(self):
        from emergent.wire.axis.schema.dialects.compose import Race

        class A:
            pass

        class B:
            pass

        r = Race(A, B)
        assert r.node_types == (A, B)

    def test_retrieve(self):
        from emergent.wire.axis.schema.dialects.compose import Retrieve

        class AuthUser:
            pass

        r = Retrieve(from_type=AuthUser)
        assert r.from_type is AuthUser


# ═══════════════════════════════════════════════════════════════════════════════
# Query Dialect
# ═══════════════════════════════════════════════════════════════════════════════


class TestQueryDialect:
    def test_filterable(self):
        from emergent.wire.axis.schema.dialects.query import Filterable

        f = Filterable()
        assert isinstance(f, Filterable)

    def test_sortable(self):
        from emergent.wire.axis.schema.dialects.query import Sortable

        s = Sortable()
        assert isinstance(s, Sortable)

    def test_selectable(self):
        from emergent.wire.axis.schema.dialects.query import Selectable

        s = Selectable()
        assert isinstance(s, Selectable)

    def test_searchable(self):
        from emergent.wire.axis.schema.dialects.query import Searchable

        s = Searchable()
        assert isinstance(s, Searchable)

    def test_operators(self):
        from emergent.wire.axis.schema.dialects.query import Operators

        o = Operators(int, str)
        assert o.allowed == (int, str)

    def test_json_queryable(self):
        from emergent.wire.axis.schema.dialects.query import JsonQueryable, QueryCapability

        cap = JsonQueryable()
        assert isinstance(cap, QueryCapability)
        assert cap == JsonQueryable()  # frozen, equal by value

    def test_array_queryable(self):
        from emergent.wire.axis.schema.dialects.query import ArrayQueryable, QueryCapability

        cap = ArrayQueryable()
        assert isinstance(cap, QueryCapability)
        assert cap == ArrayQueryable()  # frozen, equal by value

    def test_full_text_indexed(self):
        from emergent.wire.axis.schema.dialects.query import FullTextIndexed

        ft = FullTextIndexed()
        assert ft.language == "english"

        ft2 = FullTextIndexed(language="russian")
        assert ft2.language == "russian"

    def test_filterable_compile_openapi(self):
        from emergent.wire.axis.schema.dialects.query import Filterable

        f = Filterable()
        ctx = OpenAPIContext(field_name="email", field_type=str)
        result = f.compile_openapi(ctx)
        assert result.schema["x-filterable"] is True

    def test_sortable_compile_openapi(self):
        from emergent.wire.axis.schema.dialects.query import Sortable

        s = Sortable()
        ctx = OpenAPIContext(field_name="date", field_type=str)
        result = s.compile_openapi(ctx)
        assert result.schema["x-sortable"] is True

    def test_operators_compile_openapi(self):
        from emergent.wire.axis.schema.dialects.query import Operators

        o = Operators(int, str)
        ctx = OpenAPIContext(field_name="status", field_type=str)
        result = o.compile_openapi(ctx)
        assert result.schema["x-operators"] == ["int", "str"]

    def test_fold_query_schema(self):
        from emergent.wire.axis.schema.dialects.query import (
            Filterable, Sortable, fold_query_schema,
        )
        from emergent.wire.axis.schema._inspect import FieldInfo

        info = FieldInfo(
            name="email", base_type=str,
            capabilities=(Filterable(), Sortable()),
            is_optional=False,
        )
        ctx = fold_query_schema(info)
        assert ctx.filterable is True
        assert ctx.sortable is True
        assert ctx.searchable is False


# ═══════════════════════════════════════════════════════════════════════════════
# Temporal Dialect
# ═══════════════════════════════════════════════════════════════════════════════


class TestTemporalDialect:
    def test_versioned_sqlalchemy(self):
        from emergent.wire.axis.schema.dialects.temporal import Versioned

        v = Versioned()
        ctx = SQLAlchemyTableContext(class_name="User")
        result = v.compile_sqlalchemy_table(ctx)
        assert len(result.extra_columns) == 1
        col = result.extra_columns[0]
        assert col.name == "version"
        assert col.nullable is False

    def test_versioned_pydantic(self):
        from emergent.wire.axis.schema.dialects.temporal import Versioned

        v = Versioned()
        ctx = PydanticModelContext(class_name="User")
        result = v.compile_pydantic_model(ctx)
        assert len(result.extra_fields) == 1
        f = result.extra_fields[0]
        assert f.name == "version"
        assert f.default == 1

    def test_versioned_custom_field(self):
        from emergent.wire.axis.schema.dialects.temporal import Versioned

        v = Versioned(version_field="ver", start_version=0)
        ctx = SQLAlchemyTableContext(class_name="User")
        result = v.compile_sqlalchemy_table(ctx)
        assert result.extra_columns[0].name == "ver"
        assert result.extra_columns[0].default == 0

    def test_valid_from(self):
        from emergent.wire.axis.schema.dialects.temporal import ValidFrom

        vf = ValidFrom()
        ctx = SQLAlchemyTableContext(class_name="User")
        result = vf.compile_sqlalchemy_table(ctx)
        assert len(result.extra_columns) == 1
        assert result.extra_columns[0].name == "valid_from"

    def test_valid_to(self):
        from emergent.wire.axis.schema.dialects.temporal import ValidTo

        vt = ValidTo()
        ctx = SQLAlchemyTableContext(class_name="User")
        result = vt.compile_sqlalchemy_table(ctx)
        assert len(result.extra_columns) == 1
        assert result.extra_columns[0].name == "valid_to"

    def test_temporal(self):
        from emergent.wire.axis.schema.dialects.temporal import Temporal

        t = Temporal()
        ctx = SQLAlchemyTableContext(class_name="User")
        result = t.compile_sqlalchemy_table(ctx)
        assert len(result.extra_columns) == 2
        names = {c.name for c in result.extra_columns}
        assert names == {"valid_from", "valid_to"}

    def test_created_at(self):
        from emergent.wire.axis.schema.dialects.temporal import CreatedAt

        ca = CreatedAt()
        ctx = SQLAlchemyTableContext(class_name="User")
        result = ca.compile_sqlalchemy_table(ctx)
        assert len(result.extra_columns) == 1
        assert result.extra_columns[0].name == "created_at"
        assert result.extra_columns[0].nullable is False

    def test_updated_at(self):
        from emergent.wire.axis.schema.dialects.temporal import UpdatedAt

        ua = UpdatedAt()
        ctx = SQLAlchemyTableContext(class_name="User")
        result = ua.compile_sqlalchemy_table(ctx)
        col = result.extra_columns[0]
        assert col.name == "updated_at"
        assert col.onupdate is not None

    def test_timestamps(self):
        from emergent.wire.axis.schema.dialects.temporal import Timestamps

        ts = Timestamps()
        ctx = SQLAlchemyTableContext(class_name="User")
        result = ts.compile_sqlalchemy_table(ctx)
        assert len(result.extra_columns) == 2
        names = {c.name for c in result.extra_columns}
        assert names == {"created_at", "updated_at"}

    def test_soft_delete(self):
        from emergent.wire.axis.schema.dialects.temporal import SoftDelete

        sd = SoftDelete()
        ctx = SQLAlchemyTableContext(class_name="User")
        result = sd.compile_sqlalchemy_table(ctx)
        assert len(result.extra_columns) == 1
        assert result.extra_columns[0].name == "deleted_at"

    def test_temporal_filter_current(self):
        from emergent.wire.axis.schema.dialects.temporal import temporal_filter_current

        expr = temporal_filter_current()
        assert expr is not None

    def test_temporal_filter_as_of(self):
        from datetime import datetime
        from emergent.wire.axis.schema.dialects.temporal import temporal_filter_as_of

        expr = temporal_filter_as_of(datetime(2024, 1, 1))
        assert expr is not None

    def test_temporal_filter_version(self):
        from emergent.wire.axis.schema.dialects.temporal import temporal_filter_version

        expr = temporal_filter_version(2)
        assert expr is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Delta Dialect
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeltaDialect:
    def test_delta_field(self):
        from emergent.wire.axis.schema.dialects.delta import DeltaField

        df = DeltaField("numeric")
        assert df.delta_type == "numeric"

    def test_numeric_delta_add(self):
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta(add=100)
        assert d.apply(50) == 150

    def test_numeric_delta_set(self):
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta(set=0)
        assert d.apply(999) == 0

    def test_numeric_delta_multiply(self):
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta(multiply=2.0)
        assert d.apply(50) == 100

    def test_numeric_delta_preserves_int(self):
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta(add=10)
        result = d.apply(5)
        assert isinstance(result, int)
        assert result == 15

    def test_string_delta_append(self):
        from emergent.wire.axis.schema.dialects.delta import StringDelta

        d = StringDelta(append=" (updated)")
        assert d.apply("hello") == "hello (updated)"

    def test_string_delta_prepend(self):
        from emergent.wire.axis.schema.dialects.delta import StringDelta

        d = StringDelta(prepend="[URGENT] ")
        assert d.apply("msg") == "[URGENT] msg"

    def test_string_delta_replace(self):
        from emergent.wire.axis.schema.dialects.delta import StringDelta

        d = StringDelta(replace=("old", "new"))
        assert d.apply("old value") == "new value"

    def test_string_delta_set(self):
        from emergent.wire.axis.schema.dialects.delta import StringDelta

        d = StringDelta(set="replaced")
        assert d.apply("anything") == "replaced"

    def test_collection_delta_push(self):
        from emergent.wire.axis.schema.dialects.delta import CollectionDelta

        d = CollectionDelta(push=("new",))
        assert d.apply(["a", "b"]) == ["a", "b", "new"]

    def test_collection_delta_pop(self):
        from emergent.wire.axis.schema.dialects.delta import CollectionDelta

        d = CollectionDelta(pop=1)
        assert d.apply(["a", "b", "c"]) == ["a", "b"]

    def test_collection_delta_remove(self):
        from emergent.wire.axis.schema.dialects.delta import CollectionDelta

        d = CollectionDelta(remove=("b",))
        assert d.apply(["a", "b", "c"]) == ["a", "c"]

    def test_collection_delta_insert(self):
        from emergent.wire.axis.schema.dialects.delta import CollectionDelta

        d = CollectionDelta(insert=(0, "first"))
        assert d.apply(["a", "b"]) == ["first", "a", "b"]

    def test_collection_delta_set(self):
        from emergent.wire.axis.schema.dialects.delta import CollectionDelta

        d = CollectionDelta(set=("x", "y"))
        assert d.apply(["a", "b", "c"]) == ["x", "y"]

    def test_delta_type_generation(self):
        from emergent.wire.axis.schema.dialects.delta import (
            DeltaField,
            NumericDelta,
            delta_type,
        )

        @dataclass
        class Account:
            id: int
            balance: Annotated[int, DeltaField("numeric")]

        AccountDelta = delta_type(Account)
        d = AccountDelta(balance=NumericDelta(add=100))
        assert d.balance.add == 100

    def test_apply_delta(self):
        from emergent.wire.axis.schema.dialects.delta import (
            DeltaField,
            NumericDelta,
            CollectionDelta,
            delta_type,
            apply_delta,
        )

        @dataclass
        class Account:
            id: int
            balance: Annotated[int, DeltaField("numeric")]
            tags: Annotated[list[str], DeltaField("collection")]

        AccountDelta = delta_type(Account)
        account = Account(id=1, balance=100, tags=["basic"])
        delta = AccountDelta(
            balance=NumericDelta(add=50),
            tags=CollectionDelta(push=("premium",)),
        )
        new_account = apply_delta(account, delta)
        assert new_account.balance == 150
        assert new_account.tags == ["basic", "premium"]
        assert account.balance == 100  # original unchanged

    def test_compose_deltas(self):
        from emergent.wire.axis.schema.dialects.delta import (
            DeltaField,
            NumericDelta,
            delta_type,
            compose_deltas,
        )

        @dataclass
        class Account:
            id: int
            balance: Annotated[int, DeltaField("numeric")]

        AccountDelta = delta_type(Account)
        d1 = AccountDelta(balance=NumericDelta(add=100))
        d2 = AccountDelta(balance=NumericDelta(add=50))
        combined = compose_deltas(d1, d2)
        assert combined.balance.add == 150

    def test_validate_delta(self):
        from emergent.wire.axis.schema.dialects.delta import (
            DeltaField,
            NumericDelta,
            delta_type,
            validate_delta,
        )

        @dataclass
        class Account:
            id: int
            balance: Annotated[int, DeltaField("numeric")]

        AccountDelta = delta_type(Account)
        # Valid
        d = AccountDelta(balance=NumericDelta(add=10))
        errors = validate_delta(d, Account)
        assert errors == []

    def test_validate_delta_wrong_type(self):
        from emergent.wire.axis.schema.dialects.delta import (
            DeltaField,
            StringDelta,
            delta_type,
            validate_delta,
        )

        @dataclass
        class Account:
            id: int
            balance: Annotated[int, DeltaField("numeric")]

        AccountDelta = delta_type(Account)
        d = AccountDelta(balance=StringDelta(set="wrong"))
        errors = validate_delta(d, Account)
        assert len(errors) == 1
        assert "expects numeric" in errors[0]

    def test_validate_delta_field_not_found(self):
        """validate_delta reports error when delta field doesn't exist on entity."""
        from dataclasses import make_dataclass, field as dc_field
        from emergent.wire.axis.schema.dialects.delta import (
            NumericDelta,
            validate_delta,
        )

        @dataclass
        class Tiny:
            id: int

        # Manually build a delta with a field that doesn't exist on Tiny
        FakeDelta = make_dataclass(
            "FakeDelta",
            [("nonexistent", NumericDelta | None, dc_field(default=None))],
            frozen=True,
            slots=True,
        )
        d = FakeDelta(nonexistent=NumericDelta(add=1))
        errors = validate_delta(d, Tiny)
        assert len(errors) == 1
        assert "not found" in errors[0]

    def test_validate_delta_no_delta_field_capability(self):
        """validate_delta reports error when field exists but has no DeltaField."""
        from dataclasses import make_dataclass, field as dc_field
        from emergent.wire.axis.schema.dialects.delta import (
            NumericDelta,
            validate_delta,
        )

        @dataclass
        class Account:
            balance: int  # No DeltaField annotation

        FakeDelta = make_dataclass(
            "FakeDelta",
            [("balance", NumericDelta | None, dc_field(default=None))],
            frozen=True,
            slots=True,
        )
        d = FakeDelta(balance=NumericDelta(add=10))
        errors = validate_delta(d, Account)
        assert len(errors) == 1
        assert "not marked with DeltaField" in errors[0]

    def test_compose_deltas_string(self):
        """compose_deltas merges StringDelta fields correctly."""
        from emergent.wire.axis.schema.dialects.delta import (
            DeltaField,
            StringDelta,
            delta_type,
            compose_deltas,
        )

        @dataclass
        class Doc:
            id: int
            title: Annotated[str, DeltaField("string")]

        DocDelta = delta_type(Doc)
        d1 = DocDelta(title=StringDelta(append=" v1"))
        d2 = DocDelta(title=StringDelta(prepend="[NEW] "))
        combined = compose_deltas(d1, d2)
        # d2 prepend overrides d1's None, d1 append stays since d2 append is None
        assert combined.title.append == " v1"
        assert combined.title.prepend == "[NEW] "

    def test_compose_deltas_collection(self):
        """compose_deltas merges CollectionDelta fields correctly."""
        from emergent.wire.axis.schema.dialects.delta import (
            DeltaField,
            CollectionDelta,
            delta_type,
            compose_deltas,
        )

        @dataclass
        class Bag:
            id: int
            items: Annotated[list[str], DeltaField("collection")]

        BagDelta = delta_type(Bag)
        d1 = BagDelta(items=CollectionDelta(push=("a",), pop=1))
        d2 = BagDelta(items=CollectionDelta(push=("b",), remove=("x",)))
        combined = compose_deltas(d1, d2)
        assert combined.items.push == ("a", "b")
        assert combined.items.pop == 1
        assert combined.items.remove == ("x",)

    def test_compose_deltas_single(self):
        """compose_deltas with single delta returns it as-is."""
        from emergent.wire.axis.schema.dialects.delta import (
            DeltaField,
            NumericDelta,
            delta_type,
            compose_deltas,
        )

        @dataclass
        class Acc:
            id: int
            val: Annotated[int, DeltaField("numeric")]

        AccDelta = delta_type(Acc)
        d = AccDelta(val=NumericDelta(add=5))
        assert compose_deltas(d) is d

    def test_compose_deltas_empty_raises(self):
        """compose_deltas with no arguments raises ValueError."""
        from emergent.wire.axis.schema.dialects.delta import compose_deltas

        with pytest.raises(ValueError, match="At least one delta"):
            compose_deltas()

    def test_apply_delta_no_changes(self):
        """apply_delta returns same entity when all delta fields are None."""
        from emergent.wire.axis.schema.dialects.delta import (
            DeltaField,
            delta_type,
            apply_delta,
        )

        @dataclass
        class Acc:
            id: int
            val: Annotated[int, DeltaField("numeric")]

        AccDelta = delta_type(Acc)
        acc = Acc(id=1, val=100)
        d = AccDelta()  # All None
        result = apply_delta(acc, d)
        assert result is acc  # Same object — no copy


# ═══════════════════════════════════════════════════════════════════════════════
# Telegram Help Subdialect
# ═══════════════════════════════════════════════════════════════════════════════


class TestTelegramHelp:
    def test_command_capability(self):
        from emergent.wire.axis.schema.dialects.tg.help import Command

        c = Command(description="Create account", order=1)
        assert c.description == "Create account"
        assert c.order == 1
        assert c.hidden is False

    def test_command_defaults(self):
        from emergent.wire.axis.schema.dialects.tg.help import Command

        c = Command()
        assert c.description is None
        assert c.order == 100
        assert c.hidden is False

    def test_command_hidden(self):
        from emergent.wire.axis.schema.dialects.tg.help import Command

        c = Command(hidden=True)
        assert c.hidden is True

    def test_command_frozen(self):
        from emergent.wire.axis.schema.dialects.tg.help import Command

        c = Command(description="test")
        with pytest.raises(FrozenInstanceError):
            c.description = "other"  # type: ignore[misc]

    def test_command_decorator(self):
        from emergent.wire.axis.schema.dialects.tg.help import command, get_command

        @command("Create account", order=1)
        @dataclass
        class RegisterRequest:
            login: str

        cap = get_command(RegisterRequest)
        assert cap.description == "Create account"
        assert cap.order == 1

    def test_hidden_decorator(self):
        from emergent.wire.axis.schema.dialects.tg.help import hidden, is_hidden

        @hidden()
        @dataclass
        class DebugRequest:
            data: str

        assert is_hidden(DebugRequest) is True

    def test_get_command_default(self):
        """get_command returns default Command for unmarked class."""
        from emergent.wire.axis.schema.dialects.tg.help import get_command

        @dataclass
        class PlainRequest:
            data: str

        cap = get_command(PlainRequest)
        assert cap.description is None
        assert cap.order == 100
        assert cap.hidden is False

    def test_is_hidden_false_by_default(self):
        from emergent.wire.axis.schema.dialects.tg.help import is_hidden

        @dataclass
        class NormalRequest:
            data: str

        assert is_hidden(NormalRequest) is False

    def test_command_is_schema_capability(self):
        from emergent.wire.axis.schema.dialects.tg.help import Command
        from emergent.wire.axis.schema._universal import SchemaCapability

        assert issubclass(Command, SchemaCapability)


# ═══════════════════════════════════════════════════════════════════════════════
# Telegram Compile Methods
# ═══════════════════════════════════════════════════════════════════════════════


class TestTelegramCompile:
    def test_style_compile_render(self):
        from emergent.wire.axis.schema.dialects.tg import Style
        from emergent.wire.axis._capability import TelegrinderRenderContext

        cap = Style("bold")
        ctx = TelegrinderRenderContext(field_name="title", field_type=str)
        result = cap.compile_telegrinder_render(ctx)
        assert result.style == "bold"
        assert result.style_language is None

    def test_style_pre_with_language(self):
        from emergent.wire.axis.schema.dialects.tg import Pre
        from emergent.wire.axis._capability import TelegrinderRenderContext

        cap = Pre("python")
        ctx = TelegrinderRenderContext(field_name="code", field_type=str)
        result = cap.compile_telegrinder_render(ctx)
        assert result.style == "pre"
        assert result.style_language == "python"

    def test_line_compile_render(self):
        from emergent.wire.axis.schema.dialects.tg import Line
        from emergent.wire.axis._capability import TelegrinderRenderContext

        cap = Line(after=False, before=True)
        ctx = TelegrinderRenderContext(field_name="label", field_type=str)
        result = cap.compile_telegrinder_render(ctx)
        assert result.line_after is False
        assert result.line_before is True

    def test_skip_compile_render(self):
        from emergent.wire.axis.schema.dialects.tg import Skip
        from emergent.wire.axis._capability import TelegrinderRenderContext

        cap = Skip()
        ctx = TelegrinderRenderContext(field_name="internal", field_type=str)
        result = cap.compile_telegrinder_render(ctx)
        assert result.skip is True

    def test_command_arg_compile_input(self):
        from emergent.wire.axis.schema.dialects.tg import CommandArg
        from emergent.wire.axis._capability import TelegrinderInputContext

        cap = CommandArg(optional=True, greedy=True)
        ctx = TelegrinderInputContext(field_name="desc", field_type=str)
        result = cap.compile_telegrinder_input(ctx)
        assert result.is_command_arg is True
        assert result.optional is True
        assert result.greedy is True

    def test_command_arg_defaults_compile(self):
        from emergent.wire.axis.schema.dialects.tg import CommandArg
        from emergent.wire.axis._capability import TelegrinderInputContext

        cap = CommandArg()
        ctx = TelegrinderInputContext(field_name="login", field_type=str)
        result = cap.compile_telegrinder_input(ctx)
        assert result.is_command_arg is True
        assert result.optional is False
        assert result.greedy is False

    def test_button_compile_callback(self):
        from emergent.wire.axis.schema.dialects.tg import Button
        from emergent.wire.axis._capability import TelegrinderRenderContext

        cap = Button(callback="do:action")
        ctx = TelegrinderRenderContext(field_name="btn", field_type=str)
        result = cap.compile_telegrinder_render(ctx)
        assert result.button_callback == "do:action"
        assert result.button_url is None

    def test_button_compile_url(self):
        from emergent.wire.axis.schema.dialects.tg import Button
        from emergent.wire.axis._capability import TelegrinderRenderContext

        cap = Button(url="https://example.com")
        ctx = TelegrinderRenderContext(field_name="link", field_type=str)
        result = cap.compile_telegrinder_render(ctx)
        assert result.button_url == "https://example.com"
        assert result.button_callback is None

    def test_keyboard_compile_render(self):
        from emergent.wire.axis.schema.dialects.tg import Keyboard
        from emergent.wire.axis._capability import TelegrinderRenderContext

        cap = Keyboard(columns=3)
        ctx = TelegrinderRenderContext(field_name="kb", field_type=list)
        result = cap.compile_telegrinder_render(ctx)
        assert result.keyboard_columns == 3


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic Validator Compile Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestPydanticValidators:
    def test_validator_before_compile(self):
        from emergent.wire.axis.schema.dialects.pydantic import ValidatorBefore
        from emergent.wire.axis._capability import PydanticContext
        from pydantic.fields import FieldInfo as PydFieldInfo
        from pydantic import BeforeValidator

        def strip_str(v: object) -> object:
            return v.strip() if isinstance(v, str) else v

        cap = ValidatorBefore(func=strip_str)
        fi = PydFieldInfo(annotation=str)
        ctx = PydanticContext(field_name="name", field_type=str, field_info=fi)
        result = cap.compile_pydantic(ctx)
        # Should have appended BeforeValidator to metadata
        validators = [m for m in result.field_info.metadata if isinstance(m, BeforeValidator)]
        assert len(validators) == 1

    def test_validator_after_compile(self):
        from emergent.wire.axis.schema.dialects.pydantic import ValidatorAfter
        from emergent.wire.axis._capability import PydanticContext
        from pydantic.fields import FieldInfo as PydFieldInfo
        from pydantic import AfterValidator

        def upper_str(v: object) -> object:
            if isinstance(v, str):
                return v.upper()
            return v

        cap = ValidatorAfter(func=upper_str)
        fi = PydFieldInfo(annotation=str)
        ctx = PydanticContext(field_name="code", field_type=str, field_info=fi)
        result = cap.compile_pydantic(ctx)
        validators = [m for m in result.field_info.metadata if isinstance(m, AfterValidator)]
        assert len(validators) == 1

    def test_validator_wrap_compile(self):
        from emergent.wire.axis.schema.dialects.pydantic import ValidatorWrap
        from emergent.wire.axis._capability import PydanticContext
        from pydantic.fields import FieldInfo as PydFieldInfo
        from pydantic import WrapValidator

        def wrap_handler(v: object, handler: Callable[[object], object]) -> object:
            return handler(v)

        cap = ValidatorWrap(func=wrap_handler)
        fi = PydFieldInfo(annotation=str)
        ctx = PydanticContext(field_name="val", field_type=str, field_info=fi)
        result = cap.compile_pydantic(ctx)
        validators = [m for m in result.field_info.metadata if isinstance(m, WrapValidator)]
        assert len(validators) == 1

    def test_validator_before_immutable_context(self):
        """compile_pydantic doesn't mutate original context."""
        from emergent.wire.axis.schema.dialects.pydantic import ValidatorBefore
        from emergent.wire.axis._capability import PydanticContext
        from pydantic.fields import FieldInfo as PydFieldInfo

        def identity(v: object) -> object:
            return v

        cap = ValidatorBefore(func=identity)
        fi = PydFieldInfo(annotation=str)
        ctx = PydanticContext(field_name="x", field_type=str, field_info=fi)
        original_meta_len = len(ctx.field_info.metadata)
        result = cap.compile_pydantic(ctx)
        assert len(ctx.field_info.metadata) == original_meta_len  # original untouched
        assert len(result.field_info.metadata) > original_meta_len

    def test_validator_frozen(self) -> None:
        from emergent.wire.axis.schema.dialects.pydantic import (
            ValidatorBefore,
            ValidatorAfter,
            ValidatorWrap,
        )

        def identity(v: object) -> object:
            return v

        def wrap_identity(v: object, handler: Callable[[object], object]) -> object:
            return handler(v)

        before_cap = ValidatorBefore(func=identity)
        assert dataclasses.is_dataclass(before_cap)
        with pytest.raises(FrozenInstanceError):
            before_cap.func = identity  # type: ignore[misc]

        after_cap = ValidatorAfter(func=identity)
        assert dataclasses.is_dataclass(after_cap)
        with pytest.raises(FrozenInstanceError):
            after_cap.func = identity  # type: ignore[misc]

        wrap_cap = ValidatorWrap(func=wrap_identity)
        assert dataclasses.is_dataclass(wrap_cap)
        with pytest.raises(FrozenInstanceError):
            wrap_cap.func = wrap_identity  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# CLI Env Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCLIEnv:
    def test_env_reads_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from emergent.wire.axis.schema.dialects.cli import Env

        monkeypatch.setenv("TEST_API_TOKEN", "secret123")
        cap = Env("TEST_API_TOKEN")
        ctx = ArgparseContext(field_name="token", field_type=str)
        result = cap.compile_argparse(ctx)
        assert result.kwargs["default"] == "secret123"

    def test_env_missing_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from emergent.wire.axis.schema.dialects.cli import Env

        monkeypatch.delenv("NONEXISTENT_VAR_12345", raising=False)
        cap = Env("NONEXISTENT_VAR_12345")
        ctx = ArgparseContext(field_name="token", field_type=str)
        result = cap.compile_argparse(ctx)
        assert "default" not in result.kwargs

    def test_env_frozen(self):
        from emergent.wire.axis.schema.dialects.cli import Env

        cap = Env("VAR")
        with pytest.raises(FrozenInstanceError):
            cap.var = "OTHER"  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# Query Aggregatable & get_aggregate_functions
# ═══════════════════════════════════════════════════════════════════════════════


class TestQueryAggregatable:
    def test_aggregatable_default_functions(self):
        """Aggregatable() with no args includes all standard functions."""
        from emergent.wire.axis.schema.dialects.query import Aggregatable
        from emergent.wire.axis.query._aggregate import Sum, Avg, Min, Max, Count

        cap = Aggregatable()
        assert Sum in cap.functions
        assert Avg in cap.functions
        assert Min in cap.functions
        assert Max in cap.functions
        assert Count in cap.functions
        assert len(cap.functions) == 5

    def test_aggregatable_custom_functions(self):
        """Aggregatable with explicit functions only includes those."""
        from emergent.wire.axis.schema.dialects.query import Aggregatable
        from emergent.wire.axis.query._aggregate import Sum, Count

        cap = Aggregatable(Sum, Count)
        assert cap.functions == (Sum, Count)

    def test_aggregatable_compile_openapi(self):
        from emergent.wire.axis.schema.dialects.query import Aggregatable
        from emergent.wire.axis.query._aggregate import Sum, Avg

        cap = Aggregatable(Sum, Avg)
        ctx = OpenAPIContext(field_name="balance", field_type=int)
        result = cap.compile_openapi(ctx)
        assert result.schema["x-aggregatable"] is True

    def test_aggregatable_compile_query_schema(self):
        from emergent.wire.axis.schema.dialects.query import Aggregatable
        from emergent.wire.axis._capability import QuerySchemaContext
        from emergent.wire.axis.query._aggregate import Sum, Count

        cap = Aggregatable(Sum, Count)
        ctx = QuerySchemaContext(field_name="balance", field_type=int)
        result = cap.compile_query_schema(ctx)
        assert result.aggregatable is True
        assert result.aggregate_functions == (Sum, Count)


# ═══════════════════════════════════════════════════════════════════════════════
# Compose Compile Methods
# ═══════════════════════════════════════════════════════════════════════════════


class TestComposeCompile:
    def test_node_compile_request_build(self):
        from emergent.wire.axis.schema.dialects.compose import Node
        from emergent.wire.axis._capability import RequestBuildContext

        class ChatId:
            pass

        cap = Node(node_type=ChatId, default=0, map=str)
        ctx = RequestBuildContext(field_name="chat_id", field_type=int)
        result = cap.compile_request_build(ctx)
        assert result.compose_node is ChatId
        assert result.compose_node_default == 0
        assert result.compose_node_map is str

    def test_optional_compile_request_build(self):
        from emergent.wire.axis.schema.dialects.compose import Optional
        from emergent.wire.axis._capability import RequestBuildContext

        class AdminNode:
            pass

        cap = Optional(node_type=AdminNode)
        ctx = RequestBuildContext(field_name="admin", field_type=object)
        result = cap.compile_request_build(ctx)
        assert result.compose_optional_node is AdminNode

    def test_fallback_compile_request_build(self):
        from emergent.wire.axis.schema.dialects.compose import Fallback
        from emergent.wire.axis._capability import RequestBuildContext

        class A:
            pass

        class B:
            pass

        cap = Fallback(A, B)
        ctx = RequestBuildContext(field_name="user", field_type=object)
        result = cap.compile_request_build(ctx)
        assert result.compose_fallback_nodes == (A, B)

    def test_race_compile_request_build(self):
        from emergent.wire.axis.schema.dialects.compose import Race
        from emergent.wire.axis._capability import RequestBuildContext

        class API1:
            pass

        class API2:
            pass

        cap = Race(API1, API2)
        ctx = RequestBuildContext(field_name="data", field_type=object)
        result = cap.compile_request_build(ctx)
        assert result.compose_race_nodes == (API1, API2)

    def test_retrieve_compile_request_build(self):
        from emergent.wire.axis.schema.dialects.compose import Retrieve
        from emergent.wire.axis._capability import RequestBuildContext

        class AuthUser:
            pass

        cap = Retrieve(from_type=AuthUser)
        ctx = RequestBuildContext(field_name="user", field_type=object)
        result = cap.compile_request_build(ctx)
        assert result.compose_retrieve_type is AuthUser


# ═══════════════════════════════════════════════════════════════════════════════
# Compilable TypedDicts
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompilableTypedDicts:
    def test_openapi_schema_is_typeddict(self):
        from emergent.wire.axis.schema._compilable import OpenAPISchema
        from typing import get_type_hints

        assert issubclass(OpenAPISchema, dict)
        hints = get_type_hints(OpenAPISchema)
        assert "minimum" in hints
        assert "maximum" in hints
        assert "minLength" in hints
        assert "maxLength" in hints
        assert "pattern" in hints
        assert "format" in hints
        assert "description" in hints
        assert "deprecated" in hints

    def test_openapi_schema_total_false(self):
        """OpenAPISchema is total=False — all fields optional."""
        from emergent.wire.axis.schema._compilable import OpenAPISchema

        s: OpenAPISchema = {}  # Should be valid — no required keys
        assert isinstance(s, dict)

        s2: OpenAPISchema = {"minimum": 0, "maximum": 100}
        assert s2["minimum"] == 0

    def test_sqlalchemy_config_is_typeddict(self):
        from emergent.wire.axis.schema._compilable import SQLAlchemyConfig
        from typing import get_type_hints

        assert issubclass(SQLAlchemyConfig, dict)
        hints = get_type_hints(SQLAlchemyConfig)
        assert "index" in hints
        assert "unique" in hints
        assert "nullable" in hints
        assert "primary_key" in hints
        assert "default" in hints
        assert "server_default" in hints

    def test_sqlalchemy_config_total_false(self):
        """SQLAlchemyConfig is total=False — all fields optional."""
        from emergent.wire.axis.schema._compilable import SQLAlchemyConfig

        c: SQLAlchemyConfig = {}
        assert isinstance(c, dict)

        c2: SQLAlchemyConfig = {"index": True, "unique": False}
        assert c2["index"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeltaEdgeCases:
    def test_delta_type_no_delta_fields(self):
        """delta_type() on class with no DeltaField → empty delta dataclass."""
        from emergent.wire.axis.schema.dialects.delta import delta_type

        @dataclass
        class Plain:
            id: int
            name: str

        Delta = delta_type(Plain)
        import dataclasses as dc
        assert dc.is_dataclass(Delta)
        assert len(dc.fields(Delta)) == 0

    def test_numeric_delta_add_and_multiply(self):
        """add + multiply together: add first, then multiply."""
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta(add=10, multiply=2.0)
        # 100 + 10 = 110, 110 * 2 = 220
        assert d.apply(100) == 220

    def test_numeric_delta_set_overrides_add_multiply(self):
        """set overrides both add and multiply."""
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta(add=999, multiply=999.0, set=42)
        assert d.apply(100) == 42

    def test_numeric_delta_noop(self):
        """No operations → value unchanged."""
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta()
        assert d.apply(77) == 77


class TestUnwrapOptionalEdgeCases:
    def test_multi_union(self):
        """str | int | None → not simple Optional, returns original."""
        from emergent.wire.axis.schema._inspect import unwrap_optional
        from typing import Union

        hint = Union[str, int, None]
        result, is_optional = unwrap_optional(hint)
        assert is_optional is False
        assert result is hint

    def test_plain_type(self):
        """Non-union type → returns as-is, False."""
        from emergent.wire.axis.schema._inspect import unwrap_optional

        result, is_optional = unwrap_optional(int)
        assert result is int
        assert is_optional is False

    def test_simple_optional(self):
        """str | None → (str, True)."""
        from emergent.wire.axis.schema._inspect import unwrap_optional
        from typing import Optional

        result, is_optional = unwrap_optional(Optional[str])
        assert result is str
        assert is_optional is True


class TestComposeSchemaMetaEdgeCases:
    def test_no_overrides(self):
        """compose_schema_meta with no overrides → returns base schema_meta."""
        from emergent.wire.axis.schema._helpers import compose_schema_meta
        from emergent.wire.axis.schema._universal import schema_meta, SchemaName

        @schema_meta(SchemaName("users"))
        @dataclass
        class User:
            id: int

        result = compose_schema_meta(User)
        assert any(isinstance(c, SchemaName) and c.value == "users" for c in result)

    def test_with_overrides(self):
        """compose_schema_meta overrides by type."""
        from emergent.wire.axis.schema._helpers import compose_schema_meta
        from emergent.wire.axis.schema._universal import schema_meta, SchemaName, SchemaDoc

        @schema_meta(SchemaName("users"), SchemaDoc("original"))
        @dataclass
        class User:
            id: int

        result = compose_schema_meta(User, (SchemaName("custom_users"),))
        names = [c for c in result if isinstance(c, SchemaName)]
        assert len(names) == 1
        assert names[0].value == "custom_users"
        # SchemaDoc preserved
        assert any(isinstance(c, SchemaDoc) for c in result)

    def test_no_schema_meta(self):
        """Class without schema_meta → empty tuple."""
        from emergent.wire.axis.schema._helpers import compose_schema_meta

        @dataclass
        class Plain:
            id: int

        result = compose_schema_meta(Plain)
        assert result == ()


class TestGetNestedSchemaMetaEdgeCases:
    def test_non_structured_type(self):
        """Field with plain type → empty tuple."""
        from emergent.wire.axis.schema._helpers import get_nested_schema_meta
        from emergent.wire.axis.schema._inspect import inspect_type

        @dataclass
        class Flat:
            name: str

        fields = inspect_type(Flat)
        result = get_nested_schema_meta(fields["name"])
        assert result == ()

    def test_nested_with_meta_override(self):
        """Nested(meta=...) overrides nested type's schema_meta."""
        from emergent.wire.axis.schema._helpers import get_nested_schema_meta
        from emergent.wire.axis.schema._inspect import inspect_type
        from emergent.wire.axis.schema._universal import (
            schema_meta, SchemaName, Nested,
        )

        @schema_meta(SchemaName("items"))
        @dataclass
        class Item:
            id: int

        @dataclass
        class Order:
            items: Annotated[list[Item], Nested(meta=(SchemaName("order_items"),))]

        fields = inspect_type(Order)
        result = get_nested_schema_meta(fields["items"])
        names = [c for c in result if isinstance(c, SchemaName)]
        assert len(names) == 1
        assert names[0].value == "order_items"


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: Cross-dialect compilation on a single entity
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegrationCrossDialectCompilation:
    """Compile all dialect capabilities for a richly-annotated entity
    and verify each target receives the correct output."""

    def test_full_entity_all_dialects(self):
        """Entity with SQL, OpenAPI, CLI capabilities — compile each dialect."""
        from emergent.wire.axis.schema.dialects.sql import (
            Index, PrimaryKey, ForeignKey, Type, ServerDefault,
        )
        from emergent.wire.axis.schema.dialects.openapi import Description, Format
        from emergent.wire.axis.schema.dialects.cli import Help

        from emergent.wire.axis.schema._universal import (
            Identity, Unique, MaxLen, MinLen, Doc, Ref,
            SchemaName, schema_meta,
        )
        from emergent.wire.axis.schema._inspect import inspect_type
        from emergent.wire.compile._core import fold_field

        @schema_meta(SchemaName("employees"))
        @dataclass
        class Employee:
            id: Annotated[int, Identity, PrimaryKey(autoincrement=True)]
            email: Annotated[str, Unique, MaxLen(255), Index("idx_email"),
                             Description("Employee email"), Format("email"),
                             Help("Work email address")]
            name: Annotated[str, MinLen(1), MaxLen(100), Doc("Full name"),
                            Help("Employee full name")]
            department_id: Annotated[int | None, Ref(target="departments.id"),
                                     ForeignKey("departments.id", ondelete="SET NULL")] = None
            created_at: Annotated[str, ServerDefault("CURRENT_TIMESTAMP"),
                                  Type("TIMESTAMP")] = ""

        fields = inspect_type(Employee)
        assert len(fields) == 5

        from emergent.wire.axis._capability import (
            OpenAPICompilable, SQLAlchemyCompilable, ArgparseCompilable,
        )

        # SQL compilation for email
        email_sql = fold_field(
            fields["email"],
            SQLAlchemyContext(field_name="email", field_type=str),
            SQLAlchemyCompilable,
            "compile_sqlalchemy",
        )
        assert email_sql.column_kwargs.get("unique") is True
        assert email_sql.column_kwargs.get("index") is True

        # OpenAPI compilation for email
        from emergent.wire.axis._capability import OpenAPIContext as OACtx
        email_openapi = fold_field(
            fields["email"],
            OACtx(field_name="email", field_type=str),
            OpenAPICompilable,
            "compile_openapi",
        )
        assert email_openapi.schema.get("maxLength") == 255
        assert email_openapi.schema.get("description") == "Employee email"
        assert email_openapi.schema.get("format") == "email"

        # Argparse compilation for email
        email_argparse = fold_field(
            fields["email"],
            ArgparseContext(field_name="email", field_type=str),
            ArgparseCompilable,
            "compile_argparse",
        )
        assert email_argparse.kwargs.get("help") == "Work email address"

        # SQL compilation for department_id (ForeignKey)
        dept_sql = fold_field(
            fields["department_id"],
            SQLAlchemyContext(field_name="department_id", field_type=int),
            SQLAlchemyCompilable,
            "compile_sqlalchemy",
        )
        assert dept_sql.column_kwargs.get("fk_target") == "departments.id"
        assert dept_sql.column_kwargs.get("fk_ondelete") == "SET NULL"

        # SQL compilation for created_at
        created_sql = fold_field(
            fields["created_at"],
            SQLAlchemyContext(field_name="created_at", field_type=str),
            SQLAlchemyCompilable,
            "compile_sqlalchemy",
        )
        assert created_sql.column_kwargs.get("server_default") == "CURRENT_TIMESTAMP"
        assert created_sql.column_type == "TIMESTAMP"

    def test_pydantic_dialect_compilation(self):
        """Pydantic dialect capabilities compile to field metadata."""
        from emergent.wire.axis.schema.dialects.pydantic import Strict, Coerce

        from emergent.wire.axis.schema._inspect import inspect_type
        from emergent.wire.compile._core import fold_field

        @dataclass
        class Config:
            timeout: Annotated[int, Strict()]
            name: Annotated[str, Coerce()]

        fields = inspect_type(Config)

        from emergent.wire.axis._capability import PydanticContext, PydanticCompilable
        from pydantic.fields import FieldInfo as PydFieldInfo

        timeout_pyd = fold_field(
            fields["timeout"],
            PydanticContext(
                field_name="timeout",
                field_type=int,
                field_info=PydFieldInfo(annotation=int),
            ),
            PydanticCompilable,
            "compile_pydantic",
        )
        # Pydantic context should still be valid after fold
        assert timeout_pyd.field_info is not None

    def test_extra_column_and_field_specs(self):
        """ExtraColumnSpec and ExtraFieldSpec compile through table/model contexts."""
        from emergent.wire.axis.schema._universal import SchemaName

        name_cap = SchemaName("test_table")
        table_ctx = SQLAlchemyTableContext(class_name="Test")
        result = name_cap.compile_sqlalchemy_table(table_ctx)
        assert result.table_name == "test_table"

        # ExtraColumnSpec with required args
        spec = ExtraColumnSpec(name="version", column_type=int)
        assert spec.name == "version"
        assert spec.column_type is int
        assert spec.nullable is True
        assert spec.default is None

        # ExtraFieldSpec with required args + default
        fspec = ExtraFieldSpec(name="version", field_type=int, default=1)
        assert fspec.name == "version"
        assert fspec.field_type is int
        assert fspec.default == 1
