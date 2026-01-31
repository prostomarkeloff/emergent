"""Type generation from schema axis.

Pure functions: dataclass + axes → framework-specific types.

    from emergent.wire.compiler import to_pydantic, to_argparse_args

    # Generate Pydantic model from dataclass
    UserModel = to_pydantic(User, axes)

    # Generate argparse arguments
    args = to_argparse_args(User, axes)
"""

from __future__ import annotations

from dataclasses import dataclass, fields as dc_fields, MISSING
from typing import Any

from emergent.wire.compiler._core import Axes, extract_all_constraints


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic Generation
# ═══════════════════════════════════════════════════════════════════════════════


def to_pydantic(cls: type, axes: Axes) -> type:
    """Generate Pydantic model from dataclass + schema capabilities.

    Uses universal constraints (MinLen, MaxLen, Pattern, etc.)
    and openapi dialect for descriptions/examples.

    Example:
        @dataclass
        class User:
            email: Annotated[str, MaxLen(255), openapi.Description("User email")]

        UserModel = to_pydantic(User, axes)
        # → Pydantic model with max_length=255, description="User email"
    """
    try:
        from pydantic import Field, create_model
    except ImportError:
        raise ImportError("pydantic required for to_pydantic()")

    from emergent.wire.axis.schema.dialects import openapi

    all_constraints = extract_all_constraints(cls, axes)
    fields_dict = axes.schema(cls)

    pydantic_fields: dict[str, Any] = {}

    for name, (base_type, constraints) in all_constraints.items():
        field_info = fields_dict[name]
        field_kwargs: dict[str, Any] = {}

        # Universal constraints
        if constraints.min_length is not None:
            field_kwargs["min_length"] = constraints.min_length
        if constraints.max_length is not None:
            field_kwargs["max_length"] = constraints.max_length
        if constraints.min_value is not None:
            field_kwargs["ge"] = constraints.min_value
        if constraints.max_value is not None:
            field_kwargs["le"] = constraints.max_value
        if constraints.pattern is not None:
            field_kwargs["pattern"] = constraints.pattern

        # OpenAPI dialect → Pydantic Field metadata
        for cap in field_info.dialect("openapi"):
            if isinstance(cap, openapi.Description):
                field_kwargs["description"] = cap.description
            elif isinstance(cap, openapi.Title):
                field_kwargs["title"] = cap.title
            elif isinstance(cap, openapi.Examples):
                field_kwargs["examples"] = list(cap.values)
            elif isinstance(cap, openapi.Default):
                field_kwargs["default"] = cap.value
            elif isinstance(cap, openapi.Deprecated):
                field_kwargs["deprecated"] = True

        # Handle optional
        actual_type = base_type | None if constraints.is_optional else base_type

        # Check for default in original dataclass
        original_fields = {f.name: f for f in dc_fields(cls)}
        if name in original_fields:
            orig_field = original_fields[name]
            if orig_field.default is not MISSING:
                field_kwargs["default"] = orig_field.default
            elif orig_field.default_factory is not MISSING:
                field_kwargs["default_factory"] = orig_field.default_factory
            elif constraints.is_optional and "default" not in field_kwargs:
                field_kwargs["default"] = None

        pydantic_fields[name] = (actual_type, Field(**field_kwargs))

    return create_model(cls.__name__, **pydantic_fields)


# ═══════════════════════════════════════════════════════════════════════════════
# Argparse Generation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ArgSpec:
    """Specification for argparse argument."""

    name: str  # Positional name or --flag-name
    dest: str  # Destination attribute name
    kwargs: dict[str, Any]  # argparse.add_argument kwargs
    is_positional: bool = False


