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
        print(f"  sql: {info.dialect(SQLCapability)}")

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
    # Schema-level capabilities
    SchemaName,
    SchemaDoc,
    Abstract,
    # Field-level capabilities
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
    Nested,
    Embedded,
    Doc,
    Deprecated,
    ReadOnly,
    WriteOnly,
    Sensitive,
    Immutable,
    Nullable,
    Alias,
    Computed,
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
    pydantic_metadata,
    pydantic_extra,
    pydantic_field,
    combine,
    ExtraColumnSpec,
    ExtraFieldSpec,
    UNSET,
)

from emergent.wire.axis.schema._compilable import (
    OpenAPISchema,
    SQLAlchemyConfig,
)

from emergent.wire.axis.schema._patterns import (
    Id,
    Email,
    Slug,
    Username,
    Short,
    Medium,
    RequiredShort,
    NonNegative,
    Percentage,
    Probability,
    UniqueValue,
)

from emergent.wire.axis.schema._inspect import (
    # Core types
    FieldInfo,
    NO_DEFAULT,
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
    # Nested type helpers
    is_structured_type,
    unwrap_collection,
    get_nested_info,
    get_nested_type,
)

from emergent.wire.axis.schema._explain import (
    schema_dict,
    field_info_dict,
    explain_schema,
    explain_field,
)

from emergent.wire.axis.schema.dialects.sql import (
    CompositeUnique,
    CompositeIndex,
)

from emergent.wire.axis.schema.dialects.openapi import (
    Discriminator,
)

from emergent.wire.axis.schema import dialects

# Helpers — pure functions for schema navigation and capability composition
from emergent.wire.axis.schema import _helpers as helpers
from emergent.wire.axis.schema._helpers import (
    # Navigation
    get_identity_field,
    get_required_fields,
    get_optional_fields,
    partition_fields,
    field_by_name,
    field_path_type,
    fields_with_capability,
    get_refs,
    fields_by_dialect,
    # Composition
    merge_capabilities,
    override_capability,
    remove_capability,
    deduplicate_capabilities,
    filter_by_dialect,
    filter_universal,
    # Queries
    find_capability,
    find_all_capabilities,
    has_capability,
    # Schema meta composition
    compose_schema_meta,
    get_nested_schema_meta,
)

__all__ = (
    # Base
    "SchemaAxisCapability",
    "UniversalCapability",
    "SchemaCapability",
    "schema_meta",
    "get_schema_meta",
    "get_schema_capability",
    # Schema-level
    "SchemaName",
    "SchemaDoc",
    "CompositeUnique",
    "CompositeIndex",
    "Discriminator",
    "Abstract",
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
    "Nested",
    "Embedded",
    "Doc",
    "Deprecated",
    # Access control
    "ReadOnly",
    "WriteOnly",
    "Sensitive",
    "Immutable",
    # Nullability
    "Nullable",
    # Naming
    "Alias",
    # Computed
    "Computed",
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
    # Helpers
    "openapi_schema",
    "argparse_arg",
    "sqlalchemy_column",
    "pydantic_metadata",
    "pydantic_extra",
    "pydantic_field",
    "combine",
    # Spec types (generic)
    "ExtraColumnSpec",
    "ExtraFieldSpec",
    "UNSET",
    # TypedDicts
    "OpenAPISchema",
    "SQLAlchemyConfig",
    # Patterns
    "Id",
    "Email",
    "Slug",
    "Username",
    "Short",
    "Medium",
    "RequiredShort",
    "NonNegative",
    "Percentage",
    "Probability",
    "UniqueValue",
    # Introspection — Core types
    "FieldInfo",
    "Inspector",
    "NO_DEFAULT",
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
    # Introspection — Nested type helpers
    "is_structured_type",
    "unwrap_collection",
    "get_nested_info",
    "get_nested_type",
    # Dialects
    "dialects",
    # Helpers namespace
    "helpers",
    # Helper functions — Navigation
    "get_identity_field",
    "get_required_fields",
    "get_optional_fields",
    "partition_fields",
    "field_by_name",
    "field_path_type",
    "fields_with_capability",
    "get_refs",
    "fields_by_dialect",
    # Helper functions — Composition
    "merge_capabilities",
    "override_capability",
    "remove_capability",
    "deduplicate_capabilities",
    "filter_by_dialect",
    "filter_universal",
    # Helper functions — Queries
    "find_capability",
    "find_all_capabilities",
    "has_capability",
    # Helper functions — Schema meta composition
    "compose_schema_meta",
    "get_nested_schema_meta",
    # Explain
    "schema_dict",
    "field_info_dict",
    "explain_schema",
    "explain_field",
)
