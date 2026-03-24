"""Tests for the compiler development guide examples.

Every code example in the guide is tested here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace, field
from typing import Annotated, Protocol, runtime_checkable

import pytest

from emergent.wire.axis._capability import (
    Capability,
    PydanticContext,
    PydanticCompilable,
    OpenAPIContext,
    OpenAPICompilable,
    ArgparseContext,
    ArgparseCompilable,
    pydantic_field,
    openapi_schema,
    argparse_arg,
)
from emergent.wire.axis.schema import inspect_dataclass, FieldInfo
from emergent.wire.axis.schema._universal import UniversalCapability
from emergent.wire.compile._core import Axes, fold, fold_field, CapabilityHandler
from emergent.wire.compile._phase import (
    CompilationPhase,
    FieldCompilation,
    EntityCompilation,
    SchemaCompiler,
    compile_fields,
    compile_entity,
    PYDANTIC_PHASE,
    OPENAPI_PHASE,
    ARGPARSE_PHASE,
    FASTAPI_SCHEMA,
    CLI_SCHEMA,
)
from emergent.wire.compile._target import CodecBinding, TargetCompiler


# ═══════════════════════════════════════════════════════════════════════════════
# LEVEL 1: Custom Compilation Phase
# ═══════════════════════════════════════════════════════════════════════════════


# --- Example: GraphQL Phase ---

@dataclass(frozen=True, slots=True)
class GraphQLContext:
    """Per-field context for GraphQL type compilation."""
    field_name: str
    field_type: type
    graphql_type: str | None = None
    nullable: bool = True
    description: str | None = None
    deprecation_reason: str | None = None


@runtime_checkable
class GraphQLCompilable(Protocol):
    def compile_graphql(self, ctx: GraphQLContext) -> GraphQLContext: ...


def _graphql_initial(name: str, field_type: type) -> GraphQLContext:
    """Map Python types to GraphQL scalar types."""
    type_map: dict[type, str] = {
        str: "String",
        int: "Int",
        float: "Float",
        bool: "Boolean",
    }
    return GraphQLContext(
        field_name=name,
        field_type=field_type,
        graphql_type=type_map.get(field_type),
    )


GRAPHQL_PHASE = CompilationPhase(
    GraphQLContext, GraphQLCompilable, _graphql_initial,
)


class TestLevel1CustomPhase:
    """Test custom compilation phase creation."""

    def test_phase_method_auto_derived(self):
        assert GRAPHQL_PHASE.method == "compile_graphql"

    def test_phase_identity_by_context_type(self):
        assert GRAPHQL_PHASE.context_type is GraphQLContext

    def test_initial_maps_python_to_graphql(self):
        ctx = _graphql_initial("name", str)
        assert ctx.graphql_type == "String"
        assert ctx.field_name == "name"

    def test_initial_unknown_type(self):
        ctx = _graphql_initial("data", bytes)
        assert ctx.graphql_type is None

    def test_compile_fields_with_custom_phase(self):
        """compile_fields runs GraphQL phase alongside built-in phases."""

        @dataclass
        class User:
            name: str
            age: int

        axes = Axes.default()
        fields = compile_fields(User, axes, [GRAPHQL_PHASE])

        assert len(fields) == 2
        name_ctx = fields[0][GRAPHQL_PHASE]
        assert name_ctx.graphql_type == "String"
        age_ctx = fields[1][GRAPHQL_PHASE]
        assert age_ctx.graphql_type == "Int"

    def test_compile_alongside_pydantic(self):
        """Custom phase runs side-by-side with Pydantic phase."""

        @dataclass
        class Item:
            title: str
            price: float

        axes = Axes.default()
        fields = compile_fields(Item, axes, [PYDANTIC_PHASE, GRAPHQL_PHASE])

        for fc in fields:
            # Both phases produce results
            pydantic_ctx = fc[PYDANTIC_PHASE]
            graphql_ctx = fc[GRAPHQL_PHASE]
            assert pydantic_ctx is not None
            assert graphql_ctx is not None

        assert fields[1][GRAPHQL_PHASE].graphql_type == "Float"


# ═══════════════════════════════════════════════════════════════════════════════
# LEVEL 2: Custom Capability that compiles to multiple phases
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class NonNull(UniversalCapability):
    """Mark field as non-nullable in GraphQL + required in Pydantic + no-default in argparse.

    ONE capability → THREE compile_* methods → THREE compilation targets.
    Inherits UniversalCapability so inspect_dataclass picks it up from Annotated.
    """

    def compile_graphql(self, ctx: GraphQLContext) -> GraphQLContext:
        return replace(ctx, nullable=False)

    def compile_pydantic(self, ctx: PydanticContext) -> PydanticContext:
        return pydantic_field(ctx, lambda fi: fi.metadata.append({"required": True}))

    def compile_argparse(self, ctx: ArgparseContext) -> ArgparseContext:
        return argparse_arg(ctx, required=True)


@dataclass(frozen=True, slots=True)
class GQLDescription(UniversalCapability):
    """Describe field for GraphQL + OpenAPI simultaneously.

    Inherits UniversalCapability — visible to ALL compilation phases.
    """
    text: str

    def compile_graphql(self, ctx: GraphQLContext) -> GraphQLContext:
        return replace(ctx, description=self.text)

    def compile_openapi(self, ctx: OpenAPIContext) -> OpenAPIContext:
        return openapi_schema(ctx, description=self.text)


@dataclass(frozen=True, slots=True)
class Deprecated(UniversalCapability):
    """Mark field as deprecated in GraphQL + OpenAPI.

    Inherits UniversalCapability — visible to ALL compilation phases.
    """
    reason: str = ""

    def compile_graphql(self, ctx: GraphQLContext) -> GraphQLContext:
        return replace(ctx, deprecation_reason=self.reason or "deprecated")

    def compile_openapi(self, ctx: OpenAPIContext) -> OpenAPIContext:
        return openapi_schema(ctx, deprecated=True)


class TestLevel2MultiPhaseCapability:
    """Test capabilities that compile to multiple phases."""

    def test_non_null_compiles_graphql(self):
        ctx = GraphQLContext("name", str, "String")
        assert ctx.nullable is True
        result = NonNull().compile_graphql(ctx)
        assert result.nullable is False

    def test_non_null_compiles_argparse(self):
        ctx = ArgparseContext("name", str)
        result = NonNull().compile_argparse(ctx)
        assert result.kwargs["required"] is True

    def test_description_compiles_both(self):
        desc = GQLDescription("User's full name")
        gql_ctx = desc.compile_graphql(GraphQLContext("name", str))
        oapi_ctx = desc.compile_openapi(OpenAPIContext("name", str))
        assert gql_ctx.description == "User's full name"
        assert oapi_ctx.schema["description"] == "User's full name"

    def test_deprecated_compiles_both(self):
        dep = Deprecated("use email instead")
        gql_ctx = dep.compile_graphql(GraphQLContext("name", str))
        oapi_ctx = dep.compile_openapi(OpenAPIContext("name", str))
        assert gql_ctx.deprecation_reason == "use email instead"
        assert oapi_ctx.schema["deprecated"] is True

    def test_multi_cap_field_compiles_through_fold(self):
        """Capabilities on Annotated fold through all phases correctly."""

        @dataclass
        class Product:
            name: Annotated[str, NonNull(), GQLDescription("Product name")]
            old_code: Annotated[str, Deprecated("use sku")]

        axes = Axes.default()
        fields = compile_fields(
            Product, axes, [GRAPHQL_PHASE, OPENAPI_PHASE, ARGPARSE_PHASE]
        )

        name_gql = fields[0][GRAPHQL_PHASE]
        assert name_gql.nullable is False
        assert name_gql.description == "Product name"

        name_oapi = fields[0][OPENAPI_PHASE]
        assert name_oapi.schema.get("description") == "Product name"

        name_argparse = fields[0][ARGPARSE_PHASE]
        assert name_argparse.kwargs.get("required") is True

        old_gql = fields[1][GRAPHQL_PHASE]
        assert old_gql.deprecation_reason == "use sku"

        old_oapi = fields[1][OPENAPI_PHASE]
        assert old_oapi.schema.get("deprecated") is True


# ═══════════════════════════════════════════════════════════════════════════════
# LEVEL 3: Custom Handlers (override protocol dispatch per type)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class SpecialFormat(UniversalCapability):
    """Not GraphQLCompilable — but handler intercepts it."""
    pattern: str


@dataclass(frozen=True, slots=True)
class SpecialCap(UniversalCapability):
    value: int


@dataclass
class _ItemWithFormat:
    code: Annotated[str, SpecialFormat(r"\d{4}-\w+")]


@dataclass
class _ThingWithSpecial:
    x: Annotated[int, SpecialCap(42)]


class TestLevel3CustomHandlers:
    """Test custom handlers that override protocol dispatch."""

    def test_handler_overrides_capability(self):
        """Custom handler intercepts specific capability type in fold."""

        def special_format_handler(
            cap: Capability, ctx: GraphQLContext
        ) -> GraphQLContext:
            assert isinstance(cap, SpecialFormat)
            return replace(ctx, description=f"format: {cap.pattern}")

        axes = Axes.default()
        phase_with_handler = GRAPHQL_PHASE.with_handlers(
            {SpecialFormat: special_format_handler}
        )

        fields = compile_fields(_ItemWithFormat, axes, [phase_with_handler])
        code_ctx = fields[0][phase_with_handler]
        assert code_ctx.description == r"format: \d{4}-\w+"

    def test_handler_does_not_affect_other_phases(self):
        """Handler on one phase doesn't interfere with others."""

        def gql_handler(cap: Capability, ctx: GraphQLContext) -> GraphQLContext:
            assert isinstance(cap, SpecialCap)
            return replace(ctx, description=f"special-{cap.value}")

        gql_phase = GRAPHQL_PHASE.with_handlers({SpecialCap: gql_handler})

        axes = Axes.default()
        fields = compile_fields(_ThingWithSpecial, axes, [gql_phase, OPENAPI_PHASE])

        gql_ctx = fields[0][gql_phase]
        assert gql_ctx.description == "special-42"

        oapi_ctx = fields[0][OPENAPI_PHASE]
        assert oapi_ctx.schema.get("description") is None  # SpecialCap is NOT OpenAPICompilable


