"""Extended tests for schema query dialect — coverage gaps.

Covers compile_query_schema and compile_openapi for:
- Selectable
- Searchable
- JsonQueryable
- ArrayQueryable
- FullTextIndexed
"""

from __future__ import annotations

from emergent.wire.axis._capability import OpenAPIContext, QuerySchemaContext


# ─── Selectable ──────────────────────────────────────────────────────────────


class TestSelectableCompile:
    def test_selectable_compile_query_schema(self):
        """Selectable.compile_query_schema sets selectable=True."""
        from emergent.wire.axis.schema.dialects.query import Selectable

        cap = Selectable()
        ctx = QuerySchemaContext(field_name="profile", field_type=str)
        result = cap.compile_query_schema(ctx)
        assert result.selectable is True

    def test_selectable_compile_openapi(self):
        """Selectable.compile_openapi adds x-selectable to schema."""
        from emergent.wire.axis.schema.dialects.query import Selectable

        cap = Selectable()
        ctx = OpenAPIContext(field_name="profile", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["x-selectable"] is True


# ─── Searchable ──────────────────────────────────────────────────────────────


class TestSearchableCompile:
    def test_searchable_compile_query_schema(self):
        """Searchable.compile_query_schema sets searchable=True."""
        from emergent.wire.axis.schema.dialects.query import Searchable

        cap = Searchable()
        ctx = QuerySchemaContext(field_name="description", field_type=str)
        result = cap.compile_query_schema(ctx)
        assert result.searchable is True

    def test_searchable_compile_openapi(self):
        """Searchable.compile_openapi adds x-searchable to schema."""
        from emergent.wire.axis.schema.dialects.query import Searchable

        cap = Searchable()
        ctx = OpenAPIContext(field_name="description", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["x-searchable"] is True


# ─── JsonQueryable ───────────────────────────────────────────────────────────


class TestJsonQueryableCompile:
    def test_json_queryable_compile_query_schema(self):
        """JsonQueryable.compile_query_schema sets json_queryable=True."""
        from emergent.wire.axis.schema.dialects.query import JsonQueryable

        cap = JsonQueryable()
        ctx = QuerySchemaContext(field_name="metadata", field_type=dict)
        result = cap.compile_query_schema(ctx)
        assert result.json_queryable is True

    def test_json_queryable_compile_openapi(self):
        """JsonQueryable.compile_openapi adds x-json-queryable to schema."""
        from emergent.wire.axis.schema.dialects.query import JsonQueryable

        cap = JsonQueryable()
        ctx = OpenAPIContext(field_name="metadata", field_type=dict)
        result = cap.compile_openapi(ctx)
        assert result.schema["x-json-queryable"] is True


# ─── ArrayQueryable ──────────────────────────────────────────────────────────


class TestArrayQueryableCompile:
    def test_array_queryable_compile_query_schema(self):
        """ArrayQueryable.compile_query_schema sets array_queryable=True."""
        from emergent.wire.axis.schema.dialects.query import ArrayQueryable

        cap = ArrayQueryable()
        ctx = QuerySchemaContext(field_name="tags", field_type=list)
        result = cap.compile_query_schema(ctx)
        assert result.array_queryable is True

    def test_array_queryable_compile_openapi(self):
        """ArrayQueryable.compile_openapi adds x-array-queryable to schema."""
        from emergent.wire.axis.schema.dialects.query import ArrayQueryable

        cap = ArrayQueryable()
        ctx = OpenAPIContext(field_name="tags", field_type=list)
        result = cap.compile_openapi(ctx)
        assert result.schema["x-array-queryable"] is True


# ─── FullTextIndexed ─────────────────────────────────────────────────────────


class TestFullTextIndexedCompile:
    def test_full_text_indexed_compile_query_schema(self):
        """FullTextIndexed.compile_query_schema sets full_text_indexed and language."""
        from emergent.wire.axis.schema.dialects.query import FullTextIndexed

        cap = FullTextIndexed()
        ctx = QuerySchemaContext(field_name="content", field_type=str)
        result = cap.compile_query_schema(ctx)
        assert result.full_text_indexed is True
        assert result.fti_language == "english"

    def test_full_text_indexed_compile_query_schema_custom_language(self):
        """FullTextIndexed with custom language propagates to context."""
        from emergent.wire.axis.schema.dialects.query import FullTextIndexed

        cap = FullTextIndexed(language="russian")
        ctx = QuerySchemaContext(field_name="content", field_type=str)
        result = cap.compile_query_schema(ctx)
        assert result.full_text_indexed is True
        assert result.fti_language == "russian"

    def test_full_text_indexed_compile_openapi(self):
        """FullTextIndexed.compile_openapi adds x-full-text-indexed and language."""
        from emergent.wire.axis.schema.dialects.query import FullTextIndexed

        cap = FullTextIndexed()
        ctx = OpenAPIContext(field_name="content", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["x-full-text-indexed"] is True
        assert result.schema["x-fti-language"] == "english"

    def test_full_text_indexed_compile_openapi_custom_language(self):
        """FullTextIndexed custom language in OpenAPI schema."""
        from emergent.wire.axis.schema.dialects.query import FullTextIndexed

        cap = FullTextIndexed(language="german")
        ctx = OpenAPIContext(field_name="content", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["x-full-text-indexed"] is True
        assert result.schema["x-fti-language"] == "german"


# ─── Filterable compile_query_schema ─────────────────────────────────────────


class TestFilterableCompileQuerySchema:
    def test_filterable_compile_query_schema(self):
        """Filterable.compile_query_schema sets filterable=True."""
        from emergent.wire.axis.schema.dialects.query import Filterable

        cap = Filterable()
        ctx = QuerySchemaContext(field_name="email", field_type=str)
        result = cap.compile_query_schema(ctx)
        assert result.filterable is True


# ─── Sortable compile_query_schema ───────────────────────────────────────────


class TestSortableCompileQuerySchema:
    def test_sortable_compile_query_schema(self):
        """Sortable.compile_query_schema sets sortable=True."""
        from emergent.wire.axis.schema.dialects.query import Sortable

        cap = Sortable()
        ctx = QuerySchemaContext(field_name="created_at", field_type=str)
        result = cap.compile_query_schema(ctx)
        assert result.sortable is True


# ─── Operators compile_query_schema ──────────────────────────────────────────


class TestOperatorsCompileQuerySchema:
    def test_operators_compile_query_schema(self):
        """Operators.compile_query_schema sets operators tuple."""
        from emergent.wire.axis.schema.dialects.query import Operators

        cap = Operators(int, str)
        ctx = QuerySchemaContext(field_name="status", field_type=str)
        result = cap.compile_query_schema(ctx)
        assert result.operators == (int, str)
