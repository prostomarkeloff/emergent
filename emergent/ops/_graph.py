"""
Ops — data-driven dispatch with automatic parallelization via nodnod.

Core idea:
- Op[T, E] is base class for operations
- Handlers are converted to nodnod nodes
- nodnod builds dependency graph and executes in parallel
- await op.get() returns cached result (already computed by nodnod)

Example:
    @dataclass(frozen=True, slots=True)
    class GetPrice(Op[float, str]):
        product_id: int

    @dataclass(frozen=True, slots=True)
    class BuildSummary(Op[str, str]):
        product_id: int
        price: GetPrice    # Dependency
        stock: GetStock    # Dependency

    async def build_summary(
        req: BuildSummary,
        price: GetPrice,    # Op with .get() → cached Result
        stock: GetStock,    # Op with .get() → cached Result
    ) -> Result[str, str]:
        p = await price  # instant — already computed by nodnod
        s = await stock  # instant — already computed by nodnod
        ...

    runner = ops().on(GetPrice, get_price).on(BuildSummary, build_summary).compile()
    result = await runner.run(BuildSummary(...))  # GetPrice & GetStock run in parallel
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field, fields
from typing import Any, TypeVar, Callable, Awaitable, Generic, get_type_hints, cast
from abc import ABC

from kungfu import Result, Ok, Error, LazyCoroResult, Some

from nodnod import Node, EventLoopAgent
from nodnod.utils.create_node import create_node

from emergent import graph as G

T = TypeVar("T")
E = TypeVar("E")
T_co = TypeVar("T_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)

HandlerFunc = Callable[..., Awaitable[Result[Any, Any]]]


class Op(ABC, Generic[T_co, E_co]):
    """
    Base class for operations.

    Provides .get() and __await__ for accessing cached results.
    """

    def get(self) -> LazyCoroResult[T_co, E_co]:
        """Get cached result (set by runner after nodnod execution)."""
        raise RuntimeError(
            f"Operation {type(self).__name__} not bound. "
            "Did you forget to register handler via .on()?"
        )

    def __await__(self):
        return self.get().__await__()


def _is_op_type(typ: object) -> bool:
    """Check if type is an Op subclass."""
    try:
        return isinstance(typ, type) and issubclass(typ, Op)
    except TypeError:
        return False


@dataclass(frozen=True, slots=True)
class _OpReg:
    """Registration: Op type → handler + node."""
    op_type: type[Op[Any, Any]]
    handler: HandlerFunc
    node_cls: type[Node[Any, Any]]


class _CachedOp(Generic[T_co, E_co]):
    """
    Op wrapper with pre-computed result.

    .get() and __await__ return the cached Result instantly.
    """
    __slots__ = ("_result",)

    def __init__(self, result: Result[T_co, E_co]) -> None:
        object.__setattr__(self, "_result", result)

    def get(self) -> LazyCoroResult[T_co, E_co]:
        """Return cached result instantly."""
        result: Result[T_co, E_co] = object.__getattribute__(self, "_result")

        async def instant() -> Result[T_co, E_co]:
            return result

        return LazyCoroResult(instant)

    def __await__(self):
        return self.get().__await__()


def _create_node_for_handler(
    op_type: type[Op[Any, Any]],
    handler: HandlerFunc,
    registry: dict[type[Op[Any, Any]], type[Node[Any, Any]]],
    op_param_names: dict[type[Op[Any, Any]], set[str]],
) -> type[Node[Any, Any]]:
    """
    Create nodnod Node from handler function.

    Handler params become node dependencies:
    - req: OpType → injected from scope
    - other_op: OtherOp → depends on OtherOp's node (wrapped in _CachedOp)
    - dep: SomeClass → injected from scope
    """
    sig = inspect.signature(handler)
    hints = get_type_hints(handler)

    # Track which params are Op dependencies (need wrapping)
    op_dep_params: set[str] = set()

    # Build __compose__ annotations
    compose_annotations: dict[str, Any] = {}
    compose_params: list[inspect.Parameter] = []

    for pname, p in sig.parameters.items():
        ptype = hints.get(pname, p.annotation)

        if ptype is op_type:
            # Request param → inject op_type from scope
            compose_annotations[pname] = op_type
        elif _is_op_type(ptype) and ptype in registry:
            # Another Op → depend on its node (returns Result, wrap in _CachedOp)
            compose_annotations[pname] = registry[ptype]
            op_dep_params.add(pname)
        else:
            # Regular dependency → inject from scope
            compose_annotations[pname] = ptype

        compose_params.append(inspect.Parameter(pname, inspect.Parameter.POSITIONAL_OR_KEYWORD))

    compose_annotations["return"] = Result[Any, Any]

    # Create __compose__ function that wraps Op deps in _CachedOp
    async def compose_fn(**kwargs: Any) -> Result[Any, Any]:
        # Wrap Op dependency results in _CachedOp so handler can await them
        wrapped_kwargs: dict[str, Any] = {}
        for k, v in kwargs.items():
            if k in op_dep_params and isinstance(v, (Ok, Error)):
                # Wrap Result in _CachedOp
                wrapped_kwargs[k] = _CachedOp(cast(Result[Any, Any], v))
            else:
                wrapped_kwargs[k] = v
        return await handler(**wrapped_kwargs)

    compose_fn.__annotations__ = compose_annotations
    compose_fn.__signature__ = inspect.Signature(parameters=compose_params)  # type: ignore[attr-defined]
    compose_fn.__name__ = f"compose_{op_type.__name__}"

    # Store op_dep_params for reference
    op_param_names[op_type] = op_dep_params

    # Create node class
    node_cls = create_node(
        name=f"Node:{op_type.__name__}",
        base_node=Node,
        bases=(),
        namespace={
            "__compose__": compose_fn,
            "__module__": handler.__module__,
        },
    )

    return node_cls


@dataclass(slots=True, frozen=True)
class OpsBuilder:
    """Builder for operation handlers."""
    _items: tuple[tuple[type[Op[Any, Any]], HandlerFunc], ...] = ()

    def on(
        self,
        op_type: type[Op[Any, Any]],
        handler: HandlerFunc,
    ) -> OpsBuilder:
        """Register handler for operation type."""
        # Last registration wins
        others = tuple(i for i in self._items if i[0] is not op_type)
        return OpsBuilder(_items=(*others, (op_type, handler)))

    def compile(self) -> Runner:
        """
        Compile into runner.

        Creates nodnod nodes for all handlers with proper dependency wiring.
        """
        # First pass: collect all op types
        op_handlers: dict[type[Op[Any, Any]], HandlerFunc] = {}
        for op_type, handler in self._items:
            op_handlers[op_type] = handler

        # Second pass: create nodes (need to handle dependencies)
        node_registry: dict[type[Op[Any, Any]], type[Node[Any, Any]]] = {}
        registrations: dict[type[Op[Any, Any]], _OpReg] = {}
        op_param_names: dict[type[Op[Any, Any]], set[str]] = {}

        # Build in dependency order (simple: just iterate, nodes reference by type)
        for op_type, handler in op_handlers.items():
            node_cls = _create_node_for_handler(op_type, handler, node_registry, op_param_names)
            node_registry[op_type] = node_cls
            registrations[op_type] = _OpReg(
                op_type=op_type,
                handler=handler,
                node_cls=node_cls,
            )

        return Runner(_registry=registrations, _node_registry=node_registry)


@dataclass(slots=True)
class Runner:
    """
    Executes operations via nodnod for automatic parallelization.

    When running an operation:
    1. Collect all Op dependencies from request fields
    2. Build nodnod agent with all required nodes
    3. Execute via nodnod (parallel resolution)
    4. Pass cached results to handler
    """
    _registry: dict[type[Op[Any, Any]], _OpReg]
    _node_registry: dict[type[Op[Any, Any]], type[Node[Any, Any]]]
    _global_scope: G.TypedScope = field(default_factory=lambda: G.TypedScope(detail="ops:global"))

    def inject(self, typ: type[object], impl: object) -> Runner:
        """Inject shared dependency."""
        self._global_scope.inject(typ, impl)
        return self

    def _collect_op_deps(self, req: Op[Any, Any]) -> list[tuple[type[Op[Any, Any]], Op[Any, Any]]]:
        """
        Collect all Op dependencies recursively from request fields.
        """
        deps: list[tuple[type[Op[Any, Any]], Op[Any, Any]]] = []
        visited: set[int] = set()  # Track by id to avoid cycles

        def collect_recursive(op: Op[Any, Any]) -> None:
            op_id = id(op)
            if op_id in visited:
                return
            visited.add(op_id)

            if not hasattr(op, "__dataclass_fields__"):
                return

            for f in fields(op):  # type: ignore[arg-type]
                val: object = getattr(op, f.name)
                if isinstance(val, Op):
                    val_typed = cast(Op[Any, Any], val)
                    val_type = type(val_typed)
                    if val_type in self._registry:
                        deps.append((val_type, val_typed))
                        # Recursively collect nested dependencies
                        collect_recursive(val_typed)

        collect_recursive(req)
        return deps

    async def run(self, req: Op[T, E]) -> Result[T, E]:
        """
        Execute operation with automatic parallelization.

        nodnod resolves all dependencies in parallel before calling handler.
        """
        op_type = type(req)
        reg = self._registry.get(op_type)
        if not reg:
            return cast(Result[T, E], Error(f"Op not registered: {op_type.__name__}"))

        # Collect all op dependencies
        op_deps = self._collect_op_deps(req)

        # Build set of nodes to execute
        nodes_to_run: set[type[Node[Any, Any]]] = {reg.node_cls}
        for dep_type, _ in op_deps:
            dep_reg = self._registry.get(dep_type)
            if dep_reg:
                nodes_to_run.add(dep_reg.node_cls)

        # Build agent
        agent = EventLoopAgent.build(nodes_to_run)

        # Create scope with injections (use G.TypedScope for type-safety)
        async with G.TypedScope(detail=f"ops:{op_type.__name__}") as scope:
            # Inject global dependencies
            for typ, impl in self._global_scope.all_injected().items():
                scope.inject(typ, impl)

            # Inject request
            scope.inject(op_type, req)

            # Inject op dependencies (so their nodes can extract them)
            for dep_type, dep_val in op_deps:
                scope.inject(dep_type, dep_val)

            # Run agent — nodnod parallelizes automatically
            await agent.run(local_scope=scope.inner, mapped_scopes={})  # type: ignore[misc]

            # Get result from scope
            result_opt = scope.inner.retrieve(reg.node_cls)
            match result_opt:
                case Some(val):
                    node_result = val.value
                    # node_result should be Result[T, E]
                    if isinstance(node_result, (Ok, Error)):
                        return cast(Result[T, E], node_result)
                    # Wrap in Ok if not Result
                    return cast(Result[T, E], Ok(node_result))
                case _:
                    return cast(Result[T, E], Error(f"Node not found: {reg.node_cls}"))

    def __call__(self, req: Op[T, E]) -> LazyCoroResult[T, E]:
        """Execute operation (returns awaitable)."""
        async def inner() -> Result[T, E]:
            return await self.run(req)
        return LazyCoroResult(inner)


def ops() -> OpsBuilder:
    """Create ops builder: ops().on(...).compile()"""
    return OpsBuilder()


# Aliases
Returns = Op
Returning = Op

__all__ = ("Op", "Returns", "Returning", "OpsBuilder", "Runner", "ops")
