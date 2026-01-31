"""Shared store instances — single source of state."""

from roulette.auth.store import AuthStore
from roulette.game.store import GameStore

# Shared instances (would be injected via DI in production)
auth_store = AuthStore()
game_store = GameStore()
