"""Runtime enrichers — middleware for surface axis.

    from emergent.wire.axis.surface import enrichers

    endpoint(runner).expose(
        trigger,
        rrc(Request, Response),
        enrichers.Timeout(seconds=5.0),
        enrichers.Retry(policy=RetryPolicy.exponential(times=3)),
    )
"""

from emergent.wire.axis.surface.enrichers._base import (
    ScopeEnricher,
    EnricherNext,
)

from emergent.wire.axis.surface.enrichers._impl import (
    # Execution
    chain_enrichers,
    execute_with_enrichers,
    # Time
    Timeout,
    Delay,
    # Resilience
    Retry,
    RateLimit,
    # Provide / Injection
    Provide,
    Inject,
    # Validation
    Validate,
    # Cache
    Cached,
    # Control flow
    Passthrough,
    When,
)


__all__ = (
    # Protocol
    "ScopeEnricher",
    "EnricherNext",
    # Execution
    "chain_enrichers",
    "execute_with_enrichers",
    # Time
    "Timeout",
    "Delay",
    # Resilience
    "Retry",
    "RateLimit",
    # Provide / Injection
    "Provide",
    "Inject",
    # Validation
    "Validate",
    # Cache
    "Cached",
    # Control flow
    "Passthrough",
    "When",
)
