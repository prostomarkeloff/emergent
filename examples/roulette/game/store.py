"""Game store — in-memory balance storage."""


class GameStore:
    """In-memory game storage: user balances."""

    INITIAL_BALANCE = 100

    def __init__(self) -> None:
        self._balances: dict[str, int] = {}  # login → balance

    def ensure_balance(self, login: str) -> None:
        if login not in self._balances:
            self._balances[login] = self.INITIAL_BALANCE

    def get_balance(self, login: str) -> int:
        return self._balances.get(login, self.INITIAL_BALANCE)

    def update_balance(self, login: str, new_balance: int) -> None:
        self._balances[login] = new_balance