# ═══════════════════════════════════════════════════════════════════════════════
# LEVEL 4: SchemaCompiler Algebra
# ═══════════════════════════════════════════════════════════════════════════════


GRAPHQL_SCHEMA = SchemaCompiler(phases=(GRAPHQL_PHASE,))


class TestLevel4SchemaCompilerAlgebra:
    """Test SchemaCompiler algebraic operations."""

    def test_compose_two_compilers(self):
        """GRAPHQL + FASTAPI = both phases run."""
        combined = GRAPHQL_SCHEMA + FASTAPI_SCHEMA
        assert len(combined) == 3  # GraphQL + Pydantic + OpenAPI

    def test_compose_is_left_biased(self):
        """Left side's version wins on duplicate context_type."""
        custom_gql = CompilationPhase(
            GraphQLContext, GraphQLCompilable,
            lambda n, t: GraphQLContext(n, t, graphql_type="CustomScalar"),
        )
        custom = SchemaCompiler(phases=(custom_gql,))
        result = custom + GRAPHQL_SCHEMA
        assert len(result) == 1  # deduplicated

        @dataclass
        class X:
            v: int

        ec = result.compile(X, Axes.default())
        gql = list(ec)[0][result.phases[0]]
        assert gql.graphql_type == "CustomScalar"

    def test_override_with_pipe(self):
        """| operator overrides left with right."""
        custom_gql = CompilationPhase(
            GraphQLContext, GraphQLCompilable,
            lambda n, t: GraphQLContext(n, t, graphql_type="Overridden"),
        )
        result = GRAPHQL_SCHEMA | SchemaCompiler(phases=(custom_gql,))

        @dataclass
        class Y:
            v: str

        ec = result.compile(Y, Axes.default())
        gql = list(ec)[0][result.phases[0]]
        assert gql.graphql_type == "Overridden"

    def test_subtract_phase(self):
        combined = FASTAPI_SCHEMA + GRAPHQL_SCHEMA
        assert len(combined) == 3
        reduced = combined - GRAPHQL_PHASE
        assert len(reduced) == 2
        assert GRAPHQL_PHASE not in reduced

    def test_intersect(self):
        a = FASTAPI_SCHEMA + GRAPHQL_SCHEMA
        b = GRAPHQL_SCHEMA + CLI_SCHEMA
        common = a & b
        assert len(common) == 1
        assert GRAPHQL_PHASE in common

    def test_membership(self):
        assert GRAPHQL_PHASE in GRAPHQL_SCHEMA
        assert PYDANTIC_PHASE not in GRAPHQL_SCHEMA

    def test_lookup_by_context_type(self):
        compiler = FASTAPI_SCHEMA + GRAPHQL_SCHEMA
        phase = compiler[GraphQLContext]
        assert phase.context_type is GraphQLContext


