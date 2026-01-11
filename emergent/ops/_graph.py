"""
Ops — data-driven dispatch with automatic DI via nodnod.

Core idea:
- Op[T, E] is base class with .get() method returning LazyCoroResult[T, E]
- Operations are frozen dataclasses inheriting from Op[T, E]
- Runner injects executable .get() via scope per operation type
- Handlers receive operation instances with working .get() method
- Operations can be awaited directly: `result = await price_op`

Example:
    @dataclass(frozen=True, slots=True)
    class GetPrice(Op[float, str]):
        product_id: int
    
    @dataclass(frozen=True, slots=True)
    class GetStock(Op[int, str]):
        product_id: int
    
    @dataclass(frozen=True, slots=True)
    class BuildSummary(Op[str, str]):
        product_id: int
        price: GetPrice    # Dependency
        stock: GetStock    # Dependency
    
    async def get_price(req: GetPrice, db: Database) -> Result[float, str]:
        return Ok(await db.get_price(req.product_id))
    
    async def build_summary(
        req: BuildSummary,
        price: GetPrice,    # Op instance with .get()
        stock: GetStock,    # Op instance with .get()
    ) -> Result[str, str]:
        p = await price  # or price.get()
        s = await stock
        
        match (p, s):
            case (Ok(pv), Ok(sv)):
                return Ok(f"${pv}, {sv} units")
            case _:
                return Error("failed")
    
    runner = (
        ops()
        .on(GetPrice, get_price)
        .on(GetStock, get_stock)
        .on(BuildSummary, build_summary)
        .compile()
        .inject(Database, db)
    )
    
    result = await runner.run(GetPrice(123))
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field, fields
from typing import Any, TypeVar, Callable, Awaitable, Generic, get_type_hints, cast
from abc import ABC

from kungfu import Result, Error, LazyCoroResult

from emergent import graph as G
from emergent.ops._policy import Policy

T = TypeVar("T")
E = TypeVar("E")
T_co = TypeVar("T_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)

HandlerFunc = Callable[..., Awaitable[Result[Any, Any]]]


class Op(ABC, Generic[T_co, E_co]):
    """
    Base class for operations.
    
    Provides:
    - .get() → LazyCoroResult[T, E]
    - __await__ → can be awaited directly
    
    Usage:
        @dataclass(frozen=True, slots=True)
        class GetPrice(Op[float, str]):
            product_id: int
        
        async def handler(price: GetPrice):
            result = await price  # or price.get()
    """
    
    # Note: These are "overridden" by runner via wrapper class.
    # Default implementation raises error to catch unbound ops.
    
    def get(self) -> LazyCoroResult[T_co, E_co]:
        """Execute operation and return result."""
        raise RuntimeError(
            f"Operation {type(self).__name__} not bound. "
            "Did you forget to register handler via .on()?"
        )
    
    def __await__(self):
        """Allow: result = await op"""
        return self.get().__await__()


def _is_op_type(typ: object) -> bool:
    """Check if type is an Op subclass."""
    try:
        return isinstance(typ, type) and issubclass(typ, Op)
    except TypeError:
        return False


@dataclass(frozen=True, slots=True)
class _OpReg:
    """Registration: Op type → handler function."""
    op_type: type[Op[Any, Any]]
    handler: HandlerFunc
    policy: Policy


@dataclass(slots=True, frozen=True)
class OpsBuilder:
    """Builder for operation handlers."""
    _items: tuple[_OpReg, ...] = ()
    
    def on(
        self,
        op_type: type[Op[Any, Any]],
        handler: HandlerFunc,
        policy: Policy | None = None,
    ) -> OpsBuilder:
        """
        Register handler for operation type.
        
        Handler signature:
            async def handler(req: OpType, dep1: Dep1, dep2: OpType2) -> Result[T, E]
        
        - req: The operation request (same type as op_type)
        - dep1, dep2: Either injected deps OR other Op types (will have .get())
        """
        reg = _OpReg(
            op_type=op_type,
            handler=handler,
            policy=policy or Policy(),
        )
        # Last registration wins
        others = tuple(i for i in self._items if i.op_type is not op_type)
        return OpsBuilder(_items=(*others, reg))
    
    def compile(self) -> Runner:
        """Compile into executable runner."""
        registry: dict[type[Op[Any, Any]], _OpReg] = {}
        for reg in self._items:
            registry[reg.op_type] = reg
        return Runner(_registry=registry)


class _BoundOp(Generic[T_co, E_co]):
    """
    Wrapper that binds .get() to a runner.
    
    Proxies all attributes to original op, but overrides .get() and __await__.
    """
    __slots__ = ("_op", "_runner")
    
    def __init__(self, op: Op[T_co, E_co], runner: Runner) -> None:
        object.__setattr__(self, "_op", op)
        object.__setattr__(self, "_runner", runner)
    
    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_op"), name)
    
    def __setattr__(self, name: str, value: Any) -> None:
        # Redirect to original (frozen, so will raise)
        setattr(object.__getattribute__(self, "_op"), name, value)
    
    def get(self) -> LazyCoroResult[T_co, E_co]:
        """Execute operation via runner."""
        runner: Runner = object.__getattribute__(self, "_runner")
        op: Op[T_co, E_co] = object.__getattribute__(self, "_op")
        
        async def executor() -> Result[T_co, E_co]:
            return await runner.run(op)
        
        return LazyCoroResult(executor)
    
    def __await__(self):
        """Allow: result = await bound_op"""
        return self.get().__await__()


@dataclass(slots=True)
class Runner:
    """
    Executes operations via scope injection pattern.
    
    When handler requests Op[T,E] as parameter:
    1. Gets the op instance from request fields
    2. Wraps it with _BoundOp (binds .get() to this runner)
    3. Handler calls .get() or awaits → executes recursively
    """
    _registry: dict[type[Op[Any, Any]], _OpReg]
    _global_scope: G.TypedScope = field(default_factory=lambda: G.TypedScope(detail="ops:global"))
    
    def inject(self, typ: type[object], impl: object) -> Runner:
        """Inject shared dependency (Database, etc.)."""
        self._global_scope.inject(typ, impl)
        return self
    
    def _bind_op(self, op: Op[T_co, E_co]) -> _BoundOp[T_co, E_co]:
        """Wrap operation with bound .get() method."""
        return _BoundOp(op, self)
    
    async def run(self, req: Op[T, E]) -> Result[T, E]:
        """
        Execute operation.
        
        1. Find handler for operation type
        2. Resolve parameters:
           - req param: the request itself
           - Op[T,E] params: get from req fields, wrap with _BoundOp
           - Other params: get from global scope (injected deps)
        3. Call handler
        """
        op_type = type(req)
        reg = self._registry.get(op_type)
        if not reg:
            return cast(Result[T, E], Error(f"Op not registered: {op_type.__name__}"))
        
        # Extract handler signature
        sig = inspect.signature(reg.handler)
        hints = get_type_hints(reg.handler)
        kwargs: dict[str, Any] = {}
        
        # Build mapping: field_name → field_value for request
        req_fields: dict[str, Any] = {}
        if hasattr(req, "__dataclass_fields__"):
            for f in fields(req):  # type: ignore[arg-type]
                req_fields[f.name] = getattr(req, f.name)
        
        for param_name, param in sig.parameters.items():
            param_type = hints.get(param_name, param.annotation)
            
            if param_type is inspect.Parameter.empty:
                continue
            
            # Case 1: This is the request parameter (same type)
            if param_type is op_type:
                kwargs[param_name] = req
                continue
            
            # Case 2: This is another Op type → bind .get() method
            if _is_op_type(param_type) and param_type in self._registry:
                # Find matching field in request
                found_dep: object | None = None
                
                # First try: field with same name
                if param_name in req_fields:
                    field_val = req_fields[param_name]
                    if isinstance(field_val, Op):
                        found_dep = cast(object, field_val)
                
                # Second try: field with matching type
                if found_dep is None:
                    for _, fv in req_fields.items():
                        if isinstance(fv, param_type):
                            found_dep = fv
                            break
                
                if found_dep is not None:
                    # Note: found_dep is Op[?, ?] here, cast to Op[Any, Any]
                    kwargs[param_name] = self._bind_op(cast(Op[Any, Any], found_dep))
                    continue
                else:
                    return cast(
                        Result[T, E],
                        Error(f"Missing dependency field for {param_type.__name__} in {op_type.__name__}")
                    )
            
            # Case 3: Injected dependency from scope
            if isinstance(param_type, type):
                try:
                    kwargs[param_name] = self._global_scope.get(param_type)
                except KeyError:
                    return cast(
                        Result[T, E],
                        Error(f"Missing injected dependency: {param_type.__name__}")
                    )
        
        # Execute handler
        result = await reg.handler(**kwargs)
        return cast(Result[T, E], result)
    
    def __call__(self, req: Op[T, E]) -> LazyCoroResult[T, E]:
        """
        Execute operation (returns awaitable).
        
        Usage:
            result = await runner(GetPrice(123))
        """
        async def inner() -> Result[T, E]:
            return await self.run(req)
        return LazyCoroResult(inner)


def ops() -> OpsBuilder:
    """Create ops builder: ops().on(...).compile()"""
    return OpsBuilder()


# Aliases for Op (semantic naming)
Returns = Op
Returning = Op

__all__ = ("Op", "Returns", "Returning", "OpsBuilder", "Runner", "ops")
