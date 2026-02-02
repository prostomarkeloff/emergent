"""Type generation from schema axis — pure context transforms.

    from emergent.wire.compile import to_pydantic, to_argparse_args

    UserModel = to_pydantic(User, axes)
    args = to_argparse_args(User, axes)

    # With custom handlers
    Model = to_pydantic(User, axes, handlers={Sensitive: my_handler})
"""

from __future__ import annotations

import copy
import types
from dataclasses import dataclass, fields as dc_fields, MISSING
from typing import Callable, Mapping, TYPE_CHECKING

from emergent.wire.compile._core import Axes

from emergent.wire.axis._capability import (
    Capability,
    PydanticContext,
    ArgparseContext,
    PydanticCompilable,
    ArgparseCompilable,
    ArgparseKwargValue,
)

if TYPE_CHECKING:
    from pydantic import BaseModel


PydanticHandler = Callable[[Capability, PydanticContext], PydanticContext]
ArgparseHandler = Callable[[Capability, ArgparseContext], ArgparseContext]


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic
# ═══════════════════════════════════════════════════════════════════════════════


def to_pydantic(
    cls: type,
    axes: Axes,
    handlers: Mapping[type[Capability], PydanticHandler] | None = None,
) -> type["BaseModel"]:
    """Generate Pydantic model from dataclass + capabilities.

    Uses Pydantic's FieldInfo.merge_field_infos directly — no wrappers.
    Capabilities modify FieldInfo via compile_pydantic().
    """
    try:
        from pydantic import BaseModel
        from pydantic.fields import FieldInfo
    except ImportError:
        raise ImportError("pydantic required")

    fields_dict = axes.schema(cls)
    original_fields = {f.name: f for f in dc_fields(cls)}

    # Build annotations and field defaults for type() construction
    annotations: dict[str, type | types.UnionType] = {}
    field_infos: dict[str, FieldInfo] = {}

    for name, schema_field_info in fields_dict.items():
        # Start with empty FieldInfo - capabilities will add constraints
        ctx = PydanticContext(
            field_name=name,
            field_type=schema_field_info.base_type,
            field_info=FieldInfo(),
        )

        # Apply capabilities
        for cap in schema_field_info.capabilities:
            cap_type = type(cap)
            if handlers and cap_type in handlers:
                ctx = handlers[cap_type](cap, ctx)
            elif isinstance(cap, PydanticCompilable):
                ctx = cap.compile_pydantic(ctx)

        # Determine final type
        actual_type: type | types.UnionType = ctx.field_type
        if schema_field_info.is_optional:
            actual_type = ctx.field_type | None

        # Handle defaults from original dataclass field
        orig_field = original_fields.get(name)
        final_field_info = ctx.field_info

        if orig_field:
            if orig_field.default is not MISSING:
                # Copy FieldInfo and set default (avoids deprecated merge_field_infos)
                final_field_info = copy.deepcopy(final_field_info)
                final_field_info.default = orig_field.default
            elif orig_field.default_factory is not MISSING:
                # Copy and set default_factory
                final_field_info = copy.deepcopy(final_field_info)
                final_field_info.default_factory = orig_field.default_factory
            elif schema_field_info.is_optional:
                # Optional without explicit default → default=None
                final_field_info = copy.deepcopy(final_field_info)
                final_field_info.default = None

        annotations[name] = actual_type
        field_infos[name] = final_field_info

    # Build model via type() to avoid create_model's typing limitations
    namespace: dict[str, FieldInfo | dict[str, type | types.UnionType] | str] = {
        **field_infos,
        "__annotations__": annotations,
        "__module__": cls.__module__,
    }

    return type(cls.__name__, (BaseModel,), namespace)


# ═══════════════════════════════════════════════════════════════════════════════
# Argparse
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ArgSpec:
    """Argparse argument spec."""
    name: str
    dest: str
    kwargs: dict[str, ArgparseKwargValue]
    is_positional: bool = False


