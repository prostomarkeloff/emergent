"""Tests for emergent.wire.bridge._detect — run_detectors and DetectionResult."""

from __future__ import annotations

from dataclasses import dataclass

from emergent.wire.bridge._detect import (
    BodyDetection,
    DIDetection,
    DecoratorMapping,
    run_detectors,
)
from emergent.wire.bridge._introspect import (
    DecoratorInfo,
    HandlerShape,
    ParameterKind,
    ParameterShape,
    no_default,
)


# ─── test-local SurfaceCapability implementation ───────────────────────────────


@dataclass(frozen=True, slots=True)
class StubCapability:
    """Minimal SurfaceCapability stub for tests."""

    label: str


# ─── helpers to build test shapes ─────────────────────────────────────────────


def _make_param(name: str, annotation: type) -> ParameterShape:
    return ParameterShape(
        name=name,
        annotation=annotation,
        default=no_default(),
        has_default=False,
        kind=ParameterKind.POSITIONAL_OR_KEYWORD,
    )


def _make_decorator(name: str) -> DecoratorInfo:
    def _dummy() -> None:  # noqa: ANN202
        pass

    _dummy.__name__ = name
    return DecoratorInfo(
        wrapper=_dummy,
        wrapper_name=name,
        wrapper_module=None,
    )


def _make_shape(
    params: dict[str, ParameterShape] | None = None,
    decorators: tuple[DecoratorInfo, ...] = (),
) -> HandlerShape:
    def _handler() -> None:
        pass

    return HandlerShape(
        handler=_handler,
        name="test_handler",
        is_async=False,
        is_generator=False,
        parameters=params or {},
        decorators=decorators,
    )


# ─── test-local detector / mapper implementations ─────────────────────────────


class _AnnotationBodyDetector:
    """Detects a body parameter by annotation type match."""

    def __init__(self, target_annotation: type) -> None:
        self._target = target_annotation

    def detect(self, param: ParameterShape, shape: HandlerShape) -> BodyDetection | None:
        if param.annotation is self._target:
            return BodyDetection(parameter=param, body_type=self._target)
        return None


class _AnnotationDIDetector:
    """DI detector that matches by annotation type."""

    def __init__(self, target_annotation: type, source: object) -> None:
        self._target = target_annotation
        self._source = source

    def detect(self, param: ParameterShape, shape: HandlerShape) -> DIDetection | None:
        if param.annotation is self._target:
            return DIDetection(parameter=param, source=self._source)
        return None


class _NameDecoratorMapper:
    """Maps a decorator by wrapper_name to a capability."""

    def __init__(self, target_name: str, capability: StubCapability) -> None:
        self._target_name = target_name
        self._capability = capability

    def map(self, decorator: DecoratorInfo, shape: HandlerShape) -> DecoratorMapping | None:
        if decorator.wrapper_name == self._target_name:
            return DecoratorMapping(decorator=decorator, capability=self._capability)
        return None


# ─── tests ────────────────────────────────────────────────────────────────────


def test_no_detectors_returns_empty_result() -> None:
    """With no detectors at all, the result is fully empty."""
    param = _make_param("body", dict)
    shape = _make_shape(params={"body": param})

    result = run_detectors(shape)

    assert result.body is None
    assert result.di_params == ()
    assert result.decorator_capabilities == ()


def test_body_detector_matches_one_param() -> None:
    """A body detector that matches by annotation sets body."""
    param = _make_param("payload", dict)
    shape = _make_shape(params={"payload": param})

    result = run_detectors(
        shape,
        body_detectors=(_AnnotationBodyDetector(dict),),
    )

    assert result.body is not None
    assert result.body.parameter is param
    assert result.body.body_type is dict


def test_body_detector_no_match_leaves_body_none() -> None:
    """When no param matches the body detector, body stays None."""
    param = _make_param("x", int)
    shape = _make_shape(params={"x": param})

    result = run_detectors(
        shape,
        body_detectors=(_AnnotationBodyDetector(dict),),
    )

    assert result.body is None