# ═══════════════════════════════════════════════════════════════════════════════
# LEVEL 5: fold() — the universal primitive
# ═══════════════════════════════════════════════════════════════════════════════


class TestLevel5FoldPrimitive:
    """Test fold() behavior and edge cases."""

    def test_fold_skips_non_matching(self):
        """Items that don't implement protocol are silently skipped."""

        @dataclass(frozen=True, slots=True)
        class NotGraphQL:
            value: int

        items = [NotGraphQL(1), NotGraphQL(2)]
        ctx = GraphQLContext("x", int, "Int")
        result = fold(items, ctx, GraphQLCompilable, "compile_graphql")
        assert result is ctx  # unchanged — nothing matched

    def test_fold_applies_matching(self):
        items = [NonNull()]
        ctx = GraphQLContext("x", int, "Int", nullable=True)
        result = fold(items, ctx, GraphQLCompilable, "compile_graphql")
        assert result.nullable is False

    def test_fold_order_matters(self):
        """Last matching capability wins (left-to-right fold)."""

        @dataclass(frozen=True, slots=True)
        class SetDesc:
            text: str
            def compile_graphql(self, ctx: GraphQLContext) -> GraphQLContext:
                return replace(ctx, description=self.text)

        items = [SetDesc("first"), SetDesc("second")]
        ctx = GraphQLContext("x", str, "String")
        result = fold(items, ctx, GraphQLCompilable, "compile_graphql")
        assert result.description == "second"

    def test_fold_with_handler_overrides_protocol(self):
        """Custom handler takes priority over isinstance check."""

        @dataclass(frozen=True, slots=True)
        class Both:
            """Implements GraphQLCompilable AND has a handler."""
            def compile_graphql(self, ctx: GraphQLContext) -> GraphQLContext:
                return replace(ctx, description="from protocol")

        def handler(item: Capability, ctx: GraphQLContext) -> GraphQLContext:
            return replace(ctx, description="from handler")

        ctx = GraphQLContext("x", str, "String")
        result = fold(
            [Both()], ctx, GraphQLCompilable, "compile_graphql",
            handlers={Both: handler},
        )
        assert result.description == "from handler"

    def test_fold_empty_items(self):
        ctx = GraphQLContext("x", str, "String")
        result = fold([], ctx, GraphQLCompilable, "compile_graphql")
        assert result is ctx

    def test_fold_mixed_items(self):
        """Only matching items are applied, rest skipped."""

        @dataclass(frozen=True, slots=True)
        class Unrelated:
            value: int

        items: list[object] = [
            Unrelated(1),
            NonNull(),
            Unrelated(2),
            GQLDescription("hello"),
        ]
        ctx = GraphQLContext("x", str, "String", nullable=True)
        result = fold(items, ctx, GraphQLCompilable, "compile_graphql")
        assert result.nullable is False
        assert result.description == "hello"


# ═══════════════════════════════════════════════════════════════════════════════
# LEVEL 6: Traced Compilation (explain / debug)
# ═══════════════════════════════════════════════════════════════════════════════


class TestLevel6TracedCompilation:
    """Test traced compilation for debugging and introspection."""

    def test_traced_axes_records_events(self):
        from emergent.wire.compile._trace import ListCollector

        @dataclass
        class User:
            name: Annotated[str, NonNull(), GQLDescription("Full name")]

        collector = ListCollector()
        axes = Axes.traced(collector)
        compile_fields(User, axes, [GRAPHQL_PHASE])

        assert len(collector.field_phases) > 0
        fp = collector.field_phases[0]
        assert fp.field_name == "name"
        assert fp.phase == "GraphQLContext"
        assert fp.fold.items_applied > 0

    def test_traced_fold_records_steps(self):
        from emergent.wire.compile._core import traced_fold
        from emergent.wire.compile._trace import ListCollector

        collector = ListCollector()
        items = [NonNull(), GQLDescription("test")]
        ctx = GraphQLContext("x", str, "String")

        result, trace = traced_fold(
            items, ctx, GraphQLCompilable, "compile_graphql",
            None, collector,
        )

        assert result.nullable is False
        assert result.description == "test"
        assert trace.items_total == 2
        assert trace.items_applied == 2
        assert all(s.changed for s in trace.steps)


# ═══════════════════════════════════════════════════════════════════════════════
# LEVEL 7: TargetCompiler Algebra
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class MockTrigger:
    name: str


@dataclass(frozen=True, slots=True)
class CodecA:
    data: str


@dataclass(frozen=True, slots=True)
class CodecB:
    value: int


@dataclass(frozen=True, slots=True)
class CodecC:
    flag: bool


def from_codec_a(codec: CodecA, trigger: MockTrigger) -> dict[str, str]:
    return {"source": "codec_a", "data": codec.data}


def from_codec_b(codec: CodecB, trigger: MockTrigger) -> dict[str, int]:
    return {"source": "codec_b", "value": codec.value}


def from_codec_c(codec: CodecC, trigger: MockTrigger) -> dict[str, bool]:
    return {"source": "codec_c", "flag": codec.flag}


def mock_assemble(ctx: object, handler: object, axes: Axes) -> str:
    return f"assembled:{ctx}"


MOCK_COMPILER: TargetCompiler[MockTrigger] = TargetCompiler(
    trigger_type=MockTrigger,
    adapters=(
        CodecBinding(CodecA, from_codec_a),
        CodecBinding(CodecB, from_codec_b),
    ),
    pipeline_protocol=type(None),
    pipeline_method="",
    assemble=mock_assemble,
)