def to_argparse_args(
    cls: type,
    axes: Axes,
    handlers: Mapping[type[Capability], ArgparseHandler] | None = None,
) -> list[ArgSpec]:
    """Generate argparse specs from dataclass + capabilities."""
    from emergent.wire.axis.schema.dialects import cli as cli_dialect
    from emergent.wire.axis._capability import argparse_arg

    fields_dict = axes.schema(cls)
    original_fields = {f.name: f for f in dc_fields(cls)}
    result: list[ArgSpec] = []

    for name, field_info in fields_dict.items():
        ctx = ArgparseContext(field_name=name, field_type=field_info.base_type)

        for cap in field_info.capabilities:
            cap_type = type(cap)
            if handlers and cap_type in handlers:
                ctx = handlers[cap_type](cap, ctx)
            elif isinstance(cap, ArgparseCompilable):
                ctx = cap.compile_argparse(ctx)
            elif isinstance(cap, cli_dialect.Help):
                ctx = argparse_arg(ctx, help=cap.text)
            elif isinstance(cap, cli_dialect.Metavar):
                ctx = argparse_arg(ctx, metavar=cap.name)
            elif isinstance(cap, cli_dialect.Choices):
                ctx = argparse_arg(ctx, choices=list(cap.values))
            elif isinstance(cap, cli_dialect.Nargs):
                ctx = argparse_arg(ctx, nargs=cap.count)
            elif isinstance(cap, cli_dialect.Action):
                ctx = argparse_arg(ctx, action=cap.action)
            elif isinstance(cap, cli_dialect.Append):
                ctx = argparse_arg(ctx, action="append")
            elif isinstance(cap, cli_dialect.Count):
                ctx = argparse_arg(ctx, action="count", default=0)
            elif isinstance(cap, cli_dialect.Env):
                import os
                env_val = os.environ.get(cap.var)
                if env_val is not None:
                    ctx = argparse_arg(ctx, default=env_val)
            elif isinstance(cap, cli_dialect.Required):
                ctx = argparse_arg(ctx, required=True)

        kwargs = dict(ctx.kwargs)
        orig_field = original_fields.get(name)

        has_default = orig_field and (
            orig_field.default is not MISSING or orig_field.default_factory is not MISSING
        )

        cli_caps = field_info.dialect("cli")
        flag_cap = next((c for c in cli_caps if isinstance(c, cli_dialect.Flag)), None)
        positional_cap = next((c for c in cli_caps if isinstance(c, cli_dialect.Positional)), None)

        if positional_cap is not None:
            arg_name = positional_cap.name or name
            result.append(ArgSpec(name=arg_name, dest=name, kwargs=kwargs, is_positional=True))
        elif flag_cap is not None:
            arg_name = flag_cap.names[0] if flag_cap.names else f"--{name.replace('_', '-')}"
            if len(flag_cap.names) > 1:
                kwargs["aliases"] = list(flag_cap.names[1:])
            if orig_field and orig_field.default is not MISSING:
                kwargs["default"] = orig_field.default
            result.append(ArgSpec(name=arg_name, dest=name, kwargs=kwargs, is_positional=False))
        elif ctx.field_type is bool and orig_field and orig_field.default is False:
            arg_name = f"--{name.replace('_', '-')}"
            kwargs.update(action="store_true", default=False)
            result.append(ArgSpec(name=arg_name, dest=name, kwargs=kwargs, is_positional=False))
        elif has_default:
            arg_name = f"--{name.replace('_', '-')}"
            if orig_field and orig_field.default is not MISSING:
                kwargs["default"] = orig_field.default
            result.append(ArgSpec(name=arg_name, dest=name, kwargs=kwargs, is_positional=False))
        else:
            result.append(ArgSpec(name=name, dest=name, kwargs=kwargs, is_positional=True))

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# DataNode Generation
# ═══════════════════════════════════════════════════════════════════════════════


def to_datanode(cls: type, compose_from: dict[str, type], axes: Axes | None = None) -> type:
    """Generate nodnod DataNode from dataclass."""
    from dataclasses import fields as get_fields

    try:
        from nodnod import DataNode
    except ImportError:
        raise ImportError("nodnod required")

    field_names = [f.name for f in get_fields(cls)]
    compose_params = {n: compose_from[n] for n in field_names if n in compose_from}

    def make_compose(params: dict[str, type], fields: list[str]):  # type: ignore[reportUnknownParameterType]
        def __compose__(node_cls, **kwargs):  # type: ignore[reportUnknownParameterType]
            extracted = {
                n: getattr(kwargs[n], "value", kwargs[n])  # type: ignore[reportUnknownArgumentType]
                for n in fields if n in kwargs
            }
            return node_cls(**extracted)  # type: ignore[reportUnknownVariableType]

        __compose__.__annotations__ = {**params, "return": cls}
        return classmethod(__compose__)  # type: ignore[reportUnknownVariableType]

    return type(
        f"{cls.__name__}Node",
        (cls, DataNode),
        {"__compose__": make_compose(compose_params, field_names), "__module__": cls.__module__},  # type: ignore[reportUnknownArgumentType]
    )


def to_datanode_auto(cls: type, node_registry: dict[type, type], axes: Axes | None = None) -> type:
    """Generate DataNode with automatic field-to-node mapping."""
    from typing import get_type_hints
    from dataclasses import fields as get_fields

    hints = get_type_hints(cls)
    compose_from = {
        f.name: node_registry[hints.get(f.name, f.type)]
        for f in get_fields(cls) if hints.get(f.name, f.type) in node_registry
    }
    return to_datanode(cls, compose_from, axes)


def to_datanode_from_context(
    cls: type,
    field_extractors: dict[str, str] | None = None,
    axes: Axes | None = None,
) -> type:
    """Generate DataNode that extracts from telegrinder Context."""
    from dataclasses import fields as get_fields

    try:
        from nodnod import DataNode
    except ImportError:
        raise ImportError("nodnod required")

    try:
        from telegrinder.bot.dispatch.context import Context
    except ImportError:
        raise ImportError("telegrinder required")

    field_names = [f.name for f in get_fields(cls)]
    extractors = field_extractors or {n: n for n in field_names}

    def make_compose(ext: dict[str, str], fields: list[str]):  # type: ignore[reportUnknownParameterType]
        def __compose__(node_cls, ctx):  # type: ignore[reportUnknownParameterType]
            extracted: dict[str, object] = {
                n: ctx.get(ext.get(n, n))  # type: ignore[reportUnknownMemberType]
                for n in fields if ctx.get(ext.get(n, n)) is not None  # type: ignore[reportUnknownMemberType]
            }
            return node_cls(**extracted)  # type: ignore[reportUnknownVariableType]

        __compose__.__annotations__ = {"ctx": Context, "return": cls}
        return classmethod(__compose__)  # type: ignore[reportUnknownVariableType]

    return type(
        f"{cls.__name__}Node",
        (cls, DataNode),
        {"__compose__": make_compose(extractors, field_names), "__module__": cls.__module__},  # type: ignore[reportUnknownArgumentType]
    )


__all__ = (
    "to_pydantic",
    "to_argparse_args",
    "ArgSpec",
    "PydanticHandler",
    "ArgparseHandler",
    "to_datanode",
    "to_datanode_auto",
    "to_datanode_from_context",
)
