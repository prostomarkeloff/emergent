"""Game ops — generated via: emergent-meta new op."""

from dataclasses import dataclass

from emergent import ops as O

from roulette.game.domain import BetResult


@dataclass(frozen=True, slots=True)
class GetBalance(O.Returning[int, str]):
    pass


@dataclass(frozen=True, slots=True)
class PlaceBet(O.Returning[BetResult, str]):
    bet: str
    amount: int