def to_argparse_args(cls: type, axes: Axes) -> list[ArgSpec]:
    """Generate argparse argument specs from dataclass + schema capabilities.

    Uses universal constraints and cli dialect for help/choices/flags.

    Example:
        @dataclass
        class Register:
            login: Annotated[str, MinLen(3), cli.Help("Username")]
            verbose: Annotated[bool, cli.Flag("-v", "--verbose")]
            format: Annotated[str, cli.Choices("json", "yaml")]

        args = to_argparse_args(Register, axes)
    """
    from emergent.wire.axis.schema.dialects import cli as cli_dialect

    all_constraints = extract_all_constraints(cls, axes)
    fields_dict = axes.schema(cls)
    original_fields = {f.name: f for f in dc_fields(cls)}
    result: list[ArgSpec] = []

    for name, (base_type, constraints) in all_constraints.items():
        kwargs: dict[str, Any] = {}
        orig_field = original_fields.get(name)
        field_info = fields_dict[name]

        # Get CLI dialect capabilities
        cli_caps = field_info.dialect("cli")

        # Help from cli.Help
        for cap in cli_caps:
            if isinstance(cap, cli_dialect.Help):
                kwargs["help"] = cap.text
            elif isinstance(cap, cli_dialect.Metavar):
                kwargs["metavar"] = cap.name
            elif isinstance(cap, cli_dialect.Choices):
                kwargs["choices"] = list(cap.values)
            elif isinstance(cap, cli_dialect.Nargs):
                kwargs["nargs"] = cap.count
            elif isinstance(cap, cli_dialect.Action):
                kwargs["action"] = cap.action
            elif isinstance(cap, cli_dialect.Append):
                kwargs["action"] = "append"
            elif isinstance(cap, cli_dialect.Count):
                kwargs["action"] = "count"
                kwargs["default"] = 0
            elif isinstance(cap, cli_dialect.Env):
                import os
                env_val = os.environ.get(cap.var)
                if env_val is not None:
                    kwargs["default"] = env_val
            elif isinstance(cap, cli_dialect.Required):
                kwargs["required"] = True

        # Choices from universal constraints (fallback)
        if "choices" not in kwargs and constraints.choices:
            kwargs["choices"] = list(constraints.choices)

        # Determine if positional or optional
        has_default = False
        if orig_field:
            has_default = (
                orig_field.default is not MISSING
                or orig_field.default_factory is not MISSING
            )

        # Check for explicit Flag or Positional
        flag_cap = None
        positional_cap = None
        for cap in cli_caps:
            if isinstance(cap, cli_dialect.Flag):
                flag_cap = cap
            elif isinstance(cap, cli_dialect.Positional):
                positional_cap = cap

        # Explicit positional
        if positional_cap is not None:
            arg_name = positional_cap.name or name
            result.append(ArgSpec(name=arg_name, dest=name, kwargs=kwargs, is_positional=True))
            continue

        # Explicit flag
        if flag_cap is not None:
            arg_name = flag_cap.names[0] if flag_cap.names else f"--{name.replace('_', '-')}"
            # Add aliases
            if len(flag_cap.names) > 1:
                kwargs["aliases"] = list(flag_cap.names[1:])
            if orig_field and orig_field.default is not MISSING:
                kwargs["default"] = orig_field.default
            result.append(ArgSpec(name=arg_name, dest=name, kwargs=kwargs, is_positional=False))
            continue

        # Boolean with default False → store_true
        if base_type is bool and orig_field and orig_field.default is False:
            arg_name = f"--{name.replace('_', '-')}"
            kwargs["action"] = "store_true"
            kwargs["default"] = False
            result.append(ArgSpec(name=arg_name, dest=name, kwargs=kwargs, is_positional=False))
            continue

        # With default → optional flag
        if has_default:
            arg_name = f"--{name.replace('_', '-')}"
            if orig_field and orig_field.default is not MISSING:
                kwargs["default"] = orig_field.default
            result.append(ArgSpec(name=arg_name, dest=name, kwargs=kwargs, is_positional=False))
        else:
            # No default → positional
            arg_name = name
            result.append(ArgSpec(name=arg_name, dest=name, kwargs=kwargs, is_positional=True))

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Telegrinder Node Generation (placeholder)
# ═══════════════════════════════════════════════════════════════════════════════


def to_datanode(
    cls: type,
    compose_from: dict[str, type],
    axes: Axes | None = None,
) -> type:
    """Generate nodnod DataNode from dataclass.

    The generated node has __compose__ that extracts fields from composed dependencies.

    Args:
        cls: Source dataclass
        compose_from: Mapping {field_name: NodeType} — which node provides each field
        axes: Optional axes (for future constraint validation)

    Example:
        @dataclass
        class BetInput:
            bet_type: str
            amount: int

        # BetType and BetAmount are nodnod nodes from telegrinder context
        BetInputNode = to_datanode(BetInput, {
            "bet_type": BetType,
            "amount": BetAmount,
        })

        # Generated:
        # @dataclass
        # class BetInputNode(DataNode):
        #     bet_type: str
        #     amount: int
        #
        #     @classmethod
        #     def __compose__(cls, bet_type: BetType, amount: BetAmount) -> Self:
        #         return cls(bet_type=bet_type.value, amount=amount.value)
    """
    from dataclasses import fields as get_fields

    try:
        from nodnod import DataNode
    except ImportError:
        raise ImportError("nodnod required for to_datanode()")

    field_names = [f.name for f in get_fields(cls)]

    # Build __compose__ signature dynamically
    compose_params = {}
    for name in field_names:
        if name in compose_from:
            compose_params[name] = compose_from[name]

    # Create the new DataNode class
    def make_compose(params: dict[str, type], fields: list[str]):  # type: ignore[reportUnknownParameterType]
        """Create __compose__ classmethod."""
        def __compose__(node_cls, **kwargs):  # type: ignore[reportUnknownParameterType]
            # Extract .value from nodes or use directly
            extracted = {}
            for name in fields:
                if name in kwargs:
                    val = kwargs[name]  # type: ignore[reportUnknownVariableType]
                    # If node has .value attribute, extract it
                    extracted[name] = getattr(val, "value", val)  # type: ignore[reportUnknownArgumentType]
            return node_cls(**extracted)  # type: ignore[reportUnknownVariableType]

        # Set proper annotations for nodnod
        __compose__.__annotations__ = {
            **{name: typ for name, typ in params.items()},
            "return": cls,
        }
        return classmethod(__compose__)  # type: ignore[reportUnknownVariableType]

    # Create new class inheriting from DataNode
    new_cls = type(
        f"{cls.__name__}Node",
        (cls, DataNode),
        {
            "__compose__": make_compose(compose_params, field_names),  # type: ignore[reportUnknownArgumentType]
            "__module__": cls.__module__,
        },
    )

    return new_cls