class TestLevel7TargetCompilerAlgebra:
    """Test TargetCompiler algebraic operations."""

    def test_with_binding(self):
        extended = MOCK_COMPILER.with_binding(CodecC, from_codec_c)
        assert len(extended) == 3
        assert CodecC in extended

    def test_with_binding_duplicate_raises(self):
        with pytest.raises(ValueError, match="already present"):
            MOCK_COMPILER.with_binding(CodecA, from_codec_a)

    def test_replace_binding(self):
        def new_from_a(codec: CodecA, trigger: MockTrigger) -> dict[str, str]:
            return {"source": "replaced"}

        replaced = MOCK_COMPILER.replace_binding(CodecA, new_from_a)
        binding = replaced[CodecA]
        assert binding.from_codec is new_from_a

    def test_replace_binding_missing_raises(self):
        with pytest.raises(KeyError):
            MOCK_COMPILER.replace_binding(CodecC, from_codec_c)

    def test_without_binding(self):
        reduced = MOCK_COMPILER.without_binding(CodecA)
        assert len(reduced) == 1
        assert CodecA not in reduced
        assert CodecB in reduced

    def test_add_left_biased(self):
        other: TargetCompiler[MockTrigger] = TargetCompiler(
            trigger_type=MockTrigger,
            adapters=(CodecBinding(CodecC, from_codec_c),),
            pipeline_protocol=type(None),
            pipeline_method="",
            assemble=mock_assemble,
        )
        combined = MOCK_COMPILER + other
        assert len(combined) == 3

    def test_or_right_biased(self):
        def alt_from_a(codec: CodecA, trigger: MockTrigger) -> dict[str, str]:
            return {"source": "alt"}

        other: TargetCompiler[MockTrigger] = TargetCompiler(
            trigger_type=MockTrigger,
            adapters=(CodecBinding(CodecA, alt_from_a),),
            pipeline_protocol=type(None),
            pipeline_method="",
            assemble=mock_assemble,
        )
        merged = MOCK_COMPILER | other
        assert merged[CodecA].from_codec is alt_from_a

    def test_subtract(self):
        reduced = MOCK_COMPILER - CodecA
        assert len(reduced) == 1

    def test_intersect(self):
        other: TargetCompiler[MockTrigger] = TargetCompiler(
            trigger_type=MockTrigger,
            adapters=(CodecBinding(CodecA, from_codec_a), CodecBinding(CodecC, from_codec_c)),
            pipeline_protocol=type(None),
            pipeline_method="",
            assemble=mock_assemble,
        )
        common = MOCK_COMPILER & other
        assert len(common) == 1
        assert CodecA in common

    def test_lookup(self):
        binding = MOCK_COMPILER[CodecA]
        assert binding.from_codec is from_codec_a

    def test_lookup_missing_raises(self):
        with pytest.raises(KeyError):
            _ = MOCK_COMPILER[CodecC]


# ═══════════════════════════════════════════════════════════════════════════════
# LEVEL 8: Full Custom Target Compiler (end-to-end)
# ═══════════════════════════════════════════════════════════════════════════════


# --- MQTT Target Compiler Example ---

@dataclass(frozen=True, slots=True)
class MQTTTrigger:
    """WHERE: MQTT topic pattern."""
    topic: str
    qos: int = 0


@dataclass(frozen=True, slots=True)
class MQTTMessageCodec:
    """HOW: JSON message over MQTT."""
    payload_type: type
    response_type: type | None = None


@dataclass(frozen=True, slots=True)
class MQTTWrapContext:
    """Compile-time state accumulated by fold."""
    topic: str = ""
    qos: int = 0
    payload_type: type | None = None
    response_type: type | None = None
    retain: bool = False
    max_payload_size: int | None = None


@runtime_checkable
class MQTTPipelineCompilable(Protocol):
    def compile_mqtt_pipeline(self, ctx: MQTTWrapContext) -> MQTTWrapContext: ...


@dataclass(frozen=True, slots=True)
class MQTTRoute:
    """Compiled MQTT handler."""
    topic: str
    qos: int
    payload_type: type | None
    retain: bool
    max_payload_size: int | None


# from_codec
def mqtt_message_from_codec(
    codec: MQTTMessageCodec,
    trigger: MQTTTrigger,
) -> MQTTWrapContext:
    return MQTTWrapContext(
        topic=trigger.topic,
        qos=trigger.qos,
        payload_type=codec.payload_type,
        response_type=codec.response_type,
    )


# assembler
def assemble_mqtt_route(
    ctx: MQTTWrapContext,
    handler: object,
    axes: Axes,
) -> MQTTRoute:
    return MQTTRoute(
        topic=ctx.topic,
        qos=ctx.qos,
        payload_type=ctx.payload_type,
        retain=ctx.retain,
        max_payload_size=ctx.max_payload_size,
    )


# Capabilities
@dataclass(frozen=True, slots=True)
class Retained:
    """Mark MQTT message as retained."""
    def compile_mqtt_pipeline(self, ctx: MQTTWrapContext) -> MQTTWrapContext:
        return replace(ctx, retain=True)


@dataclass(frozen=True, slots=True)
class MaxPayload:
    """Limit MQTT payload size."""
    size: int
    def compile_mqtt_pipeline(self, ctx: MQTTWrapContext) -> MQTTWrapContext:
        return replace(ctx, max_payload_size=self.size)


@dataclass(frozen=True, slots=True)
class QoSOverride:
    """Override QoS at capability level."""
    qos: int
    def compile_mqtt_pipeline(self, ctx: MQTTWrapContext) -> MQTTWrapContext:
        return replace(ctx, qos=self.qos)


MQTT_COMPILER: TargetCompiler[MQTTTrigger] = TargetCompiler(
    trigger_type=MQTTTrigger,
    adapters=(
        CodecBinding(MQTTMessageCodec, mqtt_message_from_codec),
    ),
    pipeline_protocol=MQTTPipelineCompilable,
    pipeline_method="compile_mqtt_pipeline",
    assemble=assemble_mqtt_route,
)


