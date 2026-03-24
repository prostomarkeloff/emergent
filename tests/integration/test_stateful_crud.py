"""Stateful CRUD testing via hypothesis RuleBasedStateMachine.

Generates random sequences of CRUD operations against a compiled TestApp.
Model state (dict) mirrors expected database; invariants checked after every step.

Uses wire.verify to confirm entity has no contradictions, then extracts
constraints from verify phases to generate VALID random data within bounds.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Annotated

import pytest
from hypothesis import settings
from hypothesis.stateful import (
    Bundle,
    RuleBasedStateMachine,
    initialize,
    invariant,
    rule,
)
from hypothesis import strategies as st

from nodnod import scalar_node

from emergent.wire.axis.query._provider import SequenceNextId
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
from emergent.wire.axis.schema._inspect import inspect_dataclass
from emergent.wire.axis.schema._universal import (
    Identity,
    Max,
    MaxLen,
    Min,
    MinLen,
    schema_meta,
)
from emergent.wire.axis.surface._app import Application
from emergent.wire.compile._core import Axes
from emergent.wire.compile.targets.testing import testing_compile as compile_for_test
from emergent.wire.derive import compile_derive, materialize
from emergent.wire.derive._crud import http_crud
from emergent.wire.verify import verify
from emergent.wire.verify._length import LENGTH_VERIFY_PHASE
from emergent.wire.verify._numeric import NUMERIC_VERIFY_PHASE
from emergent.wire.verify._verify import VERIFY_SCHEMA


# ---------------------------------------------------------------------------
# Infrastructure helpers
# ---------------------------------------------------------------------------


def _run(coro: object) -> object:
    """Run a coroutine synchronously for hypothesis stateful testing."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)  # type: ignore[arg-type]
    finally:
        loop.close()


def _memory_node(key_field: str = "id") -> type:
    """Create a scalar_node backed by in-memory relational provider."""
    next_id = SequenceNextId()
    store: MemoryRelationalProvider[object] = MemoryRelationalProvider(
        key_fn=lambda x: getattr(x, key_field),
        next_id=next_id,
    )

    @scalar_node
    class _Node:
        @classmethod
        def __compose__(cls) -> MemoryRelationalProvider[object]:
            return store

    return _Node


# ---------------------------------------------------------------------------
# Entity definition (for verify/constraint extraction only)
# ---------------------------------------------------------------------------

_VerifyUsersNode = _memory_node()


@schema_meta(http_crud("/users", provider_node=_VerifyUsersNode))
@dataclass
class _VerifyUser:
    id: Annotated[int, Identity]
    name: Annotated[str, MinLen(1), MaxLen(50)]
    age: Annotated[int, Min(0), Max(200)]


# ---------------------------------------------------------------------------
# Verify entity has no contradictions
# ---------------------------------------------------------------------------


def test_user_entity_has_no_contradictions() -> None:
    """Smoke test: verify(User) reports zero issues."""
    issues = verify(_VerifyUser)
    assert len(issues) == 0, f"Unexpected issues: {issues}"


# ---------------------------------------------------------------------------
# Extract constraints from verify phases
# ---------------------------------------------------------------------------


def _extract_constraints(entity: type) -> dict[str, dict[str, object]]:
    """Use verify infrastructure to extract numeric and length constraints."""
    axes = Axes.default()
    ec = VERIFY_SCHEMA.compile(entity, axes)
    result: dict[str, dict[str, object]] = {}
    for fc in ec:
        numeric = fc[NUMERIC_VERIFY_PHASE]
        length = fc[LENGTH_VERIFY_PHASE]
        field_name = numeric.field_name
        result[field_name] = {
            "lower_bound": numeric.lower_bound,
            "upper_bound": numeric.upper_bound,
            "min_length": length.min_length,
            "max_length": length.max_length,
        }
    return result


def test_extracted_constraints_match_user() -> None:
    """Verify extracted constraints match what we declared."""
    constraints = _extract_constraints(_VerifyUser)
    assert constraints["age"]["lower_bound"] == 0.0
    assert constraints["age"]["upper_bound"] == 200.0
    assert constraints["name"]["min_length"] == 1
    assert constraints["name"]["max_length"] == 50


# ---------------------------------------------------------------------------
# Strategies derived from constraints
# ---------------------------------------------------------------------------

_USER_CONSTRAINTS = _extract_constraints(_VerifyUser)

_name_strategy = st.text(
    min_size=_USER_CONSTRAINTS["name"]["min_length"] or 1,  # type: ignore[arg-type]
    max_size=_USER_CONSTRAINTS["name"]["max_length"] or 50,  # type: ignore[arg-type]
    alphabet=st.characters(categories=("L", "N", "Z")),
).filter(lambda s: len(s.strip()) > 0)

_age_strategy = st.integers(
    min_value=int(_USER_CONSTRAINTS["age"]["lower_bound"] or 0),
    max_value=int(_USER_CONSTRAINTS["age"]["upper_bound"] or 200),
)


# ---------------------------------------------------------------------------
# Fresh app builder (creates new provider + entity each time)
# ---------------------------------------------------------------------------


