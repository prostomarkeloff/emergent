# pyright: reportPrivateUsage=false
"""Property-based tests covering ALL remaining uncovered derive modules.

Covers:
- auth/caps.py: Authenticated, RoleRequired, AuthorizeOps, OwnerScoped, OwnerContext
- auth/errors.py: AuthenticationRequired, AuthorizationFailed
- auth/extractors.py: AuthToken, BearerExtract, CLITokenExtract
- auth/validate.py: TokenValidate
- auth/openapi.py: AuthOpenAPI
- auth/login.py: IssueToken, LoginOp, token_converter
- patterns/methods.py: method, post, get, put, delete, patch, command, Methods, MethodDialect
- patterns/nested.py: NestedCRUD, nested_http_crud
- patterns/lookup.py: EXISTS, COUNT
- _materialize.py: materialize -> Endpoint
- _compile.py: compile_derive with http_crud/cli_crud
- _builders.py: ExposureBuilder, exposure, EndpointBuilder
- _codegen.py: create_dataclass, create_request_type, create_response_type, DirectMapper
- _trigger.py: HTTPTriggers, CLITriggers, NestedHTTPTriggers, FilteredTriggerGen, PrefixedTriggerGen
- _query_helpers.py: identity_values, serialize_op_fields, id_path
- _explain.py: explain_derive, derive_dict, explain_entity
- _error_caps.py: ErrorTransform, ProblemResponse, ERROR_CAPS
- _scoped.py: Scoped, scoped
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass
from typing import Annotated, Any

import pytest
from kungfu import Error, Ok, Result

from emergent.wire.axis.schema._universal import Identity, Ref, schema_meta
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.derive._compile import compile_derive
from emergent.wire.derive._materialize import materialize
from emergent.wire.derive._crud import (
    LIST,
    GET,
    CREATE,
    http_crud,
    cli_crud,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Test-local entity types
# ═══════════════════════════════════════════════════════════════════════════════


class Users:
    """Provider node stub."""


class Posts:
    """Provider node stub for posts."""


@dataclass
class User:
    id: Annotated[int, Identity()]
    name: str
    email: str


@dataclass
class Article:
    id: Annotated[int, Identity()]
    title: str
    body: str
    author_id: int


@dataclass
class Post:
    id: Annotated[int, Identity()]
    user_id: Annotated[int, Ref(User)]
    title: str
    content: str


@dataclass
class AuthUser:
    name: str
    roles: set[str]


def _get_roles(u: AuthUser) -> set[str]:
    """Typed role getter for AuthUser."""
    return u.roles


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Auth error types
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthErrors:
    """auth/errors.py — AuthenticationRequired, AuthorizationFailed."""

    def test_authentication_required_default_detail(self) -> None:
        err = _auth_required()
        assert err.detail == "authentication required"

    def test_authentication_required_custom_detail(self) -> None:
        err = _auth_required("no token")
        assert err.detail == "no token"

    def test_authentication_required_is_exception(self) -> None:
        assert isinstance(_auth_required(), Exception)

    def test_authorization_failed_default_detail(self) -> None:
        err = _auth_failed()
        assert err.detail == "forbidden"

    def test_authorization_failed_custom_detail(self) -> None:
        err = _auth_failed("admin only")
        assert err.detail == "admin only"

    def test_authorization_failed_is_exception(self) -> None:
        assert isinstance(_auth_failed(), Exception)

    def test_auth_errors_str(self) -> None:
        assert str(_auth_required()) == "authentication required"
        assert str(_auth_failed("nope")) == "nope"


def _auth_required(detail: str = "authentication required"):
    from emergent.wire.derive.auth.errors import AuthenticationRequired
    return AuthenticationRequired(detail)


def _auth_failed(detail: str = "forbidden"):
    from emergent.wire.derive.auth.errors import AuthorizationFailed
    return AuthorizationFailed(detail)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Auth extractors — frozen dataclasses
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthExtractors:
    """auth/extractors.py — AuthToken, BearerExtract, CLITokenExtract."""

    def test_auth_token_frozen(self) -> None:
        from emergent.wire.derive.auth.extractors import AuthToken
        token = AuthToken(value="abc123")
        assert token.value == "abc123"
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            token.value = "x"  # type: ignore[misc]

    def test_bearer_extract_frozen(self) -> None:
        from emergent.wire.derive.auth.extractors import BearerExtract
        ext = BearerExtract()
        assert ext.cli_attr == "token"
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            ext.cli_attr = "x"  # type: ignore[misc]

    def test_bearer_extract_custom_attr(self) -> None:
        from emergent.wire.derive.auth.extractors import BearerExtract
        ext = BearerExtract(cli_attr="api_key")
        assert ext.cli_attr == "api_key"

    def test_cli_token_extract_frozen(self) -> None:
        from emergent.wire.derive.auth.extractors import CLITokenExtract
        ext = CLITokenExtract()
        assert ext.attr_name == "token"
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            ext.attr_name = "x"  # type: ignore[misc]

    def test_cli_token_extract_custom_attr(self) -> None:
        from emergent.wire.derive.auth.extractors import CLITokenExtract
        ext = CLITokenExtract(attr_name="secret")
        assert ext.attr_name == "secret"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Auth validate — TokenValidate frozen
# ═══════════════════════════════════════════════════════════════════════════════


class TestTokenValidate:
    """auth/validate.py — TokenValidate construction."""

    def test_token_validate_frozen(self) -> None:
        from emergent.wire.derive.auth.validate import TokenValidate

        async def lookup(token: str) -> AuthUser | None:
            return None

        tv = TokenValidate(identity_type=AuthUser, lookup=lookup)
        assert tv.identity_type is AuthUser
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            tv.identity_type = str  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Auth capabilities — Authenticated, RoleRequired, AuthorizeOps, OwnerScoped
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthCaps:
    """auth/caps.py — SchemaCapability types for auth."""

    def test_authenticated_requires_token_validate(self) -> None:
        from emergent.wire.derive.auth.caps import Authenticated
        from emergent.wire.derive.auth.extractors import BearerExtract

        with pytest.raises(ValueError, match="TokenValidate"):
            Authenticated(BearerExtract())

    def test_authenticated_construction(self) -> None:
        from emergent.wire.derive.auth.caps import Authenticated
        from emergent.wire.derive.auth.extractors import BearerExtract
        from emergent.wire.derive.auth.validate import TokenValidate

        async def lookup(token: str) -> AuthUser | None:
            return None

        validate = TokenValidate(identity_type=AuthUser, lookup=lookup)
        auth = Authenticated(BearerExtract(), validate=validate)
        assert auth.validate is validate
        assert len(auth.extractors) == 1

    def test_authenticated_auto_detect_validate(self) -> None:
        from emergent.wire.derive.auth.caps import Authenticated
        from emergent.wire.derive.auth.extractors import BearerExtract
        from emergent.wire.derive.auth.validate import TokenValidate

        async def lookup(token: str) -> AuthUser | None:
            return None

        validate = TokenValidate(identity_type=AuthUser, lookup=lookup)
        # Passing validate as positional arg (detected by isinstance)
        auth = Authenticated(BearerExtract(), validate)
        assert auth.validate is validate
        assert len(auth.extractors) == 1

    def test_authenticated_frozen(self) -> None:
        from emergent.wire.derive.auth.caps import Authenticated
        from emergent.wire.derive.auth.extractors import BearerExtract
        from emergent.wire.derive.auth.validate import TokenValidate

        async def lookup(token: str) -> AuthUser | None:
            return None

        validate = TokenValidate(identity_type=AuthUser, lookup=lookup)
        auth = Authenticated(BearerExtract(), validate=validate)
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            auth.effect = str  # type: ignore[misc]

    def test_role_required_construction(self) -> None:
        from emergent.wire.derive.auth.caps import RoleRequired

        rr = RoleRequired(
            identity_type=AuthUser,
            role="admin",
            role_getter=_get_roles,
        )
        assert rr.role == "admin"
        assert rr.identity_type is AuthUser
        assert rr.effect is None

    def test_role_required_with_effect(self) -> None:
        from emergent.wire.derive.auth.caps import RoleRequired
        from emergent.wire.derive._effects import Mutation

        rr = RoleRequired(
            identity_type=AuthUser,
            role="admin",
            role_getter=_get_roles,
            effect=Mutation,
        )
        assert rr.effect is Mutation

    def test_authorize_ops_construction(self) -> None:
        from emergent.wire.derive.auth.caps import AuthorizeOps

        ao = AuthorizeOps(
            identity_type=AuthUser,
            role_map={"Delete": "admin", "Create": "editor"},
            role_getter=_get_roles,
        )
        assert ao.role_map == {"Delete": "admin", "Create": "editor"}
        assert ao.strict is True

    def test_authorize_ops_non_strict(self) -> None:
        from emergent.wire.derive.auth.caps import AuthorizeOps

        ao = AuthorizeOps(
            identity_type=AuthUser,
            role_map={"Delete": "admin"},
            role_getter=_get_roles,
            strict=False,
        )
        assert ao.strict is False

    def test_owner_context_frozen(self) -> None:
        from emergent.wire.derive.auth.caps import OwnerContext

        oc = OwnerContext(value="user-1")
        assert oc.value == "user-1"
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            oc.value = "x"  # type: ignore[misc]

    def test_owner_context_int_value(self) -> None:
        from emergent.wire.derive.auth.caps import OwnerContext

        oc = OwnerContext(value=42)
        assert oc.value == 42

    def test_owner_scoped_defaults(self) -> None:
        from emergent.wire.derive.auth.caps import OwnerScoped

        os = OwnerScoped(identity_type=AuthUser)
        assert os.owner_field == "owner_id"
        assert os.identity_attr == "id"

    def test_owner_scoped_custom(self) -> None:
        from emergent.wire.derive.auth.caps import OwnerScoped

        os = OwnerScoped(
            identity_type=AuthUser,
            owner_field="author_id",
            identity_attr="name",
        )
        assert os.owner_field == "author_id"
        assert os.identity_attr == "name"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Auth OpenAPI
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthOpenAPI:
    """auth/openapi.py — AuthOpenAPI frozen construction."""

    def test_auth_openapi_default_scheme(self) -> None:
        from emergent.wire.derive.auth.openapi import AuthOpenAPI

        ao = AuthOpenAPI()
        assert ao.scheme_name == "bearerAuth"

    def test_auth_openapi_custom_scheme(self) -> None:
        from emergent.wire.derive.auth.openapi import AuthOpenAPI

        ao = AuthOpenAPI(scheme_name="apiKey")
        assert ao.scheme_name == "apiKey"

    def test_auth_openapi_frozen(self) -> None:
        from emergent.wire.derive.auth.openapi import AuthOpenAPI

        ao = AuthOpenAPI()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            ao.scheme_name = "x"  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Login — token_converter
# ═══════════════════════════════════════════════════════════════════════════════


class TestTokenConverter:
    """auth/login.py — token_converter result mapping."""

    def test_token_converter_ok(self) -> None:
        from emergent.wire.derive.auth.login import token_converter

        @dataclass
        class LoginResp:
            token: str | None
            error: str | None

        result = token_converter(LoginResp, Ok("my-token"))
        assert result.token == "my-token"  # type: ignore[union-attr]
        assert result.error is None  # type: ignore[union-attr]

    def test_token_converter_error(self) -> None:
        from emergent.wire.derive.auth.login import token_converter

        @dataclass
        class LoginResp:
            token: str | None
            error: str | None

        result = token_converter(LoginResp, Error("bad credentials"))
        assert result.token is None  # type: ignore[union-attr]
        assert result.error == "bad credentials"  # type: ignore[union-attr]

    def test_token_converter_invalid_type(self) -> None:
        from emergent.wire.derive.auth.login import token_converter

        with pytest.raises(TypeError, match="Expected Result"):
            token_converter(dict, "not a result")  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════════════
# 7. compile_derive with http_crud
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompileDeriveHTTP:
    """_compile.py — compile_derive with http_crud produces contexts."""

    def test_compile_derive_produces_single_ctx(self) -> None:
        @schema_meta(http_crud("/api/users", Users))
        @dataclass
        class UserA:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(UserA)
        assert len(ctxs) == 1

    def test_compile_derive_has_specs(self) -> None:
        @schema_meta(http_crud("/api/users", Users))
        @dataclass
        class UserB:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(UserB)
        assert len(ctxs[0].specs) > 0

    def test_compile_derive_default_crud_ops_count(self) -> None:
        @schema_meta(http_crud("/api/users", Users))
        @dataclass
        class UserC:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(UserC)
        # Default ALL_CRUD_OPS = (LIST, GET, CREATE, UPDATE, PATCH, DELETE) = 6
        assert len(ctxs[0].specs) == 6

    def test_compile_derive_custom_ops_count(self) -> None:
        @schema_meta(http_crud("/api/users", Users, ops=(LIST, GET, CREATE)))
        @dataclass
        class UserD:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(UserD)
        assert len(ctxs[0].specs) == 3

    def test_compile_derive_spec_names(self) -> None:
        @schema_meta(http_crud("/api/users", Users, ops=(LIST, GET)))
        @dataclass
        class UserE:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(UserE)
        names = {s.name for s in ctxs[0].specs}
        assert names == {"List", "Get"}

    def test_compile_derive_specs_have_triggers(self) -> None:
        @schema_meta(http_crud("/api/users", Users, ops=(LIST, GET)))
        @dataclass
        class UserF:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(UserF)
        for spec in ctxs[0].specs:
            assert isinstance(spec.trigger, HTTPRouteTrigger)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. compile_derive with cli_crud
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompileDeriveCLI:
    """_compile.py — compile_derive with cli_crud."""

    def test_cli_crud_produces_single_ctx(self) -> None:
        @schema_meta(cli_crud("user", Users))
        @dataclass
        class UserG:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(UserG)
        assert len(ctxs) == 1

    def test_cli_crud_specs_have_cli_triggers(self) -> None:
        @schema_meta(cli_crud("user", Users, ops=(LIST, GET)))
        @dataclass
        class UserH:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(UserH)
        for spec in ctxs[0].specs:
            assert isinstance(spec.trigger, CLITrigger)

    def test_cli_crud_trigger_command_format(self) -> None:
        @schema_meta(cli_crud("user", Users, ops=(LIST,)))
        @dataclass
        class UserI:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(UserI)
        trigger = ctxs[0].specs[0].trigger
        assert isinstance(trigger, CLITrigger)
        assert trigger.command == "user-list"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Multiple generators compile_derive
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompileDeriveMultipleGenerators:
    """_compile.py — multiple generators produce multiple ctxs."""

    def test_two_generators_two_ctxs(self) -> None:
        @schema_meta(
            http_crud("/api/users", Users, ops=(LIST,)),
            cli_crud("user", Users, ops=(LIST,)),
        )
        @dataclass
        class UserJ:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(UserJ)
        assert len(ctxs) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 10. materialize — DeriveCtx -> Endpoint
# ═══════════════════════════════════════════════════════════════════════════════


class TestMaterialize:
    """_materialize.py — compile_derive -> materialize -> Endpoint."""

    def test_materialize_produces_endpoint(self) -> None:
        @schema_meta(http_crud("/api/users", Users, ops=(LIST, GET)))
        @dataclass
        class UserK:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(UserK)
        endpoint = materialize(ctxs[0])
        assert endpoint is not None

    def test_materialize_endpoint_has_exposures(self) -> None:
        @schema_meta(http_crud("/api/users", Users, ops=(LIST, GET, CREATE)))
        @dataclass
        class UserL:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(UserL)
        endpoint = materialize(ctxs[0])
        assert len(endpoint.exposures) == 3

    def test_materialize_exposures_have_triggers(self) -> None:
        @schema_meta(http_crud("/api/users", Users, ops=(LIST,)))
        @dataclass
        class UserM:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(UserM)
        endpoint = materialize(ctxs[0])
        exp = endpoint.exposures[0]
        assert exp.trigger is not None

    def test_materialize_exposures_have_codecs(self) -> None:
        @schema_meta(http_crud("/api/users", Users, ops=(LIST,)))
        @dataclass
        class UserN:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(UserN)
        endpoint = materialize(ctxs[0])
        exp = endpoint.exposures[0]
        assert exp.codec is not None

    def test_materialize_empty_ctx(self) -> None:
        from emergent.wire.derive._ctx import DeriveCtx

        ctx = DeriveCtx.from_entity(User)
        endpoint = materialize(ctx)
        assert len(endpoint.exposures) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 11. _codegen.py — type generation
# ═══════════════════════════════════════════════════════════════════════════════


class TestCodegen:
    """_codegen.py — create_dataclass, create_request_type, create_response_type."""

    def test_create_dataclass_frozen(self) -> None:
        from emergent.wire.derive._codegen import create_dataclass

        cls = create_dataclass("MyOp", [("name", str), ("age", int)], frozen=True)
        instance = cls(name="Alice", age=30)
        assert instance.name == "Alice"
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            instance.name = "Bob"

    def test_create_dataclass_name(self) -> None:
        from emergent.wire.derive._codegen import create_dataclass

        cls = create_dataclass("FooBar", [("x", int)], frozen=True)
        assert cls.__name__ == "FooBar"
        assert cls.__qualname__ == "FooBar"

    def test_create_request_type_has_to_domain(self) -> None:
        from emergent.wire.derive._codegen import create_dataclass, create_request_type

        op = create_dataclass("Op", [("val", str)], frozen=True)
        req = create_request_type("Req", [("val", str)], op)
        instance = req(val="hello")
        domain = instance.to_domain()
        assert domain.val == "hello"

    def test_create_response_type_has_from_domain(self) -> None:
        from emergent.wire.derive._codegen import create_response_type

        def converter(cls: type, result: object) -> object:
            return cls(value=result)

        resp: Any = create_response_type("Resp", [("value", str)], converter)
        instance: Any = resp.from_domain("test")
        assert instance.value == "test"

    def test_direct_mapper_extracts_fields(self) -> None:
        from emergent.wire.derive._codegen import DirectMapper, create_dataclass

        cls = create_dataclass("D", [("a", int), ("b", str)], frozen=True)
        mapper = DirectMapper()
        obj = cls(a=1, b="x")
        result = mapper(obj)
        assert result == {"a": 1, "b": "x"}


# ═══════════════════════════════════════════════════════════════════════════════
# 12. _trigger.py — trigger generation
# ═══════════════════════════════════════════════════════════════════════════════


class TestTriggerGen:
    """_trigger.py — HTTPTriggers, CLITriggers, and variants."""

    def test_http_triggers_list(self) -> None:
        from emergent.wire.derive._trigger import HTTPTriggers
        from emergent.wire.derive._crud import LIST

        triggers = HTTPTriggers("/api/users")
        trigger = triggers(User, LIST)
        assert isinstance(trigger, HTTPRouteTrigger)
        assert trigger.method == "GET"
        assert trigger.path == "/api/users"

    def test_http_triggers_get(self) -> None:
        from emergent.wire.derive._trigger import HTTPTriggers
        from emergent.wire.derive._crud import GET

        triggers = HTTPTriggers("/api/users")
        trigger = triggers(User, GET)
        assert isinstance(trigger, HTTPRouteTrigger)
        assert trigger.method == "GET"
        assert "{id}" in trigger.path

    def test_http_triggers_create(self) -> None:
        from emergent.wire.derive._trigger import HTTPTriggers
        from emergent.wire.derive._crud import CREATE

        triggers = HTTPTriggers("/api/users")
        trigger = triggers(User, CREATE)
        assert isinstance(trigger, HTTPRouteTrigger)
        assert trigger.method == "POST"
        assert trigger.path == "/api/users"

    def test_http_triggers_delete(self) -> None:
        from emergent.wire.derive._trigger import HTTPTriggers
        from emergent.wire.derive._crud import DELETE

        triggers = HTTPTriggers("/api/users")
        trigger = triggers(User, DELETE)
        assert isinstance(trigger, HTTPRouteTrigger)
        assert trigger.method == "DELETE"
        assert "{id}" in trigger.path

    def test_cli_triggers(self) -> None:
        from emergent.wire.derive._trigger import CLITriggers
        from emergent.wire.derive._crud import LIST

        triggers = CLITriggers("user")
        trigger = triggers(User, LIST)
        assert isinstance(trigger, CLITrigger)
        assert trigger.command == "user-list"

    def test_nested_http_triggers_list(self) -> None:
        from emergent.wire.derive._trigger import NestedHTTPTriggers
        from emergent.wire.derive._crud import LIST

        triggers = NestedHTTPTriggers("/users", ("user_id",), "posts")
        trigger = triggers(Post, LIST)
        assert isinstance(trigger, HTTPRouteTrigger)
        assert trigger.method == "GET"
        assert "{user_id}" in trigger.path
        assert "posts" in trigger.path

    def test_nested_http_triggers_get(self) -> None:
        from emergent.wire.derive._trigger import NestedHTTPTriggers
        from emergent.wire.derive._crud import GET

        triggers = NestedHTTPTriggers("/users", ("user_id",), "posts")
        trigger = triggers(Post, GET)
        assert isinstance(trigger, HTTPRouteTrigger)
        assert trigger.method == "GET"
        assert "{user_id}" in trigger.path
        assert "{id}" in trigger.path

    def test_filtered_trigger_gen_only(self) -> None:
        from emergent.wire.derive._trigger import HTTPTriggers, FilteredTriggerGen
        from emergent.wire.derive._crud import LIST, GET

        filtered = FilteredTriggerGen(
            HTTPTriggers("/api/users"),
            only_ops=frozenset({"List"}),
        )
        assert filtered(User, LIST) is not None
        assert filtered(User, GET) is None

    def test_filtered_trigger_gen_exclude(self) -> None:
        from emergent.wire.derive._trigger import HTTPTriggers, FilteredTriggerGen
        from emergent.wire.derive._crud import LIST, DELETE

        filtered = FilteredTriggerGen(
            HTTPTriggers("/api/users"),
            exclude_ops=frozenset({"Delete"}),
        )
        assert filtered(User, LIST) is not None
        assert filtered(User, DELETE) is None

    def test_prefixed_trigger_gen(self) -> None:
        from emergent.wire.derive._trigger import HTTPTriggers, PrefixedTriggerGen
        from emergent.wire.derive._crud import LIST

        prefixed = PrefixedTriggerGen(HTTPTriggers("/users"), prefix="/v2")
        trigger = prefixed(User, LIST)
        assert isinstance(trigger, HTTPRouteTrigger)
        assert trigger.path.startswith("/v2")


# ═══════════════════════════════════════════════════════════════════════════════
# 13. _query_helpers.py — pure utility functions
# ═══════════════════════════════════════════════════════════════════════════════


class TestQueryHelpers:
    """_query_helpers.py — identity_values, serialize_op_fields, id_path."""

    def test_identity_values(self) -> None:
        from emergent.wire.derive._query_helpers import identity_values

        @dataclass
        class Op:
            id: int = 42
            name: str = "test"

        result = identity_values(Op(), ("id",))
        assert result == {"id": 42}

    def test_identity_values_composite(self) -> None:
        from emergent.wire.derive._query_helpers import identity_values

        @dataclass
        class Op:
            tenant_id: int = 1
            item_id: int = 2

        result = identity_values(Op(), ("tenant_id", "item_id"))
        assert result == {"tenant_id": 1, "item_id": 2}

    def test_serialize_op_fields(self) -> None:
        from emergent.wire.derive._query_helpers import serialize_op_fields
        import json

        @dataclass
        class Op:
            name: str = "alice"
            age: int = 30

        result = serialize_op_fields(Op(), ("name", "age"))
        parsed = json.loads(result)
        assert parsed == {"name": "alice", "age": 30}

    def test_serialize_op_fields_skip_none(self) -> None:
        from emergent.wire.derive._query_helpers import serialize_op_fields
        import json

        @dataclass
        class Op:
            name: str = "bob"
            extra: str | None = None

        result = serialize_op_fields(Op(), ("name", "extra"))
        parsed = json.loads(result)
        assert "extra" not in parsed
        assert parsed["name"] == "bob"

    def test_id_path_single(self) -> None:
        from emergent.wire.derive._query_helpers import id_path

        assert id_path(("id",)) == "{id}"

    def test_id_path_composite(self) -> None:
        from emergent.wire.derive._query_helpers import id_path

        result = id_path(("tenant_id", "item_id"))
        assert result == "{tenant_id}/{item_id}"


# ═══════════════════════════════════════════════════════════════════════════════
# 14. _explain.py — explain_derive, derive_dict, explain_entity
# ═══════════════════════════════════════════════════════════════════════════════


class TestExplain:
    """_explain.py — self-description of derive pipelines."""

    def test_explain_derive_non_empty(self) -> None:
        from emergent.wire.derive._explain import explain_derive

        @schema_meta(http_crud("/api/users", Users, ops=(LIST, GET)))
        @dataclass
        class UserP:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(UserP)
        text = explain_derive(ctxs[0])
        assert len(text) > 0
        assert "UserP" in text

    def test_explain_derive_mentions_operations(self) -> None:
        from emergent.wire.derive._explain import explain_derive

        @schema_meta(http_crud("/api/users", Users, ops=(LIST, CREATE)))
        @dataclass
        class UserQ:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(UserQ)
        text = explain_derive(ctxs[0])
        assert "List" in text
        assert "Create" in text

    def test_derive_dict_has_entity(self) -> None:
        from emergent.wire.derive._explain import derive_dict

        @schema_meta(http_crud("/api/users", Users, ops=(LIST,)))
        @dataclass
        class UserR:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(UserR)
        d = derive_dict(ctxs[0])
        assert d["entity"] == "UserR"

    def test_derive_dict_has_specs(self) -> None:
        from emergent.wire.derive._explain import derive_dict

        @schema_meta(http_crud("/api/users", Users, ops=(LIST, GET)))
        @dataclass
        class UserS:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(UserS)
        d = derive_dict(ctxs[0])
        assert isinstance(d["specs"], list)
        assert len(d["specs"]) == 2

    def test_explain_entity(self) -> None:
        from emergent.wire.derive._explain import explain_entity

        @schema_meta(http_crud("/api/users", Users, ops=(LIST,)))
        @dataclass
        class UserT:
            id: Annotated[int, Identity()]
            name: str

        text = explain_entity(UserT)
        assert "UserT" in text
        assert len(text) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 15. _error_caps.py — ErrorTransform, ProblemResponse, ERROR_CAPS
# ═══════════════════════════════════════════════════════════════════════════════


class TestErrorCaps:
    """_error_caps.py — generic error-handling capabilities."""

    def test_error_transform_frozen(self) -> None:
        from emergent.wire.derive._error_caps import ErrorTransform

        et = ErrorTransform()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            et.x = 1  # type: ignore[attr-defined]

    def test_error_transform_passthrough(self) -> None:
        from emergent.wire.derive._error_caps import ErrorTransform

        et = ErrorTransform()
        result = et.apply_response("plain string")
        assert result == "plain string"

    def test_error_transform_calls_to_problem(self) -> None:
        from emergent.wire.derive._error_caps import ErrorTransform

        class HasProblem:
            def to_problem(self) -> str:
                return "problem!"

        et = ErrorTransform()
        result = et.apply_response(HasProblem())
        assert result == "problem!"

    def test_problem_response_frozen(self) -> None:
        from emergent.wire.derive._error_caps import ProblemResponse

        pr = ProblemResponse()
        assert pr.media_type == "application/problem+json"
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            pr.media_type = "x"  # type: ignore[misc]

    def test_problem_response_passthrough_non_problem(self) -> None:
        from emergent.wire.derive._error_caps import ProblemResponse

        pr = ProblemResponse()
        result = pr.apply_response("not a problem")
        assert result == "not a problem"

    def test_error_caps_tuple(self) -> None:
        from emergent.wire.derive._error_caps import ERROR_CAPS, ErrorTransform, ProblemResponse

        assert len(ERROR_CAPS) == 2
        assert isinstance(ERROR_CAPS[0], ErrorTransform)
        assert isinstance(ERROR_CAPS[1], ProblemResponse)


# ═══════════════════════════════════════════════════════════════════════════════
# 16. _builders.py — ExposureBuilder, exposure
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuilders:
    """_builders.py — declarative ExposureBuilder API."""

    def test_exposure_builder_build(self) -> None:
        from emergent.wire.derive._builders import exposure

        async def handler(op: object) -> Result[int, str]:
            return Ok(42)

        op_type, _handler, exp = (
            exposure("create", User)
            .request(name=str)
            .response(result=int)
            .handler(handler)
            .trigger(HTTPRouteTrigger("POST", "/users"))
            .build()
        )
        assert op_type.__name__ == "UserCreateOp"
        assert exp.trigger is not None

    def test_exposure_builder_no_trigger_raises(self) -> None:
        from emergent.wire.derive._builders import exposure

        async def handler(op: object) -> Result[int, str]:
            return Ok(42)

        builder = exposure("op", User).request(name=str).response(r=int).handler(handler)
        with pytest.raises(ValueError, match="Trigger not set"):
            builder.build()

    def test_exposure_builder_no_handler_raises(self) -> None:
        from emergent.wire.derive._builders import exposure

        builder = (
            exposure("op", User)
            .request(name=str)
            .response(r=int)
            .trigger(HTTPRouteTrigger("POST", "/test"))
        )
        with pytest.raises(ValueError, match="Handler not set"):
            builder.build()


# ═══════════════════════════════════════════════════════════════════════════════
# 17. _scoped.py — Scoped, scoped
# ═══════════════════════════════════════════════════════════════════════════════


class TestScoped:
    """_scoped.py — scoping modifiers to specific generators."""

    def test_scoped_construction(self) -> None:
        from emergent.wire.derive._scoped import scoped, Scoped

        gen = http_crud("/api/users", Users, ops=(LIST,))
        s = scoped(gen)
        assert isinstance(s, Scoped)
        assert s.generator is gen
        assert s.caps == ()

    def test_scoped_with_caps(self) -> None:
        from emergent.wire.derive._scoped import scoped
        from emergent.wire.derive._transforms import Readonly

        gen = http_crud("/api/users", Users, ops=(LIST, GET))
        s = scoped(gen, Readonly())
        assert len(s.caps) == 1

    def test_scoped_compile_derive(self) -> None:
        from emergent.wire.derive._scoped import scoped
        from emergent.wire.derive._transforms import Readonly

        @schema_meta(
            scoped(
                http_crud("/api/items", Users),
                Readonly(),
            )
        )
        @dataclass
        class ItemA:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(ItemA)
        assert len(ctxs) == 1
        # Readonly keeps only Read-effect specs: List, Get
        names = {s.name for s in ctxs[0].specs}
        assert "List" in names
        assert "Get" in names
        assert "Create" not in names
        assert "Delete" not in names


# ═══════════════════════════════════════════════════════════════════════════════
# 18. Patterns — lookup ops (EXISTS, COUNT)
# ═══════════════════════════════════════════════════════════════════════════════


class TestLookupPatterns:
    """patterns/lookup.py — EXISTS and COUNT ops."""

    def test_exists_op_name(self) -> None:
        from emergent.wire.derive.patterns.lookup import EXISTS

        assert EXISTS.name == "Exists"

    def test_count_op_name(self) -> None:
        from emergent.wire.derive.patterns.lookup import COUNT

        assert COUNT.name == "Count"

    def test_exists_has_read_effect(self) -> None:
        from emergent.wire.derive.patterns.lookup import EXISTS
        from emergent.wire.derive._effects import Read, has_effect

        assert has_effect(EXISTS.effects, Read)

    def test_count_has_read_effect(self) -> None:
        from emergent.wire.derive.patterns.lookup import COUNT
        from emergent.wire.derive._effects import Read, has_effect

        assert has_effect(COUNT.effects, Read)

    def test_exists_in_crud_ops(self) -> None:
        from emergent.wire.derive.patterns.lookup import EXISTS

        @schema_meta(http_crud("/api/items", Users, ops=(LIST, EXISTS)))
        @dataclass
        class ItemB:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(ItemB)
        names = {s.name for s in ctxs[0].specs}
        assert "Exists" in names
        assert "List" in names

    def test_count_in_crud_ops(self) -> None:
        from emergent.wire.derive.patterns.lookup import COUNT

        @schema_meta(http_crud("/api/items", Users, ops=(LIST, COUNT)))
        @dataclass
        class ItemC:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(ItemC)
        names = {s.name for s in ctxs[0].specs}
        assert "Count" in names


# ═══════════════════════════════════════════════════════════════════════════════
# 19. Patterns — methods
# ═══════════════════════════════════════════════════════════════════════════════


class TestMethodPatterns:
    """patterns/methods.py — decorator-based method patterns."""

    def test_post_attaches_trigger(self) -> None:
        from emergent.wire.derive.patterns.methods import post, TRIGGER_ENTRIES_ATTR

        @post("/api/orders")
        async def create(customer: str) -> Result[int, str]:
            return Ok(1)

        entries = getattr(create, TRIGGER_ENTRIES_ATTR, [])
        assert len(entries) == 1
        assert isinstance(entries[0].trigger, HTTPRouteTrigger)
        assert entries[0].trigger.method == "POST"

    def test_get_attaches_trigger(self) -> None:
        from emergent.wire.derive.patterns.methods import get, TRIGGER_ENTRIES_ATTR

        @get("/api/orders")
        async def list_orders() -> Result[list[object], str]:
            return Ok([])

        entries = getattr(list_orders, TRIGGER_ENTRIES_ATTR, [])
        assert len(entries) == 1
        assert entries[0].trigger.method == "GET"

    def test_delete_attaches_trigger(self) -> None:
        from emergent.wire.derive.patterns.methods import delete, TRIGGER_ENTRIES_ATTR

        @delete("/api/orders/{id}")
        async def remove(id: int) -> Result[bool, str]:
            return Ok(True)

        entries = getattr(remove, TRIGGER_ENTRIES_ATTR, [])
        assert len(entries) == 1
        assert entries[0].trigger.method == "DELETE"

    def test_command_attaches_cli_trigger(self) -> None:
        from emergent.wire.derive.patterns.methods import command, TRIGGER_ENTRIES_ATTR

        @command("order-create")
        async def create_cmd(customer: str) -> Result[int, str]:
            return Ok(1)

        entries = getattr(create_cmd, TRIGGER_ENTRIES_ATTR, [])
        assert len(entries) == 1
        assert isinstance(entries[0].trigger, CLITrigger)
        assert entries[0].trigger.command == "order-create"

    def test_op_decorator(self) -> None:
        from emergent.wire.derive.patterns.methods import op, OP_ENTRIES_ATTR

        @op("CreateOrder")
        async def create(customer: str) -> Result[int, str]:
            return Ok(1)

        entry = getattr(create, OP_ENTRIES_ATTR, None)
        assert entry is not None
        assert entry.name == "CreateOrder"

    def test_op_decorator_default_name(self) -> None:
        from emergent.wire.derive.patterns.methods import op, OP_ENTRIES_ATTR

        @op()
        async def my_handler() -> Result[int, str]:
            return Ok(1)

        entry = getattr(my_handler, OP_ENTRIES_ATTR, None)
        assert entry is not None
        assert entry.name == "my_handler"

    def test_multiple_triggers_on_method(self) -> None:
        from emergent.wire.derive.patterns.methods import post, command, TRIGGER_ENTRIES_ATTR

        @post("/api/orders")
        @command("order-create")
        async def create(customer: str) -> Result[int, str]:
            return Ok(1)

        entries = getattr(create, TRIGGER_ENTRIES_ATTR, [])
        assert len(entries) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 20. Auth compile_derive_modify integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthCompileIntegration:
    """Integration: auth caps applied during compile_derive."""

    def test_authenticated_adds_enrichers_to_specs(self) -> None:
        from emergent.wire.derive.auth.caps import Authenticated
        from emergent.wire.derive.auth.extractors import BearerExtract
        from emergent.wire.derive.auth.validate import TokenValidate

        async def lookup(token: str) -> AuthUser | None:
            return None

        validate = TokenValidate(identity_type=AuthUser, lookup=lookup)

        @schema_meta(
            http_crud("/api/items", Users, ops=(LIST, GET, CREATE)),
            Authenticated(BearerExtract(), validate=validate),
        )
        @dataclass
        class ItemD:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(ItemD)
        # All specs should have auth capabilities added
        for spec in ctxs[0].specs:
            cap_types = {type(c).__name__ for c in spec.capabilities}
            assert "BearerExtract" in cap_types or "TokenValidate" in cap_types or "AuthOpenAPI" in cap_types

    def test_role_required_adds_require_role_enricher(self) -> None:
        from emergent.wire.derive.auth.caps import RoleRequired

        @schema_meta(
            http_crud("/api/items", Users, ops=(CREATE,)),
            RoleRequired(
                identity_type=AuthUser,
                role="admin",
                role_getter=_get_roles,
            ),
        )
        @dataclass
        class ItemE:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(ItemE)
        spec = ctxs[0].specs[0]
        enricher_types = {type(c).__name__ for c in spec.capabilities}
        assert "RequireRole" in enricher_types

    def test_authorize_ops_strict_raises_for_unmapped(self) -> None:
        from emergent.wire.derive.auth.caps import AuthorizeOps

        @schema_meta(
            http_crud("/api/items", Users, ops=(LIST, CREATE)),
            AuthorizeOps(
                identity_type=AuthUser,
                role_map={"Create": "admin"},  # Missing "List"
                role_getter=_get_roles,
                strict=True,
            ),
        )
        @dataclass
        class ItemF:
            id: Annotated[int, Identity()]
            name: str

        with pytest.raises(ValueError, match="no role mapping"):
            compile_derive(ItemF)

    def test_authorize_ops_non_strict_skips_unmapped(self) -> None:
        from emergent.wire.derive.auth.caps import AuthorizeOps

        @schema_meta(
            http_crud("/api/items", Users, ops=(LIST, CREATE)),
            AuthorizeOps(
                identity_type=AuthUser,
                role_map={"Create": "admin"},
                role_getter=_get_roles,
                strict=False,
            ),
        )
        @dataclass
        class ItemG:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(ItemG)
        assert len(ctxs) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 21. Materialize with auth — full pipeline
# ═══════════════════════════════════════════════════════════════════════════════


class TestMaterializeWithAuth:
    """Full pipeline: entity + auth -> compile_derive -> materialize."""

    def test_materialize_with_authenticated(self) -> None:
        from emergent.wire.derive.auth.caps import Authenticated
        from emergent.wire.derive.auth.extractors import BearerExtract
        from emergent.wire.derive.auth.validate import TokenValidate

        async def lookup(token: str) -> AuthUser | None:
            return None

        validate = TokenValidate(identity_type=AuthUser, lookup=lookup)

        @schema_meta(
            http_crud("/api/secure", Users, ops=(LIST,)),
            Authenticated(BearerExtract(), validate=validate),
        )
        @dataclass
        class SecureItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(SecureItem)
        endpoint = materialize(ctxs[0])
        assert len(endpoint.exposures) == 1
        exp = endpoint.exposures[0]
        assert exp.trigger is not None
        assert exp.codec is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 22. Nested CRUD patterns
# ═══════════════════════════════════════════════════════════════════════════════


class TestNestedCRUD:
    """patterns/nested.py — NestedCRUD produces scoped endpoints."""

    def test_nested_crud_produces_specs(self) -> None:
        from emergent.wire.derive.patterns.nested import nested_http_crud

        @schema_meta(nested_http_crud("/users", parent=User, provider_node=Posts))
        @dataclass
        class PostA:
            id: Annotated[int, Identity()]
            user_id: Annotated[int, Ref(User)]
            title: str

        ctxs = compile_derive(PostA)
        assert len(ctxs) == 1
        assert len(ctxs[0].specs) == 5  # List, Get, Create, Update, Delete

    def test_nested_crud_spec_names(self) -> None:
        from emergent.wire.derive.patterns.nested import nested_http_crud

        @schema_meta(nested_http_crud("/users", parent=User, provider_node=Posts))
        @dataclass
        class PostB:
            id: Annotated[int, Identity()]
            user_id: Annotated[int, Ref(User)]
            title: str

        ctxs = compile_derive(PostB)
        names = {s.name for s in ctxs[0].specs}
        assert names == {"List", "Get", "Create", "Update", "Delete"}

    def test_nested_crud_triggers_have_parent_path(self) -> None:
        from emergent.wire.derive.patterns.nested import nested_http_crud

        @schema_meta(nested_http_crud("/users", parent=User, provider_node=Posts))
        @dataclass
        class PostC:
            id: Annotated[int, Identity()]
            user_id: Annotated[int, Ref(User)]
            title: str

        ctxs = compile_derive(PostC)
        for spec in ctxs[0].specs:
            trigger = spec.trigger
            assert isinstance(trigger, HTTPRouteTrigger)
            assert "/users/{user_id}" in trigger.path

    def test_nested_crud_materialize(self) -> None:
        from emergent.wire.derive.patterns.nested import nested_http_crud

        @schema_meta(nested_http_crud("/users", parent=User, provider_node=Posts))
        @dataclass
        class PostD:
            id: Annotated[int, Identity()]
            user_id: Annotated[int, Ref(User)]
            title: str

        ctxs = compile_derive(PostD)
        endpoint = materialize(ctxs[0])
        assert len(endpoint.exposures) == 5

    def test_nested_crud_no_ref_raises(self) -> None:
        from emergent.wire.derive.patterns.nested import nested_http_crud

        @schema_meta(nested_http_crud("/users", parent=User, provider_node=Posts))
        @dataclass
        class BadPost:
            id: Annotated[int, Identity()]
            title: str

        with pytest.raises(ValueError, match="no Ref"):
            compile_derive(BadPost)

    def test_nested_crud_custom_fk_field(self) -> None:
        from emergent.wire.derive.patterns.nested import nested_http_crud

        @schema_meta(
            nested_http_crud(
                "/users",
                parent=User,
                provider_node=Posts,
                fk_field="user_id",
            )
        )
        @dataclass
        class PostE:
            id: Annotated[int, Identity()]
            user_id: Annotated[int, Ref(User)]
            title: str

        ctxs = compile_derive(PostE)
        assert len(ctxs[0].specs) == 5


# ═══════════════════════════════════════════════════════════════════════════════
# 23. RequireRole enricher construction
# ═══════════════════════════════════════════════════════════════════════════════


class TestRequireRole:
    """auth/caps.py — RequireRole enricher."""

    def test_require_role_frozen(self) -> None:
        from emergent.wire.derive.auth.caps import RequireRole

        rr = RequireRole(
            identity_type=AuthUser,
            roles=frozenset({"admin"}),
            role_getter=_get_roles,
        )
        assert rr.roles == frozenset({"admin"})
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            rr.roles = frozenset()  # type: ignore[misc]

    def test_require_role_identity_type(self) -> None:
        from emergent.wire.derive.auth.caps import RequireRole

        rr = RequireRole(
            identity_type=AuthUser,
            roles=frozenset({"editor"}),
            role_getter=_get_roles,
        )
        assert rr.identity_type is AuthUser


# ═══════════════════════════════════════════════════════════════════════════════
# 24. Explain — trigger_dict, spec_dict
# ═══════════════════════════════════════════════════════════════════════════════


class TestExplainInternals:
    """_explain.py — internal helper functions."""

    def test_trigger_dict_http(self) -> None:
        from emergent.wire.derive._explain import trigger_dict

        d = trigger_dict(HTTPRouteTrigger("GET", "/api/users"))
        assert d["type"] == "http"
        assert d["method"] == "GET"
        assert d["path"] == "/api/users"

    def test_trigger_dict_cli(self) -> None:
        from emergent.wire.derive._explain import trigger_dict

        d = trigger_dict(CLITrigger("user-list"))
        assert d["type"] == "cli"
        assert d["command"] == "user-list"

    def test_trigger_dict_unknown(self) -> None:
        from emergent.wire.derive._explain import trigger_dict

        class CustomTrigger:
            pass

        d = trigger_dict(CustomTrigger())
        assert d["type"] == "CustomTrigger"

    def test_effect_dict_simple(self) -> None:
        from emergent.wire.derive._explain import effect_dict
        from emergent.wire.derive._effects import Read

        d = effect_dict(Read())
        assert d["type"] == "Read"

    def test_capability_dict(self) -> None:
        from emergent.wire.derive._explain import capability_dict
        from emergent.wire.derive._error_caps import ErrorTransform

        d = capability_dict(ErrorTransform())
        assert d["type"] == "ErrorTransform"
