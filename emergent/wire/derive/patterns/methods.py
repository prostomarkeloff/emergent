"""Methods pattern — decorate methods with explicit triggers and capabilities.

Supports three calling conventions via standard Python descriptors:

- ``@classmethod`` + ``@post(...)`` — ``cls`` receives the entity class.
- ``@staticmethod`` + ``@post(...)`` — plain static function.
- ``@post(...)`` alone — instance method (``self`` is always ``None``).

Stack order: ``@classmethod`` / ``@staticmethod`` outermost, trigger innermost::

    @classmethod
    @post("/api/orders")
    async def create(cls, customer: str, total: float) -> Result[int, DomainError]:
        return Ok(new_id)

    @staticmethod
    @post("/api/health")
    async def health() -> Result[str, DomainError]:
        return Ok("ok")

Multi-target: stack trigger decorators for multiple exposures per method::

    @classmethod
    @post("/api/orders")
    @command("order-create")
    async def create(cls, ...) -> Result[int, DomainError]: ...

Transport-agnostic via @op + MethodDialect::

    @schema_meta(MethodDialect(triggers=HTTPTriggers("/api/orders")))
    @dataclass
    class OrderService:
        @classmethod
        @op("Create", effects=(Creates(),))
        async def create(cls, customer: str) -> Result[Order, DomainError]: ...
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, get_args, get_origin, get_type_hints

from kungfu import Error, Ok, Result

from emergent.wire.axis.schema._universal import SchemaCapability
from emergent.wire.axis.surface import Exposure, Trigger
from emergent.wire.axis.surface.capabilities import SurfaceCapability
from emergent.wire.axis.surface.codecs import rrc
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

from emergent.wire.derive._codegen import (
    FieldSpec,
    HasAnnotations,
    annotate_handler,
    create_dataclass,
    create_request_type,
    create_response_type,
)
from emergent.wire.derive._effects import DerivationEffect
from emergent.wire.derive._error_caps import ERROR_CAPS
from emergent.wire.derive._errors import DomainError

if TYPE_CHECKING:
    from emergent.wire.derive._ctx import DeriveCtx, Operation, OperationHandler
    from emergent.wire.derive._opspec import Op
    from emergent.wire.derive._trigger import TriggerGen

F = Callable[..., object]

TRIGGER_ENTRIES_ATTR = "__trigger_entries__"
OP_ENTRIES_ATTR = "__op_entry__"


# ═══════════════════════════════════════════════════════════════════════════════
# Trigger/Op entries
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class _TriggerEntry:
    """A single trigger + capabilities pair attached to a method."""

    trigger: Trigger
    capabilities: tuple[SurfaceCapability, ...]
    description: str | None = None
    order: int = 100


@dataclass(frozen=True, slots=True)
class _OpEntry:
    """Transport-agnostic operation metadata attached by @op."""

    name: str
    effects: tuple[DerivationEffect, ...] = ()
    capabilities: tuple[SurfaceCapability, ...] = ()


# ═══════════════════════════════════════════════════════════════════════════════
# Decorators
# ═══════════════════════════════════════════════════════════════════════════════


def method(
    trigger: Trigger,
    *capabilities: SurfaceCapability,
    description: str | None = None,
    order: int = 100,
) -> Callable[[F], F]:
    """Attach a trigger and optional capabilities to a method."""
    entry = _TriggerEntry(trigger, capabilities, description=description, order=order)

    def decorator(fn: F) -> F:
        entries: list[_TriggerEntry] = getattr(fn, TRIGGER_ENTRIES_ATTR, [])
        entries.append(entry)
        setattr(fn, TRIGGER_ENTRIES_ATTR, entries)
        return fn

    return decorator


def op(
    name: str | None = None,
    *,
    effects: tuple[DerivationEffect, ...] = (),
    caps: tuple[SurfaceCapability, ...] = (),
) -> Callable[[F], F]:
    """Mark a method as a transport-agnostic operation.

    Stores metadata (name, effects, capabilities) on the function.
    The actual trigger is assigned at compile time by ``MethodDialect``'s
    ``TriggerGen``.
    """

    def decorator(fn: F) -> F:
        entry = _OpEntry(
            name=name or fn.__name__,  # type: ignore[union-attr]
            effects=effects,
            capabilities=caps,
        )
        setattr(fn, OP_ENTRIES_ATTR, entry)
        return fn

    return decorator


# ─── HTTP aliases ─────────────────────────────────────────────────────


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


# ─── CLI alias ────────────────────────────────────────────────────────


def command(name: str, *caps: SurfaceCapability, description: str = "") -> Callable[[F], F]:
    """CLI subcommand *name*."""
    return method(CLITrigger(name, description), *caps)


# ═══════════════════════════════════════════════════════════════════════════════
# Trigger enhancement (TelegrindTrigger + CommandArg)
# ═══════════════════════════════════════════════════════════════════════════════

# TelegrindTrigger is optional — telegrinder may not be installed.
_TelegrindTrigger: type | None = None
try:
    from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger as _TT

    _TelegrindTrigger = _TT
except (ImportError, RuntimeError):
    pass


def _enhance_trigger_with_args(
    trigger: Trigger,
    fields: dict[str, type],
) -> Trigger:
    """Enhance TelegrindTrigger Command rule with Arguments from field annotations."""
    if _TelegrindTrigger is None or not isinstance(trigger, _TelegrindTrigger):
        return trigger

    from typing import Annotated

    from emergent.wire._telegrinder_compat import ABCRule as ABCRuleProto
    from emergent.wire.axis.schema.dialects.tg import CommandArg
    from emergent.wire.axis.surface.triggers.telegrinder import TelegrinderTrigger
    from telegrinder.bot.rules.command import Argument, Command

    # Re-narrow with concrete type so pyright sees .rules/.view
    if not isinstance(trigger, TelegrinderTrigger):
        return trigger

    args: list[Argument] = []
    has_greedy = False

    for fname, hint in fields.items():
        if get_origin(hint) is not Annotated:
            continue
        ann_args = get_args(hint)
        base_type = ann_args[0]
        for ann in ann_args[1:]:
            if isinstance(ann, CommandArg):
                validators: list[type] = []
                if base_type is int:
                    validators.append(int)
                args.append(Argument(name=fname, validators=validators, optional=ann.optional))
                if ann.greedy:
                    has_greedy = True
                break

    if not args:
        return trigger

    new_rules: list[ABCRuleProto] = []
    for rule in trigger.rules:
        if isinstance(rule, Command) and not rule.arguments:
            enhanced: ABCRuleProto = Command(
                rule.names,
                *args,
                prefixes=rule.prefixes,
                separator=rule.separator,
                lazy=has_greedy or rule.lazy,
                validate_mention=rule.validate_mention,
                ignore_case=rule.ignore_case,
            )
            new_rules.append(enhanced)
        else:
            new_rules.append(rule)

    return TelegrinderTrigger(*new_rules, view=trigger.view)


# ═══════════════════════════════════════════════════════════════════════════════
# Build method operation — method + trigger -> (OpType, handler, Exposure)
# ═══════════════════════════════════════════════════════════════════════════════


def _build_method_operation(
    service: type,
    method_name: str,
    trigger: Trigger,
    capabilities: tuple[SurfaceCapability, ...],
    suffix: str,
    description: str | None = None,
    order: int = 100,
) -> Operation[object, DomainError]:
    """Build (OpType, annotated_handler, Exposure) from a decorated method."""
    method_fn: Callable[..., object] = getattr(service, method_name)
    hints = get_type_hints(method_fn, include_extras=True)
    sig = inspect.signature(method_fn)

    raw_attr: Callable[..., object] = inspect.getattr_static(service, method_name)
    is_static = isinstance(raw_attr, staticmethod)
    is_classmethod = isinstance(raw_attr, classmethod)

    # Validate the method is async — sync methods will crash at await
    # Extract __func__ from classmethod/staticmethod descriptors
    _has_func = hasattr(raw_attr, "__func__")
    raw_fn: Callable[..., object] = getattr(raw_attr, "__func__") if _has_func else raw_attr
    if not inspect.iscoroutinefunction(raw_fn):
        raise TypeError(
            f"{service.__name__}.{method_name} must be async. "
            f"Use 'async def {method_name}(...)' instead of 'def {method_name}(...)'."
        )

    fields: dict[str, type] = {}
    params: list[str] = []
    for name in sig.parameters:
        if name in ("self", "cls"):
            continue
        fields[name] = hints[name]
        params.append(name)

    # We validated that raw_fn is a coroutine function above, so method_fn
    # (the bound/resolved version from getattr) returns Awaitable at runtime.
    # getattr returns object, which cannot express async — Callable[..., Awaitable[...]]
    # is the tightest annotation that preserves type safety without cast.
    _method_fn: Callable[..., Awaitable[Result[object, DomainError]]] = getattr(service, method_name)
    _params = params

    async def handler(op: object) -> Result[object, DomainError]:
        kw = {n: getattr(op, n) for n in _params}
        return (
            await _method_fn(**kw)
            if is_static or is_classmethod
            else await _method_fn(None, **kw)
        )

    op_name = f"{service.__name__}{method_name.title()}{suffix}"

    raw_return = hints["return"]
    result_args = get_args(raw_return) if get_origin(raw_return) is Result else None
    if result_args is None:
        raise TypeError(
            f"{service.__name__}.{method_name} must return Result[T, E], "
            f"got {raw_return}"
        )
    result_type = result_args[0]

    caps = capabilities
    if description is not None:
        from emergent.wire.axis.surface.dialects.telegram import HelpMeta

        caps = (*caps, HelpMeta(description=description, order=order))

    trigger = _enhance_trigger_with_args(trigger, fields)

    # Build Op type — ALL fields (compose.Node fields resolved by build_request)
    field_items: list[FieldSpec] = list(fields.items())
    op_type = create_dataclass(
        op_name + "Op",
        field_items,
        frozen=True,
    )

    # Build Request type — ALL fields (compose.Node handled by build_field_value)
    request_type = create_request_type(
        op_name + "Request",
        field_items,
        op_type,
    )

    # Build Response type
    response_fields_list: list[FieldSpec] = list(
        _result_type_fields(result_type).items()
    )

    _resp_field_names = list(_result_type_fields(result_type).keys())

    def converter(cls: type, result: Result[object, object]) -> HasAnnotations:
        match result:
            case Ok(val):
                if len(_resp_field_names) == 1 and not hasattr(val, _resp_field_names[0]):
                    return cls(**{_resp_field_names[0]: val})
                else:
                    return cls(**{f: getattr(val, f, None) for f in _resp_field_names})
            case Error(err):
                return err  # type: ignore[return-value]
            case _:
                raise TypeError(f"Expected Result, got {type(result)}")

    response_type = create_response_type(
        op_name + "Response",
        response_fields_list,
        converter,
    )

    # Build annotated handler
    annotated_handler: OperationHandler[object, DomainError] = annotate_handler(handler, op_type)

    # Build Exposure
    codec = rrc(request_type, response_type)
    exposure_obj = Exposure(trigger=trigger, codec=codec, capabilities=caps)

    return op_type, annotated_handler, exposure_obj


def _result_type_fields(result_type: type) -> dict[str, type]:
    """Extract fields from result type for response.

    If result_type is a dataclass, uses its fields. Otherwise treats as
    single ``result`` field.

    Uses get_type_hints() to resolve string annotations produced by
    ``from __future__ import annotations`` in the defining module.
    """
    import dataclasses

    if dataclasses.is_dataclass(result_type):
        hints = get_type_hints(result_type, include_extras=True)
        return {f.name: hints[f.name] for f in dataclasses.fields(result_type)}
    return {"result": result_type}


# ═══════════════════════════════════════════════════════════════════════════════
# Stub Op for MethodDialect's TriggerGen dispatch
# ═══════════════════════════════════════════════════════════════════════════════


def _stub_op(name: str, effects: tuple[DerivationEffect, ...]) -> Op:
    """Create a minimal Op for TriggerGen dispatch. Only .name and .effects matter."""
    from emergent.wire.derive._handler import HandlerSpec
    from emergent.wire.derive._opspec import Op
    from emergent.wire.derive._project import NoFields, OkResponse

    @dataclass(frozen=True, slots=True)
    class _NullTemplate:
        def build[EntityT](self, spec: HandlerSpec[EntityT]) -> OperationHandler[object, DomainError]:
            raise RuntimeError("_NullTemplate should never be called")

    return Op(
        name=name,
        input_proj=NoFields(),
        output=OkResponse(),
        handler_template=_NullTemplate(),
        effects=effects,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Methods — SchemaCapability (DeriveGeneratable)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Methods(SchemaCapability):
    """Scan class for @method-decorated methods, generate one operation per trigger.

        @schema_meta(Methods())
        @dataclass
        class MyService:
            @classmethod
            @post("/api/orders")
            async def create(cls, customer: str) -> Result[int, DomainError]: ...
    """

    capabilities: tuple[SurfaceCapability, ...] = ERROR_CAPS

    def compile_derive_generate[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        entity = ctx.entity

        for name in dir(entity):
            if name.startswith("_"):
                continue
            raw: Callable[..., object] | None = inspect.getattr_static(entity, name, None)
            if raw is None:
                continue
            _has_func = hasattr(raw, "__func__")
            fn: Callable[..., object] = getattr(raw, "__func__") if _has_func else raw

            entries: list[_TriggerEntry] = getattr(fn, TRIGGER_ENTRIES_ATTR, [])
            for i, entry in enumerate(entries):
                suffix = f"_{i}" if len(entries) > 1 else ""
                operation: Operation[object, DomainError] = _build_method_operation(
                    service=entity,
                    method_name=name,
                    trigger=entry.trigger,
                    capabilities=(*self.capabilities, *entry.capabilities),
                    suffix=suffix,
                    description=entry.description,
                    order=entry.order,
                )
                ctx = ctx.add_operation(operation)

        return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# MethodDialect — transport-agnostic SchemaCapability (DeriveGeneratable)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class MethodDialect(SchemaCapability):
    """Scan class for @op-decorated methods, assign triggers via TriggerGen.

    Like ``Methods`` but transport-agnostic: methods describe WHAT
    (name, effects) via ``@op``, the ``TriggerGen`` decides WHERE (trigger).

        @schema_meta(MethodDialect(triggers=HTTPTriggers("/api/orders")))
        @dataclass
        class OrderService:
            @classmethod
            @op("Create", effects=(Creates(),))
            async def create(cls, customer: str) -> Result[Order, DomainError]: ...
    """

    triggers: TriggerGen
    capabilities: tuple[SurfaceCapability, ...] = ERROR_CAPS

    def compile_derive_generate[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        entity = ctx.entity

        for method_name in dir(entity):
            if method_name.startswith("_"):
                continue
            raw: Callable[..., object] | None = inspect.getattr_static(entity, method_name, None)
            if raw is None:
                continue
            _has_func = hasattr(raw, "__func__")
            fn: Callable[..., object] = getattr(raw, "__func__") if _has_func else raw

            entry: _OpEntry | None = getattr(fn, OP_ENTRIES_ATTR, None)
            if entry is None:
                continue

            stub = _stub_op(entry.name, entry.effects)
            trigger = self.triggers(entity, stub)
            if trigger is None:
                continue

            operation: Operation[object, DomainError] = _build_method_operation(
                service=entity,
                method_name=method_name,
                trigger=trigger,
                capabilities=(*self.capabilities, *entry.capabilities),
                suffix="",
            )
            ctx = ctx.add_operation(operation)

        return ctx


methods = Methods()
"""Default methods capability with RFC 7807 error responses."""


__all__ = (
    # Decorators
    "method",
    "op",
    # HTTP aliases
    "post",
    "get",
    "put",
    "delete",
    "patch",
    # CLI alias
    "command",
    # Capabilities
    "Methods",
    "MethodDialect",
    "methods",
)
