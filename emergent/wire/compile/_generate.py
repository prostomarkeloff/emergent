"""Type generation from schema axis — thin assemblers over compile_fields.

    from emergent.wire.compile import to_pydantic, to_argparse_args

    UserModel = to_pydantic(User, axes)
    args = to_argparse_args(User, axes)

    # With custom handlers
    Model = to_pydantic(User, axes, handlers={Sensitive: my_handler})
"""

from __future__ import annotations

import types
from dataclasses import dataclass, fields as dc_fields, MISSING
from typing import Callable, Mapping, TYPE_CHECKING

from emergent.wire.compile._core import Axes
from emergent.wire.compile._phase import (
    compile_fields,
    PYDANTIC_PHASE,
    ARGPARSE_PHASE,
    TG_RENDER_PHASE,
)

from emergent.wire.axis._capability import (
    Capability,
    PydanticContext,
    ArgparseContext,
    ArgparseKwargValue,
    TelegrinderRenderContext,
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

    Uses Annotated[type, Field(...)] for proper Pydantic v2 support.
    Capabilities modify FieldInfo via compile_pydantic().

    Thin assembler over compile_fields + PYDANTIC_PHASE.
    """
    phase = PYDANTIC_PHASE.with_handlers(handlers) if handlers else PYDANTIC_PHASE
    compiled = compile_fields(cls, axes, [phase])
    return _assemble_pydantic(cls, compiled, phase)


def _assemble_pydantic(
    cls: type,
    compiled: list,
    phase: object,
) -> type["BaseModel"]:
    """Assemble Pydantic model from compiled field results."""
    from typing import Annotated

    try:
        from pydantic import BaseModel, Field
    except ImportError:
        raise ImportError("pydantic required")

    from emergent.wire.axis.schema.dialects.compose import ComposeCapability

    original_fields = {f.name: f for f in dc_fields(cls)}
    annotations: dict[str, type] = {}

    for fc in compiled:
        ctx: PydanticContext = fc[phase]
        schema_field_info = fc.info

        # Skip compose.Node fields — resolved at runtime by nodnod, not from request body
        if schema_field_info.has(ComposeCapability):
            continue

        # Determine base type
        base_type: type | types.UnionType = ctx.field_type
        if schema_field_info.is_optional:
            base_type = ctx.field_type | None

        # Build Field() kwargs from FieldInfo
        field_kwargs: dict[str, object] = {}

        # Copy constraints from ctx.field_info metadata
        if ctx.field_info.metadata:
            field_kwargs["metadata"] = list(ctx.field_info.metadata)

        # Copy capability-set properties from compiled FieldInfo
        if ctx.field_info.alias is not None:
            field_kwargs["alias"] = ctx.field_info.alias
        if ctx.field_info.json_schema_extra:
            field_kwargs["json_schema_extra"] = ctx.field_info.json_schema_extra
        if ctx.field_info.repr is not True:
            field_kwargs["repr"] = ctx.field_info.repr
        if ctx.field_info.deprecated:
            field_kwargs["deprecated"] = ctx.field_info.deprecated
        if ctx.field_info.description:
            field_kwargs["description"] = ctx.field_info.description

        # Handle defaults from original dataclass field
        name = fc.name
        orig_field = original_fields.get(name)
        if orig_field:
            if orig_field.default is not MISSING:
                field_kwargs["default"] = orig_field.default
            elif orig_field.default_factory is not MISSING:
                field_kwargs["default_factory"] = orig_field.default_factory
            elif schema_field_info.is_optional:
                field_kwargs["default"] = None
        elif schema_field_info.is_optional:
            field_kwargs["default"] = None

        # Use Annotated[type, Field(...)] for proper Pydantic v2 model creation
        if field_kwargs:
            annotations[name] = Annotated[base_type, Field(**field_kwargs)]  # type: ignore[assignment]
        else:
            annotations[name] = base_type  # type: ignore[assignment]

    # Build model via type() with Annotated annotations
    namespace: dict[str, dict[str, type] | str] = {
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
    """Generate argparse specs from dataclass or Pydantic model + capabilities.

    Thin assembler over compile_fields + ARGPARSE_PHASE.
    """
    phase = ARGPARSE_PHASE.with_handlers(handlers) if handlers else ARGPARSE_PHASE
    compiled = compile_fields(cls, axes, [phase])
    return _assemble_argparse(cls, compiled, phase)


def _assemble_argparse(
    cls: type,
    compiled: list,
    phase: object,
) -> list[ArgSpec]:
    """Assemble argparse specs from compiled field results."""
    import dataclasses

    result: list[ArgSpec] = []

    # Get original dataclass fields if available (for defaults)
    original_fields: dict[str, dataclasses.Field[object]] = {}
    if dataclasses.is_dataclass(cls):
        original_fields = {f.name: f for f in dc_fields(cls)}

    from emergent.wire.axis.schema.dialects.compose import ComposeCapability

    for fc in compiled:
        ctx: ArgparseContext = fc[phase]
        field_info = fc.info
        name = fc.name

        # Skip compose.Node fields — resolved at runtime by nodnod, not from CLI
        if field_info.has(ComposeCapability):
            continue

        kwargs = dict(ctx.kwargs)
        orig_field = original_fields.get(name)

        # Check for defaults (dataclass fields or optional via schema)
        has_default = field_info.is_optional
        if orig_field and (orig_field.default is not MISSING or orig_field.default_factory is not MISSING):
            has_default = True

        # Post-fold: read from ctx instead of re-querying capabilities
        if ctx.is_positional:
            result.append(ArgSpec(name=ctx.field_name, dest=name, kwargs=kwargs, is_positional=True))
        elif ctx.arg_names is not None:
            arg_name = ctx.arg_names[0]
            if len(ctx.arg_names) > 1:
                kwargs["aliases"] = list(ctx.arg_names[1:])
            if orig_field and orig_field.default is not MISSING:
                default_val: ArgparseKwargValue = orig_field.default  # type: ignore[assignment]
                kwargs["default"] = default_val
            result.append(ArgSpec(name=arg_name, dest=name, kwargs=kwargs, is_positional=False))
        elif ctx.field_type is bool and has_default:
            arg_name = f"--{name.replace('_', '-')}"
            kwargs.update(action="store_true", default=False)
            result.append(ArgSpec(name=arg_name, dest=name, kwargs=kwargs, is_positional=False))
        elif has_default:
            arg_name = f"--{name.replace('_', '-')}"
            if orig_field and orig_field.default is not MISSING:
                default_val = orig_field.default  # type: ignore[assignment]
                kwargs["default"] = default_val
            result.append(ArgSpec(name=arg_name, dest=name, kwargs=kwargs, is_positional=False))
        else:
            # Required field — positional argument
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


# ═══════════════════════════════════════════════════════════════════════════════
# Telegram Render Fields
# ═══════════════════════════════════════════════════════════════════════════════


def to_telegram_fields(
    cls: type,
    axes: Axes,
) -> list[TelegrinderRenderContext]:
    """Generate Telegram render specs from dataclass + capabilities.

    Thin assembler over compile_fields + TG_RENDER_PHASE.
    """
    compiled = compile_fields(cls, axes, [TG_RENDER_PHASE])
    return [fc[TG_RENDER_PHASE] for fc in compiled]


__all__ = (
    "to_pydantic",
    "to_argparse_args",
    "ArgSpec",
    "PydanticHandler",
    "ArgparseHandler",
    "to_datanode",
    "to_datanode_auto",
    "to_datanode_from_context",
    "to_telegram_fields",
)
