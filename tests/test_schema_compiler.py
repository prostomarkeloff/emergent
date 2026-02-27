"""Tests for SchemaCompiler — composable phase compilation with algebraic operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import pytest

from emergent.wire.compile._core import Axes
from emergent.wire.compile._phase import (
    CompilationPhase,
    EntityCompilation,
    EntityFold,
    SchemaCompiler,
    PYDANTIC_PHASE,
    PYDANTIC_MODEL_FOLD,
    OPENAPI_PHASE,
    OPENAPI_SCHEMA_FOLD,
    ARGPARSE_PHASE,
    CONSTRAINTS_PHASE,
    STORAGE_FIELD_PHASE,
    FASTAPI_PHASES,
    CLI_PHASES,
    # Pre-built compilers
    FASTAPI_SCHEMA,
    CLI_SCHEMA,
    TG_SCHEMA,
    CONSTRAINTS_SCHEMA,
    STORAGE_SCHEMA,
)
from emergent.wire.axis.schema._inspect import inspect_dataclass
from emergent.wire.axis.schema._universal import (
    Identity, Min, Max, MaxLen, Unique,
    schema_meta, SchemaName, SchemaDoc,
)


# ─── Test Entity ──────────────────────────────────────────────────────────────


@dataclass
class User:
    id: Annotated[int, Identity]
    name: Annotated[str, MaxLen(100)]
    email: Annotated[str, Unique, MaxLen(255)]
    score: Annotated[int, Min(0), Max(1000)]


_AXES = Axes(schema=inspect_dataclass)


# ═══════════════════════════════════════════════════════════════════════════════
# Construction + compile
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchemaCompilerCompile:
    def test_empty_compiler(self) -> None:
        compiler = SchemaCompiler(phases=())
        fields = compiler.compile(User, _AXES)
        assert len(fields) == 4  # 4 fields, 0 phases — contexts dict empty
        for fc in fields:
            assert fc.name in ("id", "name", "email", "score")

    def test_single_phase(self) -> None:
        compiler = SchemaCompiler(phases=(CONSTRAINTS_PHASE,))
        fields = compiler.compile(User, _AXES)
        assert len(fields) == 4
        # Can read constraints context
        score_fc = next(fc for fc in fields if fc.name == "score")
        ctx = score_fc[CONSTRAINTS_PHASE]
        assert ctx.min_value == 0
        assert ctx.max_value == 1000

    def test_multi_phase(self) -> None:
        compiler = SchemaCompiler(phases=(PYDANTIC_PHASE, OPENAPI_PHASE))
        fields = compiler.compile(User, _AXES)
        assert len(fields) == 4
        # Can read both contexts
        name_fc = next(fc for fc in fields if fc.name == "name")
        pydantic_ctx = name_fc[PYDANTIC_PHASE]
        openapi_ctx = name_fc[OPENAPI_PHASE]
        assert pydantic_ctx.field_name == "name"
        assert openapi_ctx.field_name == "name"

    def test_returns_entity_compilation(self) -> None:
        ec = FASTAPI_SCHEMA.compile(User, _AXES)
        assert isinstance(ec, EntityCompilation)
        assert len(ec.fields) == 4


# ═══════════════════════════════════════════════════════════════════════════════
# Lego operations
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchemaCompilerLego:
    def test_with_phase(self) -> None:
        compiler = FASTAPI_SCHEMA.with_phase(CONSTRAINTS_PHASE)
        assert len(compiler.phases) == 3  # pydantic + openapi + constraints
        assert CONSTRAINTS_PHASE in compiler

    def test_with_phase_conflict_raises(self) -> None:
        with pytest.raises(ValueError, match="already present"):
            FASTAPI_SCHEMA.with_phase(PYDANTIC_PHASE)

    def test_with_phases(self) -> None:
        compiler = SchemaCompiler(phases=()).with_phases(
            PYDANTIC_PHASE, OPENAPI_PHASE, CONSTRAINTS_PHASE,
        )
        assert len(compiler.phases) == 3

    def test_without_phase(self) -> None:
        compiler = FASTAPI_SCHEMA.without_phase(OPENAPI_PHASE)
        assert len(compiler.phases) == 1
        assert compiler.phases == (PYDANTIC_PHASE,)

    def test_without_phase_by_type(self) -> None:
        from emergent.wire.axis._capability import OpenAPIContext
        compiler = FASTAPI_SCHEMA.without_phase(OpenAPIContext)
        assert len(compiler.phases) == 1
        assert compiler.phases == (PYDANTIC_PHASE,)

    def test_replace_phase(self) -> None:
        custom_pydantic = PYDANTIC_PHASE.with_handlers({})
        compiler = FASTAPI_SCHEMA.replace_phase(PYDANTIC_PHASE, custom_pydantic)
        assert compiler.phases[0] is custom_pydantic
        assert compiler.phases[1] is OPENAPI_PHASE

    def test_replace_phase_not_found_raises(self) -> None:
        with pytest.raises(KeyError):
            FASTAPI_SCHEMA.replace_phase(ARGPARSE_PHASE, ARGPARSE_PHASE)

    def test_immutability(self) -> None:
        original = FASTAPI_SCHEMA
        modified = original.with_phase(CONSTRAINTS_PHASE)
        # Original unchanged
        assert len(original.phases) == 2
        assert len(modified.phases) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# Algebraic operations
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchemaCompilerAlgebra:
    def test_add_monoidal_product(self) -> None:
        combined = FASTAPI_SCHEMA + CLI_SCHEMA
        assert len(combined.phases) == 3  # pydantic + openapi + argparse

    def test_add_identity(self) -> None:
        empty = SchemaCompiler(phases=())
        result = FASTAPI_SCHEMA + empty
        assert result.phases == FASTAPI_SCHEMA.phases

    def test_add_identity_left(self) -> None:
        empty = SchemaCompiler(phases=())
        result = empty + FASTAPI_SCHEMA
        assert result.phases == FASTAPI_SCHEMA.phases

    def test_add_associative(self) -> None:
        a = FASTAPI_SCHEMA
        b = CLI_SCHEMA
        c = CONSTRAINTS_SCHEMA
        left = (a + b) + c
        right = a + (b + c)
        # Same phases (by identity)
        assert len(left.phases) == len(right.phases)
        for lp, rp in zip(left.phases, right.phases):
            assert lp is rp

    def test_sub_restriction(self) -> None:
        combined = FASTAPI_SCHEMA + CLI_SCHEMA
        restricted = combined - CLI_SCHEMA
        assert restricted.phases == FASTAPI_SCHEMA.phases

    def test_sub_empty(self) -> None:
        empty = SchemaCompiler(phases=())
        result = FASTAPI_SCHEMA - empty
        assert result.phases == FASTAPI_SCHEMA.phases

    def test_contains(self) -> None:
        assert PYDANTIC_PHASE in FASTAPI_SCHEMA
        assert OPENAPI_PHASE in FASTAPI_SCHEMA
        assert ARGPARSE_PHASE not in FASTAPI_SCHEMA

    def test_fullstack_composition(self) -> None:
        """Real-world composition: FastAPI + SA + constraints."""
        from emergent.wire.compile.targets.sqlalchemy import SA_SCHEMA

        fullstack = FASTAPI_SCHEMA + SA_SCHEMA + CONSTRAINTS_SCHEMA
        # Should have: pydantic, openapi, sa, storage_field, constraints
        assert len(fullstack.phases) == 5
        assert PYDANTIC_PHASE in fullstack
        assert OPENAPI_PHASE in fullstack
        assert STORAGE_FIELD_PHASE in fullstack
        assert CONSTRAINTS_PHASE in fullstack


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-built compilers
# ═══════════════════════════════════════════════════════════════════════════════


class TestPrebuiltCompilers:
    def test_fastapi_schema(self) -> None:
        assert FASTAPI_SCHEMA.phases == FASTAPI_PHASES

    def test_cli_schema(self) -> None:
        assert CLI_SCHEMA.phases == CLI_PHASES

    def test_constraints_schema(self) -> None:
        assert CONSTRAINTS_SCHEMA.phases == (CONSTRAINTS_PHASE,)

    def test_storage_schema(self) -> None:
        assert STORAGE_SCHEMA.phases == (STORAGE_FIELD_PHASE,)

    def test_sa_schema(self) -> None:
        from emergent.wire.compile.targets.sqlalchemy import SA_SCHEMA, SA_PHASES

        assert SA_SCHEMA.phases == SA_PHASES


# ═══════════════════════════════════════════════════════════════════════════════
# Assemblers (compose + assemble pattern)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAssemblersWithSchemaCompiler:
    def test_assemble_pydantic(self) -> None:
        from emergent.wire.compile._generate import assemble_pydantic

        fields = FASTAPI_SCHEMA.compile(User, _AXES)
        Model = assemble_pydantic(User, fields)
        assert Model.__name__ == "User"
        # Should have all non-compose fields
        assert "id" in Model.model_fields
        assert "name" in Model.model_fields
        assert "email" in Model.model_fields
        assert "score" in Model.model_fields

    def test_assemble_argparse(self) -> None:
        from emergent.wire.compile._generate import assemble_argparse

        fields = CLI_SCHEMA.compile(User, _AXES)
        specs = assemble_argparse(User, fields)
        assert len(specs) == 4
        names = {s.dest for s in specs}
        assert names == {"id", "name", "email", "score"}

    def test_assemble_openapi(self) -> None:
        from emergent.wire.compile._schema import assemble_openapi

        fields = FASTAPI_SCHEMA.compile(User, _AXES)
        schema = assemble_openapi(User, fields)
        assert schema["type"] == "object"
        assert "id" in schema["properties"]
        assert "score" in schema["properties"]

    def test_assemble_sa(self) -> None:
        from sqlalchemy.orm import DeclarativeBase

        from emergent.wire.compile.targets.sqlalchemy import SA_SCHEMA, assemble_sa

        class TestBase(DeclarativeBase):
            pass

        fields = SA_SCHEMA.compile(User, _AXES)
        compiled = assemble_sa(User, fields, "test_users", base=TestBase)
        assert compiled.entity is User
        assert compiled.identity_field == "id"

    def test_compile_once_assemble_many(self) -> None:
        """Core pattern: one compilation, multiple assemblies."""
        from emergent.wire.compile._generate import assemble_pydantic
        from emergent.wire.compile._schema import assemble_openapi

        compiler = FASTAPI_SCHEMA + CONSTRAINTS_SCHEMA
        fields = compiler.compile(User, _AXES)

        # Assemble pydantic
        Model = assemble_pydantic(User, fields)
        assert "score" in Model.model_fields

        # Assemble openapi from same compilation
        schema = assemble_openapi(User, fields)
        assert "score" in schema["properties"]

        # Constraints also available
        score_fc = next(fc for fc in fields if fc.name == "score")
        ctx = score_fc[CONSTRAINTS_PHASE]
        assert ctx.min_value == 0
        assert ctx.max_value == 1000


# ═══════════════════════════════════════════════════════════════════════════════
# Entity-level compilation
# ═══════════════════════════════════════════════════════════════════════════════


@schema_meta(SchemaName("users"), SchemaDoc("User accounts"))
@dataclass
class AnnotatedUser:
    id: Annotated[int, Identity]
    name: Annotated[str, MaxLen(100)]
    email: Annotated[str, Unique, MaxLen(255)]
    score: Annotated[int, Min(0), Max(1000)]


class TestEntityLevelCompilation:
    def test_entity_compilation_has_entity_contexts(self) -> None:
        ec = FASTAPI_SCHEMA.compile(AnnotatedUser, _AXES)
        assert isinstance(ec, EntityCompilation)
        assert ec.has_entity(PYDANTIC_MODEL_FOLD)
        assert ec.has_entity(OPENAPI_SCHEMA_FOLD)

    def test_pydantic_model_context_from_schema_name(self) -> None:
        ec = FASTAPI_SCHEMA.compile(AnnotatedUser, _AXES)
        ctx = ec[PYDANTIC_MODEL_FOLD]
        assert ctx.title == "users"
        assert ctx.description == "User accounts"

    def test_openapi_schema_context_from_schema_name(self) -> None:
        ec = FASTAPI_SCHEMA.compile(AnnotatedUser, _AXES)
        ctx = ec[OPENAPI_SCHEMA_FOLD]
        assert ctx.schema.get("title") == "users"

    def test_entity_compilation_get_returns_none(self) -> None:
        """get() returns None for phases without entity fold."""
        ec = CONSTRAINTS_SCHEMA.compile(AnnotatedUser, _AXES)
        assert ec.get(PYDANTIC_MODEL_FOLD) is None

    def test_entity_compilation_getitem_raises(self) -> None:
        """__getitem__ raises KeyError for missing entity context."""
        ec = CONSTRAINTS_SCHEMA.compile(AnnotatedUser, _AXES)
        with pytest.raises(KeyError):
            ec[PYDANTIC_MODEL_FOLD]

    def test_no_schema_meta_returns_defaults(self) -> None:
        """Without @schema_meta, entity contexts have defaults."""
        ec = FASTAPI_SCHEMA.compile(User, _AXES)
        ctx = ec[PYDANTIC_MODEL_FOLD]
        assert ctx.class_name == "User"
        assert ctx.title is None
        assert ctx.description is None

    def test_entity_and_field_both_available(self) -> None:
        """Entity-level and field-level contexts coexist."""
        ec = FASTAPI_SCHEMA.compile(AnnotatedUser, _AXES)
        # Entity-level
        model_ctx = ec[PYDANTIC_MODEL_FOLD]
        assert model_ctx.title == "users"
        # Field-level
        name_fc = next(fc for fc in ec if fc.name == "name")
        pydantic_ctx = name_fc[PYDANTIC_PHASE]
        assert pydantic_ctx.field_name == "name"

    def test_iteration_backward_compat(self) -> None:
        """Iterating EntityCompilation yields FieldCompilation."""
        ec = FASTAPI_SCHEMA.compile(User, _AXES)
        names = [fc.name for fc in ec]
        assert set(names) == {"id", "name", "email", "score"}
        assert len(ec) == 4

    def test_sa_table_fold(self) -> None:
        """SA entity fold compiles SQLAlchemyTableContext."""
        from emergent.wire.compile.targets.sqlalchemy import SA_SCHEMA, SA_TABLE_FOLD

        ec = SA_SCHEMA.compile(AnnotatedUser, _AXES)
        ctx = ec[SA_TABLE_FOLD]
        assert ctx.table_name == "users"
