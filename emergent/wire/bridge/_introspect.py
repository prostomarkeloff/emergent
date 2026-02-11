"""Handler introspection — PURE facts, no heuristics.

Core infrastructure for bridging. Provides ONLY factual introspection:
- Decorator chain unwrapping (via __wrapped__)
- Class method extraction
- Signature analysis
- Type extraction

NO semantic classification here. Bridger/capabilities decide what things mean.

    from emergent.wire.bridge._introspect import (
        analyze_handler,
        unwrap_handler,
        extract_class_methods,
        HandlerShape,
        ParameterShape,
        DecoratorInfo,
    )

    shape = analyze_handler(my_view)
    # Pure facts:
    print(shape.is_async)           # True/False
    print(shape.parameters["x"].annotation)  # the type
    print(shape.parameters["x"].default)     # the default value
    print(shape.decorators)         # decorator chain

Extensibility:
    # Custom unwrap strategy (for frameworks without __wrapped__)
    class PyramidUnwrap(UnwrapStrategy):
        def unwrap(self, obj): ...

    shape = analyze_handler(view, unwrap_strategy=PyramidUnwrap())

    # Skip self for bound Celery tasks
    shape = analyze_handler(task.run, skip_params=())  # Don't skip self
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from enum import Enum
from functools import partial
from typing import Callable, Iterator, Protocol, cast, get_type_hints, runtime_checkable


# ═══════════════════════════════════════════════════════════════════════════════
# Parameter Kind
# ═══════════════════════════════════════════════════════════════════════════════


class ParameterKind(Enum):
    """Parameter kind — from inspect."""

    POSITIONAL_ONLY = "positional_only"
    POSITIONAL_OR_KEYWORD = "positional_or_keyword"
    VAR_POSITIONAL = "var_positional"
    KEYWORD_ONLY = "keyword_only"
    VAR_KEYWORD = "var_keyword"

    @classmethod
    def of(cls, param: inspect.Parameter) -> ParameterKind:
        """Get ParameterKind from inspect.Parameter."""
        kind = param.kind
        if kind == inspect.Parameter.POSITIONAL_ONLY:
            return cls.POSITIONAL_ONLY
        elif kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
            return cls.POSITIONAL_OR_KEYWORD
        elif kind == inspect.Parameter.VAR_POSITIONAL:
            return cls.VAR_POSITIONAL
        elif kind == inspect.Parameter.KEYWORD_ONLY:
            return cls.KEYWORD_ONLY
        elif kind == inspect.Parameter.VAR_KEYWORD:
            return cls.VAR_KEYWORD
        else:
            return cls.POSITIONAL_OR_KEYWORD  # fallback


# ═══════════════════════════════════════════════════════════════════════════════
# Decorator Info
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class DecoratorInfo:
    """Factual info about a wrapper in decorator chain.

    Extracted by walking __wrapped__.
    """

    wrapper: Callable[..., object]  # The wrapper function itself
    wrapper_name: str
    wrapper_module: str | None


# ═══════════════════════════════════════════════════════════════════════════════
# Unwrap Strategy — extensible decorator unwrapping
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class UnwrapStrategy(Protocol):
    """Protocol for custom unwrap strategies.

    Default uses __wrapped__ chain. Bridgers can provide custom strategies
    for frameworks that don't use functools.wraps properly.

    Example (Pyramid with venusian):
        class PyramidUnwrap:
            def unwrap(self, obj):
                if hasattr(obj, "__venusian_callbacks__"):
                    # Extract from venusian metadata
                    ...
                return default_unwrap(obj)
    """

    def unwrap(
        self,
        obj: object,
    ) -> tuple[Callable[..., object], tuple[DecoratorInfo, ...]]:
        """Unwrap decorator chain.

        Returns (original_callable, decorator_infos).
        decorator_infos ordered outer-to-inner.
        """
        ...


def _unwrap_via_wrapped(
    obj: object,
) -> tuple[Callable[..., object], tuple[DecoratorInfo, ...]]:
    """Default unwrap: walk __wrapped__ chain."""
    if not callable(obj):
        raise TypeError(f"Expected callable, got {type(obj).__name__}")

    decorators: list[DecoratorInfo] = []
    current: Callable[..., object] = obj  # type: ignore[assignment]

    while hasattr(current, "__wrapped__"):
        decorators.append(
            DecoratorInfo(
                wrapper=current,
                wrapper_name=getattr(current, "__name__", "unknown"),
                wrapper_module=getattr(current, "__module__", None),
            )
        )
        current = current.__wrapped__  # type: ignore[attr-defined]

    return current, tuple(decorators)


def _unwrap_from_closure(
    obj: object,
) -> tuple[Callable[..., object], tuple[DecoratorInfo, ...]]:
    """Try to extract original from closure (for decorators w/o __wrapped__).

    Heuristic: looks for callable in closure that isn't the wrapper itself.
    Returns (obj, ()) if nothing found.
    """
    if not callable(obj):
        raise TypeError(f"Expected callable, got {type(obj).__name__}")

    wrapper: Callable[..., object] = obj  # type: ignore[assignment]

    if hasattr(wrapper, "__closure__") and wrapper.__closure__:
        for cell in wrapper.__closure__:
            try:
                content = cell.cell_contents
                if callable(content) and content is not wrapper:
                    # Found a callable in closure
                    decorator_info = DecoratorInfo(
                        wrapper=wrapper,
                        wrapper_name=getattr(wrapper, "__name__", "unknown"),
                        wrapper_module=getattr(wrapper, "__module__", None),
                    )
                    # Recursively try to unwrap further
                    inner, inner_decorators = _unwrap_via_wrapped(content)
                    return inner, (decorator_info,) + inner_decorators
            except ValueError:
                # Empty cell
                continue

    return wrapper, ()


class ClosureFallbackUnwrap:
    """Unwrap strategy: try __wrapped__, fallback to closure inspection."""

    def unwrap(
        self,
        obj: object,
    ) -> tuple[Callable[..., object], tuple[DecoratorInfo, ...]]:
        handler, decorators = _unwrap_via_wrapped(obj)
        if not decorators:
            # No __wrapped__ found, try closure
            return _unwrap_from_closure(obj)
        return handler, decorators


def unwrap_handler(
    obj: object,
    strategy: UnwrapStrategy | None = None,
) -> tuple[Callable[..., object], tuple[DecoratorInfo, ...]]:
    """Unwrap decorator chain.

    Args:
        obj: Callable to unwrap
        strategy: Custom unwrap strategy. Default uses __wrapped__ chain.

    Returns:
        (original_callable, decorator_infos) where decorator_infos ordered outer-to-inner.

    Example:
        # Default: walk __wrapped__
        handler, decorators = unwrap_handler(wrapped_func)

        # Custom strategy for frameworks without __wrapped__
        handler, decorators = unwrap_handler(view, strategy=PyramidUnwrap())

        # Try closure as fallback
        handler, decorators = unwrap_handler(view, strategy=ClosureFallbackUnwrap())
    """
    if strategy is not None:
        return strategy.unwrap(obj)
    return _unwrap_via_wrapped(obj)


# ═══════════════════════════════════════════════════════════════════════════════
# Class Method Extraction
# ═══════════════════════════════════════════════════════════════════════════════


def extract_class_methods(
    cls: type,
    method_names: tuple[str, ...],
) -> Iterator[tuple[str, Callable[..., object]]]:
    """Extract methods from class by name.

    Args:
        cls: Class to extract from
        method_names: Exact method names to look for

    Yields:
        (method_name, method) for each existing method
    """
    for name in method_names:
        method = getattr(cls, name, None)
        if method is not None and callable(method):
            yield name, method


def get_view_class(obj: object) -> type | None:
    """Get class from object if it's a class or has view_class attr."""
    if isinstance(obj, type):
        return obj
    if hasattr(obj, "view_class"):
        return obj.view_class  # type: ignore[attr-defined]
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Parameter Shape — PURE FACTS
# ═══════════════════════════════════════════════════════════════════════════════


