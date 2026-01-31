"""Middleware execution pipelines.

Universal middleware execution logic that codecs can use.
Separates the "how to run middlewares" from codec-specific concerns.
"""

from __future__ import annotations

from typing import Any

from kungfu import Option, Some, Nothing, Ok, Error

from emergent.wire.axis.surface.scope._protocol import Middleware, StatefulMiddleware


async def run_rrc_middlewares(
    middlewares: tuple[Middleware[Any, Any, Any, Any], ...],
    request: Any,
) -> tuple[dict[type, Any], Option[Any]]:
    """Execute RRC middleware chain.

    Each middleware:
    1. Extracts Op from request
    2. Runs Op via its runner
    3. On Ok: injects value into scope_extras
    4. On Error: returns rejection response

    Args:
        middlewares: Tuple of middlewares to execute
        request: Request object that satisfies all middleware protocols

    Returns:
        (scope_extras, rejection) where:
        - scope_extras: dict of {type: value} to pass to runner.run()
        - rejection: Some(response) if middleware rejected, Nothing() otherwise
    """
    scope_extras: dict[type, Any] = {}

    for mw in middlewares:
        mw_op = mw.build(request)
        mw_result = await mw.runner.run(mw_op)

        match mw_result:
            case Ok(value):
                scope_extras[mw.inject_as] = value
            case Error():
                return (scope_extras, Some(mw.reject(mw_result)))

    return (scope_extras, Nothing())


async def run_stateful_middlewares(
    middlewares: tuple[StatefulMiddleware[Any, Any, Any, Any], ...],
    state: Any,
) -> tuple[dict[type, Any], Option[Any]]:
    """Execute Stateful middleware chain when Done.

    Like run_rrc_middlewares but extract() can return None to skip.

    Args:
        middlewares: Tuple of stateful middlewares
        state: Flow state when Done was reached

    Returns:
        (scope_extras, rejection) where:
        - scope_extras: dict of {type: value} to pass to runner.run()
        - rejection: Some(response) if middleware rejected, Nothing() otherwise
    """
    scope_extras: dict[type, Any] = {}

    for mw in middlewares:
        op = mw.build(state)
        if op is None:
            continue  # Skip this middleware

        result = await mw.runner.run(op)
        match result:
            case Ok(value):
                scope_extras[mw.inject_as] = value
            case Error():
                return (scope_extras, Some(mw.reject(result)))

    return (scope_extras, Nothing())


__all__ = ("run_rrc_middlewares", "run_stateful_middlewares")
