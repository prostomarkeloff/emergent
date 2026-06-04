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

from __future__ import annotations

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


from collections.abc import Callable
from typing import Any, TYPE_CHECKING

from emergent.wire.axis.schema._universal import SchemaCapability

if TYPE_CHECKING:
    from emergent.wire.axis.surface._app import Application
    from emergent.wire.axis.surface._endpoint import Endpoint

# ═══════════════════════════════════════════════════════════════════════════════
# High-level helpers (ported from derivelib)
# ═══════════════════════════════════════════════════════════════════════════════


def derive[T](*caps: SchemaCapability) -> Callable[[T], T]:
    """Decorator: attach capabilities to entity class.

    Alias for ``@schema_meta(*caps)``.

        @derive(http_crud("/users", Users))
        @dataclass
        class User:
            id: Annotated[int, Identity]
            name: str
    """
    from emergent.wire.axis.schema._universal import schema_meta
    return schema_meta(*caps)


def memory_node(key_field: str = "id", auto_id: bool = True) -> type:
    """Create a nodnod scalar_node backed by in-memory relational provider.

        Users = memory_node()

        @derive(http_crud("/users", Users))
        @dataclass
        class User:
            id: Annotated[int, Identity]
            name: str
    """
    from typing import Any as _Any

    from nodnod import scalar_node

    from emergent.wire.axis.query._provider import (
        MutatingRelationalProvider,
        SequenceNextId,
    )
    from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider

    next_id = SequenceNextId() if auto_id else None
    store: MemoryRelationalProvider[_Any] = MemoryRelationalProvider(
        key_fn=lambda x: getattr(x, key_field),
        next_id=next_id,
    )

    @scalar_node
    class _Node:
        @classmethod
        def __compose__(cls) -> MutatingRelationalProvider[_Any]:
            return store

    return _Node


def build_application_from_decorated(*entities: type) -> Application:
    """Compile @derive-decorated entities into a wire Application.

        Users = memory_node()

        @derive(http_crud("/users", Users))
        @dataclass
        class User: ...

        app = build_application_from_decorated(User)
        fastapi_app = targets.fastapi.compile(app)
    """
    from emergent.wire.axis.surface._app import application

    endpoints: list[Endpoint] = []
    for entity in entities:
        derive_ctxs: list[DeriveCtx[Any]] = compile_derive(entity)
        for ctx in derive_ctxs:
            endpoints.append(materialize(ctx))
    app = application()
    for ep in endpoints:
        app = app.mount(ep)
    return app


def endpoint_count(app: Application) -> int:
    """Count total exposures across all endpoints."""
    return sum(len(ep.exposures) for ep in app.endpoints)




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
    # High-level helpers
    "derive",
    "memory_node",
    "build_application_from_decorated",
    "endpoint_count",
)