# Sentinel for "no default"
_NO_DEFAULT = object()


@dataclass(frozen=True, slots=True)
class ParameterShape:
    """Pure factual parameter info. No semantic classification."""

    name: str
    annotation: type | None  # None if not annotated
    default: object  # _NO_DEFAULT if no default
    has_default: bool
    kind: ParameterKind

    @classmethod
    def from_parameter(
        cls,
        param: inspect.Parameter,
        resolved_annotation: type | None = None,
    ) -> ParameterShape:
        """Create from inspect.Parameter."""
        # Annotation
        annotation = resolved_annotation
        if annotation is None and param.annotation is not inspect.Parameter.empty:
            annotation = param.annotation

        # Default
        has_default = param.default is not inspect.Parameter.empty
        default = param.default if has_default else _NO_DEFAULT

        return cls(
            name=param.name,
            annotation=annotation,
            default=default,
            has_default=has_default,
            kind=ParameterKind.of(param),
        )


def no_default() -> object:
    """Sentinel for 'no default value'."""
    return _NO_DEFAULT


# ═══════════════════════════════════════════════════════════════════════════════
# Instance Info — for callable instances with __call__
# ═══════════════════════════════════════════════════════════════════════════════


def _empty_init_params() -> dict[str, ParameterShape]:
    return {}


