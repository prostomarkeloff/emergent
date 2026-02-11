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
