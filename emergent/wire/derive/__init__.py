"""Derivation infrastructure — entity -> wire Endpoint via capabilities.

    from emergent.wire.derive import DeriveCtx, compile_derive, materialize

    @schema_meta(http_crud("/api/users", Users), Paginated(20), Readonly())
    @dataclass
    class User:
        id: Annotated[int, Identity]
        name: str

    ctx = compile_derive(User)
    endpoint = materialize(ctx)
"""

from emergent.wire.derive._builders import ExposureBuilder, endpoint_builder, exposure
from emergent.wire.derive._codegen import DirectMapper, ResultConversion
from emergent.wire.derive._compile import compile_derive
from emergent.wire.derive._crud import CRUD, cli_crud, crud, http_crud
from emergent.wire.derive._ctx import DeriveCtx, Operation, OperationHandler
from emergent.wire.derive._explain import derive_dict, explain_derive, explain_entity
from emergent.wire.derive._handler import DescriptiveTemplate
from emergent.wire.derive._materialize import materialize
from emergent.wire.derive._metadata import DerivedMetadata
from emergent.wire.derive._project import (
    ComposedResponseSpec,
    ResponseConverterProto,
    ResponseProjection,
    composed_response,
)
from emergent.wire.derive._protocols import (
    DeriveAugmentable,
    DeriveGeneratable,
    DeriveModifiable,
)
from emergent.wire.derive._opspec import OpLike, generate_specs, normalize_op
from emergent.wire.derive._query_strategy import (
    NoQueryStrategy,
    ProviderInjection,
    QueryStrategy,
    RelationalStrategy,
)
from emergent.wire.derive._transforms import (
    CreateOnly,
    EffectDeprecated,
    EffectRateLimited,
    Filtered,
    MutationsOnly,
    OnlyOps,
    Paginated,
    ProjectResponse,
    Readonly,
    Searchable,
    SoftDelete,
    Sorted,
    Timestamped,
    UpdateOnly,
    WithoutCreate,
    WithoutDelete,
    WithRateLimit,
    WithRetry,
    WithTimeout,
)
from emergent.wire.derive._pipeline import Pipeline, PipelineContext, PipelineStep
from emergent.wire.derive._scoped import Scoped, scoped
from emergent.wire.derive._trigger import (
    FilteredTriggerGen,
    MultiTriggerGen,
    PrefixedTriggerGen,
)

__all__ = (
    # Core
    "DeriveCtx",
    "Operation",
    "OperationHandler",
    "DeriveGeneratable",
    "DeriveModifiable",
    "DeriveAugmentable",
    "compile_derive",
    "materialize",
    # CRUD
    "CRUD",
    "crud",
    "http_crud",
    "cli_crud",
    # Op helpers
    "DescriptiveTemplate",
    "OpLike",
    "normalize_op",
    "generate_specs",
    # Query Strategy
    "QueryStrategy",
    "RelationalStrategy",
    "NoQueryStrategy",
    "ProviderInjection",
    # Metadata
    "DerivedMetadata",
    # Codegen
    "DirectMapper",
    "ResultConversion",
    # Response
    "ResponseProjection",
    "ResponseConverterProto",
    "ComposedResponseSpec",
    "composed_response",
    # Pipeline
    "Pipeline",
    "PipelineStep",
    "PipelineContext",
    # Triggers
    "FilteredTriggerGen",
    "PrefixedTriggerGen",
    "MultiTriggerGen",
    # Transforms
    "Paginated",
    "Sorted",
    "Readonly",
    "MutationsOnly",
    "WithoutDelete",
    "WithoutCreate",
    "CreateOnly",
    "UpdateOnly",
    "OnlyOps",
    "ProjectResponse",
    "SoftDelete",
    "Timestamped",
    "Filtered",
    "Searchable",
    "WithTimeout",
    "WithRetry",
    "WithRateLimit",
    "EffectRateLimited",
    "EffectDeprecated",
    # Scoped
    "Scoped",
    "scoped",
    # Builders
    "ExposureBuilder",
    "exposure",
    "endpoint_builder",
    # Explain
    "explain_derive",
    "explain_entity",
    "derive_dict",
)
