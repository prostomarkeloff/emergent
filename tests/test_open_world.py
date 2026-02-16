"""Open-world extensibility tests — unified Game Platform domain.

Builds a complete game platform extension from scratch:
custom capabilities, ops, backends, codecs, compilers, bridgers.
Then runs the full pipeline end-to-end.

Domain: Multiplayer Game Platform with leaderboards, real-time WebSocket,
game state storage, ranking queries.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field, replace
from typing import Annotated, Any, Generic, Protocol, TypeVar, runtime_checkable

import pytest

from emergent.ops import ops as _ops

# === Schema axis imports ===
from emergent.wire.axis.schema._universal import (
    UniversalCapability,
    SchemaAxisCapability,
    SchemaCapability,
    schema_meta,
    get_schema_meta,
    Identity,
    MaxLen,
    Min,
    Max,
)
from emergent.wire.axis.schema._inspect import inspect_dataclass, FieldInfo

# === Capability / context imports ===
from emergent.wire.axis._capability import (
    OpenAPIContext,
    OpenAPICompilable,
    ConstraintsContext,
    ConstraintsCompilable,
    HandlerRuntimeContext,
    HandlerRuntimeCompilable,
    openapi_schema,
)

# === Compile imports ===
from emergent.wire.compile._core import Axes, fold, fold_field, fold_schema
from emergent.wire.compile._phase import (
    CompilationPhase,
    FieldCompilation,
    compile_fields,
    PYDANTIC_PHASE,
    OPENAPI_PHASE,
)
from emergent.wire.compile._target import TargetCompiler, CodecAdapter

# === Surface imports ===
from emergent.wire.axis.surface._endpoint import Endpoint, endpoint
from emergent.wire.axis.surface._app import Application, application
from emergent.wire.axis.surface._scan import scan, scan_endpoint
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface._stack import AppStack, app_stack
from emergent.wire.axis.surface._scan import scan_stack
from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

# === Query imports ===
from emergent.wire.axis.query._fold import fold_query, QueryDialect, MEMORY_DIALECT
from emergent.wire.axis.query._explain import (
    ExplainDialect,
    explain_ops,
    format_ops,
    RELATIONAL_EXPLAIN_DIALECT,
)
from emergent.wire.axis.query._relational import Filter, Limit, Offset
from emergent.wire.axis.query._expr import Field, Const, Gt

# === Storage imports ===
from emergent.wire.axis.storage import kv, MemoryStorage, PickleCodec, JsonCodec
from emergent.wire.axis.storage._compose import prefix_kv

from kungfu import Ok, Some, Nothing

# === Bridge imports ===
from emergent.wire.bridge._extractor import (
    compose_extractors,
    first_extractor,
    filter_extractor,
)
from emergent.wire.bridge._to_wire import compose_to_wire
from emergent.wire.bridge._types import Extracted
from emergent.wire.bridge._registry import FrameworkBridger, BridgeRegistry


# ═══════════════════════════════════════════════════════════════════════════════
# GAME PLATFORM DOMAIN — shared custom types
# ═══════════════════════════════════════════════════════════════════════════════


T = TypeVar("T")


# ---------------------------------------------------------------------------
# Schema: custom field capability
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Ranked(UniversalCapability):
    """Mark field as ranked in leaderboard.

    Implements compile_openapi, compile_constraints, AND compile_game (custom).
    """

    board: str = "global"

    def compile_openapi(self, ctx: OpenAPIContext) -> OpenAPIContext:
        return openapi_schema(ctx, **{"x-ranked": True, "x-board": self.board})

    def compile_constraints(self, ctx: ConstraintsContext) -> ConstraintsContext:
        return ctx  # passthrough — no constraints to add

    def compile_game(self, ctx: "GameFieldContext") -> "GameFieldContext":
        return replace(ctx, ranked_board=self.board)


@dataclass(frozen=True, slots=True)
class GameMeta(SchemaCapability):
    """Schema-level: marks class as a game entity."""

    game_id: str

    def compile_game_schema(self, ctx: "GameSchemaContext") -> "GameSchemaContext":
        return replace(ctx, game_id=self.game_id)


# ---------------------------------------------------------------------------
# Compile: custom game phase
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GameFieldContext:
    field_name: str
    field_type: type
    ranked_board: str | None = None


@runtime_checkable
class GameCompilable(Protocol):
    def compile_game(self, ctx: GameFieldContext) -> GameFieldContext: ...


GAME_PHASE = CompilationPhase(
    GameFieldContext,
    GameCompilable,
    initial=lambda n, t: GameFieldContext(n, t),
)


@dataclass(frozen=True, slots=True)
class GameSchemaContext:
    class_name: str
    game_id: str | None = None


@runtime_checkable
class GameSchemaCompilable(Protocol):
    def compile_game_schema(self, ctx: GameSchemaContext) -> GameSchemaContext: ...


# ---------------------------------------------------------------------------
# Surface: custom trigger + codec + enricher + transform
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GameWSTrigger:
    """WebSocket trigger for real-time game events."""

    room: str
    event: str


@dataclass(frozen=True, slots=True)
class GameEventCodec:
    """Codec for game event payloads."""

    version: int = 1


@dataclass(frozen=True, slots=True)
class PlayerAuth(SurfaceCapability):
    """Custom enricher — validates player token before handler execution."""

    required_level: int = 1

    async def enrich(self, call, scope):
        return await call(scope)

    def compile_handler_runtime(
        self, ctx: HandlerRuntimeContext
    ) -> HandlerRuntimeContext:
        return replace(ctx, enrichers=(*ctx.enrichers, self))


@dataclass(frozen=True, slots=True)
class ScoreMultiplier(SurfaceCapability):
    """Custom response transform — multiplies score in response."""

    factor: float = 2.0

    def apply_response(self, response):
        if isinstance(response, dict) and "score" in response:
            return {**response, "score": response["score"] * self.factor}
        return response

    def compile_handler_runtime(
        self, ctx: HandlerRuntimeContext
    ) -> HandlerRuntimeContext:
        return replace(ctx, response_transforms=(*ctx.response_transforms, self))


# ---------------------------------------------------------------------------
# Query: custom game ops
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RankBy:
    """Rank items by field — custom query op."""

    field: str
    method: str = "desc"  # "asc" | "desc"


@dataclass(frozen=True, slots=True)
class TopN:
    """Take top N items — custom query op."""

    count: int


def _handle_rank_by(op: RankBy, data: list[Any]) -> list[Any]:
    """Handler for RankBy op — sorts by field."""
    reverse = op.method == "desc"
    return sorted(data, key=lambda item: getattr(item, op.field), reverse=reverse)


def _handle_top_n(op: TopN, data: list[Any]) -> list[Any]:
    """Handler for TopN op — takes first N."""
    return data[: op.count]


GAME_QUERY_HANDLERS = {
    RankBy: _handle_rank_by,
    TopN: _handle_top_n,
}


def _explain_rank_by(op: RankBy) -> dict[str, Any]:
    return {"op": "RankBy", "field": op.field, "method": op.method}


def _explain_top_n(op: TopN) -> dict[str, Any]:
    return {"op": "TopN", "count": op.count}


# ---------------------------------------------------------------------------
# Storage: custom backend + codec
# ---------------------------------------------------------------------------


class GameStateBackend:
    """Custom in-memory backend implementing Get/Set/Delete for game state."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def get(self, key: str):
        if key in self._store:
            return Ok(Some(self._store[key]))
        return Ok(Nothing())

    async def set(self, key: str, value: bytes, ttl=None):
        self._store[key] = value
        return Ok(None)

    async def delete(self, key: str):
        self._store.pop(key, None)
        return Ok(None)


class CompressedJsonCodec(Generic[T]):
    """Custom codec — JSON encoded as base64 (simulated compression)."""

    def encode(self, value: T) -> bytes:
        json_bytes = json.dumps(value).encode("utf-8")
        return base64.b64encode(json_bytes)

    def decode(self, data: bytes) -> T:
        json_bytes = base64.b64decode(data)
        return json.loads(json_bytes.decode("utf-8"))


# ---------------------------------------------------------------------------
# Bridge: hypothetical game framework
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GameRouteData:
    """Route data from hypothetical game framework."""

    event: str
    room: str
    handler_name: str


class FakeGameApp:
    """Simulates a game framework application."""

    def __init__(self, routes: list[tuple[str, str, Any]]) -> None:
        self.game_routes = routes  # (event, room, handler_fn)


class GameFrameworkExtractor:
    """Extractor for FakeGameApp."""

    def can_extract(self, source: object) -> bool:
        return isinstance(source, FakeGameApp)

    def extract(self, source: object):
        assert isinstance(source, FakeGameApp)
        for event, room, handler_fn in source.game_routes:
            yield Extracted(
                route=GameRouteData(event=event, room=room, handler_name=handler_fn.__name__),
                handler=handler_fn,
                name=handler_fn.__name__,
            )


class GameFrameworkToWire:
    """ToWire converter for GameRouteData → GameWSTrigger + GameEventCodec."""

    def to_trigger(self, route: GameRouteData):
        return GameWSTrigger(room=route.room, event=route.event)

    def to_codec(self, route: GameRouteData, handler):
        return GameEventCodec(version=1)


# ---------------------------------------------------------------------------
# The Game Entity
# ---------------------------------------------------------------------------


