"""Tests for compile._generate — to_pydantic, to_argparse_args, to_datanode, to_telegram_fields.

Covers missed lines:
- Pydantic: custom handlers, field_info.alias/description/deprecated/repr/json_schema_extra,
  default_factory, optional without orig_field
- Argparse: custom handlers, arg_names with aliases, bool flag with default, positional via ctx
- DataNode: to_datanode_from_context, to_datanode_auto with registry
- Telegram: to_telegram_fields compilation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Mapping

from emergent.wire.compile._core import Axes
from emergent.wire.compile._generate import (
    to_pydantic,
    to_argparse_args,
    to_datanode,
    to_datanode_auto,
    to_telegram_fields,
    ArgSpec,
    PydanticHandler,
    ArgparseHandler,
)
from emergent.wire.axis._capability import Capability, PydanticContext, ArgparseContext
from emergent.wire.axis.schema import MaxLen, MinLen, Min, Max, Doc, Deprecated, Alias
from emergent.wire.axis.schema.dialects.compose import Node as ComposeNode
from emergent.wire.axis.schema.dialects.cli import Flag, Positional, Help as CLIHelp


# ═══════════════════════════════════════════════════════════════════════════════
# Domain types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class GenUser:
    name: Annotated[str, MinLen(1), MaxLen(100)]
    age: Annotated[int, Min(0), Max(150)]


@dataclass
class OptGenUser:
    name: str
    bio: str | None = None


@dataclass
class DefaultGenUser:
    name: str
    greeting: str = "hello"


@dataclass
class BoolEntity:
    name: str
    verbose: bool = False


@dataclass
class ComposeEntity:
    name: str
    config: Annotated[str, ComposeNode(str)] = ""


def _empty_str_list() -> list[str]:
    return []


@dataclass
class DefaultFactoryEntity:
    name: str
    tags: list[str] = field(default_factory=_empty_str_list)


@dataclass
class DocEntity:
    name: Annotated[str, Doc("The user name")]
    bio: Annotated[str, Doc("A biography"), Deprecated] = ""


@dataclass
class AliasEntity:
    name: Annotated[str, Alias("user_name")]


@dataclass
class FlagEntity:
    name: str
    output: Annotated[str, Flag("-o", "--output")] = "json"


@dataclass
class PositionalEntity:
    file: Annotated[str, Positional("input_file")]
    name: str


@dataclass
class CLIHelpEntity:
    name: Annotated[str, CLIHelp("Your full name")]
    verbose: bool = False


# ═══════════════════════════════════════════════════════════════════════════════
# to_pydantic
# ═══════════════════════════════════════════════════════════════════════════════


class TestToPydantic:
    """Covers _assemble_pydantic: Annotated fields, defaults, optional, compose skip."""

    def test_basic_model_creation(self) -> None:
        axes = Axes.default()
        Model = to_pydantic(GenUser, axes)
        assert Model.__name__ == "GenUser"
        instance = Model(name="Alice", age=25)
        data = instance.model_dump()
        assert data["name"] == "Alice"
        assert data["age"] == 25

    def test_optional_field_defaults_to_none(self) -> None:
        axes = Axes.default()
        Model = to_pydantic(OptGenUser, axes)
        instance = Model(name="Bob")
        assert instance.model_dump()["bio"] is None

    def test_default_value_preserved(self) -> None:
        axes = Axes.default()
        Model = to_pydantic(DefaultGenUser, axes)
        instance = Model(name="Charlie")
        assert instance.model_dump()["greeting"] == "hello"

    def test_compose_node_fields_excluded(self) -> None:
        axes = Axes.default()
        Model = to_pydantic(ComposeEntity, axes)
        # ComposeNode fields are excluded from Pydantic models
        fields = Model.model_fields
        assert "config" not in fields
        instance = Model(name="test")
        assert instance.model_dump()["name"] == "test"

    def test_model_fields_present(self) -> None:
        axes = Axes.default()
        Model = to_pydantic(GenUser, axes)
        assert "name" in Model.model_fields
        assert "age" in Model.model_fields

    def test_default_factory_preserved(self) -> None:
        """default_factory fields produce proper Pydantic defaults."""
        axes = Axes.default()
        Model = to_pydantic(DefaultFactoryEntity, axes)
        instance = Model(name="test")
        assert instance.model_dump()["tags"] == []

    def test_doc_becomes_description(self) -> None:
        """Doc capability compiles to Pydantic field description."""
        axes = Axes.default()
        Model = to_pydantic(DocEntity, axes)
        name_field = Model.model_fields["name"]
        assert name_field.description == "The user name"

    def test_deprecated_field(self) -> None:
        """Deprecated capability compiles to Pydantic deprecated flag."""
        axes = Axes.default()
        Model = to_pydantic(DocEntity, axes)
        bio_field = Model.model_fields["bio"]
        assert bio_field.deprecated is not None

    def test_alias_field(self) -> None:
        """Alias capability compiles to Pydantic alias."""
        axes = Axes.default()
        Model = to_pydantic(AliasEntity, axes)
        name_field = Model.model_fields["name"]
        assert name_field.alias == "user_name"

    def test_custom_pydantic_handler(self) -> None:
        """Custom handler overrides default capability compilation."""
        call_count = 0

        def my_minlen_handler(cap: Capability, ctx: PydanticContext) -> PydanticContext:
            nonlocal call_count
            call_count += 1
            # Custom handler that just passes through
            return ctx

        axes = Axes.default()
        handlers: Mapping[type[Capability], PydanticHandler] = {MinLen: my_minlen_handler}
        Model = to_pydantic(GenUser, axes, handlers=handlers)
        assert Model.__name__ == "GenUser"
        assert call_count > 0

    def test_model_module_preserved(self) -> None:
        """Generated model preserves __module__ from source class."""
        axes = Axes.default()
        Model = to_pydantic(GenUser, axes)
        assert Model.__module__ == GenUser.__module__


# ═══════════════════════════════════════════════════════════════════════════════
# to_argparse_args
# ═══════════════════════════════════════════════════════════════════════════════


class TestToArgparseArgs:
    """Covers _assemble_argparse: positional, optional, bool flag, defaults, compose skip."""

    def test_required_field_is_positional(self) -> None:
        axes = Axes.default()
        args = to_argparse_args(GenUser, axes)
        name_spec = next(a for a in args if a.dest == "name")
        assert name_spec.is_positional

    def test_optional_field_is_flag(self) -> None:
        axes = Axes.default()
        args = to_argparse_args(OptGenUser, axes)
        bio_spec = next(a for a in args if a.dest == "bio")
        assert not bio_spec.is_positional
        assert bio_spec.name.startswith("--")

    def test_default_field_is_flag_with_default(self) -> None:
        axes = Axes.default()
        args = to_argparse_args(DefaultGenUser, axes)
        greeting_spec = next(a for a in args if a.dest == "greeting")
        assert not greeting_spec.is_positional
        assert greeting_spec.kwargs.get("default") == "hello"

    def test_bool_field_is_store_true(self) -> None:
        axes = Axes.default()
        args = to_argparse_args(BoolEntity, axes)
        verbose_spec = next(a for a in args if a.dest == "verbose")
        assert verbose_spec.kwargs.get("action") == "store_true"

    def test_compose_node_fields_excluded(self) -> None:
        axes = Axes.default()
        args = to_argparse_args(ComposeEntity, axes)
        dests = {a.dest for a in args}
        assert "config" not in dests

    def test_argspec_structure(self) -> None:
        axes = Axes.default()
        args = to_argparse_args(GenUser, axes)
        assert all(isinstance(a, ArgSpec) for a in args)
        assert all(isinstance(a.kwargs, dict) for a in args)

    def test_flag_with_aliases(self) -> None:
        """Flag with multiple names produces arg_names and aliases."""
        axes = Axes.default()
        args = to_argparse_args(FlagEntity, axes)
        output_spec = next(a for a in args if a.dest == "output")
        assert not output_spec.is_positional
        # The first name should be used as the arg name
        assert output_spec.name == "-o"
        # Additional names go to aliases
        assert "aliases" in output_spec.kwargs
        assert output_spec.kwargs["aliases"] == ["--output"]

    def test_positional_via_capability(self) -> None:
        """Positional capability marks field as positional with custom name."""
        axes = Axes.default()
        args = to_argparse_args(PositionalEntity, axes)
        file_spec = next(a for a in args if a.dest == "file")
        assert file_spec.is_positional
        assert file_spec.name == "input_file"

    def test_custom_argparse_handler(self) -> None:
        """Custom handler overrides default capability compilation."""
        call_count = 0

        def my_handler(cap: Capability, ctx: ArgparseContext) -> ArgparseContext:
            nonlocal call_count
            call_count += 1
            return ctx

        axes = Axes.default()
        handlers: Mapping[type[Capability], ArgparseHandler] = {MinLen: my_handler}
        args = to_argparse_args(GenUser, axes, handlers=handlers)
        assert len(args) > 0
        assert call_count > 0

    def test_cli_help_in_kwargs(self) -> None:
        """CLIHelp capability produces help kwarg."""
        axes = Axes.default()
        args = to_argparse_args(CLIHelpEntity, axes)
        name_spec = next(a for a in args if a.dest == "name")
        assert name_spec.kwargs.get("help") == "Your full name"

    def test_default_factory_field(self) -> None:
        """default_factory fields treated as having defaults."""
        axes = Axes.default()
        args = to_argparse_args(DefaultFactoryEntity, axes)
        tags_spec = next(a for a in args if a.dest == "tags")
        # Has default (default_factory) so should be flag
        assert not tags_spec.is_positional


# ═══════════════════════════════════════════════════════════════════════════════
# to_datanode
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class Point:
    x: int
    y: int


class XNode:
    pass


class YNode:
    pass


class TestToDatanode:
    """Covers to_datanode: manual compose_from mapping."""

    def test_basic_datanode_creation(self) -> None:
        PointNode = to_datanode(Point, compose_from={"x": XNode, "y": YNode})
        assert PointNode.__name__ == "PointNode"
        assert issubclass(PointNode, Point)

    def test_partial_compose_from(self) -> None:
        # Only x mapped, y not
        PointNode = to_datanode(Point, compose_from={"x": XNode})
        assert PointNode.__name__ == "PointNode"

    def test_has_compose_classmethod(self) -> None:
        PointNode = to_datanode(Point, compose_from={"x": XNode})
        assert hasattr(PointNode, "__compose__")

    def test_compose_annotations_set(self) -> None:
        """__compose__ classmethod has correct annotations."""
        PointNode = to_datanode(Point, compose_from={"x": XNode, "y": YNode})
        compose_attr: object = getattr(PointNode, "__compose__")
        compose_func: object = getattr(compose_attr, "__func__")
        annotations: dict[str, type] = getattr(compose_func, "__annotations__")
        assert "x" in annotations
        assert annotations["x"] is XNode
        assert annotations["return"] is Point

    def test_empty_compose_from(self) -> None:
        """Empty compose_from produces a DataNode with no compose dependencies."""
        PointNode = to_datanode(Point, compose_from={})
        assert PointNode.__name__ == "PointNode"


# ═══════════════════════════════════════════════════════════════════════════════
# to_datanode_auto
# ═══════════════════════════════════════════════════════════════════════════════


class TestToDatanodeAuto:
    """Covers to_datanode_auto: automatic field-to-node mapping."""

    def test_auto_mapping(self) -> None:
        registry: dict[type, type] = {int: XNode}
        PointNode = to_datanode_auto(Point, node_registry=registry)
        assert PointNode.__name__ == "PointNode"

    def test_unmapped_types_skipped(self) -> None:
        registry: dict[type, type] = {}
        PointNode = to_datanode_auto(Point, node_registry=registry)
        assert PointNode.__name__ == "PointNode"

    def test_full_registry_mapping(self) -> None:
        """All field types in registry produces compose params for all."""
        registry: dict[type, type] = {int: XNode}
        PointNode = to_datanode_auto(Point, node_registry=registry)
        compose_attr: object = getattr(PointNode, "__compose__")
        compose_func: object = getattr(compose_attr, "__func__")
        annotations: dict[str, type] = getattr(compose_func, "__annotations__")
        # Both x and y are int, so both should be mapped to XNode
        assert annotations.get("x") is XNode
        assert annotations.get("y") is XNode


# ═══════════════════════════════════════════════════════════════════════════════
# to_telegram_fields
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class TGEntity:
    name: Annotated[str, Doc("User name")]
    age: int


class TestToTelegramFields:
    """Covers to_telegram_fields: TG_RENDER_PHASE compilation."""

    def test_returns_list_of_contexts(self) -> None:
        axes = Axes.default()
        fields = to_telegram_fields(TGEntity, axes)
        assert isinstance(fields, list)
        assert len(fields) == 2

    def test_field_contexts_have_attributes(self) -> None:
        axes = Axes.default()
        fields = to_telegram_fields(TGEntity, axes)
        # Each should be a TelegrinderRenderContext
        for ctx in fields:
            assert hasattr(ctx, "field_name")
            assert hasattr(ctx, "field_type")

    def test_field_names_match(self) -> None:
        axes = Axes.default()
        fields = to_telegram_fields(TGEntity, axes)
        names = [ctx.field_name for ctx in fields]
        assert "name" in names
        assert "age" in names

    def test_field_types_match(self) -> None:
        axes = Axes.default()
        fields = to_telegram_fields(TGEntity, axes)
        name_ctx = next(c for c in fields if c.field_name == "name")
        assert name_ctx.field_type is str
        age_ctx = next(c for c in fields if c.field_name == "age")
        assert age_ctx.field_type is int
