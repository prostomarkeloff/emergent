"""Schema axis — dataclass annotations that compile to multiple backends.

    from emergent.wire.axis.schema import (
        Identity, Unique, Min, Max, MinLen, MaxLen, Pattern, Doc,
        PydanticContext, OpenAPIContext, openapi_schema,
    )

    @dataclass
    class User:
        email: Annotated[str, Unique, MaxLen(255), Doc("User email")]
"""

from emergent.wire.axis.schema._universal import (
    Capability,
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
    FieldInfo,
    inspect_field,
    inspect_dataclass,
    get_table_capabilities,
    DIALECT_BASES,
)

from emergent.wire.axis.schema import dialects

__all__ = (
    # Base
    "Capability",
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
    # Introspection
    "FieldInfo",
    "inspect_field",
    "inspect_dataclass",
    "get_table_capabilities",
    "DIALECT_BASES",
    # Dialects
    "dialects",
)
