"""Tests for derivelib._codegen — type generation infrastructure."""

from __future__ import annotations

import dataclasses

from kungfu import Error, Ok

from derivelib._codegen import (
    create_dataclass,
    create_request_type,
    create_response_type,
    set_type_name,
)


class TestCreateDataclass:
    def test_creates_dataclass(self) -> None:
        cls = create_dataclass("MyType", [("x", int), ("y", str)])
        assert dataclasses.is_dataclass(cls)

    def test_name_set(self) -> None:
        cls = create_dataclass("MyType", [("x", int)])
        assert cls.__name__ == "MyType"
        assert cls.__qualname__ == "MyType"

    def test_frozen_by_default(self) -> None:
        cls = create_dataclass("Frozen", [("x", int)])
        instance = cls(x=1)
        with_error = False
        try:
            instance.x = 2
        except dataclasses.FrozenInstanceError:
            with_error = True
        assert with_error

    def test_not_frozen(self) -> None:
        cls = create_dataclass("Mutable", [("x", int)], frozen=False)
        instance = cls(x=1)
        instance.x = 2
        assert instance.x == 2

    def test_with_defaults(self) -> None:
        cls = create_dataclass("WithDefault", [("x", int, 42)])
        instance = cls()
        assert instance.x == 42

    def test_with_namespace(self) -> None:
        cls = create_dataclass(
            "WithMethod",
            [("x", int)],
            namespace={"double": lambda self: self.x * 2},
        )
        instance = cls(x=5)
        assert instance.double() == 10


class TestSetTypeName:
    def test_sets_both(self) -> None:
        cls = create_dataclass("Old", [("x", int)])
        set_type_name(cls, "New")
        assert cls.__name__ == "New"
        assert cls.__qualname__ == "New"


class TestCreateRequestType:
    def test_has_to_domain(self) -> None:
        OpType = create_dataclass("MyOp", [("name", str), ("age", int)])
        RequestType = create_request_type(
            "MyRequest", [("name", str), ("age", int)], OpType
        )
        assert hasattr(RequestType, "to_domain")

    def test_to_domain_converts(self) -> None:
        OpType = create_dataclass("MyOp", [("name", str), ("age", int)])
        RequestType = create_request_type(
            "MyRequest", [("name", str), ("age", int)], OpType
        )
        req = RequestType(name="Alice", age=30)
        op = req.to_domain()
        assert op.name == "Alice"
        assert op.age == 30
        assert type(op).__name__ == "MyOp"

    def test_with_mapper(self) -> None:
        OpType = create_dataclass("MyOp", [("full_name", str)])
        RequestType = create_request_type(
            "MyRequest",
            [("first", str), ("last", str)],
            OpType,
            mapper=lambda req: {"full_name": f"{req.first} {req.last}"},
        )
        req = RequestType(first="Alice", last="Smith")
        op = req.to_domain()
        assert op.full_name == "Alice Smith"


class TestCreateResponseType:
    def test_has_from_domain(self) -> None:
        def converter(cls: type, result: object) -> object:
            return cls(value=42)

        ResponseType = create_response_type(
            "MyResponse", [("value", int)], converter
        )
        assert hasattr(ResponseType, "from_domain")

    def test_from_domain_converts(self) -> None:
        def converter(cls: type, result: object) -> object:
            match result:
                case Ok(val):
                    return cls(value=val)
                case _:
                    return result

        ResponseType = create_response_type(
            "MyResponse", [("value", int)], converter
        )
        resp = ResponseType.from_domain(Ok(99))
        assert resp.value == 99
