"""Tests for emergent.wire.bridge._introspect."""

from __future__ import annotations

import functools
import inspect
from functools import partial

import pytest

from emergent.wire.bridge._introspect import (
    ClosureFallbackUnwrap,
    DecoratorInfo,
    ParameterKind,
    ParameterShape,
    analyze_handler,
    extract_class_methods,
    get_view_class,
    no_default,
    resolve_descriptor,
    unwrap_handler,
)


# ─── helpers ──────────────────────────────────────────────────────────────────


def plain_sync(x: int, y: str = "default") -> bool:
    return True


async def plain_async(value: float) -> str:
    return str(value)


def decorated_target(n: int) -> int:
    return n * 2


@functools.wraps(decorated_target)
def outer_wrapper(*args: int, **kwargs: int) -> int:
    return decorated_target(*args, **kwargs)


outer_wrapper.__wrapped__ = decorated_target  # type: ignore[attr-defined]


# ─── ParameterKind.of ─────────────────────────────────────────────────────────


def test_parameter_kind_positional_only() -> None:
    # Build a parameter with POSITIONAL_ONLY kind explicitly
    param = inspect.Parameter("x", inspect.Parameter.POSITIONAL_ONLY)
    assert ParameterKind.of(param) == ParameterKind.POSITIONAL_ONLY


def test_parameter_kind_positional_or_keyword() -> None:
    param = inspect.Parameter("x", inspect.Parameter.POSITIONAL_OR_KEYWORD)
    assert ParameterKind.of(param) == ParameterKind.POSITIONAL_OR_KEYWORD


def test_parameter_kind_var_positional() -> None:
    param = inspect.Parameter("args", inspect.Parameter.VAR_POSITIONAL)
    assert ParameterKind.of(param) == ParameterKind.VAR_POSITIONAL


def test_parameter_kind_keyword_only() -> None:
    param = inspect.Parameter("kw", inspect.Parameter.KEYWORD_ONLY)
    assert ParameterKind.of(param) == ParameterKind.KEYWORD_ONLY


def test_parameter_kind_var_keyword() -> None:
    param = inspect.Parameter("kwargs", inspect.Parameter.VAR_KEYWORD)
    assert ParameterKind.of(param) == ParameterKind.VAR_KEYWORD


# ─── ParameterShape.from_parameter ────────────────────────────────────────────


def test_parameter_shape_with_annotation_and_default() -> None:
    param = inspect.Parameter(
        "count",
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        default=42,
        annotation=int,
    )
    shape = ParameterShape.from_parameter(param)
    assert shape.name == "count"
    assert shape.annotation is int
    assert shape.has_default is True
    assert shape.default == 42
    assert shape.kind == ParameterKind.POSITIONAL_OR_KEYWORD


def test_parameter_shape_no_annotation_no_default() -> None:
    param = inspect.Parameter("value", inspect.Parameter.POSITIONAL_OR_KEYWORD)
    shape = ParameterShape.from_parameter(param)
    assert shape.annotation is None
    assert shape.has_default is False
    assert shape.default is no_default()


def test_parameter_shape_resolved_annotation_overrides() -> None:
    param = inspect.Parameter(
        "item",
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        annotation=str,
    )
    shape = ParameterShape.from_parameter(param, resolved_annotation=float)
    # resolved_annotation takes precedence when provided
    assert shape.annotation is float


# ─── unwrap_handler ───────────────────────────────────────────────────────────


def test_unwrap_handler_no_wrapped_returns_itself() -> None:
    def simple(x: int) -> int:
        return x

    handler, decorators = unwrap_handler(simple)
    assert handler is simple
    assert decorators == ()


def test_unwrap_handler_with_wrapped_chain() -> None:
    handler, decorators = unwrap_handler(outer_wrapper)
    assert handler is decorated_target
    assert len(decorators) == 1
    assert isinstance(decorators[0], DecoratorInfo)
    assert decorators[0].wrapper is outer_wrapper


def test_unwrap_handler_non_callable_raises() -> None:
    with pytest.raises(TypeError):
        unwrap_handler(42)


# ─── ClosureFallbackUnwrap ────────────────────────────────────────────────────


def test_closure_fallback_finds_callable_in_closure() -> None:
    def inner_func(x: int) -> int:
        return x

    def make_wrapper() -> object:
        # Create a closure that captures inner_func but has NO __wrapped__
        def wrapper(*args: int, **kwargs: int) -> int:
            return inner_func(*args, **kwargs)

        return wrapper

    wrapper_obj = make_wrapper()
    strategy = ClosureFallbackUnwrap()
    found, decorators = strategy.unwrap(wrapper_obj)
    # The closure contains inner_func, so it should be extracted
    assert found is inner_func
    assert len(decorators) == 1


def test_closure_fallback_no_closure_callable_returns_itself() -> None:
    # A plain function with no closure containing a callable
    def no_closure(x: int) -> int:
        return x

    strategy = ClosureFallbackUnwrap()
    found, decorators = strategy.unwrap(no_closure)
    assert found is no_closure
    assert decorators == ()