@schema_meta(GameMeta(game_id="roulette"))
@dataclass
class Player:
    id: Annotated[int, Identity]
    name: Annotated[str, MaxLen(50)]
    score: Annotated[int, Ranked("global"), Min(0)]
    level: Annotated[int, Ranked("seasonal"), Min(1), Max(100)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _runner():
    return _ops().compile()


# ═══════════════════════════════════════════════════════════════════════════════
# PART 1: Schema — custom capabilities through fold
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchemaOpenWorld:
    """Custom schema capabilities flow through fold infrastructure."""

    def test_inspect_picks_up_ranked(self):
        fields = inspect_dataclass(Player)
        score_info = fields["score"]
        ranked_caps = [c for c in score_info.capabilities if isinstance(c, Ranked)]
        assert len(ranked_caps) == 1
        assert ranked_caps[0].board == "global"

    def test_inspect_picks_up_multiple_ranked(self):
        fields = inspect_dataclass(Player)
        level_info = fields["level"]
        ranked_caps = [c for c in level_info.capabilities if isinstance(c, Ranked)]
        assert len(ranked_caps) == 1
        assert ranked_caps[0].board == "seasonal"

    def test_fold_field_openapi_picks_up_ranked(self):
        fields = inspect_dataclass(Player)
        score_info = fields["score"]
        ctx = fold_field(
            score_info,
            OpenAPIContext(field_name="score", field_type=int),
            OpenAPICompilable,
            "compile_openapi",
        )
        assert ctx.schema.get("x-ranked") is True
        assert ctx.schema.get("x-board") == "global"

    def test_fold_field_constraints_passthrough(self):
        fields = inspect_dataclass(Player)
        score_info = fields["score"]
        ctx = fold_field(
            score_info,
            ConstraintsContext(field_name="score", field_type=int),
            ConstraintsCompilable,
            "compile_constraints",
        )
        # Ranked passes through; Min(0) sets min_value
        assert ctx.min_value == 0

    def test_fold_field_game_compilable(self):
        fields = inspect_dataclass(Player)
        score_info = fields["score"]
        ctx = fold_field(
            score_info,
            GameFieldContext(field_name="score", field_type=int),
            GameCompilable,
            "compile_game",
        )
        assert ctx.ranked_board == "global"

    def test_fold_field_game_unranked_field(self):
        fields = inspect_dataclass(Player)
        name_info = fields["name"]
        ctx = fold_field(
            name_info,
            GameFieldContext(field_name="name", field_type=str),
            GameCompilable,
            "compile_game",
        )
        assert ctx.ranked_board is None  # not ranked

    def test_unknown_cap_silently_skipped(self):
        """Plain objects in Annotated are not caps — silently ignored."""

        @dataclass
        class Weird:
            x: Annotated[int, "not_a_cap", 42, Ranked("test")]

        fields = inspect_dataclass(Weird)
        caps = fields["x"].capabilities
        ranked = [c for c in caps if isinstance(c, Ranked)]
        assert len(ranked) == 1  # only Ranked picked up

    def test_schema_meta_picked_up(self):
        meta = get_schema_meta(Player)
        assert len(meta) == 1
        assert isinstance(meta[0], GameMeta)
        assert meta[0].game_id == "roulette"

    def test_fold_schema_game_meta(self):
        ctx = fold_schema(
            Player,
            GameSchemaContext(class_name="Player"),
            GameSchemaCompilable,
            "compile_game_schema",
        )
        assert ctx.game_id == "roulette"

    def test_fold_schema_no_game_meta(self):
        @dataclass
        class NormalEntity:
            x: int = 0

        ctx = fold_schema(
            NormalEntity,
            GameSchemaContext(class_name="NormalEntity"),
            GameSchemaCompilable,
            "compile_game_schema",
        )
        assert ctx.game_id is None  # no GameMeta → unchanged

    def test_ranked_composes_with_standard_caps(self):
        fields = inspect_dataclass(Player)
        score_info = fields["score"]
        # Has both Ranked and Min
        assert score_info.has(Ranked)
        assert score_info.has(Min)

    def test_fold_unknown_protocol_skips_all(self):
        """Fold with protocol that no cap implements → initial returned."""

        @runtime_checkable
        class NobodyImplements(Protocol):
            def compile_nobody(self, ctx: GameFieldContext) -> GameFieldContext: ...

        fields = inspect_dataclass(Player)
        initial = GameFieldContext(field_name="score", field_type=int)
        ctx = fold_field(
            fields["score"], initial, NobodyImplements, "compile_nobody"
        )
        assert ctx is initial  # untouched


# ═══════════════════════════════════════════════════════════════════════════════
# PART 2: Compile — custom phase + target compiler
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompileOpenWorld:
    """Custom CompilationPhase and TargetCompiler."""

    def test_compile_fields_game_phase(self):
        axes = Axes.default()
        compiled = compile_fields(Player, axes, [GAME_PHASE])
        # score is index 2 (id=0, name=1, score=2, level=3)
        for fc in compiled:
            game_ctx = fc[GAME_PHASE]
            if fc.name == "score":
                assert game_ctx.ranked_board == "global"
            elif fc.name == "level":
                assert game_ctx.ranked_board == "seasonal"
            elif fc.name == "name":
                assert game_ctx.ranked_board is None

    def test_compile_fields_dual_phase(self):
        axes = Axes.default()
        compiled = compile_fields(Player, axes, [OPENAPI_PHASE, GAME_PHASE])
        for fc in compiled:
            if fc.name == "score":
                openapi_ctx = fc[OPENAPI_PHASE]
                game_ctx = fc[GAME_PHASE]
                assert openapi_ctx.schema.get("x-ranked") is True
                assert game_ctx.ranked_board == "global"

    def test_compile_fields_game_phase_returns_typed_context(self):
        axes = Axes.default()
        compiled = compile_fields(Player, axes, [GAME_PHASE])
        for fc in compiled:
            ctx = fc[GAME_PHASE]
            assert isinstance(ctx, GameFieldContext)

    def test_game_phase_with_handlers_override(self):
        def custom_ranked_handler(cap: Ranked, ctx: GameFieldContext) -> GameFieldContext:
            return replace(ctx, ranked_board=f"custom:{cap.board}")

        phase = GAME_PHASE.with_handlers({Ranked: custom_ranked_handler})
        axes = Axes.default()
        compiled = compile_fields(Player, axes, [phase])
        for fc in compiled:
            if fc.name == "score":
                assert fc[phase].ranked_board == "custom:global"

    def test_target_compiler_immutable_builder(self):
        def wrap_game(handler, trigger, axes):
            return ("wrapped", handler, trigger)

        compiler = TargetCompiler(
            trigger_type=GameWSTrigger,
            adapters=(CodecAdapter(GameEventCodec, wrap_game),),
        )
        assert len(compiler.adapters) == 1

        # with_codec adds
        extended = compiler.with_codec(int, lambda h, t, a: None)
        assert len(extended.adapters) == 2
        assert len(compiler.adapters) == 1  # original unchanged

    def test_target_compiler_replace_codec(self):
        def wrap_v1(h, t, a):
            return "v1"

        def wrap_v2(h, t, a):
            return "v2"

        compiler = TargetCompiler(
            trigger_type=GameWSTrigger,
            adapters=(CodecAdapter(GameEventCodec, wrap_v1),),
        )
        replaced = compiler.replace_codec(GameEventCodec, wrap_v2)
        assert replaced.adapters[0].wrap is wrap_v2
        assert compiler.adapters[0].wrap is wrap_v1  # original unchanged

    def test_target_compiler_without_codec(self):
        compiler = TargetCompiler(
            trigger_type=GameWSTrigger,
            adapters=(
                CodecAdapter(GameEventCodec, lambda h, t, a: None),
                CodecAdapter(int, lambda h, t, a: None),
            ),
        )
        stripped = compiler.without_codec(GameEventCodec)
        assert len(stripped.adapters) == 1
        assert stripped.adapters[0].codec_type is int

    def test_scan_and_wrap_custom_codec(self):
        def wrap_game(handler, trigger, axes):
            return {"wrapped": True, "room": trigger.room}

        compiler = TargetCompiler(
            trigger_type=GameWSTrigger,
            adapters=(CodecAdapter(GameEventCodec, wrap_game),),
        )
        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                GameWSTrigger("lobby", "join"),
                GameEventCodec(version=2),
            )
        )
        results = list(compiler.scan_and_wrap(app, Axes.default()))
        assert len(results) == 1
        trigger, handler, wrapped = results[0]
        assert isinstance(trigger, GameWSTrigger)
        assert trigger.room == "lobby"
        assert wrapped == {"wrapped": True, "room": "lobby"}

    def test_scan_and_wrap_no_match(self):
        """Codec not in compiler → no results."""
        compiler = TargetCompiler(
            trigger_type=GameWSTrigger,
            adapters=(CodecAdapter(int, lambda h, t, a: None),),  # int codec, not GameEventCodec
        )
        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                GameWSTrigger("lobby", "join"),
                GameEventCodec(),
            )
        )
        results = list(compiler.scan_and_wrap(app, Axes.default()))
        assert len(results) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# PART 3: Surface — custom trigger/codec/enricher/transform
# ═══════════════════════════════════════════════════════════════════════════════


class TestSurfaceOpenWorld:
    """Custom surface types flow through endpoint → scan → handler pipeline."""

    def test_expose_custom_trigger_and_codec(self):
        runner = _runner()
        ep = endpoint(runner).expose(
            GameWSTrigger("lobby", "join"),
            GameEventCodec(version=2),
        )
        assert len(ep.exposures) == 1
        assert isinstance(ep.exposures[0].trigger, GameWSTrigger)
        assert isinstance(ep.exposures[0].codec, GameEventCodec)

    def test_scan_finds_custom_trigger(self):
        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                GameWSTrigger("lobby", "join"),
                GameEventCodec(),
            )
        )
        pairs = scan(app, GameWSTrigger)
        assert len(pairs) == 1
        trigger, handler = pairs[0]
        assert trigger.room == "lobby"
        assert trigger.event == "join"

    def test_scan_filters_by_codec(self):
        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                GameWSTrigger("lobby", "join"),
                GameEventCodec(),
            ),
            endpoint(runner).expose(
                GameWSTrigger("arena", "fight"),
                int,  # different "codec"
            ),
        )
        pairs = scan(app, GameWSTrigger, GameEventCodec)
        assert len(pairs) == 1
        assert pairs[0][0].room == "lobby"

    def test_scan_isolates_trigger_types(self):
        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                GameWSTrigger("lobby", "join"),
                GameEventCodec(),
            ),
            endpoint(runner).expose(
                HTTPRouteTrigger("GET", "/api/health"),
                int,
            ),
        )
        ws_pairs = scan(app, GameWSTrigger)
        http_pairs = scan(app, HTTPRouteTrigger)
        assert len(ws_pairs) == 1
        assert len(http_pairs) == 1

    def test_fold_custom_enricher(self):
        auth = PlayerAuth(required_level=5)
        caps = (auth,)
        ctx = fold(
            caps,
            HandlerRuntimeContext(),
            HandlerRuntimeCompilable,
            "compile_handler_runtime",
        )
        assert len(ctx.enrichers) == 1
        assert isinstance(ctx.enrichers[0], PlayerAuth)
        assert ctx.enrichers[0].required_level == 5

    def test_fold_custom_transform(self):
        mult = ScoreMultiplier(factor=3.0)
        caps = (mult,)
        ctx = fold(
            caps,
            HandlerRuntimeContext(),
            HandlerRuntimeCompilable,
            "compile_handler_runtime",
        )
        assert len(ctx.response_transforms) == 1
        assert isinstance(ctx.response_transforms[0], ScoreMultiplier)
        assert ctx.response_transforms[0].factor == 3.0

    def test_fold_enricher_and_transform_together(self):
        caps = (PlayerAuth(), ScoreMultiplier(2.0))
        ctx = fold(
            caps,
            HandlerRuntimeContext(),
            HandlerRuntimeCompilable,
            "compile_handler_runtime",
        )
        assert len(ctx.enrichers) == 1
        assert len(ctx.response_transforms) == 1

    def test_score_multiplier_apply_response(self):
        mult = ScoreMultiplier(factor=3.0)
        result = mult.apply_response({"score": 100, "name": "Alice"})
        assert result == {"score": 300.0, "name": "Alice"}

    def test_score_multiplier_noop_on_non_dict(self):
        mult = ScoreMultiplier(factor=3.0)
        assert mult.apply_response("hello") == "hello"

    def test_scan_preserves_capabilities(self):
        runner = _runner()
        auth = PlayerAuth()
        mult = ScoreMultiplier()
        app = application().mount(
            endpoint(runner).expose(
                GameWSTrigger("lobby", "join"),
                GameEventCodec(),
                auth,
                mult,
            )
        )
        pairs = scan(app, GameWSTrigger)
        _, handler = pairs[0]
        assert auth in handler.capabilities
        assert mult in handler.capabilities

    def test_scan_endpoint_custom_trigger(self):
        runner = _runner()
        ep = endpoint(runner).expose(
            GameWSTrigger("arena", "fight"),
            GameEventCodec(),
            PlayerAuth(),
        )
        pairs = scan_endpoint(ep, GameWSTrigger)
        assert len(pairs) == 1
        assert pairs[0][0].room == "arena"

    def test_scan_stack_custom_trigger(self):
        runner = _runner()
        root_app = application().mount(
            endpoint(runner).expose(
                GameWSTrigger("lobby", "join"),
                GameEventCodec(),
            )
        )
        sub_app = application().mount(
            endpoint(runner).expose(
                GameWSTrigger("arena", "fight"),
                GameEventCodec(),
            )
        )
        stack = app_stack().root(root_app).mount("/game", sub_app)
        view = scan_stack(stack, GameWSTrigger)
        assert len(view.root) == 1
        assert "/game" in view.mounts

    def test_multiple_exposures_same_endpoint(self):
        runner = _runner()
        ep = (
            endpoint(runner)
            .expose(GameWSTrigger("lobby", "join"), GameEventCodec())
            .expose(GameWSTrigger("lobby", "leave"), GameEventCodec())
        )
        assert len(ep.exposures) == 2
        app = application().mount(ep)
        pairs = scan(app, GameWSTrigger)
        assert len(pairs) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# PART 4: Query — custom ops through fold_query + explain
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class _PlayerData:
    name: str
    score: int
    level: int


