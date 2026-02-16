"""Tests for emergent.wire.axis.schema._helpers — navigation, composition, queries."""

from dataclasses import dataclass
from typing import Annotated

import pytest

from emergent.wire.axis.schema._universal import (
    Identity,
    Unique,
    Ref,
    MaxLen,
    MinLen,
    Doc,
    Nested,
    Embedded,
    SchemaName,
    SchemaCapability,
    schema_meta,
)
from emergent.wire.axis.schema._inspect import FieldInfo, inspect_type
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


# ═══════════════════════════════════════════════════════════════════════════════
# Test Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class Address:
    city: str
    zip_code: str


@dataclass
class Team:
    id: Annotated[int, Identity]
    name: Annotated[str, Unique, MaxLen(100)]


@dataclass
class User:
    id: Annotated[int, Identity]
    email: Annotated[str, Unique, MaxLen(255), Doc("User email")]
    name: Annotated[str, MaxLen(100)]
    team_id: Annotated[int | None, Ref(target=Team)] = None
    bio: str | None = None


@dataclass
class Order:
    id: Annotated[int, Identity]
    user: User
    items: Annotated[list[Address], Nested()]


# ═══════════════════════════════════════════════════════════════════════════════
# Navigation
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetIdentityField:
    def test_found(self):
        fi = get_identity_field(User)
        assert fi is not None
        assert fi.name == "id"

    def test_not_found(self):
        fi = get_identity_field(Address)
        assert fi is None


class TestGetRequiredFields:
    def test_required(self):
        required = get_required_fields(User)
        names = [f.name for f in required]
        assert "id" in names
        assert "email" in names
        assert "name" in names
        assert "bio" not in names

    def test_all_required(self):
        required = get_required_fields(Address)
        assert len(required) == 2


class TestGetOptionalFields:
    def test_optional(self):
        optional = get_optional_fields(User)
        names = [f.name for f in optional]
        assert "team_id" in names
        assert "bio" in names

    def test_none_optional(self):
        optional = get_optional_fields(Team)
        assert len(optional) == 0


class TestPartitionFields:
    def test_partition(self):
        required, optional = partition_fields(User)
        req_names = [f.name for f in required]
        opt_names = [f.name for f in optional]
        assert "id" in req_names
        assert "email" in req_names
        assert "team_id" in opt_names
        assert "bio" in opt_names


class TestFieldByName:
    def test_found(self):
        fi = field_by_name(User, "email")
        assert fi is not None
        assert fi.name == "email"

    def test_not_found(self):
        fi = field_by_name(User, "nonexistent")
        assert fi is None


class TestFieldPathType:
    def test_direct_field(self):
        tp = field_path_type(User, "email")
        assert tp is str

    def test_nested_path(self):
        tp = field_path_type(Order, "user")
        # user field's base_type is User
        assert tp is User

    def test_invalid_path(self):
        tp = field_path_type(User, "nonexistent.field")
        assert tp is None


class TestFieldsWithCapability:
    def test_unique_fields(self):
        result = fields_with_capability(User, Unique)
        names = [name for name, _, _ in result]
        assert "email" in names
        assert "id" not in names

    def test_identity_fields(self):
        result = fields_with_capability(User, Identity)
        assert len(result) == 1
        assert result[0][0] == "id"

    def test_no_matches(self):
        result = fields_with_capability(Address, Identity)
        assert len(result) == 0


class TestGetRefs:
    def test_refs(self):
        result = get_refs(User)
        assert len(result) == 1
        name, info, ref = result[0]
        assert name == "team_id"

    def test_no_refs(self):
        result = get_refs(Address)
        assert len(result) == 0


class TestFieldsByDialect:
    def test_with_sql_dialect(self):
        from emergent.wire.axis.schema.dialects.sql import SQLCapability, Index

        @dataclass
        class Indexed:
            email: Annotated[str, Index("idx_email")]
            name: str

        result = fields_by_dialect(Indexed, SQLCapability)
        assert len(result) == 1
        assert result[0][0] == "email"


# ═══════════════════════════════════════════════════════════════════════════════
# Composition
# ═══════════════════════════════════════════════════════════════════════════════


class TestMergeCapabilities:
    def test_no_overlap(self):
        a = (MaxLen(100),)
        b = (Doc("hi"),)
        merged = merge_capabilities(a, b)
        assert len(merged) == 2

    def test_later_overrides(self):
        a = (MaxLen(100), Doc("old"))
        b = (MaxLen(50),)
        merged = merge_capabilities(a, b)
        assert len(merged) == 2
        ml = next(c for c in merged if isinstance(c, MaxLen))
        assert ml.value == 50

    def test_single_tuple(self):
        caps = (MaxLen(100), Doc("hi"))
        merged = merge_capabilities(caps)
        assert len(merged) == 2

    def test_empty(self):
        merged = merge_capabilities()
        assert merged == ()