def to_datanode_auto(
    cls: type,
    node_registry: dict[type, type],
    axes: Axes | None = None,
) -> type:
    """Generate DataNode with automatic field-to-node mapping.

    Looks up each field's type in node_registry to find the corresponding node.

    Args:
        cls: Source dataclass
        node_registry: Mapping {field_type: NodeType}
        axes: Optional axes

    Example:
        @dataclass
        class BetInput:
            bet_type: str
            amount: int

        # Registry maps types to nodes
        registry = {
            str: BetTypeNode,   # str fields come from BetTypeNode
            int: BetAmountNode, # int fields come from BetAmountNode
        }

        BetInputNode = to_datanode_auto(BetInput, registry)
    """
    from typing import get_type_hints
    from dataclasses import fields as get_fields

    hints = get_type_hints(cls)
    compose_from: dict[str, type] = {}

    for f in get_fields(cls):
        field_type = hints.get(f.name, f.type)
        if field_type in node_registry:
            compose_from[f.name] = node_registry[field_type]

    return to_datanode(cls, compose_from, axes)


def to_datanode_from_context(
    cls: type,
    field_extractors: dict[str, str] | None = None,
    axes: Axes | None = None,
) -> type:
    """Generate DataNode that extracts fields from telegrinder Context.

    For telegrinder integration — the generated node's __compose__ takes
    Context and extracts fields via ctx.get(key).

    Args:
        cls: Source dataclass
        field_extractors: Optional mapping {field_name: ctx_key}.
                         If not provided, uses field name as ctx key.
        axes: Optional axes

    Example:
        @dataclass
        class BetInput:
            user_id: int
            bet_type: str
            amount: int

        # All fields extracted from ctx by their names
        BetInputNode = to_datanode_from_context(BetInput)

        # Custom mapping
        BetInputNode = to_datanode_from_context(BetInput, {
            "user_id": "from_user_id",  # ctx.get("from_user_id")
            "bet_type": "bet",          # ctx.get("bet")
            "amount": "amount",         # ctx.get("amount")
        })

        # Generated:
        # @dataclass
        # class BetInputNode(DataNode):
        #     user_id: int
        #     bet_type: str
        #     amount: int
        #
        #     @classmethod
        #     def __compose__(cls, ctx: Context) -> Self:
        #         return cls(
        #             user_id=ctx.get("user_id"),
        #             bet_type=ctx.get("bet_type"),
        #             amount=ctx.get("amount"),
        #         )
    """
    from dataclasses import fields as get_fields

    try:
        from nodnod import DataNode
    except ImportError:
        raise ImportError("nodnod required for to_datanode_from_context()")

    try:
        from telegrinder.bot.dispatch.context import Context
    except ImportError:
        raise ImportError("telegrinder required for to_datanode_from_context()")

    field_names = [f.name for f in get_fields(cls)]
    extractors = field_extractors or {name: name for name in field_names}

    def make_compose(ext: dict[str, str], fields: list[str]):  # type: ignore[reportUnknownParameterType]
        """Create __compose__ classmethod that extracts from Context."""
        def __compose__(node_cls, ctx):  # type: ignore[reportUnknownParameterType]
            extracted = {}
            for name in fields:
                ctx_key = ext.get(name, name)
                value = ctx.get(ctx_key)  # type: ignore[reportUnknownMemberType]
                if value is not None:
                    extracted[name] = value
            return node_cls(**extracted)  # type: ignore[reportUnknownVariableType]

        # Set annotations for nodnod — Context is the only dependency
        __compose__.__annotations__ = {
            "ctx": Context,
            "return": cls,
        }
        return classmethod(__compose__)  # type: ignore[reportUnknownVariableType]

    # Create new class inheriting from DataNode
    new_cls = type(
        f"{cls.__name__}Node",
        (cls, DataNode),
        {
            "__compose__": make_compose(extractors, field_names),  # type: ignore[reportUnknownArgumentType]
            "__module__": cls.__module__,
        },
    )

    return new_cls


__all__ = (
    "to_pydantic",
    "to_argparse_args",
    "ArgSpec",
    "to_datanode",
    "to_datanode_auto",
    "to_datanode_from_context",
)