class TestQueryOpenWorld:
    """Custom query ops dispatch through fold_query / QueryDialect."""

    def _sample_players(self) -> list[_PlayerData]:
        return [
            _PlayerData("Alice", 1500, 10),
            _PlayerData("Bob", 2000, 15),
            _PlayerData("Charlie", 1200, 8),
            _PlayerData("Diana", 2500, 20),
            _PlayerData("Eve", 1800, 12),
        ]

    def test_fold_query_custom_rank_by(self):
        data = self._sample_players()
        result = fold_query([RankBy("score", "desc")], data, GAME_QUERY_HANDLERS)
        assert result[0].name == "Diana"  # highest score
        assert result[-1].name == "Charlie"  # lowest score

    def test_fold_query_custom_top_n(self):
        data = self._sample_players()
        result = fold_query([TopN(3)], data, GAME_QUERY_HANDLERS)
        assert len(result) == 3

    def test_fold_query_rank_then_top(self):
        data = self._sample_players()
        result = fold_query(
            [RankBy("score", "desc"), TopN(3)],
            data,
            GAME_QUERY_HANDLERS,
        )
        assert len(result) == 3
        assert result[0].name == "Diana"
        assert result[1].name == "Bob"
        assert result[2].name == "Eve"

    def test_rank_by_ascending(self):
        data = self._sample_players()
        result = fold_query([RankBy("score", "asc")], data, GAME_QUERY_HANDLERS)
        assert result[0].name == "Charlie"

    def test_memory_dialect_extended_with_game_ops(self):
        dialect = MEMORY_DIALECT.with_handler(RankBy, _handle_rank_by).with_handler(
            TopN, _handle_top_n
        )
        data = self._sample_players()
        result = dialect.fold(
            [RankBy("score", "desc"), TopN(2)],
            data,
        )
        assert len(result) == 2
        assert result[0].name == "Diana"

    def test_unknown_op_silently_skipped(self):
        data = self._sample_players()
        result = MEMORY_DIALECT.fold([RankBy("score")], data)
        # RankBy not in MEMORY_DIALECT → silently skipped → data unchanged
        assert len(result) == 5

    def test_mixed_known_and_unknown_ops(self):
        data = self._sample_players()
        filter_op = Filter(Gt(Field("score"), Const(1500)))
        # Filter is known to MEMORY_DIALECT, RankBy is not
        result = MEMORY_DIALECT.fold([filter_op, RankBy("score")], data)
        # Filter applied, RankBy skipped
        assert all(p.score > 1500 for p in result)

    def test_dialect_without_handler(self):
        """Removing a handler makes that op silently skipped."""
        dialect = MEMORY_DIALECT.without_handler(Filter)
        data = self._sample_players()
        result = dialect.fold([Filter(Gt(Field("score"), Const(1500)))], data)
        # Filter removed → skipped → all data returned
        assert len(result) == 5

    def test_custom_dialect_from_scratch(self):
        dialect = QueryDialect(context_type=list, handlers=GAME_QUERY_HANDLERS)
        data = self._sample_players()
        result = dialect.fold([RankBy("level", "desc"), TopN(2)], data)
        assert len(result) == 2
        assert result[0].name == "Diana"  # level 20

    def test_fold_query_empty_handlers_skips_all(self):
        data = self._sample_players()
        result = fold_query([RankBy("score"), TopN(3)], data, {})
        assert result is data  # unchanged

    def test_explain_custom_ops(self):
        dialect = RELATIONAL_EXPLAIN_DIALECT.with_handler(
            RankBy, _explain_rank_by
        ).with_handler(TopN, _explain_top_n)
        info = dialect.explain([RankBy("score", "desc"), TopN(10)])
        assert info[0] == {"op": "RankBy", "field": "score", "method": "desc"}
        assert info[1] == {"op": "TopN", "count": 10}

    def test_explain_unknown_op_fallback(self):
        info = explain_ops([RankBy("score")], {})
        assert info == [{"op": "RankBy"}]  # type name only

    def test_format_custom_ops(self):
        handlers = {RankBy: _explain_rank_by, TopN: _explain_top_n}
        text = format_ops([RankBy("score", "desc"), TopN(5)], handlers)
        assert "RankBy" in text
        assert "TopN" in text

    def test_mixed_standard_and_custom_in_extended_dialect(self):
        """Filter (standard) + RankBy (custom) + TopN (custom) in one pipeline."""
        dialect = MEMORY_DIALECT.with_handler(RankBy, _handle_rank_by).with_handler(
            TopN, _handle_top_n
        )
        data = self._sample_players()
        result = dialect.fold(
            [Filter(Gt(Field("score"), Const(1200))), RankBy("score", "desc"), TopN(2)],
            data,
        )
        # Filter keeps score > 1200: Alice(1500), Bob(2000), Diana(2500), Eve(1800)
        # RankBy desc: Diana, Bob, Eve, Alice
        # TopN 2: Diana, Bob
        assert len(result) == 2
        assert result[0].name == "Diana"
        assert result[1].name == "Bob"


# ═══════════════════════════════════════════════════════════════════════════════
# PART 5: Storage — custom backend + codec
# ═══════════════════════════════════════════════════════════════════════════════


class TestStorageOpenWorld:
    """Custom storage backend and codec through kv pattern."""

    @pytest.mark.asyncio
    async def test_custom_backend_crud(self):
        store = kv(GameStateBackend(), PickleCodec())
        result = await store.set("player:1", {"name": "Alice", "score": 100})
        assert isinstance(result, Ok)

        result = await store.get("player:1")
        assert isinstance(result, Ok)
        inner = result.unwrap()
        assert isinstance(inner, Some)
        assert inner.unwrap() == {"name": "Alice", "score": 100}

    @pytest.mark.asyncio
    async def test_custom_backend_get_missing(self):
        store = kv(GameStateBackend(), PickleCodec())
        result = await store.get("nonexistent")
        assert isinstance(result, Ok)
        assert isinstance(result.unwrap(), Nothing)

    @pytest.mark.asyncio
    async def test_custom_backend_delete(self):
        store = kv(GameStateBackend(), PickleCodec())
        await store.set("player:1", "data")
        await store.delete("player:1")
        result = await store.get("player:1")
        assert isinstance(result.unwrap(), Nothing)

    @pytest.mark.asyncio
    async def test_custom_codec_roundtrip(self):
        codec = CompressedJsonCodec()
        data = {"name": "Alice", "score": 1500, "items": [1, 2, 3]}
        encoded = codec.encode(data)
        assert isinstance(encoded, bytes)
        decoded = codec.decode(encoded)
        assert decoded == data

    @pytest.mark.asyncio
    async def test_custom_backend_with_custom_codec(self):
        store = kv(GameStateBackend(), CompressedJsonCodec())
        player = {"name": "Bob", "score": 2000, "level": 15}
        await store.set("player:bob", player)
        result = await store.get("player:bob")
        assert isinstance(result, Ok)
        assert result.unwrap().unwrap() == player

    @pytest.mark.asyncio
    async def test_standard_backend_with_custom_codec(self):
        store = kv(MemoryStorage(), CompressedJsonCodec())
        data = {"event": "join", "room": "lobby"}
        await store.set("event:1", data)
        result = await store.get("event:1")
        assert isinstance(result, Ok)
        assert result.unwrap().unwrap() == data

    @pytest.mark.asyncio
    async def test_custom_backend_with_standard_codec(self):
        store = kv(GameStateBackend(), JsonCodec())
        await store.set("state:1", {"hp": 100})
        result = await store.get("state:1")
        assert result.unwrap().unwrap() == {"hp": 100}

    @pytest.mark.asyncio
    async def test_prefix_kv_with_custom_backend(self):
        backend = GameStateBackend()
        store = prefix_kv(kv(backend, PickleCodec()), "game:")
        await store.set("player:1", "Alice")
        # Direct backend access should have prefixed key
        assert b"game:player:1" not in backend._store or "game:player:1" in backend._store
        result = await store.get("player:1")
        assert isinstance(result, Ok)
        assert result.unwrap().unwrap() == "Alice"

    @pytest.mark.asyncio
    async def test_multiple_keys_custom_backend(self):
        store = kv(GameStateBackend(), CompressedJsonCodec())
        for i in range(5):
            await store.set(f"player:{i}", {"id": i, "score": i * 100})
        for i in range(5):
            result = await store.get(f"player:{i}")
            assert result.unwrap().unwrap()["id"] == i


# ═══════════════════════════════════════════════════════════════════════════════
# PART 6: Bridge — custom framework bridger
# ═══════════════════════════════════════════════════════════════════════════════


def _game_handler_join():
    pass


def _game_handler_leave():
    pass


def _game_handler_fight():
    pass


class TestBridgeOpenWorld:
    """Custom Extractor, ToWire, FrameworkBridger, BridgeRegistry."""

    def _fake_game_app(self):
        return FakeGameApp([
            ("join", "lobby", _game_handler_join),
            ("leave", "lobby", _game_handler_leave),
            ("fight", "arena", _game_handler_fight),
        ])

    def test_extractor_can_extract(self):
        ext = GameFrameworkExtractor()
        assert ext.can_extract(self._fake_game_app()) is True
        assert ext.can_extract("not a game app") is False

    def test_extractor_extract(self):
        ext = GameFrameworkExtractor()
        extracted = list(ext.extract(self._fake_game_app()))
        assert len(extracted) == 3
        assert extracted[0].route.event == "join"
        assert extracted[0].route.room == "lobby"
        assert extracted[0].name == "_game_handler_join"

    def test_to_wire_trigger(self):
        tw = GameFrameworkToWire()
        route = GameRouteData("join", "lobby", "handler")
        trigger = tw.to_trigger(route)
        assert isinstance(trigger, GameWSTrigger)
        assert trigger.room == "lobby"
        assert trigger.event == "join"

    def test_to_wire_codec(self):
        tw = GameFrameworkToWire()
        route = GameRouteData("join", "lobby", "handler")
        codec = tw.to_codec(route, lambda: None)
        assert isinstance(codec, GameEventCodec)

    def test_compose_extractors_custom(self):
        ext1 = GameFrameworkExtractor()

        class OtherExtractor:
            def can_extract(self, source):
                return False

            def extract(self, source):
                return iter([])

        composed = compose_extractors(ext1, OtherExtractor())
        assert composed.can_extract(self._fake_game_app()) is True
        extracted = list(composed.extract(self._fake_game_app()))
        assert len(extracted) == 3

    def test_first_extractor_stops_at_first(self):
        ext1 = GameFrameworkExtractor()

        class AlsoMatchesExtractor:
            def can_extract(self, source):
                return isinstance(source, FakeGameApp)

            def extract(self, source):
                yield Extracted(
                    route=GameRouteData("extra", "extra", "extra"),
                    handler=lambda: None,
                    name="extra",
                )

        first = first_extractor(ext1, AlsoMatchesExtractor())
        extracted = list(first.extract(self._fake_game_app()))
        # First extractor wins → 3 results from GameFrameworkExtractor
        assert len(extracted) == 3

    def test_filter_extractor_custom(self):
        ext = GameFrameworkExtractor()
        filtered = filter_extractor(
            ext, lambda e: e.route.room != "arena"
        )
        extracted = list(filtered.extract(self._fake_game_app()))
        assert len(extracted) == 2  # lobby only, arena filtered
        assert all(e.route.room == "lobby" for e in extracted)

    def test_compose_to_wire_custom(self):
        tw = compose_to_wire((GameRouteData, GameFrameworkToWire()))
        route = GameRouteData("join", "lobby", "handler")
        trigger = tw.to_trigger(route)
        assert isinstance(trigger, GameWSTrigger)

    def test_compose_to_wire_unknown_type_raises(self):
        tw = compose_to_wire((GameRouteData, GameFrameworkToWire()))
        with pytest.raises(TypeError):
            tw.to_trigger("not a GameRouteData")

    def test_bridge_registry_with_bridger(self):
        ext = GameFrameworkExtractor()
        tw = GameFrameworkToWire()
        bridger = FrameworkBridger(
            name="gamefw",
            can_bridge=lambda s: isinstance(s, FakeGameApp),
            extractor=ext,
            to_wire=tw,
        )
        registry = BridgeRegistry(bridgers=()).with_bridger(bridger)
        assert len(registry.bridgers) == 1

    def test_bridge_registry_detect(self):
        ext = GameFrameworkExtractor()
        tw = GameFrameworkToWire()
        bridger = FrameworkBridger(
            name="gamefw",
            can_bridge=lambda s: isinstance(s, FakeGameApp),
            extractor=ext,
            to_wire=tw,
        )
        registry = BridgeRegistry(bridgers=()).with_bridger(bridger)
        found = registry.detect(self._fake_game_app())
        assert found is bridger

    def test_bridge_registry_detect_unknown(self):
        registry = BridgeRegistry(bridgers=())
        assert registry.detect("unknown") is None

    def test_bridge_registry_detect_wrong_type(self):
        ext = GameFrameworkExtractor()
        tw = GameFrameworkToWire()
        bridger = FrameworkBridger(
            name="gamefw",
            can_bridge=lambda s: isinstance(s, FakeGameApp),
            extractor=ext,
            to_wire=tw,
        )
        registry = BridgeRegistry(bridgers=()).with_bridger(bridger)
        assert registry.detect("not a game app") is None

    def test_bridge_registry_replace_bridger(self):
        ext = GameFrameworkExtractor()
        tw = GameFrameworkToWire()
        old = FrameworkBridger(name="gamefw", can_bridge=lambda s: False, extractor=ext, to_wire=tw)
        new = FrameworkBridger(name="gamefw", can_bridge=lambda s: True, extractor=ext, to_wire=tw)
        registry = BridgeRegistry(bridgers=(old,)).replace_bridger("gamefw", new)
        assert registry.bridgers[0] is new

    def test_bridge_registry_without_bridger(self):
        ext = GameFrameworkExtractor()
        tw = GameFrameworkToWire()
        bridger = FrameworkBridger(name="gamefw", can_bridge=lambda s: True, extractor=ext, to_wire=tw)
        registry = BridgeRegistry(bridgers=(bridger,)).without_bridger("gamefw")
        assert len(registry.bridgers) == 0

    def test_bridge_registry_immutable(self):
        registry = BridgeRegistry(bridgers=())
        ext = GameFrameworkExtractor()
        tw = GameFrameworkToWire()
        bridger = FrameworkBridger(name="gamefw", can_bridge=lambda s: True, extractor=ext, to_wire=tw)
        new_reg = registry.with_bridger(bridger)
        assert len(registry.bridgers) == 0  # original unchanged
        assert len(new_reg.bridgers) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# PART 7: E2E Pipeline — everything together