class TestOverrideCapability:
    def test_replace_existing(self):
        caps = (MaxLen(100), Doc("hi"))
        result = override_capability(caps, MaxLen(50))
        assert len(result) == 2
        ml = next(c for c in result if isinstance(c, MaxLen))
        assert ml.value == 50

    def test_add_new(self):
        caps = (Doc("hi"),)
        result = override_capability(caps, MaxLen(50))
        assert len(result) == 2


class TestRemoveCapability:
    def test_remove(self):
        caps = (MaxLen(100), Doc("hi"), Identity())
        result = remove_capability(caps, MaxLen)
        assert len(result) == 2
        assert not any(isinstance(c, MaxLen) for c in result)

    def test_remove_nonexistent(self):
        caps = (Doc("hi"),)
        result = remove_capability(caps, MaxLen)
        assert len(result) == 1


class TestDeduplicateCapabilities:
    def test_dedup(self):
        caps = (MaxLen(100), Doc("hi"), MaxLen(50))
        result = deduplicate_capabilities(caps)
        assert len(result) == 2
        ml = next(c for c in result if isinstance(c, MaxLen))
        assert ml.value == 50  # last wins

    def test_delegates_to_merge(self):
        """deduplicate_capabilities delegates to merge_capabilities."""
        caps = (MaxLen(100), MaxLen(50))
        assert deduplicate_capabilities(caps) == merge_capabilities(caps)


class TestFilterByDialect:
    def test_filter(self):
        from emergent.wire.axis.schema.dialects.sql import SQLCapability, Index

        caps = (Identity(), Index("idx"), MaxLen(100))
        result = filter_by_dialect(caps, SQLCapability)
        assert len(result) == 1
        assert isinstance(result[0], Index)


class TestFilterUniversal:
    def test_filter(self):
        from emergent.wire.axis.schema.dialects.sql import Index

        caps = (Identity(), Index("idx"), MaxLen(100))
        result = filter_universal(caps)
        assert len(result) == 2  # Identity and MaxLen


# ═══════════════════════════════════════════════════════════════════════════════
# Queries
# ═══════════════════════════════════════════════════════════════════════════════


class TestFindCapability:
    def test_found(self):
        caps = (MaxLen(100), Doc("hi"))
        result = find_capability(caps, MaxLen)
        assert result is not None
        assert result.value == 100

    def test_not_found(self):
        caps = (MaxLen(100),)
        result = find_capability(caps, Doc)
        assert result is None


class TestFindAllCapabilities:
    def test_multiple(self):
        from emergent.wire.axis.schema._universal import UniversalCapability

        caps = (Identity(), MaxLen(100), Doc("hi"))
        result = find_all_capabilities(caps, UniversalCapability)
        assert len(result) == 3

    def test_empty(self):
        caps = (Identity(),)
        result = find_all_capabilities(caps, Doc)
        assert len(result) == 0


class TestHasCapability:
    def test_has(self):
        caps = (Identity(), MaxLen(100))
        assert has_capability(caps, Identity) is True

    def test_not_has(self):
        caps = (MaxLen(100),)
        assert has_capability(caps, Identity) is False


# ═══════════════════════════════════════════════════════════════════════════════
# Schema Meta Composition
# ═══════════════════════════════════════════════════════════════════════════════


class TestComposeSchemaMetaCaps:
    def test_no_overrides(self):
        @schema_meta(SchemaName("users"))
        @dataclass
        class User:
            id: int

        caps = compose_schema_meta(User)
        assert len(caps) == 1

    def test_with_overrides(self):
        @schema_meta(SchemaName("users"))
        @dataclass
        class User:
            id: int

        caps = compose_schema_meta(User, (SchemaName("admins"),))
        assert len(caps) == 1
        name = next(c for c in caps if isinstance(c, SchemaName))
        assert name.value == "admins"

    def test_no_schema_meta(self):
        @dataclass
        class Plain:
            id: int

        caps = compose_schema_meta(Plain)
        assert caps == ()


