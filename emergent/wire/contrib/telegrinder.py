"""Telegrinder compiler — re-exports from _impls._telegrinder."""

try:
    from emergent.wire.contrib._impls._telegrinder import (
        add_endpoint_to_dispatch,
        from_application,
    )
except ImportError:
    pass

__all__ = ("add_endpoint_to_dispatch", "from_application")
