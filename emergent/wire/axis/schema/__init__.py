"""Schema axis — dataclass annotations that compile to multiple backends.

    from emergent.wire.axis.schema import (
        Identity, Unique, Min, Max, MinLen, MaxLen, Pattern, Doc,
        PydanticContext, OpenAPIContext, openapi_schema,
    )

    @dataclass
    class User:
        email: Annotated[str, Unique, MaxLen(255), Doc("User email")]

## Type Inspection — Pure Composable Inspectors

Unified inspection for ANY structured type (dataclass, Pydantic, TypedDict, NamedTuple):

    from emergent.wire.axis.schema import inspect_type, FieldInfo

    # Works for any supported type
    fields = inspect_type(User)  # dataclass, Pydantic, TypedDict, NamedTuple

    for name, info in fields.items():
        print(f"{name}: {info.base_type}")
        print(f"  universal: {info.universal}")
        print(f"  sql: {info.dialect('sql')}")

Custom composition with `first_match`:

    from emergent.wire.axis.schema import (
        first_match, dataclass_inspector, pydantic_inspector
    )

    # Prioritize attrs over dataclass
    my_inspector = first_match(
        attrs_inspector,
        dataclass_inspector,
        pydantic_inspector,
    )
    axes = Axes(schema=my_inspector)
"""

from emergent.wire.axis.schema._universal import (
    SchemaAxisCapability,
    UniversalCapability,
    SchemaCapability,
    schema_meta,
    get_schema_meta,
    get_schema_capability,
    Identity,
    Unique,
    Ref,
    Min,
    Max,
    ExclusiveMin,
    ExclusiveMax,
    MultipleOf,
    MinLen,
    MaxLen,
    Pattern,
    OneOf,
    Either,
    Embedded,
    Doc,
    Deprecated,
)

from emergent.wire.axis._capability import (
    PydanticContext,
    OpenAPIContext,
    ArgparseContext,
    SQLAlchemyContext,
    PydanticCompilable,
    OpenAPICompilable,
    ArgparseCompilable,
    SQLAlchemyCompilable,
    openapi_schema,
    argparse_arg,
    sqlalchemy_column,
    combine,
)

from emergent.wire.axis.schema._compilable import (
    OpenAPISchema,
    SQLAlchemyConfig,
    ProtobufSchema,
)

from emergent.wire.axis.schema._patterns import (
    Id,
    Email,
    Slug,
    Username,
    Short,
    Medium,
    RequiredShort,
    Positive,
    Percentage,
    Probability,
    UniqueValue,
)

from emergent.wire.axis.schema._inspect import (
    # Core types
    FieldInfo,
    Inspector,
    # Combinator
    first_match,
    # Individual inspectors (for custom composition)
    dataclass_inspector,
    pydantic_inspector,
    typeddict_inspector,
    namedtuple_inspector,
    # Default composed inspector
    inspect_type,
    # Backwards compat
    inspect_dataclass,
    # Helpers
    inspect_field,
    unwrap_optional,
    unwrap_annotated,
    extract_capabilities,
    # Dialect registry
    DIALECT_BASES,
)

from emergent.wire.axis.schema import dialects

__all__ = (
    # Base
    "SchemaAxisCapability",
    "UniversalCapability",
    "SchemaCapability",
    "schema_meta",
    "get_schema_meta",
    "get_schema_capability",
    # Universal
    "Identity",
    "Unique",
    "Ref",
    "Min",
    "Max",
    "ExclusiveMin",
    "ExclusiveMax",
    "MultipleOf",
    "MinLen",
    "MaxLen",
    "Pattern",
    "OneOf",
    "Either",
    "Embedded",
    "Doc",
    "Deprecated",
    # Contexts
    "PydanticContext",
    "OpenAPIContext",
    "ArgparseContext",
    "SQLAlchemyContext",
    # Protocols
    "PydanticCompilable",
    "OpenAPICompilable",
    "ArgparseCompilable",
    "SQLAlchemyCompilable",
    # Helpers (pydantic uses FieldInfo.merge_field_infos directly)
    "openapi_schema",
    "argparse_arg",
    "sqlalchemy_column",
    "combine",
    # TypedDicts
    "OpenAPISchema",
    "SQLAlchemyConfig",
    "ProtobufSchema",
    # Patterns
    "Id",
    "Email",
    "Slug",
    "Username",
    "Short",
    "Medium",
    "RequiredShort",
    "Positive",
    "Percentage",
    "Probability",
    "UniqueValue",
    # Introspection — Core types
    "FieldInfo",
    "Inspector",
    # Introspection — Combinator
    "first_match",
    # Introspection — Individual inspectors (for custom composition)
    "dataclass_inspector",
    "pydantic_inspector",
    "typeddict_inspector",
    "namedtuple_inspector",
    # Introspection — Default composed inspector
    "inspect_type",
    # Introspection — Backwards compat
    "inspect_dataclass",
    # Introspection — Helpers
    "inspect_field",
    "unwrap_optional",
    "unwrap_annotated",
    "extract_capabilities",
    "DIALECT_BASES",
    # Dialects
    "dialects",
)