class TestLevel8FullCustomTarget:
    """Test complete custom target compiler end-to-end."""

    def test_from_codec_seeds_context(self):
        codec = MQTTMessageCodec(payload_type=dict, response_type=None)
        trigger = MQTTTrigger(topic="sensors/temp", qos=1)
        ctx = mqtt_message_from_codec(codec, trigger)
        assert ctx.topic == "sensors/temp"
        assert ctx.qos == 1
        assert ctx.payload_type is dict

    def test_capability_refines_context(self):
        ctx = MQTTWrapContext(topic="t", qos=0)
        ctx = Retained().compile_mqtt_pipeline(ctx)
        assert ctx.retain is True

    def test_fold_capabilities(self):
        caps = [Retained(), MaxPayload(1024), QoSOverride(2)]
        ctx = MQTTWrapContext(topic="t", qos=0)
        result = fold(
            caps, ctx,
            MQTTPipelineCompilable, "compile_mqtt_pipeline",
        )
        assert result.retain is True
        assert result.max_payload_size == 1024
        assert result.qos == 2

    def test_assembler_produces_route(self):
        ctx = MQTTWrapContext(
            topic="sensors/temp", qos=2,
            payload_type=dict, retain=True, max_payload_size=4096,
        )
        route = assemble_mqtt_route(ctx, None, Axes.default())
        assert route.topic == "sensors/temp"
        assert route.qos == 2
        assert route.retain is True
        assert route.max_payload_size == 4096

    def test_full_pipeline(self):
        """from_codec → fold → assemble — complete pipeline."""
        codec = MQTTMessageCodec(payload_type=dict)
        trigger = MQTTTrigger(topic="devices/+/status", qos=1)
        caps = [Retained(), MaxPayload(2048)]

        # Step 1: from_codec
        ctx = mqtt_message_from_codec(codec, trigger)
        assert ctx.topic == "devices/+/status"

        # Step 2: fold
        ctx = fold(caps, ctx, MQTTPipelineCompilable, "compile_mqtt_pipeline")
        assert ctx.retain is True
        assert ctx.max_payload_size == 2048

        # Step 3: assemble
        route = assemble_mqtt_route(ctx, None, Axes.default())
        assert isinstance(route, MQTTRoute)
        assert route.topic == "devices/+/status"
        assert route.retain is True

    def test_extend_with_new_codec(self):
        """Add a new codec type to existing compiler."""

        @dataclass(frozen=True, slots=True)
        class MQTTBinaryCodec:
            payload_type: type

        def binary_from_codec(
            codec: MQTTBinaryCodec, trigger: MQTTTrigger,
        ) -> MQTTWrapContext:
            return MQTTWrapContext(
                topic=trigger.topic,
                qos=trigger.qos,
                payload_type=codec.payload_type,
                max_payload_size=65536,  # binary default
            )

        extended = MQTT_COMPILER.with_binding(MQTTBinaryCodec, binary_from_codec)
        assert len(extended) == 2
        assert MQTTBinaryCodec in extended

    def test_replace_from_codec(self):
        """Replace how a codec is processed."""

        def traced_from_codec(
            codec: MQTTMessageCodec, trigger: MQTTTrigger,
        ) -> MQTTWrapContext:
            ctx = mqtt_message_from_codec(codec, trigger)
            # Add tracing metadata
            return replace(ctx, max_payload_size=999)

        traced = MQTT_COMPILER.replace_binding(MQTTMessageCodec, traced_from_codec)
        codec = MQTTMessageCodec(payload_type=dict)
        trigger = MQTTTrigger(topic="t", qos=0)

        binding = traced[MQTTMessageCodec]
        ctx = binding.from_codec(codec, trigger)
        assert ctx.max_payload_size == 999


# ═══════════════════════════════════════════════════════════════════════════════
# LEVEL 9: Cross-Axis Capability (Schema + Surface)
# ═══════════════════════════════════════════════════════════════════════════════


class TestLevel9CrossAxisCapability:
    """Test capability that bridges schema and surface axes."""

    def test_capability_compiles_schema_and_pipeline(self):
        """One capability, two axes: GraphQL field type + MQTT pipeline."""

        @dataclass(frozen=True, slots=True)
        class SensorField:
            """Annotate a field for sensor data."""
            unit: str
            precision: int = 2

            def compile_graphql(self, ctx: GraphQLContext) -> GraphQLContext:
                return replace(ctx, description=f"Sensor value in {self.unit}")

            def compile_mqtt_pipeline(self, ctx: MQTTWrapContext) -> MQTTWrapContext:
                return replace(ctx, max_payload_size=self.precision * 100)

        cap = SensorField(unit="celsius", precision=3)

        gql_ctx = cap.compile_graphql(GraphQLContext("temp", float, "Float"))
        assert gql_ctx.description == "Sensor value in celsius"

        mqtt_ctx = cap.compile_mqtt_pipeline(MQTTWrapContext())
        assert mqtt_ctx.max_payload_size == 300


# ═══════════════════════════════════════════════════════════════════════════════
# LEVEL 10: EntityFold — Schema-Level Compilation
# ═══════════════════════════════════════════════════════════════════════════════


from emergent.wire.compile._phase import EntityFold
from emergent.wire.axis.schema._universal import schema_meta


@dataclass(frozen=True, slots=True)
class GraphQLTypeContext:
    """Entity-level context for GraphQL type configuration."""
    class_name: str
    type_name: str | None = None
    description: str | None = None
    interfaces: tuple[str, ...] = ()


@runtime_checkable
class GraphQLTypeCompilable(Protocol):
    def compile_graphql_type(self, ctx: GraphQLTypeContext) -> GraphQLTypeContext: ...


GRAPHQL_TYPE_FOLD: EntityFold[GraphQLTypeContext] = EntityFold(
    GraphQLTypeContext, GraphQLTypeCompilable,
    lambda name: GraphQLTypeContext(class_name=name),
)

GRAPHQL_PHASE_WITH_ENTITY = GRAPHQL_PHASE.with_entity(GRAPHQL_TYPE_FOLD)


@dataclass(frozen=True, slots=True)
class GQLTypeName:
    """Set GraphQL type name for an entity."""
    name: str

    def compile_graphql_type(self, ctx: GraphQLTypeContext) -> GraphQLTypeContext:
        return replace(ctx, type_name=self.name)


@dataclass(frozen=True, slots=True)
class GQLInterface:
    """Declare a GraphQL interface implementation."""
    interface: str

    def compile_graphql_type(self, ctx: GraphQLTypeContext) -> GraphQLTypeContext:
        return replace(ctx, interfaces=(*ctx.interfaces, self.interface))


