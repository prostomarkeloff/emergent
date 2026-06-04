"""Exposure and Endpoint builders — declarative API for pattern authoring.

Used INSIDE compile_derive_generate to build operations without OpSpec.
For hand-crafted patterns that bypass the OpSpec pipeline.

    from emergent.wire.derive._builders import exposure, endpoint_builder

    op, handler, exp = (
        exposure("create", Order)
        .request(customer=str, total=float)
        .response(id=int, state=str)
        .handler(lambda op: ...)
        .trigger(HTTPRouteTrigger("POST", "/orders"))
        .build()
    )
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Never

from emergent.wire.derive._codegen import (
    HasAnnotations,
    annotate_handler,
    create_dataclass,
    create_request_type,
    create_response_type,
)

if TYPE_CHECKING:
    from emergent.wire.axis.surface import Endpoint, Trigger
    from emergent.wire.axis.surface.capabilities import SurfaceCapability
    from kungfu import Result

    from emergent.wire.derive._codegen import FieldSpec
    from emergent.wire.derive._ctx import Operation, OperationHandler
    from emergent.wire.derive._project import ResponseConverter


@dataclass(frozen=True, slots=True)
class ExposureBuilder[T, E]:
    """Declarative builder for Exposure (Trigger x Codec x Capabilities).

        op_type, handler, exp = (
            exposure("create", Order)
            .request(customer=str, total=float)
            .response(id=int, state=str)
            .handler(my_handler)
            .trigger(HTTPRouteTrigger("POST", "/orders"))
            .build()
        )
    """

    _name: str
    _entity: type
    _request_fields: dict[str, type]
    _response_fields: dict[str, type | tuple[type, int | str | float | bool | None]]
    _handler: OperationHandler[T, E] | None
    _trigger: Trigger | None
    _capabilities: tuple[SurfaceCapability, ...]
    _response_converter: ResponseConverter | None

    def request(self, **fields: type) -> ExposureBuilder[T, E]:
        return replace(self, _request_fields=fields)

    def response(
        self, **fields: type | tuple[type, int | str | float | bool | None]
    ) -> ExposureBuilder[T, E]:
        return replace(self, _response_fields=fields)

    def handler[NewT, NewE](
        self, fn: OperationHandler[NewT, NewE]
    ) -> ExposureBuilder[NewT, NewE]:
        return ExposureBuilder(
            _name=self._name,
            _entity=self._entity,
            _request_fields=self._request_fields,
            _response_fields=self._response_fields,
            _handler=fn,
            _trigger=self._trigger,
            _capabilities=self._capabilities,
            _response_converter=self._response_converter,
        )

    def trigger(self, t: Trigger) -> ExposureBuilder[T, E]:
        return replace(self, _trigger=t)

    def caps(self, *capabilities: SurfaceCapability) -> ExposureBuilder[T, E]:
        return replace(self, _capabilities=(*self._capabilities, *capabilities))

    def response_converter(self, converter: ResponseConverter) -> ExposureBuilder[T, E]:
        return replace(self, _response_converter=converter)

    def build(self) -> Operation[T, E]:
        if self._trigger is None:
            raise ValueError(f"Trigger not set for operation '{self._name}'")
        if self._handler is None:
            raise ValueError(f"Handler not set for operation '{self._name}'")

        op_type = create_dataclass(
            f"{self._entity.__name__}{self._name.title()}Op",
            list(self._request_fields.items()),
            frozen=True,
        )

        request_type = create_request_type(
            f"{self._name.title()}Request",
            list(self._request_fields.items()),
            op_type,
        )

        response_field_specs: list[FieldSpec] = []
        for name, spec in self._response_fields.items():
            if isinstance(spec, tuple):
                response_field_specs.append((name, spec[0], spec[1]))
            else:
                response_field_specs.append((name, spec))

        if self._response_converter is not None:
            converter = self._response_converter
        else:
            _fields = list(self._response_fields.keys())

            def converter[U, V](cls: type, result: Result[U, V]) -> HasAnnotations:
                from kungfu import Error, Ok

                match result:
                    case Ok(val):
                        if len(_fields) == 1 and not hasattr(val, _fields[0]):
                            return cls(**{_fields[0]: val})
                        else:
                            return cls(**{f: getattr(val, f, None) for f in _fields})
                    case Error(err):
                        return err
                    case _:
                        raise TypeError(f"Expected Result, got {type(result)}")

        response_type = create_response_type(
            f"{self._name.title()}Response",
            response_field_specs,
            converter,
        )

        annotated_handler = annotate_handler(self._handler, op_type)

        from emergent.wire.axis.surface import Exposure as _Exposure
        from emergent.wire.axis.surface.codecs import rrc

        codec = rrc(request_type, response_type)
        exposure_obj = _Exposure(
            trigger=self._trigger,
            codec=codec,
            capabilities=tuple(self._capabilities),
        )

        return (op_type, annotated_handler, exposure_obj)


def exposure(name: str, entity: type) -> ExposureBuilder[Never, Never]:
    """Create ExposureBuilder for an operation."""
    return ExposureBuilder(
        _name=name,
        _entity=entity,
        _request_fields={},
        _response_fields={},
        _handler=None,
        _trigger=None,
        _capabilities=(),
        _response_converter=None,
    )


class EndpointBuilder:
    """Builder for Endpoint (Runner + multiple Exposures)."""

    def build[T, E](self, operations: list[Operation[T, E]]) -> Endpoint:
        from emergent.ops import ops as ops_builder
        from emergent.wire.axis.surface import Endpoint as _Endpoint
        from emergent.wire.axis.surface import Exposure as _Exposure

        builder = ops_builder()
        exposures: list[_Exposure] = []

        for op_type, handler, exposure_obj in operations:
            builder = builder.on(op_type, handler)
            exposures.append(exposure_obj)

        runner = builder.compile()
        return _Endpoint(runner=runner, exposures=tuple(exposures))


def endpoint_builder() -> EndpointBuilder:
    return EndpointBuilder()


__all__ = (
    "ExposureBuilder",
    "exposure",
    "EndpointBuilder",
    "endpoint_builder",
)
