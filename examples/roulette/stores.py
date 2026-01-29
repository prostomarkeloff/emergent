"""Shared store instances — single source of state."""

from roulette.auth.store import AuthStore
from roulette.game.store import GameStore

auth_store = AuthStore()
game_store = GameStore()
