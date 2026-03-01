"""methods pattern — decorate methods with explicit triggers and capabilities.

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

Composition via .chain()::

    from derivelib.transforms import add_method_capability

    @derive(methods.chain(add_method_capability(AuthCap())))
    @dataclass
    class SecureService: ...

Custom capabilities (no RFC 7807)::

    @derive(MethodsPattern(capabilities=(MyErrorHandler(),)))
    @dataclass
    class CustomService: ...
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar, cast, get_args, get_origin, get_type_hints

from kungfu import Result

from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

# TelegrindTrigger is optional — telegrinder may not be installed.
_TelegrindTrigger: type | None = None
try:
    from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger as _TT
    _TelegrindTrigger = _TT
except (ImportError, RuntimeError):
    pass

from derivelib import (
    Derivation,
    Step,
    SurfaceCtx,
    derive,
    exposure,
)
from derivelib._derivation import DerivationT
from derivelib._dialect import Op, TriggerGen
from derivelib._effects import DerivationEffect
from derivelib._errors import DomainError
from derivelib.axes.schema import inspect_entity

F = TypeVar("F", bound=Callable[..., object])

TRIGGER_ENTRIES_ATTR = "__trigger_entries__"
OP_ENTRIES_ATTR = "__op_entry__"


# --- trigger entry: one decorator = one entry ---


@dataclass(frozen=True, slots=True)
class _TriggerEntry:
    """A single trigger + capabilities pair attached to a method."""

    trigger: object
    capabilities: tuple[SurfaceCapability, ...]
    description: str | None = None
    order: int = 100


# --- op entry: transport-agnostic operation metadata ---


@dataclass(frozen=True, slots=True)
class _OpEntry:
    """Transport-agnostic operation metadata attached by @op."""

    name: str
    effects: tuple[DerivationEffect, ...] = ()
    capabilities: tuple[SurfaceCapability, ...] = ()


# --- base decorator ---


def method(
    trigger: object,
    *capabilities: SurfaceCapability,
    description: str | None = None,
    order: int = 100,
) -> Callable[[F], F]:
    """Attach a trigger and optional capabilities to a method.

    Works with all three Python calling conventions:

    - ``@classmethod`` — ``cls`` is ``type[Self]`` (the entity class).
    - ``@staticmethod`` — plain static, no implicit first arg.
    - plain method — ``self`` is always ``None`` (entity is never instantiated).

    The trigger decorator goes *inside* ``@classmethod`` / ``@staticmethod``::

        @classmethod
        @post("/api/orders")
        async def create(cls, ...) -> Result[int, DomainError]: ...

        @staticmethod
        @post("/api/health")
        async def health() -> Result[str, DomainError]: ...

    Stacking multiple trigger decorators is supported::

        @classmethod
        @post("/api/orders")
        @command("order-create")
        async def create(cls, ...) -> Result[int, DomainError]: ...

    This is the base decorator. Use ``post``, ``get``, ``command``, etc.
    for convenience.
    """
    entry = _TriggerEntry(trigger, capabilities, description=description, order=order)

    def decorator(fn: F) -> F:
        entries: list[_TriggerEntry] = getattr(fn, TRIGGER_ENTRIES_ATTR, [])
        entries.append(entry)
        setattr(fn, TRIGGER_ENTRIES_ATTR, entries)
        return fn

    return cast(Callable[[F], F], decorator)


# --- transport-agnostic op decorator ---


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

    Can coexist with ``@post``/``@command`` — ``MethodsPattern`` reads effects
    from ``@op`` even when using explicit triggers.

        @classmethod
        @op("Create", effects=(Creates(),))
        async def create(cls, ...) -> Result[Order, DomainError]: ...
    """

    def decorator(fn: F) -> F:
        entry = _OpEntry(
            name=name or fn.__name__,
            effects=effects,
            capabilities=caps,
        )
        setattr(fn, OP_ENTRIES_ATTR, entry)
        return fn

    return cast(Callable[[F], F], decorator)


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


# --- trigger enhancement: add Arguments from tg.CommandArg annotations ---


