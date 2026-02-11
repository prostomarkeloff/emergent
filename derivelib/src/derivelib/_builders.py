"""Exposure and Endpoint builders — declarative API for pattern authoring.

Used INSIDE pattern.compile() to build operations without DeriveOp.
For hand-crafted patterns that bypass the dialect/fold pipeline.

    from derivelib._builders import exposure, endpoint_builder

    op, handler, exp = (
        exposure("create", Order)
        .request(customer=str, total=float)
        .response(id=int, state=str)
        .handler(lambda op, prov: prov.insert(Order(...)))
        .trigger(HTTPRouteTrigger("POST", "/orders"))
        .build()
    )
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Never

from derivelib._codegen import (
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

    from derivelib._codegen import FieldSpec
    from derivelib._ctx import Operation, OperationHandler
    from derivelib._project import ResponseConverter


# ═══════════════════════════════════════════════════════════════════════════════
# ExposureBuilder — Declarative API for single operation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ExposureBuilder[T, E]:
    """Declarative builder for Exposure (Trigger x Codec x Capabilities).

    Used INSIDE pattern.compile() to eliminate boilerplate.

    Example:
        op_type, handler, exp = (
            exposure("create", Order)
            .request(customer=str, total=float)
            .response(id=int, state=str)
            .handler(lambda op, prov: prov.insert(Order(...)))
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
        """Define request fields."""
        return replace(self, _request_fields=fields)

    def response(self, **fields: type | tuple[type, int | str | float | bool | None]) -> ExposureBuilder[T, E]:
        """Define response fields (with optional defaults)."""
        return replace(self, _response_fields=fields)

    def handler[NewT, NewE](self, fn: OperationHandler[NewT, NewE]) -> ExposureBuilder[NewT, NewE]:
        """Set handler function — fixes T, E for the builder chain."""
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
        """Set trigger (wire-level, can be HTTP/CLI/Telegram/any)."""
        return replace(self, _trigger=t)

    def caps(self, *capabilities: SurfaceCapability) -> ExposureBuilder[T, E]:
        """Add capabilities (wire-level)."""
        return replace(self, _capabilities=(*self._capabilities, *capabilities))

    def response_converter(self, converter: ResponseConverter) -> ExposureBuilder[T, E]:
        """Custom response converter (Result[T, E] -> Response)."""
        return replace(self, _response_converter=converter)

    def build(self) -> Operation[T, E]:
        """Build Op type, handler, and Exposure.

        Returns:
            (OpType, annotated_handler, Exposure)
        """
        if self._trigger is None:
            raise ValueError(f"Trigger not set for operation '{self._name}'")
        if self._handler is None:
            raise ValueError(f"Handler not set for operation '{self._name}'")

        # Create Op Type
        OpType = create_dataclass(
            f"{self._entity.__name__}{self._name.title()}Op",
            list(self._request_fields.items()),
            frozen=True,
        )

        # Create Request Type (with to_domain baked in)
        RequestType = create_request_type(
            f"{self._name.title()}Request",
            list(self._request_fields.items()),
            OpType,
        )

        # Build response field specs (support (type, default) tuples)
        response_field_specs: list[FieldSpec] = []
        for name, spec in self._response_fields.items():
            if isinstance(spec, tuple):
                response_field_specs.append((name, spec[0], spec[1]))
            else:
                response_field_specs.append((name, spec))

        # Build converter
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

        # Create Response Type (with from_domain baked in)
        ResponseType = create_response_type(
            f"{self._name.title()}Response",
            response_field_specs,
            converter,
        )

        # Annotate handler
        annotated_handler = annotate_handler(self._handler, OpType)

        # Create Exposure
        from emergent.wire.axis.surface import Exposure as _Exposure
        from emergent.wire.axis.surface.codecs import rrc

        codec = rrc(RequestType, ResponseType)
        exposure_obj = _Exposure(
            trigger=self._trigger,
            codec=codec,
            capabilities=tuple(self._capabilities),
        )

        return (OpType, annotated_handler, exposure_obj)


def exposure(name: str, entity: type) -> ExposureBuilder[Never, Never]:
    """Create ExposureBuilder for an operation.

    Args:
        name: Operation name (e.g., "create", "update")
        entity: Entity type (used for naming Op types)

    Returns:
        ExposureBuilder for chaining — T, E determined by .handler() call.
    """
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


# ═══════════════════════════════════════════════════════════════════════════════
# EndpointBuilder — Compose operations into Endpoint
# ═══════════════════════════════════════════════════════════════════════════════


class EndpointBuilder:
    """Builder for Endpoint (Runner + multiple Exposures).

    Used INSIDE pattern.compile() to compose operations.
    """

    def build[T, E](self, operations: list[Operation[T, E]]) -> Endpoint:
        """Build Endpoint from operations."""
        from emergent.ops import ops as ops_builder
        from emergent.wire.axis.surface import Endpoint as _Endpoint
        from emergent.wire.axis.surface import Exposure as _Exposure

        builder = ops_builder()
        exposures: list[_Exposure] = []

        for op_type, handler, exposure_obj in operations:
            builder = builder.on(op_type, handler)
            exposures.append(exposure_obj)

        runner = builder.compile()
        return _Endpoint(runner=runner, exposures=exposures)


def endpoint_builder() -> EndpointBuilder:
    """Create EndpointBuilder."""
    return EndpointBuilder()


__all__ = (
    "ExposureBuilder",
    "exposure",
    "EndpointBuilder",
    "endpoint_builder",
)