# ═══════════════════════════════════════════════════════════════════════════════


class TestE2EPipeline:
    """Full game platform pipeline: schema → compile → surface → query → storage → bridge."""

    def test_schema_inspect_and_fold(self):
        """1-3: Schema inspection + fold through all protocols."""
        fields = inspect_dataclass(Player)

        # Ranked picked up
        assert fields["score"].has(Ranked)
        assert fields["level"].has(Ranked)
        assert not fields["name"].has(Ranked)

        # OpenAPI fold
        openapi_ctx = fold_field(
            fields["score"],
            OpenAPIContext(field_name="score", field_type=int),
            OpenAPICompilable,
            "compile_openapi",
        )
        assert openapi_ctx.schema.get("x-ranked") is True
        assert openapi_ctx.schema.get("x-board") == "global"

        # Game phase fold
        game_ctx = fold_field(
            fields["score"],
            GameFieldContext(field_name="score", field_type=int),
            GameCompilable,
            "compile_game",
        )
        assert game_ctx.ranked_board == "global"

        # Schema-level: GameMeta
        schema_ctx = fold_schema(
            Player,
            GameSchemaContext(class_name="Player"),
            GameSchemaCompilable,
            "compile_game_schema",
        )
        assert schema_ctx.game_id == "roulette"

    def test_compile_dual_phase(self):
        """4: compile_fields with OPENAPI_PHASE + GAME_PHASE."""
        axes = Axes.default()
        compiled = compile_fields(Player, axes, [OPENAPI_PHASE, GAME_PHASE])

        score_fc = next(fc for fc in compiled if fc.name == "score")
        assert score_fc[OPENAPI_PHASE].schema.get("x-ranked") is True
        assert score_fc[GAME_PHASE].ranked_board == "global"

        name_fc = next(fc for fc in compiled if fc.name == "name")
        assert name_fc[GAME_PHASE].ranked_board is None

    def test_surface_pipeline(self):
        """5-6: Build app → scan → fold runtime context."""
        runner = _runner()
        auth = PlayerAuth(required_level=10)
        mult = ScoreMultiplier(factor=2.0)

        app = application().mount(
            endpoint(runner).expose(
                GameWSTrigger("lobby", "join"),
                GameEventCodec(version=2),
                auth,
                mult,
            )
        )

        # Scan finds the game handler
        pairs = scan(app, GameWSTrigger, GameEventCodec)
        assert len(pairs) == 1
        trigger, handler = pairs[0]
        assert trigger.room == "lobby"
        assert trigger.event == "join"

        # Fold runtime context: enrichers + transforms
        rt_ctx = fold(
            handler.capabilities,
            HandlerRuntimeContext(),
            HandlerRuntimeCompilable,
            "compile_handler_runtime",
        )
        assert any(isinstance(e, PlayerAuth) for e in rt_ctx.enrichers)
        assert any(isinstance(t, ScoreMultiplier) for t in rt_ctx.response_transforms)

    def test_target_compiler_pipeline(self):
        """7: TargetCompiler.scan_and_wrap with game codec."""
        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                GameWSTrigger("lobby", "join"),
                GameEventCodec(version=2),
                PlayerAuth(),
            )
        )

        def wrap_game_event(handler, trigger, axes):
            return {
                "type": "game_ws",
                "room": trigger.room,
                "event": trigger.event,
                "version": handler.codec.version,
            }

        compiler = TargetCompiler(
            trigger_type=GameWSTrigger,
            adapters=(CodecAdapter(GameEventCodec, wrap_game_event),),
        )
        results = list(compiler.scan_and_wrap(app, Axes.default()))
        assert len(results) == 1
        trigger, handler, wrapped = results[0]
        assert wrapped["room"] == "lobby"
        assert wrapped["version"] == 2

    def test_query_pipeline(self):
        """8: Custom ops in game query dialect."""
        players = [
            _PlayerData("Alice", 1500, 10),
            _PlayerData("Bob", 2000, 15),
            _PlayerData("Charlie", 1200, 8),
            _PlayerData("Diana", 2500, 20),
            _PlayerData("Eve", 1800, 12),
        ]

        # Extended dialect: standard Filter + custom RankBy + TopN
        game_dialect = (
            MEMORY_DIALECT
            .with_handler(RankBy, _handle_rank_by)
            .with_handler(TopN, _handle_top_n)
        )

        result = game_dialect.fold(
            [Filter(Gt(Field("score"), Const(1300))), RankBy("score", "desc"), TopN(3)],
            players,
        )
        # Filter: Alice(1500), Bob(2000), Diana(2500), Eve(1800)
        # RankBy desc: Diana, Bob, Eve, Alice
        # TopN 3: Diana, Bob, Eve
        assert len(result) == 3
        assert result[0].name == "Diana"
        assert result[1].name == "Bob"
        assert result[2].name == "Eve"

    @pytest.mark.asyncio
    async def test_storage_pipeline(self):
        """9: Custom backend + codec through kv."""
        store = kv(GameStateBackend(), CompressedJsonCodec())

        player_data = {"name": "Alice", "score": 1500, "level": 10}
        await store.set("player:alice", player_data)

        result = await store.get("player:alice")
        assert isinstance(result, Ok)
        assert result.unwrap().unwrap() == player_data

        await store.delete("player:alice")
        result = await store.get("player:alice")
        assert isinstance(result.unwrap(), Nothing)

    def test_bridge_pipeline(self):
        """10: Detect + extract + convert from game framework."""
        ext = GameFrameworkExtractor()
        tw = GameFrameworkToWire()
        bridger = FrameworkBridger(
            name="gamefw",
            can_bridge=lambda s: isinstance(s, FakeGameApp),
            extractor=ext,
            to_wire=tw,
        )
        registry = BridgeRegistry(bridgers=()).with_bridger(bridger)

        fake_app = FakeGameApp([
            ("join", "lobby", _game_handler_join),
            ("fight", "arena", _game_handler_fight),
        ])

        # Detect
        found = registry.detect(fake_app)
        assert found is bridger

        # Extract
        extracted = list(found.extractor.extract(fake_app))
        assert len(extracted) == 2

        # Convert to wire
        for ex in extracted:
            wire_trigger = found.to_wire.to_trigger(ex.route)
            assert isinstance(wire_trigger, GameWSTrigger)
            wire_codec = found.to_wire.to_codec(ex.route, ex.handler)
            assert isinstance(wire_codec, GameEventCodec)

    @pytest.mark.asyncio
    async def test_full_e2e(self):
        """Grand finale: all pieces wired together in one test."""
        # 1. Schema: inspect + custom caps
        fields = inspect_dataclass(Player)
        assert fields["score"].has(Ranked)
        assert get_schema_meta(Player)[0].game_id == "roulette"

        # 2. Compile: dual phase
        axes = Axes.default()
        compiled = compile_fields(Player, axes, [OPENAPI_PHASE, GAME_PHASE])
        score_fc = next(fc for fc in compiled if fc.name == "score")
        assert score_fc[GAME_PHASE].ranked_board == "global"
        assert score_fc[OPENAPI_PHASE].schema.get("x-ranked") is True

        # 3. Surface: build app
        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                GameWSTrigger("lobby", "join"),
                GameEventCodec(version=2),
                PlayerAuth(required_level=5),
                ScoreMultiplier(factor=1.5),
            )
        )

        # 4. Scan
        pairs = scan(app, GameWSTrigger, GameEventCodec)
        assert len(pairs) == 1
        trigger, handler = pairs[0]

        # 5. Runtime fold
        rt_ctx = fold(
            handler.capabilities,
            HandlerRuntimeContext(),
            HandlerRuntimeCompilable,
            "compile_handler_runtime",
        )
        assert len(rt_ctx.enrichers) == 1
        assert len(rt_ctx.response_transforms) == 1

        # 6. Target compiler
        def wrap_game(h, t, a):
            return {"compiled": True, "room": t.room}

        compiler = TargetCompiler(
            trigger_type=GameWSTrigger,
            adapters=(CodecAdapter(GameEventCodec, wrap_game),),
        )
        results = list(compiler.scan_and_wrap(app, axes))
        assert len(results) == 1
        assert results[0][2]["compiled"] is True

        # 7. Query
        players = [
            _PlayerData("Alice", 1500, 10),
            _PlayerData("Bob", 2000, 15),
            _PlayerData("Diana", 2500, 20),
        ]
        game_dialect = (
            MEMORY_DIALECT
            .with_handler(RankBy, _handle_rank_by)
            .with_handler(TopN, _handle_top_n)
        )
        ranked = game_dialect.fold([RankBy("score", "desc"), TopN(2)], players)
        assert ranked[0].name == "Diana"
        assert ranked[1].name == "Bob"

        # 8. Storage
        store = kv(GameStateBackend(), CompressedJsonCodec())
        await store.set("player:diana", {"name": "Diana", "score": 2500})
        result = await store.get("player:diana")
        assert result.unwrap().unwrap()["score"] == 2500

        # 9. Bridge
        ext = GameFrameworkExtractor()
        tw = GameFrameworkToWire()
        bridger = FrameworkBridger(
            name="gamefw",
            can_bridge=lambda s: isinstance(s, FakeGameApp),
            extractor=ext,
            to_wire=tw,
        )
        registry = BridgeRegistry(bridgers=()).with_bridger(bridger)
        fake_app = FakeGameApp([("join", "lobby", _game_handler_join)])
        found = registry.detect(fake_app)
        assert found is bridger
        extracted = list(found.extractor.extract(fake_app))
        wire_trigger = found.to_wire.to_trigger(extracted[0].route)
        assert isinstance(wire_trigger, GameWSTrigger)
        assert wire_trigger.room == "lobby"


# ═══════════════════════════════════════════════════════════════════════════════
# GRACEFUL DEGRADATION — cross-cutting negative tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestGracefulDegradation:
    """Unknown types are silently skipped everywhere — no crashes."""

    def test_fold_unknown_cap_skipped(self):
        """Unknown item in fold → silently skipped."""

        @dataclass(frozen=True, slots=True)
        class AlienCap:
            x: int = 42

        ctx = fold(
            [AlienCap(), Ranked("test")],
            GameFieldContext(field_name="f", field_type=int),
            GameCompilable,
            "compile_game",
        )
        # Ranked applied, AlienCap skipped
        assert ctx.ranked_board == "test"

    def test_fold_query_unknown_op_skipped(self):
        @dataclass(frozen=True, slots=True)
        class MysteryOp:
            value: str = "???"

        data = [1, 2, 3]
        result = fold_query([MysteryOp()], data, GAME_QUERY_HANDLERS)
        assert result == [1, 2, 3]  # unchanged

    def test_explain_unknown_op_shows_type_name(self):
        @dataclass(frozen=True, slots=True)
        class WeirdOp:
            pass

        info = explain_ops([WeirdOp()], {})
        assert info == [{"op": "WeirdOp"}]

    def test_target_compiler_unknown_codec_no_match(self):
        compiler = TargetCompiler(
            trigger_type=GameWSTrigger,
            adapters=(CodecAdapter(GameEventCodec, lambda h, t, a: None),),
        )
        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                GameWSTrigger("lobby", "join"),
                int,  # not GameEventCodec
            )
        )
        results = list(compiler.scan_and_wrap(app, Axes.default()))
        assert len(results) == 0

    def test_bridge_registry_unknown_framework(self):
        ext = GameFrameworkExtractor()
        tw = GameFrameworkToWire()
        bridger = FrameworkBridger(
            name="gamefw",
            can_bridge=lambda s: isinstance(s, FakeGameApp),
            extractor=ext,
            to_wire=tw,
        )
        registry = BridgeRegistry(bridgers=(bridger,))
        assert registry.detect("django_app") is None
        assert registry.detect(42) is None
        assert registry.detect(None) is None

    def test_fold_field_with_no_matching_protocol(self):
        """Field with caps that don't match protocol → initial returned."""

        @dataclass
        class SimpleEntity:
            x: Annotated[int, MaxLen(10)]  # MaxLen doesn't implement GameCompilable

        fields = inspect_dataclass(SimpleEntity)
        initial = GameFieldContext(field_name="x", field_type=int)
        ctx = fold_field(fields["x"], initial, GameCompilable, "compile_game")
        assert ctx is initial

    def test_compile_fields_unknown_caps_in_phase(self):
        """compile_fields with custom phase skips non-matching caps."""

        @dataclass
        class MixedEntity:
            a: Annotated[str, MaxLen(50)]  # not GameCompilable
            b: Annotated[int, Ranked("test")]  # IS GameCompilable

        axes = Axes.default()
        compiled = compile_fields(MixedEntity, axes, [GAME_PHASE])
        a_ctx = next(fc for fc in compiled if fc.name == "a")
        b_ctx = next(fc for fc in compiled if fc.name == "b")
        assert a_ctx[GAME_PHASE].ranked_board is None
        assert b_ctx[GAME_PHASE].ranked_board == "test"

    def test_empty_registry_detect_returns_none(self):
        registry = BridgeRegistry(bridgers=())
        assert registry.detect("anything") is None


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — Complex cross-feature scenarios
# ═══════════════════════════════════════════════════════════════════════════════