class TestLevel10EntityFold:
    """Test entity-level compilation (EntityFold)."""

    def test_entity_fold_method_derived(self):
        assert GRAPHQL_TYPE_FOLD.method == "compile_graphql_type"

    def test_entity_fold_on_schema_meta(self):
        @schema_meta(GQLTypeName("UserType"), GQLInterface("Node"))
        @dataclass
        class User:
            id: int
            name: str

        axes = Axes.default()
        ec = compile_entity(User, axes, [GRAPHQL_PHASE_WITH_ENTITY])

        type_ctx = ec[GRAPHQL_TYPE_FOLD]
        assert type_ctx.type_name == "UserType"
        assert "Node" in type_ctx.interfaces

        # Field-level still works
        for fc in ec:
            gql = fc[GRAPHQL_PHASE_WITH_ENTITY]
            assert gql.graphql_type is not None

    def test_entity_fold_multiple_interfaces(self):
        @schema_meta(GQLInterface("Node"), GQLInterface("Timestamped"))
        @dataclass
        class Post:
            id: int
            title: str

        axes = Axes.default()
        ec = compile_entity(Post, axes, [GRAPHQL_PHASE_WITH_ENTITY])
        type_ctx = ec[GRAPHQL_TYPE_FOLD]
        assert type_ctx.interfaces == ("Node", "Timestamped")


# ═══════════════════════════════════════════════════════════════════════════════
# LEVEL 11: Composing SchemaCompiler + TargetCompiler
# ═══════════════════════════════════════════════════════════════════════════════


class TestLevel11ComposedCompilers:
    """Test combining schema and target compilers."""

    def test_fullstack_schema(self):
        """FASTAPI + GRAPHQL = 3 phases (Pydantic + OpenAPI + GraphQL)."""
        fullstack = FASTAPI_SCHEMA + GRAPHQL_SCHEMA
        assert len(fullstack) == 3

        @dataclass
        class User:
            name: Annotated[str, NonNull(), GQLDescription("Username")]
            age: int

        ec = fullstack.compile(User, Axes.default())
        for fc in ec:
            assert fc[PYDANTIC_PHASE] is not None
            assert fc[OPENAPI_PHASE] is not None
            assert fc[GRAPHQL_PHASE] is not None

    def test_target_compiler_algebra_with_schema(self):
        """Extend MQTT compiler with a new codec AND use combined schema."""

        @dataclass(frozen=True, slots=True)
        class MQTTStreamCodec:
            payload_type: type

        def stream_from_codec(
            codec: MQTTStreamCodec, trigger: MQTTTrigger,
        ) -> MQTTWrapContext:
            return MQTTWrapContext(
                topic=trigger.topic,
                qos=trigger.qos,
                payload_type=codec.payload_type,
            )

        extended_mqtt = MQTT_COMPILER.with_binding(MQTTStreamCodec, stream_from_codec)
        assert MQTTMessageCodec in extended_mqtt
        assert MQTTStreamCodec in extended_mqtt


# ═══════════════════════════════════════════════════════════════════════════════
# LEVEL 12: FULL END-TO-END — Build Application → Scan → Compile → Run
#
# This mirrors exactly what fastapi_compile() and testing_compile() do,
# but for a completely custom target: an MQTT broker.
# ═══════════════════════════════════════════════════════════════════════════════


from collections.abc import Awaitable, Callable, Mapping
from emergent.ops._graph import Op, ops
from emergent.wire.axis.surface._app import Application, application
from emergent.wire.axis.surface._endpoint import Endpoint, endpoint
from emergent.wire.axis.surface._types import Exposure
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface._scan import scan
from emergent.wire.axis.surface.capabilities import SurfaceCapability
from kungfu import Result, Ok


# ── Domain Types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SensorReading:
    device_id: str
    value: float
    unit: str


@dataclass(frozen=True, slots=True)
class Ack:
    ok: bool
    message: str


# ── Domain Ops ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class RecordReading(Op[Ack, str]):
    device_id: str
    value: float
    unit: str


@dataclass(frozen=True, slots=True)
class GetLastReading(Op[SensorReading, str]):
    device_id: str


# ── Handlers ──────────────────────────────────────────────────────────────────

_store: dict[str, SensorReading] = {}


async def handle_record(req: RecordReading) -> Result[Ack, str]:
    reading = SensorReading(req.device_id, req.value, req.unit)
    _store[req.device_id] = reading
    return Ok(Ack(ok=True, message=f"recorded {req.device_id}"))


async def handle_get_last(req: GetLastReading) -> Result[SensorReading, str]:
    reading = _store.get(req.device_id)
    if reading is None:
        from kungfu import Error
        return Error(f"no reading for {req.device_id}")
    return Ok(reading)


# ── MQTT Codec (uses RRC-like pattern but for MQTT) ──────────────────────────


@dataclass(frozen=True, slots=True)
class MQTTPayloadCodec:
    """Typed MQTT codec: deserialize payload → Op, run, serialize Ack."""
    op_type: type
    response_type: type


# ── MQTT WrapContext, Pipeline Protocol, Route (full custom) ─────────────────

# Reusing MQTTTrigger and MQTTWrapContext from Level 8, but with execute fn

@dataclass(frozen=True, slots=True)
class MQTTFullWrapContext:
    """Full wrap context with execute function (like FastAPIWrapContext)."""
    topic: str = ""
    qos: int = 0
    op_type: type | None = None
    response_type: type | None = None
    execute: Callable[..., Awaitable[object]] | None = None
    retain: bool = False
    max_payload_size: int | None = None


@runtime_checkable
class MQTTFullPipelineCompilable(Protocol):
    def compile_mqtt_full_pipeline(
        self, ctx: MQTTFullWrapContext,
    ) -> MQTTFullWrapContext: ...


@dataclass(frozen=True, slots=True)
class MQTTFullRoute:
    """Compiled MQTT subscription — ready to receive messages."""
    topic: str
    qos: int
    retain: bool
    max_payload_size: int | None
    handler: Callable[[dict[str, object]], Awaitable[object]]


# ── Pipeline Capabilities ────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class MQTTRetain(SurfaceCapability):
    """Retain last message on topic."""
    def compile_mqtt_full_pipeline(self, ctx: MQTTFullWrapContext) -> MQTTFullWrapContext:
        return replace(ctx, retain=True)


