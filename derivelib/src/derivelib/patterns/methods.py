"""methods pattern — decorate methods with explicit triggers and capabilities.

Write async methods. Decorate each with its trigger. Get endpoints.

    from derivelib import derive
    from derivelib.patterns.methods import methods, post, get

    @derive(methods)
    @dataclass
    class OrderService:
        @post("/api/orders")
        async def create(self, customer: str, total: float) -> Result[int, DomainError]:
            return Ok(new_id)

        @get("/api/orders")
        async def list_all(self) -> Result[list[Order], DomainError]:
            ...

Multi-target: stack decorators for multiple exposures per method:

    @post("/api/orders")
    @command("order-create")
    async def create(self, ...) -> Result[int, DomainError]: ...

Composition via .chain():

    from derivelib.transforms import add_method_capability

    @derive(methods.chain(add_method_capability(AuthCap())))
    @dataclass
    class SecureService: ...

Custom capabilities (no RFC 7807):

    @derive(MethodsPattern(capabilities=(MyErrorHandler(),)))
    @dataclass
    class CustomService: ...
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar, get_args, get_origin, get_type_hints

from kungfu import Result

from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

from derivelib import (
    Derivation,
    Step,
    SurfaceCtx,
    derive,
    exposure,
)
from derivelib._derivation import DerivationT
from derivelib._errors import DomainError
from derivelib.axes.schema import inspect_entity

F = TypeVar("F", bound=Callable[..., object])

TRIGGER_ENTRIES_ATTR = "__trigger_entries__"


# --- trigger entry: one decorator = one entry ---


@dataclass(frozen=True, slots=True)
class _TriggerEntry:
    """A single trigger + capabilities pair attached to a method."""

    trigger: object
    capabilities: tuple[SurfaceCapability, ...]


# --- base decorator ---


def method(trigger: object, *capabilities: SurfaceCapability) -> Callable[[F], F]:
    """Attach a trigger and optional capabilities to a method.

    This is the base decorator. Use ``post``, ``get``, ``command``, etc.
    for convenience.
    """
    entry = _TriggerEntry(trigger, capabilities)

    def decorator(fn: F) -> F:
        entries: list[_TriggerEntry] = getattr(fn, TRIGGER_ENTRIES_ATTR, [])
        entries.append(entry)
        setattr(fn, TRIGGER_ENTRIES_ATTR, entries)
        return fn

    return decorator


# --- HTTP aliases ---


def post(path: str, *caps: SurfaceCapability) -> Callable[[F], F]:
    """POST endpoint at *path*."""
    return method(HTTPRouteTrigger("POST", path), *caps)


def get(path: str, *caps: SurfaceCapability) -> Callable[[F], F]:
    """GET endpoint at *path*."""
    return method(HTTPRouteTrigger("GET", path), *caps)


def put(path: str, *caps: SurfaceCapability) -> Callable[[F], F]:
    """PUT endpoint at *path*."""
    return method(HTTPRouteTrigger("PUT", path), *caps)


def delete(path: str, *caps: SurfaceCapability) -> Callable[[F], F]:
    """DELETE endpoint at *path*."""
    return method(HTTPRouteTrigger("DELETE", path), *caps)


def patch(path: str, *caps: SurfaceCapability) -> Callable[[F], F]:
    """PATCH endpoint at *path*."""
    return method(HTTPRouteTrigger("PATCH", path), *caps)


# --- CLI alias ---


def command(name: str, *caps: SurfaceCapability, description: str = "") -> Callable[[F], F]:
    """CLI subcommand *name*."""
    return method(CLITrigger(name, description), *caps)


# --- surface step: one method + one trigger -> one endpoint ---


@dataclass(frozen=True, slots=True)
class ExposeMethod:
    """Introspect method signature, build exposure with explicit trigger + caps.

    Capabilities = pattern-level + decorator-level, merged at compile time.
    Errors pass through the converter and are handled by capabilities
    (e.g. ErrorTransform + ProblemResponse).
    """

    service: type
    method_name: str
    trigger: object
    capabilities: tuple[SurfaceCapability, ...]
    suffix: str

    def derive_surface[EntityT](self, ctx: SurfaceCtx[EntityT]) -> SurfaceCtx[EntityT]:
        method_fn = getattr(self.service, self.method_name)
        hints = get_type_hints(method_fn, include_extras=True)
        sig = inspect.signature(method_fn)

        fields: dict[str, type] = {}
        params: list[str] = []
        for name in sig.parameters:
            if name == "self":
                continue
            fields[name] = hints[name]
            params.append(name)

        _method_fn, _params = method_fn, params
        is_static = isinstance(
            inspect.getattr_static(self.service, self.method_name), staticmethod
        )

        async def handler[OpT](op: OpT) -> Result[OpT, DomainError]:
            kw = {n: getattr(op, n) for n in _params}
            raw_result = (
                await _method_fn(**kw) if is_static else await _method_fn(None, **kw)
            )
            return raw_result

        op_name = f"{self.service.__name__}{self.method_name.title()}{self.suffix}"
        raw_return = hints["return"]

        result_args = get_args(raw_return) if get_origin(raw_return) is Result else None
        if result_args is None:
            raise TypeError(
                f"{self.service.__name__}.{self.method_name} must return Result[T, E], "
                f"got {raw_return}"
            )
        result_type = result_args[0]

        builder = (
            exposure(op_name, self.service)
            .request(**fields)
            .handler(handler)
            .trigger(self.trigger)
            .caps(*self.capabilities)
            .response(result=result_type)
        )

        return ctx.add_exposure(builder)


# --- the pattern ---


@dataclass(frozen=True, slots=True)
class MethodsPattern:
    """Scan class for @method-decorated methods, generate one exposure per trigger entry.

    Consistent with Dialect: has capabilities and .chain().

        methods = MethodsPattern(capabilities=ERROR_CAPS)  # default
        MethodsPattern()                                    # no error caps
        methods.chain(add_method_capability(AuthCap()))     # composable
    """

    capabilities: tuple[SurfaceCapability, ...] = ()

    def chain(self, *transforms: DerivationT) -> ChainedPattern:
        """Chain DerivationT transforms after compile.

        Returns a new Pattern that compiles this pattern then applies transforms.

            methods.chain(add_method_capability(AuthCap()))
        """
        from derivelib._dialect import ChainedPattern
        return ChainedPattern(self, transforms)

    def compile(self, entity: type) -> Derivation:
        steps: list[Step] = [inspect_entity()]
        for name in dir(entity):
            if name.startswith("_"):
                continue
            attr = getattr(entity, name, None)
            if attr is None:
                continue
            entries: list[_TriggerEntry] = getattr(attr, TRIGGER_ENTRIES_ATTR, [])
            if not entries:
                continue
            for i, entry in enumerate(entries):
                suffix = f"_{i}" if len(entries) > 1 else ""
                steps.append(
                    ExposeMethod(
                        service=entity,
                        method_name=name,
                        trigger=entry.trigger,
                        capabilities=(*self.capabilities, *entry.capabilities),
                        suffix=suffix,
                    )
                )
        return tuple(steps)


# Lazy import to avoid circular dependency at module level
from derivelib._dialect import ChainedPattern as ChainedPattern  # noqa: E402, F401

from derivelib._error_caps import ERROR_CAPS  # noqa: E402

methods = MethodsPattern(capabilities=ERROR_CAPS)
"""Default methods pattern with RFC 7807 error responses: ``@derive(methods)``."""


__all__ = (
    # Base decorator
    "method",
    # HTTP aliases
    "post",
    "get",
    "put",
    "delete",
    "patch",
    # CLI alias
    "command",
    # Step
    "ExposeMethod",
    # Pattern
    "MethodsPattern",
    "methods",
)