class TestGetNestedSchemaMetaCaps:
    def test_nested_with_meta_override(self):
        @schema_meta(SchemaName("addresses"))
        @dataclass
        class Address:
            city: str

        fi = FieldInfo(
            name="addr", base_type=Address, is_optional=False,
            capabilities=(Nested(meta=(SchemaName("billing"),)),),
        )
        caps = get_nested_schema_meta(fi)
        name = next(c for c in caps if isinstance(c, SchemaName))
        assert name.value == "billing"  # override wins

    def test_nested_without_override(self):
        @schema_meta(SchemaName("addresses"))
        @dataclass
        class Address:
            city: str

        fi = FieldInfo(
            name="addr", base_type=Address, is_optional=False,
            capabilities=(Nested(),),
        )
        caps = get_nested_schema_meta(fi)
        name = next(c for c in caps if isinstance(c, SchemaName))
        assert name.value == "addresses"

    def test_non_nested_returns_empty(self):
        fi = FieldInfo(name="x", base_type=int, is_optional=False, capabilities=())
        caps = get_nested_schema_meta(fi)
        assert caps == ()

    def test_embedded_with_meta(self):
        @dataclass
        class Address:
            city: str

        fi = FieldInfo(
            name="addr", base_type=Address, is_optional=False,
            capabilities=(Embedded(meta=(SchemaName("inline_addr"),)),),
        )
        caps = get_nested_schema_meta(fi)
        name = next(c for c in caps if isinstance(c, SchemaName))
        assert name.value == "inline_addr"


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: Full helper pipeline on complex entity graph
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegrationHelpersPipeline:
    """Use navigation + composition + query helpers together on a
    multi-entity domain model."""

    def test_full_navigation_composition_query_pipeline(self):
        """Navigate → compose → query on complex entity."""
        from emergent.wire.axis.schema._universal import (
            MinLen, Doc, Deprecated, ReadOnly, Sensitive,
        )
        from emergent.wire.axis.schema.dialects.sql import Index, SQLCapability

        @schema_meta(SchemaName("accounts"))
        @dataclass
        class Account:
            id: Annotated[int, Identity]
            email: Annotated[str, Unique, MaxLen(255), Doc("Email"), Index("idx_email")]
            name: Annotated[str, MinLen(1), MaxLen(100)]
            password: Annotated[str, Sensitive(), MaxLen(128)]
            legacy_field: Annotated[str, Deprecated(reason="Use name"), MaxLen(50)] = ""
            bio: str | None = None

        # Navigation
        id_field = get_identity_field(Account)
        assert id_field is not None
        assert id_field.name == "id"

        required, optional = partition_fields(Account)
        req_names = {f.name for f in required}
        opt_names = {f.name for f in optional}
        assert req_names == {"id", "email", "name", "password", "legacy_field"}
        assert opt_names == {"bio"}

        # fields_with_capability
        unique_fields = fields_with_capability(Account, Unique)
        assert len(unique_fields) == 1
        assert unique_fields[0][0] == "email"

        # fields_by_dialect
        sql_fields = fields_by_dialect(Account, SQLCapability)
        assert len(sql_fields) == 1
        assert sql_fields[0][0] == "email"

        # Queries on field capabilities
        email_info = field_by_name(Account, "email")
        assert email_info is not None
        caps = email_info.capabilities

        found_maxlen = find_capability(caps, MaxLen)
        assert found_maxlen is not None
        assert found_maxlen.value == 255

        from emergent.wire.axis.schema._universal import UniversalCapability
        all_universal = find_all_capabilities(caps, UniversalCapability)
        assert len(all_universal) >= 2  # Unique + MaxLen + Doc at minimum

        assert has_capability(caps, Unique) is True
        assert has_capability(caps, Deprecated) is False

        # Composition: merge email caps with password caps
        pwd_info = field_by_name(Account, "password")
        assert pwd_info is not None
        merged = merge_capabilities(caps, pwd_info.capabilities)
        # MaxLen from password (128) overrides MaxLen from email (255)
        ml = find_capability(merged, MaxLen)
        assert ml is not None
        assert ml.value == 128

        # Override
        overridden = override_capability(caps, MaxLen(500))
        ml2 = find_capability(overridden, MaxLen)
        assert ml2 is not None
        assert ml2.value == 500

        # Filter
        universal_only = filter_universal(caps)
        dialect_only = filter_by_dialect(caps, SQLCapability)
        assert len(dialect_only) == 1  # Index
        assert all(not isinstance(c, SQLCapability) for c in universal_only)

    def test_nested_schema_meta_composition(self):
        """compose_schema_meta and get_nested_schema_meta on related entities."""

        @schema_meta(SchemaName("addresses"))
        @dataclass
        class Addr:
            city: str
            zip_code: str

        @schema_meta(SchemaName("users"))
        @dataclass
        class Usr:
            id: Annotated[int, Identity]
            home: Annotated[Addr, Nested(meta=(SchemaName("home_addr"),))]
            work: Annotated[Addr, Nested()]

        fields = inspect_type(Usr)

        # home has Nested with meta override
        home_meta = get_nested_schema_meta(fields["home"])
        home_name = next(c for c in home_meta if isinstance(c, SchemaName))
        assert home_name.value == "home_addr"

        # work has Nested without override → inherits from Addr
        work_meta = get_nested_schema_meta(fields["work"])
        work_name = next(c for c in work_meta if isinstance(c, SchemaName))
        assert work_name.value == "addresses"

        # compose_schema_meta with override
        composed = compose_schema_meta(Usr, (SchemaName("admins"),))
        name = next(c for c in composed if isinstance(c, SchemaName))
        assert name.value == "admins"