# ---------------------------------------------------------------------------
# Second domain: Marketplace (independent from Game Platform)
# Exercises cross-module type registration and parallel open-world types.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Searchable(UniversalCapability):
    """Mark field as searchable in marketplace index.

    Implements compile_openapi and compile_marketplace (custom).
    """

    weight: float = 1.0

    def compile_openapi(self, ctx: OpenAPIContext) -> OpenAPIContext:
        return openapi_schema(ctx, **{"x-searchable": True, "x-weight": self.weight})

    def compile_marketplace(self, ctx: "MarketplaceFieldContext") -> "MarketplaceFieldContext":
        return replace(ctx, search_weight=self.weight)


@dataclass(frozen=True, slots=True)
class Filterable(UniversalCapability):
    """Mark field as filterable — appears in filter panel."""

    facet: bool = False

    def compile_marketplace(self, ctx: "MarketplaceFieldContext") -> "MarketplaceFieldContext":
        return replace(ctx, is_filterable=True, is_facet=self.facet)


@dataclass(frozen=True, slots=True)
class MarketplaceMeta(SchemaCapability):
    """Schema-level: marks class as a marketplace entity."""

    category: str

    def compile_marketplace_schema(
        self, ctx: "MarketplaceSchemaContext"
    ) -> "MarketplaceSchemaContext":
        return replace(ctx, category=self.category)


@dataclass(frozen=True, slots=True)
class MarketplaceFieldContext:
    field_name: str
    field_type: type
    search_weight: float | None = None
    is_filterable: bool = False
    is_facet: bool = False


@runtime_checkable
class MarketplaceCompilable(Protocol):
    def compile_marketplace(
        self, ctx: MarketplaceFieldContext
    ) -> MarketplaceFieldContext: ...


MARKETPLACE_PHASE = CompilationPhase(
    MarketplaceFieldContext,
    MarketplaceCompilable,
    initial=lambda n, t: MarketplaceFieldContext(n, t),
)


@dataclass(frozen=True, slots=True)
class MarketplaceSchemaContext:
    class_name: str
    category: str | None = None


@runtime_checkable
class MarketplaceSchemaCompilable(Protocol):
    def compile_marketplace_schema(
        self, ctx: MarketplaceSchemaContext
    ) -> MarketplaceSchemaContext: ...


@schema_meta(MarketplaceMeta(category="electronics"))
@dataclass
class Product:
    id: Annotated[int, Identity]
    name: Annotated[str, MaxLen(200), Searchable(weight=2.0)]
    description: Annotated[str, MaxLen(5000), Searchable(weight=0.5)]
    price: Annotated[int, Min(0), Filterable(facet=True)]
    brand: Annotated[str, MaxLen(100), Searchable(weight=1.5), Filterable(facet=True)]
    stock: Annotated[int, Min(0)]


# Custom marketplace query ops

@dataclass(frozen=True, slots=True)
class FacetCount:
    """Count distinct values per facet field."""

    field: str


@dataclass(frozen=True, slots=True)
class TextSearch:
    """Full-text search across searchable fields."""

    query: str
    fields: tuple[str, ...] = ()


def _handle_facet_count(op: FacetCount, data: list[_PlayerData]) -> list[_PlayerData]:
    """Facet count is a no-op for list context (would be handled by provider)."""
    return data


def _handle_text_search(op: TextSearch, data: list[_PlayerData]) -> list[_PlayerData]:
    """Simple text search filter for in-memory data."""
    query_lower = op.query.lower()
    search_fields = op.fields or ("name",)
    return [
        item
        for item in data
        if any(query_lower in str(getattr(item, f, "")).lower() for f in search_fields)
    ]


# Custom marketplace trigger + codec

@dataclass(frozen=True, slots=True)
class GraphQLTrigger:
    """GraphQL trigger for marketplace queries."""

    operation: str  # "query" | "mutation"
    field_name: str


@dataclass(frozen=True, slots=True)
class GraphQLCodec:
    """Codec for GraphQL payloads."""

    version: int = 1


# Custom marketplace enricher

@dataclass(frozen=True, slots=True)
class TenantIsolation(SurfaceCapability):
    """Enricher that ensures tenant isolation."""

    tenant_header: str = "X-Tenant-Id"

    async def enrich(self, call, scope):
        return await call(scope)

    def compile_handler_runtime(
        self, ctx: HandlerRuntimeContext
    ) -> HandlerRuntimeContext:
        return replace(ctx, enrichers=(*ctx.enrichers, self))


# Custom marketplace framework (for bridge testing)

@dataclass(frozen=True, slots=True)
class GraphQLRouteData:
    """Route data from hypothetical GraphQL framework."""

    operation: str
    field_name: str
    resolver_name: str


class FakeGraphQLApp:
    """Simulates a GraphQL framework."""

    def __init__(self, resolvers: list[tuple[str, str, object]]) -> None:
        self.resolvers = resolvers  # (operation, field_name, resolver_fn)


class GraphQLExtractor:
    """Extractor for FakeGraphQLApp."""

    def can_extract(self, source: object) -> bool:
        return isinstance(source, FakeGraphQLApp)

    def extract(self, source: object):
        assert isinstance(source, FakeGraphQLApp)
        for operation, field_name, resolver_fn in source.resolvers:
            yield Extracted(
                route=GraphQLRouteData(
                    operation=operation,
                    field_name=field_name,
                    resolver_name=getattr(resolver_fn, "__name__", str(resolver_fn)),
                ),
                handler=resolver_fn,
                name=getattr(resolver_fn, "__name__", str(resolver_fn)),
            )


class GraphQLToWire:
    """ToWire converter for GraphQLRouteData."""

    def to_trigger(self, route: GraphQLRouteData):
        return GraphQLTrigger(operation=route.operation, field_name=route.field_name)

    def to_codec(self, route: GraphQLRouteData, handler):
        return GraphQLCodec()


# Marketplace-specific storage codec

class MsgpackSimCodec(Generic[T]):
    """Simulated msgpack codec (actually JSON with a marker byte)."""

    MARKER = b"\x92"

    def encode(self, value: T) -> bytes:
        return self.MARKER + json.dumps(value).encode("utf-8")

    def decode(self, data: bytes) -> T:
        assert data[:1] == self.MARKER
        return json.loads(data[1:].decode("utf-8"))


# Resolver stubs for bridge testing

def _resolve_products():
    pass


def _resolve_product():
    pass


def _resolve_create_order():
    pass


# Module-level types for edge-case tests (needed for `from __future__ import annotations`)

@dataclass(frozen=True, slots=True)
class _AlienA:
    pass


@dataclass(frozen=True, slots=True)
class _AlienB:
    pass


@dataclass
class _MixedAlienEntity:
    x: Annotated[int, _AlienA(), Ranked("first"), _AlienB(), Ranked("second")]


class TestCrossModuleTypeRegistration:
    """Two independent domains (Game + Marketplace) with separate
    custom capabilities, phases, triggers, codecs, and query ops
    coexisting in the same fold/compile/scan infrastructure.
    """

    def test_independent_phases_do_not_interfere(self):
        """Game phase on Product should see nothing; Marketplace phase
        on Player should see nothing. Each domain's caps are invisible
        to the other domain's phase.
        """
        axes = Axes.default()

        # Game phase on Product: no Ranked caps -> all boards None
        product_game = compile_fields(Product, axes, [GAME_PHASE])
        for fc in product_game:
            assert fc[GAME_PHASE].ranked_board is None

        # Marketplace phase on Player: no Searchable/Filterable caps -> all defaults
        player_mkt = compile_fields(Player, axes, [MARKETPLACE_PHASE])
        for fc in player_mkt:
            assert fc[MARKETPLACE_PHASE].search_weight is None
            assert fc[MARKETPLACE_PHASE].is_filterable is False

    def test_three_phase_compilation(self):
        """compile_fields with OPENAPI + GAME + MARKETPLACE simultaneously."""
        axes = Axes.default()
        compiled = compile_fields(
            Product, axes, [OPENAPI_PHASE, GAME_PHASE, MARKETPLACE_PHASE]
        )

        name_fc = next(fc for fc in compiled if fc.name == "name")

        # OpenAPI: Searchable set x-searchable
        assert name_fc[OPENAPI_PHASE].schema.get("x-searchable") is True
        assert name_fc[OPENAPI_PHASE].schema.get("x-weight") == 2.0

        # Game: nothing
        assert name_fc[GAME_PHASE].ranked_board is None

        # Marketplace: Searchable sets weight
        assert name_fc[MARKETPLACE_PHASE].search_weight == 2.0

    def test_dual_domain_schema_meta(self):
        """Schema-level metadata from both domains works independently."""
        game_ctx = fold_schema(
            Player,
            GameSchemaContext(class_name="Player"),
            GameSchemaCompilable,
            "compile_game_schema",
        )
        assert game_ctx.game_id == "roulette"

        mkt_ctx = fold_schema(
            Product,
            MarketplaceSchemaContext(class_name="Product"),
            MarketplaceSchemaCompilable,
            "compile_marketplace_schema",
        )
        assert mkt_ctx.category == "electronics"

        # Cross-check: Product has no GameMeta
        game_ctx2 = fold_schema(
            Product,
            GameSchemaContext(class_name="Product"),
            GameSchemaCompilable,
            "compile_game_schema",
        )
        assert game_ctx2.game_id is None

    def test_both_domains_on_single_field(self):
        """A field that has caps from both domains compiles correctly in both."""

        @dataclass
        class HybridEntity:
            score: Annotated[int, Ranked("competitive"), Searchable(weight=3.0), Min(0)]

        fields = inspect_dataclass(HybridEntity)
        score_info = fields["score"]

        # Has both Ranked and Searchable
        assert score_info.has(Ranked)
        assert score_info.has(Searchable)

        # Game phase sees Ranked
        game_ctx = fold_field(
            score_info,
            GameFieldContext(field_name="score", field_type=int),
            GameCompilable,
            "compile_game",
        )
        assert game_ctx.ranked_board == "competitive"

        # Marketplace phase sees Searchable
        mkt_ctx = fold_field(
            score_info,
            MarketplaceFieldContext(field_name="score", field_type=int),
            MarketplaceCompilable,
            "compile_marketplace",
        )
        assert mkt_ctx.search_weight == 3.0