@dataclass(frozen=True, slots=True)
class MQTTMaxPayload(SurfaceCapability):
    """Limit payload size in bytes."""
    size: int
    def compile_mqtt_full_pipeline(self, ctx: MQTTFullWrapContext) -> MQTTFullWrapContext:
        return replace(ctx, max_payload_size=self.size)


@dataclass(frozen=True, slots=True)
class MQTTQoS(SurfaceCapability):
    """Override QoS level."""
    level: int
    def compile_mqtt_full_pipeline(self, ctx: MQTTFullWrapContext) -> MQTTFullWrapContext:
        return replace(ctx, qos=self.level)


# ── from_codec ───────────────────────────────────────────────────────────────

async def _mqtt_execute(
    handler: Handler[MQTTPayloadCodec],
    fields: dict[str, object],
) -> object:
    """Execute MQTT handler: build Op from fields → run → return result."""
    op = handler.codec.op_type(**fields)
    result = await handler.runner.run(op)
    return result


def mqtt_payload_from_codec(
    codec: MQTTPayloadCodec,
    trigger: MQTTTrigger,
) -> MQTTFullWrapContext:
    """Seed context from codec + trigger."""
    return MQTTFullWrapContext(
        topic=trigger.topic,
        qos=trigger.qos,
        op_type=codec.op_type,
        response_type=codec.response_type,
        execute=_mqtt_execute,
    )


# ── Assembler ────────────────────────────────────────────────────────────────

def assemble_mqtt_full_route(
    ctx: MQTTFullWrapContext,
    handler: Handler[MQTTPayloadCodec],
    axes: Axes,
) -> MQTTFullRoute:
    """Build the final MQTTFullRoute from compiled context."""
    execute_fn = ctx.execute

    async def _handle_message(payload: dict[str, object]) -> object:
        return await execute_fn(handler, payload)

    return MQTTFullRoute(
        topic=ctx.topic,
        qos=ctx.qos,
        retain=ctx.retain,
        max_payload_size=ctx.max_payload_size,
        handler=_handle_message,
    )


# ── TargetCompiler ───────────────────────────────────────────────────────────

MQTT_FULL_COMPILER: TargetCompiler[MQTTTrigger] = TargetCompiler(
    trigger_type=MQTTTrigger,
    adapters=(
        CodecBinding(MQTTPayloadCodec, mqtt_payload_from_codec),
    ),
    pipeline_protocol=MQTTFullPipelineCompilable,
    pipeline_method="compile_mqtt_full_pipeline",
    assemble=assemble_mqtt_full_route,
)


# ── MQTTApp — the compiled artifact (like FastAPI app or argparse parser) ────

@dataclass
class MQTTApp:
    """Compiled MQTT application — collection of topic subscriptions."""
    subscriptions: tuple[MQTTFullRoute, ...]

    async def dispatch(self, topic: str, payload: dict[str, object]) -> object:
        """Dispatch incoming message to matching subscription."""
        for sub in self.subscriptions:
            if self._topic_matches(sub.topic, topic):
                if sub.max_payload_size is not None:
                    import json
                    encoded = json.dumps(payload).encode()
                    if len(encoded) > sub.max_payload_size:
                        raise ValueError(
                            f"Payload too large: {len(encoded)} > {sub.max_payload_size}"
                        )
                return await sub.handler(payload)
        raise KeyError(f"No subscription for topic: {topic}")

    @staticmethod
    def _topic_matches(pattern: str, topic: str) -> bool:
        """Simple MQTT topic matching (+ = single level wildcard)."""
        pat_parts = pattern.split("/")
        top_parts = topic.split("/")
        if len(pat_parts) != len(top_parts):
            return False
        return all(
            p == "+" or p == t
            for p, t in zip(pat_parts, top_parts)
        )


# ── mqtt_compile — mirrors fastapi_compile() ────────────────────────────────

def mqtt_compile(
    app: Application,
    axes: Axes | None = None,
    compiler: TargetCompiler[MQTTTrigger] | None = None,
) -> MQTTApp:
    """Compile wire Application to MQTTApp.

    Same pattern as fastapi_compile:
    1. scan_and_wrap(app, axes) → (trigger, handler, route)
    2. Collect all routes
    3. Return compiled app
    """
    axes = axes or Axes.default()
    _compiler = compiler or MQTT_FULL_COMPILER

    routes: list[MQTTFullRoute] = []
    for trigger, handler, route in _compiler.scan_and_wrap(app, axes):
        routes.append(route)

    return MQTTApp(subscriptions=tuple(routes))


# ── Tests ────────────────────────────────────────────────────────────────────

