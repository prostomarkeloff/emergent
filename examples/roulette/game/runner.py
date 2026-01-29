"""Game runner — generated via: emergent-meta new runner."""

from emergent import ops as O

from roulette.game.ops import GetBalance, PlaceBet
from roulette.game.handlers import handle_get_balance, handle_place_bet
from roulette.game.store import GameStore
from roulette.stores import game_store

game_runner = (
    O.ops()
    .on(GetBalance, handle_get_balance)
    .on(PlaceBet, handle_place_bet)
    .compile()
    .inject(GameStore, game_store)
)