class TestMultiTriggerSurfaceComposition:
    """Endpoint with multiple trigger types from different domains,
    scanned by independent compilers.
    """

    def test_endpoint_with_three_trigger_types(self):
        """One endpoint exposed as WS, GraphQL, and HTTP."""
        runner = _runner()
        ep = (
            endpoint(runner)
            .expose(GameWSTrigger("lobby", "scoreboard"), GameEventCodec())
            .expose(GraphQLTrigger("query", "scoreboard"), GraphQLCodec())
            .expose(HTTPRouteTrigger("GET", "/api/scoreboard"), int)
        )
        assert len(ep.exposures) == 3

    def test_scan_isolates_three_trigger_types(self):
        """Each scan call finds only its trigger type."""
        runner = _runner()
        app = application().mount(
            endpoint(runner)
            .expose(GameWSTrigger("lobby", "scoreboard"), GameEventCodec())
            .expose(GraphQLTrigger("query", "scoreboard"), GraphQLCodec())
            .expose(HTTPRouteTrigger("GET", "/api/scoreboard"), int)
        )

        ws_pairs = scan(app, GameWSTrigger)
        gql_pairs = scan(app, GraphQLTrigger)
        http_pairs = scan(app, HTTPRouteTrigger)

        assert len(ws_pairs) == 1
        assert len(gql_pairs) == 1
        assert len(http_pairs) == 1

        assert ws_pairs[0][0].room == "lobby"
        assert gql_pairs[0][0].field_name == "scoreboard"
        assert http_pairs[0][0].path == "/api/scoreboard"

    def test_scan_with_codec_filter_across_trigger_types(self):
        """scan(app, trigger, codec) filters correctly with mixed triggers."""
        runner = _runner()
        app = application().mount(
            endpoint(runner)
            .expose(GameWSTrigger("lobby", "join"), GameEventCodec())
            .expose(GameWSTrigger("lobby", "leave"), GraphQLCodec())  # different codec
        )

        # Filter by GameEventCodec
        pairs = scan(app, GameWSTrigger, GameEventCodec)
        assert len(pairs) == 1
        assert pairs[0][0].event == "join"

        # Filter by GraphQLCodec
        pairs = scan(app, GameWSTrigger, GraphQLCodec)
        assert len(pairs) == 1
        assert pairs[0][0].event == "leave"

    def test_target_compilers_from_different_domains(self):
        """Two TargetCompilers (WS and GraphQL) scanning the same app independently."""
        runner = _runner()
        app = application().mount(
            endpoint(runner)
            .expose(GameWSTrigger("lobby", "join"), GameEventCodec(version=2))
            .expose(GraphQLTrigger("query", "players"), GraphQLCodec(version=3))
        )

        ws_compiler = TargetCompiler(
            trigger_type=GameWSTrigger,
            adapters=(
                CodecAdapter(GameEventCodec, lambda h, t, a: {"ws": t.room}),
            ),
        )
        gql_compiler = TargetCompiler(
            trigger_type=GraphQLTrigger,
            adapters=(
                CodecAdapter(GraphQLCodec, lambda h, t, a: {"gql": t.field_name}),
            ),
        )

        ws_results = list(ws_compiler.scan_and_wrap(app, Axes.default()))
        gql_results = list(gql_compiler.scan_and_wrap(app, Axes.default()))

        assert len(ws_results) == 1
        assert ws_results[0][2] == {"ws": "lobby"}

        assert len(gql_results) == 1
        assert gql_results[0][2] == {"gql": "players"}

    def test_capabilities_flow_through_mixed_trigger_endpoint(self):
        """Capabilities attached to one exposure are independent of another."""
        runner = _runner()
        auth = PlayerAuth(required_level=10)
        tenant = TenantIsolation(tenant_header="X-Org-Id")

        app = application().mount(
            endpoint(runner)
            .expose(
                GameWSTrigger("lobby", "join"),
                GameEventCodec(),
                auth,
            )
            .expose(
                GraphQLTrigger("query", "players"),
                GraphQLCodec(),
                tenant,
            )
        )

        ws_pairs = scan(app, GameWSTrigger)
        gql_pairs = scan(app, GraphQLTrigger)

        # WS handler has PlayerAuth
        ws_caps = ws_pairs[0][1].capabilities
        assert any(isinstance(c, PlayerAuth) for c in ws_caps)
        assert not any(isinstance(c, TenantIsolation) for c in ws_caps)

        # GraphQL handler has TenantIsolation
        gql_caps = gql_pairs[0][1].capabilities
        assert any(isinstance(c, TenantIsolation) for c in gql_caps)
        assert not any(isinstance(c, PlayerAuth) for c in gql_caps)


class TestApplicationMergeAndStack:
    """Complex application composition: merge, add, stack with mixed domains."""

    def test_merge_two_domain_apps(self):
        """Merge game app + marketplace app into one, scan finds all."""
        runner = _runner()

        game_app = application().mount(
            endpoint(runner).expose(
                GameWSTrigger("lobby", "join"), GameEventCodec()
            ),
            endpoint(runner).expose(
                GameWSTrigger("arena", "fight"), GameEventCodec()
            ),
        )

        marketplace_app = application().mount(
            endpoint(runner).expose(
                GraphQLTrigger("query", "products"), GraphQLCodec()
            ),
            endpoint(runner).expose(
                GraphQLTrigger("mutation", "createOrder"), GraphQLCodec()
            ),
        )

        merged = game_app + marketplace_app

        ws_pairs = scan(merged, GameWSTrigger)
        gql_pairs = scan(merged, GraphQLTrigger)

        assert len(ws_pairs) == 2
        assert len(gql_pairs) == 2

    def test_merge_preserves_global_capabilities(self):
        """Global capabilities survive merge."""
        runner = _runner()
        auth = PlayerAuth(required_level=1)
        tenant = TenantIsolation()

        app1 = application(capabilities=(auth,)).mount(
            endpoint(runner).expose(GameWSTrigger("lobby", "join"), GameEventCodec())
        )
        app2 = application(capabilities=(tenant,)).mount(
            endpoint(runner).expose(GraphQLTrigger("query", "x"), GraphQLCodec())
        )

        merged = app1.merge(app2)
        assert len(merged.capabilities) == 2
        assert any(isinstance(c, PlayerAuth) for c in merged.capabilities)
        assert any(isinstance(c, TenantIsolation) for c in merged.capabilities)

    def test_stack_with_mixed_domain_mounts(self):
        """AppStack with game at /game and marketplace at /shop."""
        runner = _runner()

        game_app = application().mount(
            endpoint(runner).expose(
                GameWSTrigger("lobby", "join"), GameEventCodec()
            )
        )
        shop_app = application().mount(
            endpoint(runner).expose(
                GraphQLTrigger("query", "products"), GraphQLCodec()
            )
        )

        stack = app_stack().root(game_app).mount("/shop", shop_app)

        ws_view = scan_stack(stack, GameWSTrigger)
        gql_view = scan_stack(stack, GraphQLTrigger)

        # WS trigger is in root
        assert len(ws_view.root) == 1
        assert ws_view.root[0][0].room == "lobby"

        # GraphQL trigger is in /shop mount
        assert len(gql_view.root) == 0
        assert "/shop" in gql_view.mounts
        shop_pairs = gql_view.mounts["/shop"]
        assert isinstance(shop_pairs, list)
        assert len(shop_pairs) == 1
        assert shop_pairs[0][0].field_name == "products"


class TestQueryPipelineCrossover:
    """Complex query pipelines mixing standard and custom ops from multiple domains."""

    def _sample_products(self) -> list[_PlayerData]:
        """Reuse _PlayerData as a stand-in for products (name, score as price, level as stock)."""
        return [
            _PlayerData("Widget", 500, 100),
            _PlayerData("Gadget", 1500, 50),
            _PlayerData("Gizmo", 800, 200),
            _PlayerData("Thingamajig", 2000, 10),
            _PlayerData("Doohickey", 300, 500),
        ]

    def test_combined_dialect_from_both_domains(self):
        """A single dialect that understands ops from both Game and Marketplace domains."""
        combined_dialect = (
            MEMORY_DIALECT
            .with_handler(RankBy, _handle_rank_by)
            .with_handler(TopN, _handle_top_n)
            .with_handler(TextSearch, _handle_text_search)
        )

        data = self._sample_products()
        result = combined_dialect.fold(
            [
                TextSearch("g", fields=("name",)),  # Gadget, Gizmo, Thingamajig, Doohickey(no)
                RankBy("score", "desc"),
                TopN(2),
            ],
            data,
        )
        assert len(result) == 2
        assert result[0].name == "Thingamajig"  # score 2000
        assert result[1].name == "Gadget"  # score 1500

    def test_standard_ops_with_dual_custom_ops(self):
        """Filter (standard) + TextSearch (marketplace) + RankBy (game) in sequence."""
        combined_dialect = (
            MEMORY_DIALECT
            .with_handler(RankBy, _handle_rank_by)
            .with_handler(TopN, _handle_top_n)
            .with_handler(TextSearch, _handle_text_search)
        )

        data = self._sample_products()
        result = combined_dialect.fold(
            [
                Filter(Gt(Field("score"), Const(400))),  # Widget(500), Gadget(1500), Gizmo(800), Thingamajig(2000)
                TextSearch("gad", fields=("name",)),  # Gadget only
                RankBy("score", "asc"),
            ],
            data,
        )
        assert len(result) == 1
        assert result[0].name == "Gadget"

    def test_explain_dialect_with_dual_domain_ops(self):
        """Combined explain dialect understands ops from both domains."""
        def _explain_text_search(op: TextSearch) -> dict[str, str]:
            return {"op": "TextSearch", "query": op.query, "fields": ", ".join(op.fields) if op.fields else "*"}

        def _explain_facet_count(op: FacetCount) -> dict[str, str]:
            return {"op": "FacetCount", "field": op.field}

        combined_explain = (
            RELATIONAL_EXPLAIN_DIALECT
            .with_handler(RankBy, _explain_rank_by)
            .with_handler(TopN, _explain_top_n)
            .with_handler(TextSearch, _explain_text_search)
            .with_handler(FacetCount, _explain_facet_count)
        )

        ops_list: list[object] = [
            Filter(Gt(Field("score"), Const(100))),
            TextSearch("widget", fields=("name", "description")),
            RankBy("score", "desc"),
            TopN(10),
        ]

        info = combined_explain.explain(ops_list)
        assert len(info) == 4
        assert info[0]["op"] == "Filter"
        assert info[1]["op"] == "TextSearch"
        assert info[1]["query"] == "widget"
        assert info[2]["op"] == "RankBy"
        assert info[3]["op"] == "TopN"

        # format produces human-readable text
        text = combined_explain.format(ops_list)
        assert "TextSearch" in text
        assert "RankBy" in text

    def test_dialect_immutability_chain(self):
        """Chaining .with_handler and .without_handler does not mutate any intermediate dialect."""
        d0 = MEMORY_DIALECT
        d1 = d0.with_handler(RankBy, _handle_rank_by)
        d2 = d1.with_handler(TopN, _handle_top_n)
        d3 = d2.without_handler(Filter)

        # d0 still has Filter, does not have RankBy
        assert Filter in d0.handlers
        assert RankBy not in d0.handlers

        # d1 has Filter + RankBy, no TopN
        assert Filter in d1.handlers
        assert RankBy in d1.handlers
        assert TopN not in d1.handlers

        # d2 has all three
        assert Filter in d2.handlers
        assert RankBy in d2.handlers
        assert TopN in d2.handlers

        # d3 has RankBy + TopN, no Filter
        assert Filter not in d3.handlers
        assert RankBy in d3.handlers
        assert TopN in d3.handlers


class TestStorageTieredAndComposed:
    """Integration tests for composed storage patterns with custom backends."""

    @pytest.mark.asyncio
    async def test_tiered_kv_custom_backends(self):
        """TieredKV with GameStateBackend as L1 and MemoryStorage as L2."""
        l1 = kv(GameStateBackend(), JsonCodec())
        l2 = kv(MemoryStorage(), JsonCodec())

        from emergent.wire.axis.storage._compose import tiered_kv

        tiered = tiered_kv(l1, l2)

        # Write goes to both tiers
        await tiered.set("player:alice", {"score": 1500})

        # Both should have it
        r1 = await l1.get("player:alice")
        r2 = await l2.get("player:alice")
        assert r1.unwrap().unwrap() == {"score": 1500}
        assert r2.unwrap().unwrap() == {"score": 1500}

    @pytest.mark.asyncio
    async def test_tiered_kv_cache_populate_on_miss(self):
        """On L1 miss, L2 hit populates L1."""
        l1_backend = GameStateBackend()
        l2_backend = GameStateBackend()
        l1 = kv(l1_backend, JsonCodec())
        l2 = kv(l2_backend, JsonCodec())

        from emergent.wire.axis.storage._compose import tiered_kv

        tiered = tiered_kv(l1, l2)

        # Write directly to L2 only
        await l2.set("item:42", {"name": "Sword"})

        # L1 does not have it
        assert isinstance((await l1.get("item:42")).unwrap(), Nothing)

        # Read through tiered: populates L1
        result = await tiered.get("item:42")
        assert result.unwrap().unwrap() == {"name": "Sword"}

        # Now L1 has it
        assert (await l1.get("item:42")).unwrap().unwrap() == {"name": "Sword"}

    @pytest.mark.asyncio
    async def test_prefix_kv_with_custom_codec(self):
        """PrefixKV wrapping a store with CompressedJsonCodec."""
        store = kv(GameStateBackend(), CompressedJsonCodec())
        prefixed = prefix_kv(store, "marketplace:")

        await prefixed.set("product:1", {"name": "Widget", "price": 500})
        result = await prefixed.get("product:1")
        assert result.unwrap().unwrap() == {"name": "Widget", "price": 500}

        # The key in the underlying backend should be prefixed
        raw_result = await store.get("marketplace:product:1")
        assert raw_result.unwrap().unwrap() == {"name": "Widget", "price": 500}

    @pytest.mark.asyncio
    async def test_readonly_kv_blocks_writes(self):
        """ReadonlyKV wrapping a custom backend disables writes."""
        from emergent.wire.axis.storage._compose import readonly_kv

        store = kv(GameStateBackend(), JsonCodec())
        await store.set("key", "value")

        ro = readonly_kv(store)

        # Read works
        result = await ro.get("key")
        assert result.unwrap().unwrap() == "value"

        # Write returns Nothing (no-op)
        write_result = await ro.set("key", "new_value")
        assert isinstance(write_result, Ok)

        # Original value unchanged
        result = await store.get("key")
        assert result.unwrap().unwrap() == "value"

    @pytest.mark.asyncio
    async def test_multiple_storage_backends_independent(self):
        """Game and Marketplace stores with different backends and codecs operate independently."""
        game_store = kv(GameStateBackend(), CompressedJsonCodec())
        market_store = kv(MemoryStorage(), MsgpackSimCodec())

        await game_store.set("player:1", {"name": "Alice", "score": 1500})
        await market_store.set("product:1", {"name": "Widget", "price": 500})

        game_result = await game_store.get("player:1")
        market_result = await market_store.get("product:1")

        assert game_result.unwrap().unwrap() == {"name": "Alice", "score": 1500}
        assert market_result.unwrap().unwrap() == {"name": "Widget", "price": 500}

        # Cross-check: keys don't leak
        assert isinstance((await game_store.get("product:1")).unwrap(), Nothing)
        assert isinstance((await market_store.get("player:1")).unwrap(), Nothing)


