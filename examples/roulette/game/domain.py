"""Game domain — pure data, no framework deps."""

from dataclasses import dataclass

REDS: frozenset[int] = frozenset(
    {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
)
BLACKS: frozenset[int] = frozenset(
    {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}
)


@dataclass(frozen=True, slots=True)
class BetResult:
    won: bool
    number: int
    payout: int
    new_balance: int


def parse_bet(s: str) -> str | int:
    """Validate bet string. Returns 'red', 'black', or 0–36."""
    low = s.lower().strip()
    if low in ("red", "black"):
        return low
    try:
        n = int(low)
    except ValueError:
        msg = f"invalid bet: {s!r}"
        raise ValueError(msg) from None
    if not (0 <= n <= 36):
        msg = f"number must be 0–36, got {n}"
        raise ValueError(msg)
    return n
