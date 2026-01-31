"""Scope enrichment axis — middleware for wire codecs.

Middleware injects typed values into scope before the main handler runs.
It's orthogonal to codecs (execution shapes) and triggers (attachment points).

Usage::

    from emergent.wire import inject

    # RRC middleware: inject AuthUser from request
    http_auth_mw = (
        inject(AuthUser)
            .using(auth_runner)
            .from_request(HasAuth, HasAuth.to_auth)
            .on_reject(AuthErrorResponse.from_domain)
            .build()
    )

    # Stateful middleware: inject from state (can skip via None)
    tg_auth_mw = (
        inject(AuthUser)
            .using(auth_runner)
            .from_state(HasChatId, lambda s: TelegramIdentity(s.chat_id) if s.chat_id else None)
            .on_reject(AuthErrorResponse.from_domain)
            .build()
    )

    # Use in codecs
    codec = rrc(Request, Response).use(http_auth_mw).build()
    codec = stateful(Flow, Response).key(Key).use(tg_auth_mw).build()

Architecture::

    wire/axis/surface/
    ├── codecs/     # HOW to execute (shapes)
    ├── triggers/   # WHERE to attach
    └── scope/      # WITH WHAT CONTEXT (this module)
"""

# Protocols
from emergent.wire.axis.surface.scope._protocol import (
    Middleware,
    StatefulMiddleware,
)

# Primary API
from emergent.wire.axis.surface.scope._inject import (
    inject,
    InjectBuilder,
)

# Execution (for codec authors)
from emergent.wire.axis.surface.scope._execute import (
    run_rrc_middlewares,
    run_stateful_middlewares,
)


__all__ = (
    # Protocols
    "Middleware",
    "StatefulMiddleware",
    # Primary API
    "inject",
    "InjectBuilder",
    # Execution (for codec authors)
    "run_rrc_middlewares",
    "run_stateful_middlewares",
)
