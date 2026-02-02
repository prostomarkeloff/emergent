"""Immediate codec — direct response without domain layer.

Two patterns:

1. Class with produce() method:

    endpoint(empty_runner()).expose(
        TelegrindTrigger(Command("help")),
        immediate(HelpResponse),
    )

    @dataclass
    class HelpResponse:
        text: str

        @classmethod
        def produce(cls) -> Self:
            return cls(text="Help!")

2. Factory function (closure over variables):

    help_text = generate_help(app)

    endpoint(empty_runner()).expose(
        TelegrindTrigger(Command("help")),
        immediate_factory(lambda: HelpResponse(text=help_text)),
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol, TypeVar


R_co = TypeVar("R_co", covariant=True)


class Producing(Protocol[R_co]):
    """Protocol for types that can produce themselves directly.

    Used by ImmediateCodec for responses that don't need domain layer.
    The produce() classmethod can accept composed nodes as parameters.
    """

    @classmethod
    def produce(cls) -> R_co: ...


@dataclass(frozen=True, slots=True)
class ImmediateCodec:
    """Immediate response codec — no domain, just produce().

    Attributes:
        response: Response class implementing Producing protocol.
    """

    response: type[Producing[Any]]


@dataclass(frozen=True, slots=True)
class ImmediateFactoryCodec:
    """Immediate response codec with factory function.

    Attributes:
        factory: Callable that returns response instance.
    """

    factory: Callable[[], Any]


def immediate(response: type[Producing[R_co]]) -> ImmediateCodec:
    """Create immediate codec from Producing response class.

    Args:
        response: Class implementing Producing protocol.

    Example::

        @dataclass
        class HelpResponse:
            text: str

            @classmethod
            def produce(cls) -> Self:
                return cls(text="Help!")

        immediate(HelpResponse)
    """
    return ImmediateCodec(response=response)


def immediate_factory(factory: Callable[[], R_co]) -> ImmediateFactoryCodec:
    """Create immediate codec from factory function.

    Useful for closures over runtime variables.

    Args:
        factory: Callable that returns response instance.

    Example::

        help_text = generate_help(app)
        immediate_factory(lambda: HelpResponse(text=help_text))
    """
    return ImmediateFactoryCodec(factory=factory)