def test_two_body_detectors_first_match_wins() -> None:
    """First matching body detector wins; second is never used."""
    param = _make_param("payload", dict)
    shape = _make_shape(params={"payload": param})

    # Second detector also matches dict but we verify first detector's result is used
    # by checking the body_type returned is dict (both would return dict here,
    # so we verify via object identity of the BodyDetection returned)
    call_log: list[str] = []

    class _LoggingBodyDetector:
        def __init__(self, tag: str) -> None:
            self._tag = tag

        def detect(self, param: ParameterShape, shape: HandlerShape) -> BodyDetection | None:
            call_log.append(self._tag)
            if param.annotation is dict:
                return BodyDetection(parameter=param, body_type=dict)
            return None

    first = _LoggingBodyDetector("first")
    second = _LoggingBodyDetector("second")

    result = run_detectors(shape, body_detectors=(first, second))

    assert result.body is not None
    # Only the first detector should have been called (first match stops iteration)
    assert call_log == ["first"]


def test_di_detector_matches_two_params() -> None:
    """DI detector that matches by annotation collects all matching params."""
    param_a = _make_param("db", str)
    param_b = _make_param("cache", str)
    shape = _make_shape(params={"db": param_a, "cache": param_b})

    result = run_detectors(
        shape,
        di_detectors=(_AnnotationDIDetector(str, "injected"),),
    )

    assert len(result.di_params) == 2
    detected_names = {d.parameter.name for d in result.di_params}
    assert detected_names == {"db", "cache"}
    for detection in result.di_params:
        assert detection.source == "injected"


def test_di_detector_no_match_empty_di_params() -> None:
    """When no param matches the DI detector, di_params is empty."""
    param = _make_param("x", int)
    shape = _make_shape(params={"x": param})

    result = run_detectors(
        shape,
        di_detectors=(_AnnotationDIDetector(str, "injected"),),
    )

    assert result.di_params == ()


def test_multiple_di_detectors_first_match_per_param_wins() -> None:
    """For each param, only the first matching DI detector's result is used."""
    param = _make_param("dep", str)
    shape = _make_shape(params={"dep": param})

    call_log: list[str] = []

    class _LoggingDIDetector:
        def __init__(self, tag: str, source: str) -> None:
            self._tag = tag
            self._source = source

        def detect(self, param: ParameterShape, shape: HandlerShape) -> DIDetection | None:
            call_log.append(self._tag)
            if param.annotation is str:
                return DIDetection(parameter=param, source=self._source)
            return None

    first = _LoggingDIDetector("first", "source_a")
    second = _LoggingDIDetector("second", "source_b")

    result = run_detectors(shape, di_detectors=(first, second))

    assert len(result.di_params) == 1
    assert result.di_params[0].source == "source_a"
    # Second detector should not have been called for this param
    assert call_log == ["first"]


def test_decorator_mapper_matches_one_decorator() -> None:
    """A decorator mapper that matches by name produces one DecoratorMapping."""
    capability = StubCapability(label="cache")
    dec = _make_decorator("cache_page")
    shape = _make_shape(decorators=(dec,))

    result = run_detectors(
        shape,
        decorator_mappers=(_NameDecoratorMapper("cache_page", capability),),
    )

    assert len(result.decorator_capabilities) == 1
    assert result.decorator_capabilities[0].decorator is dec
    assert result.decorator_capabilities[0].capability is capability


def test_decorator_mapper_no_match_empty_capabilities() -> None:
    """When the decorator name doesn't match, decorator_capabilities is empty."""
    capability = StubCapability(label="cache")
    dec = _make_decorator("login_required")
    shape = _make_shape(decorators=(dec,))

    result = run_detectors(
        shape,
        decorator_mappers=(_NameDecoratorMapper("cache_page", capability),),
    )

    assert result.decorator_capabilities == ()


def test_combined_body_di_decorator_all_matched() -> None:
    """All three detectors fire together and produce a fully populated DetectionResult."""
    body_param = _make_param("payload", dict)
    di_param = _make_param("db", str)
    capability = StubCapability(label="auth")
    dec = _make_decorator("login_required")

    shape = _make_shape(
        params={"payload": body_param, "db": di_param},
        decorators=(dec,),
    )

    result = run_detectors(
        shape,
        body_detectors=(_AnnotationBodyDetector(dict),),
        di_detectors=(_AnnotationDIDetector(str, "db_connection"),),
        decorator_mappers=(_NameDecoratorMapper("login_required", capability),),
    )

    # Body
    assert result.body is not None
    assert result.body.parameter is body_param
    assert result.body.body_type is dict

    # DI
    assert len(result.di_params) == 1
    assert result.di_params[0].parameter is di_param
    assert result.di_params[0].source == "db_connection"

    # Decorator
    assert len(result.decorator_capabilities) == 1
    assert result.decorator_capabilities[0].decorator is dec
    assert result.decorator_capabilities[0].capability is capability
