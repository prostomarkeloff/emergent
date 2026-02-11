"""Unified request building — all compilers use this.

Single function to construct request from any context (HTTP, CLI, Telegram).
Reads ALL capabilities uniformly via inspect_dataclass.

    from emergent.wire.compile._request import build_request

    # Same function for all targets
    request = await build_request(
        request_cls=RegisterRequest,
        get_value=lambda name: ctx.get(name),  # context accessor
        agent_cls=EventLoopAgent,
        scope=scope,  # for node composition
    )
"""

from __future__ import annotations

import dataclasses
from typing import Any, Callable, TYPE_CHECKING

from kungfu import Some, Nothing

from emergent.wire.axis.schema._inspect import inspect_dataclass, FieldInfo
from emergent.wire.axis._capability import RequestBuildCompilable, RequestBuildContext
from emergent.wire.compile._core import fold_field

if TYPE_CHECKING:
    from nodnod import Scope
    from nodnod.agent.base import Agent


async def compose_node_value(
    node_type: type,
    agent_cls: type[Agent],
    scope: Scope,
) -> tuple[bool, Any]:
    """Compose a nodnod node and return its value.

    Uses nodnod's agent system to compose the node with proper
    dependency resolution.

    Returns: (success, value_or_error)
    """
    try:
        # Build agent for this single node
        agent = agent_cls.build({node_type})

        # Run agent - it will compose the node and store in scope
        await agent.run(local_scope=scope, mapped_scopes={})

        # Retrieve composed value from scope
        result = scope.retrieve(node_type)
        match result:
            case Some(value):
                # value is nodnod.Value wrapper, extract actual value
                return True, value.value
            case Nothing():
                return False, f"Node {node_type.__name__} not composed"

    except Exception as e:
        return False, str(e)


async def build_field_value(
    name: str,
    info: FieldInfo,
    get_value: Callable[[str], Any],
    agent_cls: type[Agent],
    scope: Scope | None,
    dataclass_field: dataclasses.Field[Any] | None,
) -> tuple[bool, Any]:
    """Build value for a single field.

    Uses fold_field to read compose.* capabilities into RequestBuildContext,
    then executes the appropriate strategy.

    Returns: (has_value, value)
    """
    # 1. Fold capabilities into context
    ctx = RequestBuildContext(field_name=name, field_type=info.base_type)
    ctx = fold_field(info, ctx, RequestBuildCompilable, "compile_request_build")

    # 2. Execute strategy from folded context
    if ctx.compose_node is not None and scope is not None:
        success, value = await compose_node_value(ctx.compose_node, agent_cls, scope)
        if success:
            if ctx.compose_node_map is not None:
                value = ctx.compose_node_map(value)
            return True, value
        elif ctx.compose_node_default is not None:
            return True, ctx.compose_node_default
        else:
            return False, f"Failed to compose {ctx.compose_node.__name__}"

    if ctx.compose_optional_node is not None and scope is not None:
        success, value = await compose_node_value(ctx.compose_optional_node, agent_cls, scope)
        if success:
            return True, Some(value)
        else:
            return True, Nothing()

    if ctx.compose_fallback_nodes is not None and scope is not None:
        for node_type in ctx.compose_fallback_nodes:
            success, value = await compose_node_value(node_type, agent_cls, scope)
            if success:
                return True, value
        return False, "All fallback nodes failed"

    if ctx.compose_race_nodes is not None and scope is not None:
        import asyncio
        tasks = [compose_node_value(nt, agent_cls, scope) for nt in ctx.compose_race_nodes]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, tuple) and r[0]:
                return True, r[1]
        return False, "All race nodes failed"

    if ctx.compose_retrieve_type is not None and scope is not None:
        result = scope.retrieve(ctx.compose_retrieve_type)
        match result:
            case Some(v):
                return True, v.value
            case Nothing():
                return False, f"Failed to retrieve {ctx.compose_retrieve_type.__name__}"

    # 3. Regular — from context
    value = get_value(name)
    if value is not None:
        return True, value

    # 4. Check for default
    if dataclass_field is not None:
        if dataclass_field.default is not dataclasses.MISSING:
            return True, dataclass_field.default
        if dataclass_field.default_factory is not dataclasses.MISSING:
            return True, dataclass_field.default_factory()

    # 5. Optional field without value
    if info.is_optional:
        return True, None

    return False, f"No value for required field {name}"


async def build_request(
    request_cls: type,
    get_value: Callable[[str], Any],
    agent_cls: type[Agent] | None = None,
    scope: Scope | None = None,
) -> Any:
    """Build request instance from context.

    Unified function for all compilers. Reads ALL capabilities
    via inspect_dataclass and handles them uniformly.

    Args:
        request_cls: Request dataclass type
        get_value: Function to get value by field name from context
        agent_cls: Agent class for node composition (optional)
        scope: nodnod Scope for composition (optional)

    Returns:
        Constructed request instance

    Raises:
        RuntimeError: If required field cannot be resolved

    Example:
        # Telegrinder
        request = await build_request(
            RegisterRequest,
            get_value=lambda name: ctx.get(name),
            agent_cls=EventLoopAgent,
            scope=scope,
        )

        # CLI
        request = await build_request(
            RegisterRequest,
            get_value=lambda name: getattr(namespace, name, None),
        )
    """
    from nodnod.agent.event_loop.agent import EventLoopAgent

    if not dataclasses.is_dataclass(request_cls):
        raise TypeError(f"{request_cls} is not a dataclass")

    _agent_cls = agent_cls or EventLoopAgent
    fields = inspect_dataclass(request_cls)
    dc_fields = {f.name: f for f in dataclasses.fields(request_cls)}

    kwargs: dict[str, Any] = {}

    for name, info in fields.items():
        dc_field = dc_fields.get(name)
        has_value, value = await build_field_value(
            name=name,
            info=info,
            get_value=get_value,
            agent_cls=_agent_cls,
            scope=scope,
            dataclass_field=dc_field,
        )

        if has_value:
            kwargs[name] = value
        elif not info.is_optional:
            raise RuntimeError(f"Cannot resolve required field '{name}': {value}")

    return request_cls(**kwargs)


def build_request_sync(
    request_cls: type,
    get_value: Callable[[str], Any],
) -> Any:
    """Sync version of build_request.

    WARNING: Does NOT support compose.* capabilities (Node, Optional, Retrieve).
    Use build_request() for full support.

    Only for backwards compatibility or truly sync-only contexts.
    """
    if not dataclasses.is_dataclass(request_cls):
        raise TypeError(f"{request_cls} is not a dataclass")

    fields = inspect_dataclass(request_cls)
    dc_fields = {f.name: f for f in dataclasses.fields(request_cls)}

    kwargs: dict[str, Any] = {}

    for name, info in fields.items():
        value = get_value(name)

        if value is not None:
            kwargs[name] = value
        else:
            dc_field = dc_fields.get(name)
            if dc_field is not None:
                if dc_field.default is not dataclasses.MISSING:
                    kwargs[name] = dc_field.default
                elif dc_field.default_factory is not dataclasses.MISSING:
                    kwargs[name] = dc_field.default_factory()
                elif not info.is_optional:
                    raise RuntimeError(f"No value for required field '{name}'")

    return request_cls(**kwargs)


__all__ = (
    "build_request",
    "build_request_sync",
    "build_field_value",
    "compose_node_value",
)
