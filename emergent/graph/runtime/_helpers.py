"""Reusable building blocks for custom graph runtime agents.

Provides GraphInfo (dependency structure), build_graph_info, and
CallbackAgent — an asyncio-based agent with pluggable per-node execution.

    from emergent.graph.runtime._helpers import (
        GraphInfo, build_graph_info, CallbackAgent, NodeExecutor,
    )

    # Custom scheduling policy
    @dataclass(frozen=True, slots=True)
    class RemoteCluster:
        requires_free_threaded: bool = False

        def build_agent(self, nodes: set[type[Node]]) -> Agent:
            async def execute(node, node_scope, local_scope):
                if should_remote(node):
                    return await remote_compose(node, node_scope, local_scope)
                return await compose_node(node, node_scope, local_scope)

            return CallbackAgent.build_with_executor(nodes, execute)
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import kungfu
from nodnod.agent.base import Agent
from nodnod.builder.build_queue import traverse_all
from nodnod.compose import compose_node
from nodnod.error import NodeError
from nodnod.node import Node
from nodnod.scope import Scope, validate_local_scope_is_linked_to_node_scopes


@dataclass(frozen=True, slots=True)
class GraphInfo:
    """Static dependency graph structure.

    Built once from a set of target nodes. Immutable — safe to reuse
    across multiple runs.

    Attributes:
        all_nodes: All nodes in topological order (targets + transitive deps).
        dependents: node -> set of nodes that depend on it.
        initial_pending: node -> number of unsatisfied dependencies.
        ready_roots: Nodes with zero dependencies (can start immediately).
        final_nodes: The originally requested target nodes.
    """

    all_nodes: tuple[type[Node], ...]
    dependents: Mapping[type[Node], frozenset[type[Node]]]
    initial_pending: Mapping[type[Node], int]
    ready_roots: frozenset[type[Node]]
    final_nodes: frozenset[type[Node]]


def build_graph_info(nodes: set[type[Node]]) -> GraphInfo:
    """Build GraphInfo from a set of target nodes.

    Traverses the full dependency graph, computes dependency counters,
    identifies ready roots and final nodes.
    """
    all_nodes_list = traverse_all(nodes)
    dependents_mut: dict[type[Node], set[type[Node]]] = {}
    initial_pending: dict[type[Node], int] = {}

    for node in all_nodes_list:
        deps = node.__dependencies__
        initial_pending[node] = len(deps)
        for dep in deps:
            dependents_mut.setdefault(dep, set()).add(node)

    dependents = {k: frozenset(v) for k, v in dependents_mut.items()}
    ready_roots = frozenset(
        node for node in all_nodes_list if initial_pending.get(node, 0) == 0
    )

    return GraphInfo(
        all_nodes=tuple(all_nodes_list),
        dependents=MappingProxyType(dependents),
        initial_pending=MappingProxyType(initial_pending),
        ready_roots=ready_roots,
        final_nodes=frozenset(nodes),
    )


type NodeExecutor = Callable[
    [type[Node], Scope, Scope],
    Awaitable[kungfu.Result[Any, NodeError]],
]


async def default_executor(
    node: type[Node], node_scope: Scope, local_scope: Scope
) -> kungfu.Result[Any, NodeError]:
    """Default node executor — delegates to nodnod's compose_node."""
    return await compose_node(node, node_scope, local_scope)