class TestLevel12FullE2E:
    """Full end-to-end: build wire app → mqtt_compile → dispatch messages."""

    def _build_app(self) -> Application:
        """Build wire Application with MQTT endpoints."""
        runner = (
            ops()
            .on(RecordReading, handle_record)
            .on(GetLastReading, handle_get_last)
            .compile()
        )

        return application().mount(
            endpoint(runner)
                .expose(
                    MQTTTrigger("sensors/+/record", qos=1),
                    MQTTPayloadCodec(RecordReading, Ack),
                    MQTTRetain(),
                    MQTTMaxPayload(4096),
                )
                .expose(
                    MQTTTrigger("sensors/+/last"),
                    MQTTPayloadCodec(GetLastReading, SensorReading),
                )
        )

    @pytest.mark.asyncio
    async def test_compile_and_dispatch_record(self):
        """Build app → compile → send MQTT message → get response."""
        _store.clear()
        app = self._build_app()
        mqtt = mqtt_compile(app)

        assert len(mqtt.subscriptions) == 2

        # Record a sensor reading
        result = await mqtt.dispatch("sensors/temp-01/record", {
            "device_id": "temp-01",
            "value": 23.5,
            "unit": "celsius",
        })
        assert result.unwrap().ok is True
        assert result.unwrap().message == "recorded temp-01"

    @pytest.mark.asyncio
    async def test_compile_and_dispatch_get_last(self):
        """Query last reading via MQTT."""
        _store.clear()
        _store["temp-01"] = SensorReading("temp-01", 23.5, "celsius")

        app = self._build_app()
        mqtt = mqtt_compile(app)

        result = await mqtt.dispatch("sensors/temp-01/last", {
            "device_id": "temp-01",
        })
        reading = result.unwrap()
        assert reading.device_id == "temp-01"
        assert reading.value == 23.5
        assert reading.unit == "celsius"

    @pytest.mark.asyncio
    async def test_capabilities_are_applied(self):
        """Capabilities (Retain, MaxPayload) actually affect compiled routes."""
        app = self._build_app()
        mqtt = mqtt_compile(app)

        record_sub = mqtt.subscriptions[0]
        assert record_sub.retain is True
        assert record_sub.max_payload_size == 4096
        assert record_sub.qos == 1

        last_sub = mqtt.subscriptions[1]
        assert last_sub.retain is False
        assert last_sub.max_payload_size is None
        assert last_sub.qos == 0

    @pytest.mark.asyncio
    async def test_max_payload_enforced(self):
        """MaxPayload capability is enforced at dispatch time."""
        _store.clear()
        app = self._build_app()
        mqtt = mqtt_compile(app)

        huge_payload = {
            "device_id": "x",
            "value": 1.0,
            "unit": "a" * 10000,
        }
        with pytest.raises(ValueError, match="Payload too large"):
            await mqtt.dispatch("sensors/x/record", huge_payload)

    def test_scan_finds_correct_triggers(self):
        """scan(app, MQTTTrigger) finds all MQTT exposures."""
        app = self._build_app()
        pairs = scan(app, MQTTTrigger)
        assert len(pairs) == 2
        topics = {t.topic for t, _h in pairs}
        assert "sensors/+/record" in topics
        assert "sensors/+/last" in topics

    def test_scan_filters_by_codec(self):
        """scan(app, trigger, codec) narrows to specific codec type."""
        app = self._build_app()
        pairs = scan(app, MQTTTrigger, MQTTPayloadCodec)
        assert len(pairs) == 2

    def test_topic_matching(self):
        """MQTT topic wildcard matching works."""
        app = MQTTApp(subscriptions=())
        assert app._topic_matches("sensors/+/record", "sensors/foo/record")
        assert app._topic_matches("sensors/+/record", "sensors/bar/record")
        assert not app._topic_matches("sensors/+/record", "sensors/foo/bar/record")
        assert not app._topic_matches("sensors/+/record", "other/foo/record")

    @pytest.mark.asyncio
    async def test_extend_compiler_with_new_codec(self):
        """Add binary codec to MQTT compiler, compile same app."""
        _store.clear()

        @dataclass(frozen=True, slots=True)
        class MQTTBinaryPayloadCodec:
            op_type: type
            response_type: type

        async def _binary_execute(
            handler: Handler[MQTTBinaryPayloadCodec],
            fields: dict[str, object],
        ) -> object:
            op = handler.codec.op_type(**fields)
            return await handler.runner.run(op)

        def binary_from_codec(
            codec: MQTTBinaryPayloadCodec, trigger: MQTTTrigger,
        ) -> MQTTFullWrapContext:
            return MQTTFullWrapContext(
                topic=trigger.topic,
                qos=trigger.qos,
                op_type=codec.op_type,
                response_type=codec.response_type,
                execute=_binary_execute,
                max_payload_size=65536,
            )

        extended = MQTT_FULL_COMPILER.with_binding(
            MQTTBinaryPayloadCodec, binary_from_codec,
        )

        runner = ops().on(RecordReading, handle_record).compile()
        app = application().mount(
            endpoint(runner).expose(
                MQTTTrigger("binary/+/record", qos=2),
                MQTTBinaryPayloadCodec(RecordReading, Ack),
                MQTTQoS(2),
            )
        )

        mqtt = mqtt_compile(app, compiler=extended)
        assert len(mqtt.subscriptions) == 1
        assert mqtt.subscriptions[0].qos == 2
        assert mqtt.subscriptions[0].max_payload_size == 65536

        result = await mqtt.dispatch("binary/dev-01/record", {
            "device_id": "dev-01", "value": 42.0, "unit": "psi",
        })
        assert result.unwrap().ok is True

    @pytest.mark.asyncio
    async def test_traced_compilation(self):
        """Compile with tracing enabled — verify trace events recorded."""
        from emergent.wire.compile._trace import ListCollector

        _store.clear()
        app = self._build_app()
        collector = ListCollector()
        axes = Axes.traced(collector)

        mqtt = mqtt_compile(app, axes=axes)

        # Trace should record scan + wrap events
        assert len(collector.scan_events) == 2  # 2 endpoints scanned
        assert len(collector.wrap_events) == 2  # 2 endpoints wrapped

        # Still functional
        result = await mqtt.dispatch("sensors/t/record", {
            "device_id": "t", "value": 1.0, "unit": "c",
        })
        assert result.unwrap().ok is True

    def test_compiler_algebra_on_real_compiler(self):
        """Real TargetCompiler algebra: add, remove, replace codecs."""
        # Start with base
        assert len(MQTT_FULL_COMPILER) == 1
        assert MQTTPayloadCodec in MQTT_FULL_COMPILER

        # Add a new codec
        @dataclass(frozen=True, slots=True)
        class MQTTEventCodec:
            event_type: type

        def event_from_codec(
            codec: MQTTEventCodec, trigger: MQTTTrigger,
        ) -> MQTTFullWrapContext:
            return MQTTFullWrapContext(topic=trigger.topic)

        extended = MQTT_FULL_COMPILER.with_binding(MQTTEventCodec, event_from_codec)
        assert len(extended) == 2

        # Replace the original codec
        def custom_from_codec(
            codec: MQTTPayloadCodec, trigger: MQTTTrigger,
        ) -> MQTTFullWrapContext:
            return MQTTFullWrapContext(topic=trigger.topic, retain=True)

        replaced = extended.replace_binding(MQTTPayloadCodec, custom_from_codec)
        ctx = replaced[MQTTPayloadCodec].from_codec(
            MQTTPayloadCodec(op_type=RecordReading, response_type=Ack),
            MQTTTrigger("t"),
        )
        assert ctx.retain is True

        # Remove a codec
        minimal = replaced.without_binding(MQTTEventCodec)
        assert len(minimal) == 1
        assert MQTTEventCodec not in minimal