def _enhance_trigger_with_args(
    trigger: object,
    fields: dict[str, type],
) -> object:
    """Enhance TelegrindTrigger Command rule with Arguments from field annotations.

    Inspects raw Annotated hints for tg.CommandArg() and builds Argument objects.
    Returns the original trigger unchanged if not a TelegrindTrigger or no args found.
    """
    if _TelegrindTrigger is None or not isinstance(trigger, _TelegrindTrigger):
        return trigger

    from typing import Annotated
    from emergent.wire.axis.schema.dialects.tg import CommandArg
    from telegrinder.bot.rules.command import Command, Argument
    from telegrinder.bot.rules.abc import ABCRule

    args: list[Argument] = []
    has_greedy = False

    for name, hint in fields.items():
        if get_origin(hint) is not Annotated:
            continue
        ann_args = get_args(hint)
        base_type = ann_args[0]
        for ann in ann_args[1:]:
            if isinstance(ann, CommandArg):
                validators: list[type] = []
                if base_type is int:
                    validators.append(int)
                args.append(Argument(name=name, validators=validators, optional=ann.optional))
                if ann.greedy:
                    has_greedy = True
                break

    if not args:
        return trigger

    new_rules: list[ABCRule] = []
    for rule in trigger.rules:
        if isinstance(rule, Command) and not rule.arguments:
            enhanced = Command(
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

    return _TelegrindTrigger(*new_rules, view=trigger.view)


# --- surface step: one method + one trigger -> one endpoint ---


@dataclass(frozen=True, slots=True)
class ExposeMethod:
    """Introspect method signature, build exposure with explicit trigger + caps.

    Capabilities = pattern-level + decorator-level, merged at compile time.
    Errors pass through the converter and are handled by capabilities
    (e.g. ErrorTransform + ProblemResponse).

    Satisfies TransformableStep — visible to effect-based transforms.
    """

    service: type
    method_name: str
    trigger: object
    capabilities: tuple[SurfaceCapability, ...]
    suffix: str
    description: str | None = None
    order: int = 100
    effects: tuple[DerivationEffect, ...] = ()

    @property
    def name(self) -> str:
        return f"{self.service.__name__}.{self.method_name}"

    def derive_surface[EntityT](self, ctx: SurfaceCtx[EntityT]) -> SurfaceCtx[EntityT]:
        method_fn = getattr(self.service, self.method_name)
        hints = get_type_hints(method_fn, include_extras=True)
        sig = inspect.signature(method_fn)

        fields: dict[str, type] = {}
        params: list[str] = []
        for name in sig.parameters:
            if name in ("self", "cls"):
                continue
            fields[name] = hints[name]
            params.append(name)

        _method_fn, _params = method_fn, params
        raw_attr = inspect.getattr_static(self.service, self.method_name)
        is_static = isinstance(raw_attr, staticmethod)
        is_classmethod = isinstance(raw_attr, classmethod)

        async def handler[OpT](op: OpT) -> Result[OpT, DomainError]:
            kw = {n: getattr(op, n) for n in _params}
            raw_result = (
                await _method_fn(**kw)
                if is_static or is_classmethod
                else await _method_fn(None, **kw)
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

        caps: tuple[SurfaceCapability, ...] = self.capabilities
        if self.description is not None:
            from emergent.wire.axis.surface.dialects.telegram import HelpMeta
            caps = (*caps, HelpMeta(description=self.description, order=self.order))

        trigger = _enhance_trigger_with_args(self.trigger, fields)

        builder = (
            exposure(op_name, self.service)
            .request(**fields)
            .handler(handler)
            .trigger(trigger)
            .caps(*caps)
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
        # TG delegate support is optional — telegrinder may not be installed
        # or may fail at import time (e.g. Python 3.14+ asyncio changes).
        _delegate_imports: tuple[str, type, type] | None = None
        try:
            from teleflow.methods import (
                DELEGATE_ENTRIES_ATTR,
                ExposeDelegateMethod,
                _DelegateEntry,
            )
            _delegate_imports = (DELEGATE_ENTRIES_ATTR, ExposeDelegateMethod, _DelegateEntry)
        except (ImportError, RuntimeError):
            pass

        steps: list[Step] = [inspect_entity()]
        for name in dir(entity):
            if name.startswith("_"):
                continue
            raw = inspect.getattr_static(entity, name, None)
            if raw is None:
                continue
            # Unwrap classmethod/staticmethod to find trigger entries
            fn = raw.__func__ if isinstance(raw, (classmethod, staticmethod)) else raw

            # Read @op entry for effects (used by both trigger and MethodDialect paths)
            op_entry: _OpEntry | None = getattr(fn, OP_ENTRIES_ATTR, None)
            op_effects = op_entry.effects if op_entry is not None else ()

            # Standard trigger entries → ExposeMethod (RRC codec)
            entries: list[_TriggerEntry] = getattr(fn, TRIGGER_ENTRIES_ATTR, [])
            for i, entry in enumerate(entries):
                suffix = f"_{i}" if len(entries) > 1 else ""
                steps.append(
                    ExposeMethod(
                        service=entity,
                        method_name=name,
                        trigger=entry.trigger,
                        capabilities=(*self.capabilities, *entry.capabilities),
                        suffix=suffix,
                        description=entry.description,
                        order=entry.order,
                        effects=op_effects,
                    )
                )

            # Delegate entries → ExposeDelegateMethod (DelegateCodec)
            if _delegate_imports is not None:
                delegate_attr, DelegateStep, DelegateEntry = _delegate_imports
                delegate_entries: list[object] = getattr(fn, delegate_attr, [])
                for entry in delegate_entries:
                    assert isinstance(entry, DelegateEntry)
                    steps.append(
                        DelegateStep(
                            service=entity,
                            method_name=name,
                            trigger=entry.trigger,
                            capabilities=(*self.capabilities, *entry.capabilities),
                            description=entry.description,
                            order=entry.order,
                        )
                    )
        return tuple(steps)


# --- stub Op for MethodDialect's TriggerGen dispatch ---


@dataclass(frozen=True, slots=True)
class _NullTemplate:
    """Sentinel — never called. Exists only to satisfy Op's required field."""

    def build(self, spec: object) -> object:
        raise RuntimeError("_NullTemplate should never be called")


def _stub_op(name: str, effects: tuple[DerivationEffect, ...]) -> Op:
    """Create a minimal Op for TriggerGen dispatch. Only .name and .effects matter."""
    from derivelib._project import NoFields, OkResponse

    return Op(
        name=name,
        input_proj=NoFields(),
        output=OkResponse(),
        handler_template=_NullTemplate(),
        effects=effects,
    )


# --- transport-agnostic method dialect ---


@dataclass(frozen=True, slots=True)
class MethodDialect:
    """Scan class for @op-decorated methods, assign triggers via TriggerGen.

    Like ``MethodsPattern`` but transport-agnostic: methods describe WHAT
    (name, effects) via ``@op``, the ``TriggerGen`` decides WHERE (trigger).

    ``@op`` name controls route generation:

    - Well-known names (``Create``, ``Get``, ``List``, ``Update``, ``Delete``)
      map to standard REST routes via ``HTTPTriggers``.
    - Custom names become ``POST /base/{name_lower}``.
    - Override via ``HTTPTriggers(routes={...})`` for full control.

    ::

        @derive(MethodDialect(triggers=HTTPTriggers("/api/orders"), capabilities=ERROR_CAPS))
        @dataclass
        class OrderService:
            @classmethod
            @op("Create", effects=(Creates(),))
            async def create(cls, customer: str) -> Result[Order, DomainError]: ...

            @classmethod
            @op("Get", effects=(Read(),))
            async def get_order(cls, id: int) -> Result[Order, DomainError]: ...

            @classmethod
            @op("Submit", effects=(Mutation(),))
            async def submit(cls, id: int) -> Result[Order, DomainError]: ...

        # Produces:
        #   POST /api/orders           (Create → REST default)
        #   GET  /api/orders/{id}      (Get → REST default)
        #   POST /api/orders/submit    (Submit → unknown → POST fallback)

    Multi-target — same service on HTTP + CLI::

        @derive(
            MethodDialect(triggers=HTTPTriggers("/api/orders"), capabilities=ERROR_CAPS),
            MethodDialect(triggers=CLITriggers("order")),
        )

    Composable via .chain()::

        MethodDialect(triggers=HTTPTriggers("/api"), capabilities=ERROR_CAPS).chain(
            readonly(),
            add_capability(AuthCap(), Mutation),
        )
    """

    triggers: TriggerGen
    capabilities: tuple[SurfaceCapability, ...] = ()

    def chain(self, *transforms: DerivationT) -> ChainedPattern:
        """Chain DerivationT transforms after compile."""
        from derivelib._dialect import ChainedPattern

        return ChainedPattern(self, transforms)

    def compile(self, entity: type) -> Derivation:
        steps: list[Step] = [inspect_entity()]
        for method_name in dir(entity):
            if method_name.startswith("_"):
                continue
            raw = inspect.getattr_static(entity, method_name, None)
            if raw is None:
                continue
            fn = raw.__func__ if isinstance(raw, (classmethod, staticmethod)) else raw

            entry: _OpEntry | None = getattr(fn, OP_ENTRIES_ATTR, None)
            if entry is None:
                continue

            stub = _stub_op(entry.name, entry.effects)
            trigger = self.triggers(entity, stub)
            if trigger is None:
                continue

            steps.append(
                ExposeMethod(
                    service=entity,
                    method_name=method_name,
                    trigger=trigger,
                    capabilities=(*self.capabilities, *entry.capabilities),
                    suffix="",
                    effects=entry.effects,
                )
            )
        return tuple(steps)


# Lazy import to avoid circular dependency at module level
from derivelib._dialect import ChainedPattern as ChainedPattern  # noqa: E402, F401

from derivelib._error_caps import ERROR_CAPS  # noqa: E402

methods = MethodsPattern(capabilities=ERROR_CAPS)
"""Default methods pattern with RFC 7807 error responses: ``@derive(methods)``."""


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
    # Step
    "ExposeMethod",
    # Patterns
    "MethodsPattern",
    "MethodDialect",
    "methods",
)
