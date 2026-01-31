"""Schema axis — dataclass annotations that compile to multiple backends.

Dataclasses with Annotated fields carry semantic metadata that compilers translate
to backend-specific constructs (SQLAlchemy models, OpenAPI schemas, Pydantic models).

    from emergent.wire.axis.schema import (
        # Universal capabilities (all compilers understand)
        Identity, Unique, Ref, Min, Max, MinLen, MaxLen, Pattern, OneOf, Either,
        # Common patterns (pre-built capability tuples)
        Id, Email, Slug, Username,
        # Introspection
        inspect_dataclass, FieldInfo,
    )
    from emergent.wire.axis.schema.dialects import sql, openapi, pydantic

    @dataclass
    class User:
        id: Annotated[int, Id]
        email: Annotated[str,
            Email,                       # Pattern: Unique + MaxLen(255)
            sql.Index("idx_email"),      # SQL only
            openapi.Format("email"),     # OpenAPI only
            pydantic.Strict(),           # Pydantic only
        ]

Each compiler takes what it understands and ignores the rest.
"""

# Universal capabilities
from emergent.wire.axis.schema._universal import (
    Capability,
    UniversalCapability,
    Identity,
    Unique,
    Ref,
    Min,
    Max,
    MinLen,
    MaxLen,
    Pattern,
    OneOf,
    Either,
    Embedded,
    Doc,
    Deprecated,
)

# Compilation protocols (for custom capabilities)
from emergent.wire.axis.schema._compilable import (
    OpenAPICompilable,
    SQLAlchemyCompilable,
    PydanticCompilable,
    CLICompilable,
    ProtobufCompilable,
    compile_openapi,
    compile_pydantic,
    compile_cli,
)

# Patterns (common capability compositions)
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

# Introspection
from emergent.wire.axis.schema._inspect import (
    FieldInfo,
    inspect_field,
    inspect_dataclass,
    get_table_capabilities,
    DIALECT_BASES,
)

# Dialects namespace
from emergent.wire.axis.schema import dialects

__all__ = (
    # Base
    "Capability",
    "UniversalCapability",
    # Universal capabilities
    "Identity",
    "Unique",
    "Ref",
    "Min",
    "Max",
    "MinLen",
    "MaxLen",
    "Pattern",
    "OneOf",
    "Either",
    "Embedded",
    "Doc",
    "Deprecated",
    # Compilation protocols
    "OpenAPICompilable",
    "SQLAlchemyCompilable",
    "PydanticCompilable",
    "CLICompilable",
    "ProtobufCompilable",
    "compile_openapi",
    "compile_pydantic",
    "compile_cli",
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