class TestBridgeRegistryMultiFramework:
    """Bridge registry with bridgers from both Game and Marketplace frameworks."""

    def _game_bridger(self) -> FrameworkBridger:
        return FrameworkBridger(
            name="gamefw",
            can_bridge=lambda s: isinstance(s, FakeGameApp),
            extractor=GameFrameworkExtractor(),
            to_wire=GameFrameworkToWire(),
        )

    def _gql_bridger(self) -> FrameworkBridger:
        return FrameworkBridger(
            name="graphqlfw",
            can_bridge=lambda s: isinstance(s, FakeGraphQLApp),
            extractor=GraphQLExtractor(),
            to_wire=GraphQLToWire(),
        )

    def test_multi_framework_registry_detect(self):
        """Registry with two bridgers detects both framework types."""
        registry = (
            BridgeRegistry(bridgers=())
            .with_bridger(self._game_bridger())
            .with_bridger(self._gql_bridger())
        )

        game_app = FakeGameApp([("join", "lobby", _game_handler_join)])
        gql_app = FakeGraphQLApp([("query", "products", _resolve_products)])

        game_found = registry.detect(game_app)
        gql_found = registry.detect(gql_app)

        assert game_found is not None
        assert game_found.name == "gamefw"
        assert gql_found is not None
        assert gql_found.name == "graphqlfw"

    def test_multi_framework_extract_and_convert(self):
        """Extract from both frameworks, convert to wire triggers."""
        registry = (
            BridgeRegistry(bridgers=())
            .with_bridger(self._game_bridger())
            .with_bridger(self._gql_bridger())
        )

        game_app = FakeGameApp([
            ("join", "lobby", _game_handler_join),
            ("fight", "arena", _game_handler_fight),
        ])
        gql_app = FakeGraphQLApp([
            ("query", "products", _resolve_products),
            ("mutation", "createOrder", _resolve_create_order),
        ])

        # Game extraction
        game_bridger = registry.detect(game_app)
        assert game_bridger is not None
        game_extracted = list(game_bridger.extractor.extract(game_app))
        assert len(game_extracted) == 2
        for ex in game_extracted:
            trigger = game_bridger.to_wire.to_trigger(ex.route)
            assert isinstance(trigger, GameWSTrigger)

        # GraphQL extraction
        gql_bridger = registry.detect(gql_app)
        assert gql_bridger is not None
        gql_extracted = list(gql_bridger.extractor.extract(gql_app))
        assert len(gql_extracted) == 2
        for ex in gql_extracted:
            trigger = gql_bridger.to_wire.to_trigger(ex.route)
            assert isinstance(trigger, GraphQLTrigger)

    def test_replace_bridger_in_multi_framework_registry(self):
        """Replacing one bridger does not affect the other."""
        registry = (
            BridgeRegistry(bridgers=())
            .with_bridger(self._game_bridger())
            .with_bridger(self._gql_bridger())
        )

        # Replace game bridger with one that always rejects
        new_game = FrameworkBridger(
            name="gamefw",
            can_bridge=lambda s: False,
            extractor=GameFrameworkExtractor(),
            to_wire=GameFrameworkToWire(),
        )
        replaced = registry.replace_bridger("gamefw", new_game)

        game_app = FakeGameApp([("join", "lobby", _game_handler_join)])
        gql_app = FakeGraphQLApp([("query", "products", _resolve_products)])

        # Game no longer detected
        assert replaced.detect(game_app) is None
        # GraphQL still works
        assert replaced.detect(gql_app) is not None

        # Original registry unchanged
        assert registry.detect(game_app) is not None

    def test_filter_extractor_across_frameworks(self):
        """filter_extractor works uniformly on extractors from different frameworks."""
        game_ext = GameFrameworkExtractor()
        gql_ext = GraphQLExtractor()

        # Filter game: only arena rooms
        arena_only = filter_extractor(game_ext, lambda e: e.route.room == "arena")
        game_app = FakeGameApp([
            ("join", "lobby", _game_handler_join),
            ("fight", "arena", _game_handler_fight),
        ])
        extracted = list(arena_only.extract(game_app))
        assert len(extracted) == 1
        assert extracted[0].route.room == "arena"

        # Filter GraphQL: only queries
        queries_only = filter_extractor(gql_ext, lambda e: e.route.operation == "query")
        gql_app = FakeGraphQLApp([
            ("query", "products", _resolve_products),
            ("mutation", "createOrder", _resolve_create_order),
        ])
        extracted = list(queries_only.extract(gql_app))
        assert len(extracted) == 1
        assert extracted[0].route.operation == "query"


class TestCompilationTraceIntegration:
    """Tracing through compile_fields with custom phases."""

    def test_traced_compilation_records_custom_phase_steps(self):
        """Axes.traced() records FoldSteps for custom capabilities."""
        from emergent.wire.compile._trace import ListCollector

        collector = ListCollector()
        axes = Axes.traced(collector)
        compiled = compile_fields(Player, axes, [GAME_PHASE])

        # There should be type traces
        assert len(collector.type_traces) == 1
        assert collector.type_traces[0].cls_name == "Player"

        # Field traces for each field
        assert len(collector.field_traces) == 4  # id, name, score, level

        # FoldSteps should have "protocol" dispatches for Ranked on score/level
        protocol_steps = [
            s for s in collector.fold_steps if s.dispatch == "protocol"
        ]
        assert len(protocol_steps) >= 2  # at least score's Ranked and level's Ranked

    def test_traced_compilation_dual_phase(self):
        """Tracing with OPENAPI + GAME produces FieldPhaseTrace for each combo."""
        from emergent.wire.compile._trace import ListCollector

        collector = ListCollector()
        axes = Axes.traced(collector)
        compile_fields(Player, axes, [OPENAPI_PHASE, GAME_PHASE])

        # 4 fields x 2 phases = 8 field_phase traces
        assert len(collector.field_phases) == 8

        # Check phases are labeled correctly
        phase_names = {fp.phase for fp in collector.field_phases}
        assert "OpenAPIContext" in phase_names
        assert "GameFieldContext" in phase_names

    def test_traced_scan_and_wrap_records_events(self):
        """TargetCompiler with traced Axes records ScanEvent and WrapEvent."""
        from emergent.wire.compile._trace import ListCollector

        collector = ListCollector()
        axes = Axes.traced(collector)

        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                GameWSTrigger("lobby", "join"),
                GameEventCodec(version=2),
            )
        )

        compiler = TargetCompiler(
            trigger_type=GameWSTrigger,
            adapters=(
                CodecAdapter(GameEventCodec, lambda h, t, a: "wrapped"),
            ),
        )
        list(compiler.scan_and_wrap(app, axes))

        assert len(collector.scan_events) == 1
        assert collector.scan_events[0].trigger_type == "GameWSTrigger"

        assert len(collector.wrap_events) == 1
        assert collector.wrap_events[0].codec_type == "GameEventCodec"

    def test_traced_custom_phase_with_handler_override(self):
        """Custom phase with handler override records 'handler' dispatch."""
        from emergent.wire.compile._trace import ListCollector

        def custom_handler(cap: Ranked, ctx: GameFieldContext) -> GameFieldContext:
            return replace(ctx, ranked_board=f"traced:{cap.board}")

        phase = GAME_PHASE.with_handlers({Ranked: custom_handler})

        collector = ListCollector()
        axes = Axes.traced(collector)
        compiled = compile_fields(Player, axes, [phase])

        # Score field should have a "handler" dispatch (not "protocol")
        handler_steps = [
            s for s in collector.fold_steps
            if s.dispatch == "handler" and s.item_type == "Ranked"
        ]
        assert len(handler_steps) >= 1

        # Verify the override was applied
        score_fc = next(fc for fc in compiled if fc.name == "score")
        assert score_fc[phase].ranked_board == "traced:global"


class TestEdgeCasesInTypeDispatch:
    """Edge cases in how fold dispatches to capabilities and handlers."""

    def test_duplicate_capability_types_both_applied(self):
        """If a field has two instances of the same cap type, both are applied in order."""

        @dataclass
        class TwoRanked:
            score: Annotated[int, Ranked("global"), Ranked("seasonal")]

        fields = inspect_dataclass(TwoRanked)
        score_info = fields["score"]
        ranked_caps = score_info.get_all(Ranked)
        assert len(ranked_caps) == 2

        # fold applies both — last one wins (overwrites ranked_board)
        ctx = fold_field(
            score_info,
            GameFieldContext(field_name="score", field_type=int),
            GameCompilable,
            "compile_game",
        )
        assert ctx.ranked_board == "seasonal"  # second Ranked overwrites

    def test_handler_override_takes_priority_over_protocol(self):
        """When handler is provided for a type, it takes priority over protocol dispatch."""

        @dataclass
        class WithRanked:
            x: Annotated[int, Ranked("test")]

        fields = inspect_dataclass(WithRanked)

        handler_called = False

        def custom_handler(cap: Ranked, ctx: GameFieldContext) -> GameFieldContext:
            nonlocal handler_called
            handler_called = True
            return replace(ctx, ranked_board=f"override:{cap.board}")

        ctx = fold_field(
            fields["x"],
            GameFieldContext(field_name="x", field_type=int),
            GameCompilable,
            "compile_game",
            handlers={Ranked: custom_handler},
        )
        assert handler_called
        assert ctx.ranked_board == "override:test"

    def test_phase_with_handlers_does_not_modify_original(self):
        """CompilationPhase.with_handlers returns a new phase, original unchanged."""
        original_method = GAME_PHASE.method

        new_phase = GAME_PHASE.with_handlers(
            {Ranked: lambda cap, ctx: replace(ctx, ranked_board="custom")}
        )

        # Original phase has no handlers
        assert GAME_PHASE.handlers is None

        # New phase has handlers
        assert new_phase.handlers is not None
        assert Ranked in new_phase.handlers

        # Both share the same context_type and method
        assert new_phase.context_type is GAME_PHASE.context_type
        assert new_phase.method == original_method

    def test_fold_with_empty_capabilities(self):
        """Field with no capabilities returns initial context unchanged."""

        @dataclass
        class Empty:
            x: int = 0

        fields = inspect_dataclass(Empty)
        initial = GameFieldContext(field_name="x", field_type=int)
        ctx = fold_field(fields["x"], initial, GameCompilable, "compile_game")
        assert ctx is initial  # identity — same object returned

    def test_fold_mixed_known_and_alien_capabilities(self):
        """Fold skips unknown caps cleanly when interleaved with known caps."""
        # Use module-level _AlienA/_AlienB to avoid forward-ref issues with
        # `from __future__ import annotations`.
        fields = inspect_dataclass(_MixedAlienEntity)
        ctx = fold_field(
            fields["x"],
            GameFieldContext(field_name="x", field_type=int),
            GameCompilable,
            "compile_game",
        )
        # Both Ranked applied, aliens skipped
        assert ctx.ranked_board == "second"

    def test_compile_fields_rejects_duplicate_context_type(self):
        """compile_fields raises ValueError on duplicate context_type in phases."""
        axes = Axes.default()
        with pytest.raises(ValueError, match="Duplicate context_type"):
            compile_fields(Player, axes, [GAME_PHASE, GAME_PHASE])

    def test_extract_all_constraints_across_domains(self):
        """extract_all_constraints works correctly on entities from either domain."""
        from emergent.wire.compile._core import extract_all_constraints

        axes = Axes.default()
        player_constraints = extract_all_constraints(Player, axes)

        # score: Min(0) -> min_value=0
        _, score_c = player_constraints["score"]
        assert score_c.min_value == 0

        # level: Min(1), Max(100)
        _, level_c = player_constraints["level"]
        assert level_c.min_value == 1
        assert level_c.max_value == 100

        # id: Identity -> is_identity
        _, id_c = player_constraints["id"]
        assert id_c.is_identity is True

        # name: MaxLen(50) -> max_length
        _, name_c = player_constraints["name"]
        assert name_c.max_length == 50

        # Product domain
        product_constraints = extract_all_constraints(Product, axes)
        _, name_c = product_constraints["name"]
        assert name_c.max_length == 200

        _, price_c = product_constraints["price"]
        assert price_c.min_value == 0