@dataclass(frozen=True, slots=True)
class InstanceInfo:
    """Info about callable instance (if handler is instance with __call__).

    Useful for detecting DI in __init__ parameters.

    Example:
        class MyHandler:
            def __init__(self, db):  # DI here!
                self.db = db
            def __call__(self, request):
                return self.db.get_all()

        shape = analyze_handler(MyHandler(real_db))
        shape.instance_info.init_parameters["db"]  # ParameterShape for db
    """

    instance: object
    cls: type
    init_parameters: dict[str, ParameterShape] = field(
        default_factory=_empty_init_params
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Handler Shape — PURE FACTS
# ═══════════════════════════════════════════════════════════════════════════════


def _empty_params() -> dict[str, ParameterShape]:
    return {}


def _empty_decorators() -> tuple[DecoratorInfo, ...]:
    return ()


def _empty_partial_keywords() -> dict[str, object]:
    return {}


@dataclass(frozen=True, slots=True)
class HandlerShape:
    """Pure factual handler analysis. No semantic classification."""

    handler: Callable[..., object]  # The unwrapped handler
    name: str
    is_async: bool
    is_generator: bool
    parameters: dict[str, ParameterShape] = field(default_factory=_empty_params)
    return_type: type | None = None
    decorators: tuple[DecoratorInfo, ...] = field(default_factory=_empty_decorators)
    original: object = None  # type: ignore[assignment]
    source_file: str | None = None
    source_line: int | None = None
    # For callable instances
    instance_info: InstanceInfo | None = None
    # For functools.partial
    partial_func: Callable[..., object] | None = None
    partial_keywords: dict[str, object] = field(default_factory=_empty_partial_keywords)


# ═══════════════════════════════════════════════════════════════════════════════
# Descriptor Resolution
# ═══════════════════════════════════════════════════════════════════════════════


def resolve_descriptor(obj: object, owner: type | None = None) -> object:
    """If obj is a descriptor, resolve it to get the actual callable.

    Args:
        obj: Potential descriptor
        owner: Owner class for __get__ call

    Returns:
        Resolved object (or original if not a descriptor)
    """
    if hasattr(obj, "__get__") and not isinstance(obj, type):
        try:
            return obj.__get__(None, owner)  # type: ignore[union-attr]
        except Exception:
            pass
    return obj


# Default params to skip (self, cls for normal methods)
DEFAULT_SKIP_PARAMS: frozenset[str] = frozenset({"self", "cls"})




def analyze_handler(
    obj: object,
    *,
    unwrap_strategy: UnwrapStrategy | None = None,
    skip_params: frozenset[str] = DEFAULT_SKIP_PARAMS,
    resolve_descriptors: bool = True,
) -> HandlerShape:
    """Analyze handler — extract pure facts.

    NO heuristics. NO semantic classification.
    Just unwrap, inspect signature, extract types.

    Args:
        obj: Callable to analyze
        unwrap_strategy: Custom unwrap for frameworks without __wrapped__
        skip_params: Parameter names to skip (default: self, cls).
            Use empty frozenset for Celery bound tasks.
        resolve_descriptors: Whether to resolve descriptor protocol

    Returns:
        HandlerShape with factual info

    Example:
        # Normal usage
        shape = analyze_handler(my_view)

        # Celery bound task (don't skip self)
        shape = analyze_handler(task.run, skip_params=frozenset())

        # Custom unwrap for Pyramid
        shape = analyze_handler(view, unwrap_strategy=PyramidUnwrap())
    """
    original = obj

    # Resolve descriptor if enabled
    if resolve_descriptors:
        obj = resolve_descriptor(obj)

    # Handle functools.partial
    partial_func: Callable[..., object] | None = None
    partial_keywords: dict[str, object] = {}
    to_unwrap: object = obj

    if isinstance(obj, partial):
        # partial.func is typed as generic, we treat it as object for unwrapping
        underlying: object = obj.func
        # REASON FOR CAST: partial.func has type _T which becomes Unknown at runtime
        # introspection. We know it's callable, so cast to Callable is safe.
        partial_func = cast(Callable[..., object], obj.func)
        # obj.keywords is Mapping[str, Any], convert to dict[str, object]
        partial_keywords = {k: v for k, v in obj.keywords.items()}
        to_unwrap = underlying

    # Unwrap decorator chain
    handler, decorators = unwrap_handler(to_unwrap, strategy=unwrap_strategy)

    # Facts about the handler
    is_async = inspect.iscoroutinefunction(handler)
    is_generator = inspect.isgeneratorfunction(handler) or inspect.isasyncgenfunction(
        handler
    )

    # Detect callable instance (__call__ pattern)
    instance_info: InstanceInfo | None = None
    target_for_signature = handler

    if (
        not isinstance(handler, type)
        and hasattr(handler, "__call__")
        and not inspect.isfunction(handler)
        and not inspect.ismethod(handler)
        and not isinstance(handler, partial)
    ):
        # It's an instance with __call__
        cls = type(handler)
        try:
            init_sig = inspect.signature(cls.__init__)
            init_hints = {}
            try:
                init_hints = get_type_hints(cls.__init__)
            except Exception:
                pass

            init_params: dict[str, ParameterShape] = {}
            for pname, param in init_sig.parameters.items():
                if pname in skip_params:
                    continue
                resolved = init_hints.get(pname)
                init_params[pname] = ParameterShape.from_parameter(param, resolved)

            instance_info = InstanceInfo(
                instance=handler,
                cls=cls,
                init_parameters=init_params,
            )
            # Use __call__ for signature
            target_for_signature = handler.__call__  # type: ignore[union-attr]
        except Exception:
            pass

    # Signature
    try:
        sig = inspect.signature(target_for_signature)
    except (ValueError, TypeError):
        sig = None

    # Type hints with forward ref resolution
    try:
        hints = get_type_hints(target_for_signature)
    except Exception:
        hints = {}

    # Parameters
    parameters: dict[str, ParameterShape] = {}
    if sig is not None:
        for name, param in sig.parameters.items():
            if name in skip_params:
                continue
            # Skip params already bound in partial
            if name in partial_keywords:
                continue
            resolved = hints.get(name)
            parameters[name] = ParameterShape.from_parameter(param, resolved)

    # Return type
    return_type = hints.get("return")
    if return_type is None and sig is not None:
        if sig.return_annotation is not inspect.Signature.empty:
            return_type = sig.return_annotation

    # Source location (use target_for_signature as it's the actual function)
    source_file: str | None = None
    source_line: int | None = None
    try:
        source_file = inspect.getfile(target_for_signature)
        source_line = inspect.getsourcelines(target_for_signature)[1]
    except (TypeError, OSError):
        pass

    # Name
    name = (
        getattr(target_for_signature, "__name__", None)
        or getattr(original, "__name__", None)
        or "unknown"
    )

    # Construct result
    # REASON FOR CAST: Pyright's flow analysis creates complex union types
    # including partial[Unknown] from functools.partial introspection.
    # handler is verified callable by unwrap_handler, cast is safe.
    return HandlerShape(
        handler=cast(Callable[..., object], handler),
        name=name,
        is_async=is_async,
        is_generator=is_generator,
        parameters=parameters,
        return_type=return_type,
        decorators=decorators,
        original=original,
        source_file=source_file,
        source_line=source_line,
        instance_info=instance_info,
        partial_func=partial_func,
        partial_keywords=partial_keywords,
    )


__all__ = (
    # Parameter kind
    "ParameterKind",
    # Decorator
    "DecoratorInfo",
    # Unwrap strategies
    "UnwrapStrategy",
    "ClosureFallbackUnwrap",
    "unwrap_handler",
    # Class methods
    "extract_class_methods",
    "get_view_class",
    # Descriptor
    "resolve_descriptor",
    # Parameter
    "ParameterShape",
    "no_default",
    # Instance
    "InstanceInfo",
    # Handler
    "HandlerShape",
    "DEFAULT_SKIP_PARAMS",
    "analyze_handler",
)