def _build_fresh_test_app() -> object:
    """Build a test app with isolated in-memory state.

    Creates a NEW _memory_node and a NEW entity class so the underlying
    MemoryRelationalProvider is fresh per state-machine run.
    """
    node = _memory_node()

    @schema_meta(http_crud("/users", provider_node=node))
    @dataclass
    class User:
        id: Annotated[int, Identity]
        name: Annotated[str, MinLen(1), MaxLen(50)]
        age: Annotated[int, Min(0), Max(200)]

    endpoints = []
    for ctx in compile_derive(User):
        endpoints.append(materialize(ctx))
    app = Application().mount(*endpoints)
    axes = Axes(schema=inspect_dataclass)
    return compile_for_test(app, axes=axes)


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class CrudStateMachine(RuleBasedStateMachine):
    """Stateful test: random CRUD operations with model oracle."""

    created_ids = Bundle("created_ids")

    def __init__(self) -> None:
        super().__init__()
        self.model: dict[int, dict[str, object]] = {}
        self.test_app = _build_fresh_test_app()

    # -- routes ---------------------------------------------------------------

    @property
    def _list_route(self) -> object:
        return self.test_app.routes[0]  # type: ignore[union-attr]

    @property
    def _get_route(self) -> object:
        return self.test_app.routes[1]  # type: ignore[union-attr]

    @property
    def _create_route(self) -> object:
        return self.test_app.routes[2]  # type: ignore[union-attr]

    @property
    def _update_route(self) -> object:
        return self.test_app.routes[3]  # type: ignore[union-attr]

    @property
    def _delete_route(self) -> object:
        return self.test_app.routes[5]  # type: ignore[union-attr]

    # -- rules ----------------------------------------------------------------

    @rule(target=created_ids, name=_name_strategy, age=_age_strategy)
    def create(self, name: str, age: int) -> int:
        result = _run(self._create_route.call({"name": name, "age": age}))  # type: ignore[union-attr]
        entity_id: int = result.id  # type: ignore[union-attr]
        self.model[entity_id] = {"id": entity_id, "name": name, "age": age}
        return entity_id

    @rule(entity_id=created_ids)
    def get_by_id(self, entity_id: int) -> None:
        result = _run(self._get_route.call({"id": entity_id}))  # type: ignore[union-attr]
        if entity_id in self.model:
            expected = self.model[entity_id]
            assert result.id == expected["id"]  # type: ignore[union-attr]
            assert result.name == expected["name"]  # type: ignore[union-attr]
            assert result.age == expected["age"]  # type: ignore[union-attr]

    @rule(entity_id=created_ids, name=_name_strategy, age=_age_strategy)
    def update(self, entity_id: int, name: str, age: int) -> None:
        if entity_id not in self.model:
            return
        result = _run(
            self._update_route.call(  # type: ignore[union-attr]
                {"id": entity_id, "name": name, "age": age}
            )
        )
        assert result.id == entity_id  # type: ignore[union-attr]
        assert result.name == name  # type: ignore[union-attr]
        assert result.age == age  # type: ignore[union-attr]
        self.model[entity_id] = {"id": entity_id, "name": name, "age": age}

    @rule(entity_id=created_ids)
    def delete(self, entity_id: int) -> None:
        if entity_id not in self.model:
            return
        result = _run(self._delete_route.call({"id": entity_id}))  # type: ignore[union-attr]
        assert result.success is True  # type: ignore[union-attr]
        del self.model[entity_id]

    @rule()
    def list_all(self) -> None:
        result = _run(self._list_route.call())  # type: ignore[union-attr]
        items = result.items  # type: ignore[union-attr]
        assert len(items) == len(self.model)

    # -- invariants -----------------------------------------------------------

    @invariant()
    def list_count_matches_model(self) -> None:
        """After every step, list count equals model size."""
        result = _run(self._list_route.call())  # type: ignore[union-attr]
        items = result.items  # type: ignore[union-attr]
        assert len(items) == len(self.model), (
            f"List returned {len(items)} items but model has {len(self.model)}"
        )

    @invariant()
    def every_listed_item_matches_model(self) -> None:
        """Every listed item matches the model by id."""
        result = _run(self._list_route.call())  # type: ignore[union-attr]
        items = result.items  # type: ignore[union-attr]
        listed_ids = {item.id for item in items}  # type: ignore[union-attr]
        model_ids = set(self.model.keys())
        assert listed_ids == model_ids, (
            f"Listed ids {listed_ids} != model ids {model_ids}"
        )

    @invariant()
    def get_by_id_returns_matching_data(self) -> None:
        """For each model entry, GET by id returns matching data."""
        for entity_id, expected in self.model.items():
            result = _run(self._get_route.call({"id": entity_id}))  # type: ignore[union-attr]
            assert result.id == expected["id"], (  # type: ignore[union-attr]
                f"GET id mismatch: {result.id} != {expected['id']}"  # type: ignore[union-attr]
            )
            assert result.name == expected["name"], (  # type: ignore[union-attr]
                f"GET name mismatch: {result.name} != {expected['name']}"  # type: ignore[union-attr]
            )
            assert result.age == expected["age"], (  # type: ignore[union-attr]
                f"GET age mismatch: {result.age} != {expected['age']}"  # type: ignore[union-attr]
            )


# Hypothesis runs the state machine as a test
TestCrudStateMachine = CrudStateMachine.TestCase
TestCrudStateMachine.settings = settings(
    max_examples=30,
    stateful_step_count=15,
    deadline=None,
)