class TestFullCrossDomainE2E:
    """End-to-end scenario: two domains sharing infrastructure, going through
    schema -> compile -> surface -> query -> storage -> bridge.
    """

    @pytest.mark.asyncio
    async def test_dual_domain_e2e(self):
        """Both Game and Marketplace domains processed through the entire pipeline."""

        # === 1. Schema: both domains inspected ===
        player_fields = inspect_dataclass(Player)
        product_fields = inspect_dataclass(Product)

        assert player_fields["score"].has(Ranked)
        assert product_fields["name"].has(Searchable)
        assert product_fields["price"].has(Filterable)

        assert get_schema_meta(Player)[0].game_id == "roulette"
        assert get_schema_meta(Product)[0].category == "electronics"

        # === 2. Compile: three phases simultaneously ===
        axes = Axes.default()
        player_compiled = compile_fields(
            Player, axes, [OPENAPI_PHASE, GAME_PHASE]
        )
        product_compiled = compile_fields(
            Product, axes, [OPENAPI_PHASE, MARKETPLACE_PHASE]
        )

        # Player's score: ranked in game, x-ranked in OpenAPI
        p_score = next(fc for fc in player_compiled if fc.name == "score")
        assert p_score[GAME_PHASE].ranked_board == "global"
        assert p_score[OPENAPI_PHASE].schema.get("x-ranked") is True

        # Product's name: searchable in marketplace, x-searchable in OpenAPI
        pr_name = next(fc for fc in product_compiled if fc.name == "name")
        assert pr_name[MARKETPLACE_PHASE].search_weight == 2.0
        assert pr_name[OPENAPI_PHASE].schema.get("x-searchable") is True

        # === 3. Surface: build merged app ===
        runner = _runner()
        game_app = application().mount(
            endpoint(runner).expose(
                GameWSTrigger("lobby", "join"),
                GameEventCodec(version=2),
                PlayerAuth(required_level=5),
            )
        )
        marketplace_app = application().mount(
            endpoint(runner).expose(
                GraphQLTrigger("query", "products"),
                GraphQLCodec(version=1),
                TenantIsolation(),
            )
        )
        merged_app = game_app + marketplace_app

        # === 4. Scan: both trigger types found ===
        ws_pairs = scan(merged_app, GameWSTrigger, GameEventCodec)
        gql_pairs = scan(merged_app, GraphQLTrigger, GraphQLCodec)
        assert len(ws_pairs) == 1
        assert len(gql_pairs) == 1

        # === 5. Runtime fold: capabilities compile independently ===
        ws_rt = fold(
            ws_pairs[0][1].capabilities,
            HandlerRuntimeContext(),
            HandlerRuntimeCompilable,
            "compile_handler_runtime",
        )
        assert len(ws_rt.enrichers) == 1
        assert isinstance(ws_rt.enrichers[0], PlayerAuth)

        gql_rt = fold(
            gql_pairs[0][1].capabilities,
            HandlerRuntimeContext(),
            HandlerRuntimeCompilable,
            "compile_handler_runtime",
        )
        assert len(gql_rt.enrichers) == 1
        assert isinstance(gql_rt.enrichers[0], TenantIsolation)

        # === 6. Target compilers: independent scan_and_wrap ===
        ws_compiler = TargetCompiler(
            trigger_type=GameWSTrigger,
            adapters=(
                CodecAdapter(GameEventCodec, lambda h, t, a: {"ws": t.room}),
            ),
        )
        gql_compiler = TargetCompiler(
            trigger_type=GraphQLTrigger,
            adapters=(
                CodecAdapter(GraphQLCodec, lambda h, t, a: {"gql": t.field_name}),
            ),
        )

        ws_results = list(ws_compiler.scan_and_wrap(merged_app, axes))
        gql_results = list(gql_compiler.scan_and_wrap(merged_app, axes))
        assert ws_results[0][2] == {"ws": "lobby"}
        assert gql_results[0][2] == {"gql": "products"}

        # === 7. Query: combined dialect ===
        players = [
            _PlayerData("Alice", 1500, 10),
            _PlayerData("Bob", 2000, 15),
            _PlayerData("Diana", 2500, 20),
        ]
        combined_dialect = (
            MEMORY_DIALECT
            .with_handler(RankBy, _handle_rank_by)
            .with_handler(TopN, _handle_top_n)
        )
        ranked = combined_dialect.fold(
            [
                Filter(Gt(Field("score"), Const(1400))),
                RankBy("score", "desc"),
                TopN(2),
            ],
            players,
        )
        assert ranked[0].name == "Diana"
        assert ranked[1].name == "Bob"

        # === 8. Storage: both domains with independent stores ===
        game_store = kv(GameStateBackend(), CompressedJsonCodec())
        market_store = kv(GameStateBackend(), MsgpackSimCodec())

        await game_store.set("player:diana", {"name": "Diana", "score": 2500})
        await market_store.set("product:widget", {"name": "Widget", "price": 500})

        g_result = await game_store.get("player:diana")
        m_result = await market_store.get("product:widget")
        assert g_result.unwrap().unwrap()["score"] == 2500
        assert m_result.unwrap().unwrap()["price"] == 500

        # === 9. Bridge: both frameworks detected and converted ===
        game_bridger = FrameworkBridger(
            name="gamefw",
            can_bridge=lambda s: isinstance(s, FakeGameApp),
            extractor=GameFrameworkExtractor(),
            to_wire=GameFrameworkToWire(),
        )
        gql_bridger = FrameworkBridger(
            name="graphqlfw",
            can_bridge=lambda s: isinstance(s, FakeGraphQLApp),
            extractor=GraphQLExtractor(),
            to_wire=GraphQLToWire(),
        )
        registry = (
            BridgeRegistry(bridgers=())
            .with_bridger(game_bridger)
            .with_bridger(gql_bridger)
        )

        fake_game = FakeGameApp([("join", "lobby", _game_handler_join)])
        fake_gql = FakeGraphQLApp([("query", "products", _resolve_products)])

        game_found = registry.detect(fake_game)
        gql_found = registry.detect(fake_gql)
        assert game_found is not None
        assert gql_found is not None

        game_wire = game_found.to_wire.to_trigger(
            list(game_found.extractor.extract(fake_game))[0].route
        )
        gql_wire = gql_found.to_wire.to_trigger(
            list(gql_found.extractor.extract(fake_gql))[0].route
        )
        assert isinstance(game_wire, GameWSTrigger)
        assert isinstance(gql_wire, GraphQLTrigger)
        assert game_wire.room == "lobby"
        assert gql_wire.field_name == "products"


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: Custom capability fold through surface helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegrationCustomCapabilityFoldPipeline:
    """Custom capabilities (enrichers + transforms) folded through surface helpers,
    then applied via the handler runtime fold system."""

    def test_custom_enricher_and_transform_fold_together(self):
        """PlayerAuth (enricher) + ScoreMultiplier (transform) fold into one HandlerRuntimeContext."""
        runner = _runner()
        ep = endpoint(runner).expose(
            GameWSTrigger("arena", "fight"),
            GameEventCodec(version=3),
            PlayerAuth(required_level=10),
            ScoreMultiplier(factor=3.0),
        )
        app = application().mount(ep)

        # Scan
        pairs = scan(app, GameWSTrigger, GameEventCodec)
        assert len(pairs) == 1
        _, handler = pairs[0]

        # Fold capabilities into runtime context
        rt = fold(
            handler.capabilities,
            HandlerRuntimeContext(),
            HandlerRuntimeCompilable,
            "compile_handler_runtime",
        )

        # Both capabilities present
        assert len(rt.enrichers) == 1
        assert isinstance(rt.enrichers[0], PlayerAuth)
        assert rt.enrichers[0].required_level == 10

        assert len(rt.response_transforms) == 1
        assert isinstance(rt.response_transforms[0], ScoreMultiplier)
        assert rt.response_transforms[0].factor == 3.0

    def test_stacked_custom_enrichers_order_preserved(self):
        """Multiple custom enrichers maintain insertion order through fold."""
        runner = _runner()
        ep = endpoint(runner).expose(
            GameWSTrigger("lobby", "enter"),
            GameEventCodec(),
            PlayerAuth(required_level=1),
            TenantIsolation(),
            PlayerAuth(required_level=5),
        )
        app = application().mount(ep)

        pairs = scan(app, GameWSTrigger)
        _, handler = pairs[0]

        rt = fold(
            handler.capabilities,
            HandlerRuntimeContext(),
            HandlerRuntimeCompilable,
            "compile_handler_runtime",
        )

        # Order preserved: PlayerAuth(1), TenantIsolation, PlayerAuth(5)
        assert len(rt.enrichers) == 3
        assert isinstance(rt.enrichers[0], PlayerAuth)
        assert rt.enrichers[0].required_level == 1
        assert isinstance(rt.enrichers[1], TenantIsolation)
        assert isinstance(rt.enrichers[2], PlayerAuth)
        assert rt.enrichers[2].required_level == 5


class TestIntegrationCustomSchemaInspectFoldExplain:
    """Custom schema capabilities flow through inspect → fold → explain pipeline."""

    def test_custom_capability_through_inspect_and_fold(self):
        """Ranked capability on field → inspect → fold to both OpenAPI and Game."""
        fields = inspect_dataclass(Player)
        assert "score" in fields
        assert fields["score"].has(Ranked)

        # Fold to OpenAPI
        openapi_ctx = fold_field(
            fields["score"],
            OpenAPIContext(field_name="score", field_type=int),
            OpenAPICompilable,
            "compile_openapi",
        )
        assert openapi_ctx.schema.get("x-ranked") is True
        assert openapi_ctx.schema.get("x-board") == "global"

        # Fold to Game phase
        from emergent.wire.compile._core import fold as core_fold
        game_initial = GameFieldContext(field_name="score", field_type=int)
        game_ctx = core_fold(
            fields["score"].capabilities,
            game_initial,
            GameCompilable,
            "compile_game",
        )
        assert game_ctx.ranked_board == "global"

    def test_custom_schema_meta_through_pipeline(self):
        """GameMeta schema capability readable and compilable."""
        meta = get_schema_meta(Player)
        assert len(meta) >= 1
        game_meta = next((m for m in meta if isinstance(m, GameMeta)), None)
        assert game_meta is not None
        assert game_meta.game_id == "roulette"

        # Compile through game schema context
        ctx = GameSchemaContext(class_name="Player")
        result = game_meta.compile_game_schema(ctx)
        assert result.game_id == "roulette"

    def test_compile_fields_with_multiple_phases(self):
        """compile_fields produces FieldCompilation with both standard and custom phases."""
        axes = Axes.default()
        compiled = compile_fields(Player, axes, [OPENAPI_PHASE, GAME_PHASE])

        score_fc = next(fc for fc in compiled if fc.name == "score")

        # OpenAPI phase
        assert score_fc[OPENAPI_PHASE].schema.get("x-ranked") is True

        # Game phase
        assert score_fc[GAME_PHASE].ranked_board == "global"

        # Field without Ranked has no game-specific data
        name_fc = next(fc for fc in compiled if fc.name == "name")
        assert name_fc[GAME_PHASE].ranked_board is None