# ─── extract_class_methods ────────────────────────────────────────────────────


def test_extract_class_methods_existing_methods() -> None:
    class MyView:
        def get(self) -> str:
            return "get"

        def post(self) -> str:
            return "post"

    results = list(extract_class_methods(MyView, ("get", "post")))
    names = [name for name, _ in results]
    assert "get" in names
    assert "post" in names
    assert len(results) == 2


def test_extract_class_methods_skips_missing() -> None:
    class MyView:
        def get(self) -> str:
            return "get"

    results = list(extract_class_methods(MyView, ("get", "delete", "patch")))
    names = [name for name, _ in results]
    assert names == ["get"]


def test_extract_class_methods_empty_when_none_match() -> None:
    class EmptyView:
        pass

    results = list(extract_class_methods(EmptyView, ("get", "post")))
    assert results == []


# ─── get_view_class ───────────────────────────────────────────────────────────


def test_get_view_class_returns_class_itself() -> None:
    class MyClass:
        pass

    result = get_view_class(MyClass)
    assert result is MyClass


def test_get_view_class_returns_view_class_attr() -> None:
    class Inner:
        pass

    class Holder:
        view_class = Inner

    result = get_view_class(Holder())
    assert result is Inner


def test_get_view_class_returns_none_for_plain_object() -> None:
    result = get_view_class(object())
    assert result is None


# ─── resolve_descriptor ───────────────────────────────────────────────────────


def test_resolve_descriptor_with_get() -> None:
    class MyDescriptor:
        def __get__(self, obj: object, owner: type | None = None) -> str:
            return "resolved"

    desc = MyDescriptor()
    result = resolve_descriptor(desc)
    assert result == "resolved"


def test_resolve_descriptor_plain_object_returns_itself() -> None:
    obj = object()
    result = resolve_descriptor(obj)
    assert result is obj


def test_resolve_descriptor_type_returns_itself() -> None:
    # isinstance(obj, type) branch: class objects should be returned as-is
    # even though they have __get__ via the descriptor protocol.
    result = resolve_descriptor(int)
    assert result is int


# ─── analyze_handler ──────────────────────────────────────────────────────────


def test_analyze_handler_sync_function() -> None:
    shape = analyze_handler(plain_sync)
    assert shape.is_async is False
    assert shape.is_generator is False
    assert shape.name == "plain_sync"
    assert "x" in shape.parameters
    assert "y" in shape.parameters
    assert shape.parameters["x"].annotation is int
    assert shape.parameters["y"].annotation is str
    assert shape.parameters["y"].has_default is True
    assert shape.return_type is bool


def test_analyze_handler_async_function() -> None:
    shape = analyze_handler(plain_async)
    assert shape.is_async is True
    assert shape.parameters["value"].annotation is float
    assert shape.return_type is str


def test_analyze_handler_default_skips_self_and_cls() -> None:
    def handler(self: object, x: int) -> None:
        pass

    shape = analyze_handler(handler)
    assert "self" not in shape.parameters
    assert "x" in shape.parameters


def test_analyze_handler_custom_skip_params() -> None:
    def handler(self: object, x: int) -> None:
        pass

    shape = analyze_handler(handler, skip_params=frozenset())
    # With empty skip_params, "self" should appear
    assert "self" in shape.parameters
    assert "x" in shape.parameters


def test_analyze_handler_decorator_chain() -> None:
    shape = analyze_handler(outer_wrapper)
    assert len(shape.decorators) == 1
    assert shape.decorators[0].wrapper is outer_wrapper
    assert shape.handler is decorated_target


def test_analyze_handler_callable_instance_detects_instance_info() -> None:
    class CallableHandler:
        def __init__(self, db: str) -> None:
            self.db = db

        def __call__(self, request: int) -> str:
            return self.db

    instance = CallableHandler(db="postgres")
    shape = analyze_handler(instance)
    assert shape.instance_info is not None
    assert shape.instance_info.instance is instance
    assert shape.instance_info.cls is CallableHandler
    # db is an __init__ param (self is skipped by default)
    assert "db" in shape.instance_info.init_parameters
    assert "request" in shape.parameters


def test_analyze_handler_partial_skips_bound_params() -> None:
    def add(x: int, y: int) -> int:
        return x + y

    bound = partial(add, x=10)
    shape = analyze_handler(bound)
    assert shape.partial_func is add
    assert shape.partial_keywords == {"x": 10}
    # x is bound, so it should NOT appear in parameters
    assert "x" not in shape.parameters
    assert "y" in shape.parameters


def test_analyze_handler_no_default_sentinel() -> None:
    def f(n: int) -> None:
        pass

    shape = analyze_handler(f)
    param = shape.parameters["n"]
    assert param.has_default is False
    assert param.default is no_default()


def test_no_default_is_singleton() -> None:
    # no_default() always returns the same sentinel object
    assert no_default() is no_default()