class CallbackAgent(Agent):
    """Graph executor with pluggable per-node execution.

    Handles all nodnod orchestration: dependency tracking, Either nodes
    (concurrent and sequential), ResultNode wrapping, error propagation.
    The user only provides the NodeExecutor — how to run a single node.

        # Default — identical to EventLoopAgent
        agent = CallbackAgent.build(nodes)

        # Custom — remote execution for some nodes
        async def my_executor(node, node_scope, local_scope):
            if node in remote_nodes:
                return await remote_compose(node, node_scope, local_scope)
            return await compose_node(node, node_scope, local_scope)

        agent = CallbackAgent.build_with_executor(nodes, my_executor)
    """

    def __init__(self, graph_info: GraphInfo, execute: NodeExecutor) -> None:
        self._graph_info = graph_info
        self._execute = execute

    @classmethod
    def build(cls, nodes: set[type[Node]]) -> CallbackAgent:
        """Build with default executor (compose_node)."""
        return cls(graph_info=build_graph_info(nodes), execute=default_executor)

    @classmethod
    def build_with_executor(cls, nodes: set[type[Node]], execute: NodeExecutor) -> CallbackAgent:
        """Build with custom executor."""
        return cls(graph_info=build_graph_info(nodes), execute=execute)

    async def run(self, local_scope: Scope, mapped_scopes: dict[type[Node], Scope]) -> None:
        validate_local_scope_is_linked_to_node_scopes(local_scope, mapped_scopes)

        if not self._graph_info.all_nodes:
            return

        futures: dict[type[Node], asyncio.Future[kungfu.Result[kungfu.Value, NodeError]]] = {}
        self._push_futures(local_scope, mapped_scopes, futures)

        final_futures = [futures[node] for node in self._graph_info.final_nodes]
        results = await asyncio.gather(*final_futures)

        for result in results:
            if kungfu.is_err(result):
                raise result.error

    def _push_futures(
        self,
        local_scope: Scope,
        mapped_scopes: dict[type[Node], Scope],
        futures: dict[type[Node], asyncio.Future[kungfu.Result[kungfu.Value, NodeError]]],
    ) -> None:
        """Build the asyncio task DAG — same structure as EventLoopAgent."""
        from nodnod.interface.either import Either
        from nodnod.interface.result_node import ResultNode

        for node in self._graph_info.all_nodes:
            node_scope = mapped_scopes.get(node, local_scope)

            if issubclass(node, Either):
                if node.is_concurrent:
                    dep_futures = [futures[dep] for dep in node.__dependencies__]
                    futures[node] = asyncio.ensure_future(_concurrent_either_coroutine(
                        node, dep_futures, node_scope, local_scope, self._execute
                    ))
                else:
                    first_dep = node.__either__[0]
                    first_future = futures[first_dep]
                    other_deps = node.__either__[1:]
                    futures[node] = asyncio.ensure_future(_sequential_either_coroutine(
                        first_node=first_dep,
                        first_future=first_future,
                        other_deps=other_deps,
                        futures=futures,
                        push_fn=self._push_futures,
                        mapped_scopes=mapped_scopes,
                        local_scope=local_scope,
                        execute=self._execute,
                    ))
            elif issubclass(node, ResultNode):
                dep_futures = [futures[dep] for dep in node.__dependencies__]
                futures[node] = asyncio.ensure_future(_result_node_coroutine(
                    node, dep_futures, node_scope, local_scope, self._execute
                ))
            else:
                dep_futures = [futures[dep] for dep in node.__dependencies__]
                futures[node] = asyncio.ensure_future(_compose_coroutine(
                    node, dep_futures, node_scope, local_scope, self._execute
                ))


async def _compose_coroutine(
    node: type[Node],
    dep_futures: list[asyncio.Future[kungfu.Result[Any, NodeError]]],
    node_scope: Scope,
    local_scope: Scope,
    execute: NodeExecutor,
) -> kungfu.Result[Any, NodeError]:
    for dep_future in dep_futures:
        dep_result = await dep_future
        if kungfu.is_err(dep_result):
            return dep_result
    return await execute(node, node_scope, local_scope)


async def _concurrent_either_coroutine(
    node: type[Node],
    dep_futures: list[asyncio.Future[kungfu.Result[Any, NodeError]]],
    node_scope: Scope,
    local_scope: Scope,
    execute: NodeExecutor,
) -> kungfu.Result[Any, NodeError]:
    results = await asyncio.gather(*dep_futures)
    for dep, result in zip(node.__either__, results):
        if kungfu.is_ok(result):
            return await execute(node, node_scope, local_scope)
    return results[-1]


async def _sequential_either_coroutine(
    first_node: type[Node],
    first_future: asyncio.Future[kungfu.Result[Any, NodeError]],
    other_deps: tuple[type[Node], ...],
    futures: dict[type[Node], asyncio.Future[kungfu.Result[Any, NodeError]]],
    push_fn: Callable[..., None],
    mapped_scopes: dict[type[Node], Scope],
    local_scope: Scope,
    execute: NodeExecutor,
) -> kungfu.Result[Any, NodeError]:
    result = await first_future
    if kungfu.is_ok(result):
        return result
    for dep in other_deps:
        if dep in futures:
            result = await futures[dep]
        else:
            result = await execute(dep, mapped_scopes.get(dep, local_scope), local_scope)
        if kungfu.is_ok(result):
            return result
    return result


async def _result_node_coroutine(
    node: type[Node],
    dep_futures: list[asyncio.Future[kungfu.Result[Any, NodeError]]],
    node_scope: Scope,
    local_scope: Scope,
    execute: NodeExecutor,
) -> kungfu.Result[Any, NodeError]:
    for dep_future in dep_futures:
        await dep_future
    return await execute(node, node_scope, local_scope)


__all__ = ("GraphInfo", "build_graph_info", "NodeExecutor", "default_executor", "CallbackAgent")
