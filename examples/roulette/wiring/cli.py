"""CLI wiring — command-line interface for roulette.

Run with:
    python -m examples.roulette.wiring.cli register myuser mypass
    python -m examples.roulette.wiring.cli login myuser mypass     # saves session
    python -m examples.roulette.wiring.cli balance                  # uses saved session
    python -m examples.roulette.wiring.cli bet red 100              # uses saved session
    python -m examples.roulette.wiring.cli bet-flow                 # interactive
    python -m examples.roulette.wiring.cli logout                   # clears session
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Self

from kungfu import Option, Some, Nothing
from nodnod import DataNode, NodeError
from nodnod.interface.scalar import scalar_node

from emergent.wire import endpoint, application
from emergent.wire.codecs.rrc import RequestResponseCodec, rrc
from emergent.wire.codecs.stateful import stateful, stateful_middleware, Done
from emergent.wire.triggers.cli import CLITrigger, cli_field
from emergent.wire.contrib import cli as wire_cli

from examples.roulette.auth.ops import Register, Login, TrustedIdentity, AuthUser
from examples.roulette.game.ops import GetBalance, PlaceBet
from examples.roulette.wiring import (
    auth_runner,
    game_runner,
    cli_auth_mw,
    RegisterResponse,
    LoginResponse,
    BalanceResponse,
    BetResponse,
)
from examples.roulette.wiring.base import AuthErrorResponse


# ═══════════════════════════════════════════════════════════════════════════
# CLI Session Management
# ═══════════════════════════════════════════════════════════════════════════


def _session_path() -> Path:
    return Path.home() / ".roulette" / "session"


def save_cli_session(login: str) -> None:
    """Save login to session file."""
    path = _session_path()
    path.parent.mkdir(exist_ok=True)
    path.write_text(login)


def load_cli_session() -> str | None:
    """Load login from session file."""
    path = _session_path()
    if path.exists():
        return path.read_text().strip() or None
    return None


def clear_cli_session() -> None:
    """Remove session file."""
    path = _session_path()
    if path.exists():
        path.unlink()


# ═══════════════════════════════════════════════════════════════════════════
# CLI Session Node — compose'ится в login из session file
# ═══════════════════════════════════════════════════════════════════════════


@scalar_node
class CLILogin:
    """Node that composes to login from session file.

    Used by requests/flows that need trusted CLI auth.
    Fails if not logged in — middleware will reject.
    """

    @classmethod
    def __compose__(cls) -> str:
        login = load_cli_session()
        if not login:
            raise NodeError("not logged in — run 'login' first")
        return login


# ═══════════════════════════════════════════════════════════════════════════
# CLI Request Types
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class RegisterRequest:
    """Register — public, no auth needed."""

    login: str = cli_field(help="Username for registration")
    password: str = cli_field(help="Password for registration")

    def to_domain(self) -> Register:
        return Register(login=self.login, password=self.password)


@dataclass
class LoginRequest:
    """Login — public, no auth needed."""

    login: str = cli_field(help="Username")
    password: str = cli_field(help="Password")

    def to_domain(self) -> Login:
        return Login(login=self.login, password=self.password)


@dataclass
class BalanceRequest(DataNode):
    """Balance request — compose'ится с CLILogin для trusted auth."""

    login: str

    @classmethod
    def __compose__(cls, cli_login: CLILogin) -> BalanceRequest:
        return cls(login=cli_login)

    def to_domain(self) -> GetBalance:
        return GetBalance()


@dataclass
class BetRequest(DataNode):
    """Bet request — compose'ится с CLILogin для trusted auth.

    - login: composed from CLILogin node (no CLI arg)
    - bet, amount: from CLI args (cli_field)
    """

    login: str  # composed, not from CLI
    bet: str = cli_field(help="Bet type: red, black, or number (0-36)")
    amount: int = cli_field(help="Bet amount")

    @classmethod
    def __compose__(
        cls,
        cli_login: CLILogin,
        ns: argparse.Namespace,
    ) -> BetRequest:
        return cls(
            login=cli_login,
            bet=ns.bet,
            amount=ns.amount,
        )

    def to_domain(self) -> PlaceBet:
        return PlaceBet(bet=self.bet, amount=self.amount)


# ═══════════════════════════════════════════════════════════════════════════
# Interactive Betting Flow (StatefulCodec)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class BetFlow:
    """Interactive betting flow — prompts for each field step by step.

    Gets login from CLILogin node via __transition__ compose.
    """

    login: str = ""
    bet_type: Option[str] = field(default_factory=Nothing)
    amount: Option[int] = field(default_factory=Nothing)

    async def __transition__(
        self,
        cli_login: Option[CLILogin],  # compose'ится!
        bet_type: Option[str],
        amount: Option[int],
    ) -> Self | tuple[Self, str] | Done:
        """Collect betting parameters interactively."""

        # Step 1: Get login from CLILogin node
        if not self.login:
            match cli_login:
                case Some(login):
                    return replace(self, login=login), "Choose bet type (red/black):"
                case Nothing():
                    return self, "Not logged in. Run 'login' first."

        # Step 2: Collect and validate bet type
        match (self.bet_type, bet_type):
            case (Nothing(), Some(bt)):
                bt_lower = bt.lower().strip()
                if bt_lower not in ("red", "black"):
                    return self, "Invalid! Enter 'red' or 'black':"
                return replace(self, bet_type=Some(bt_lower)), f"Bet: {bt_lower}. Enter amount:"
            case _:
                pass

        # Step 3: Collect and validate amount → Done
        match (self.bet_type, amount):
            case (Some(_), Some(amt)):
                if amt <= 0:
                    return self, "Invalid! Enter a positive number:"
                self.amount = Some(amt)
                return Done()
            case _:
                pass

        return self

    def to_domain(self) -> PlaceBet:
        """Called when Done — constructs Op from accumulated state."""
        return PlaceBet(
            bet=self.bet_type.unwrap(),
            amount=self.amount.unwrap(),
        )


class CLISession:
    """Key node for CLI stateful flows — session lives in memory."""

    @classmethod
    def __compose__(cls) -> str:
        return "cli-session"


# ═══════════════════════════════════════════════════════════════════════════
# CLI Stateful Middleware — reads login from flow state
# ═══════════════════════════════════════════════════════════════════════════


class HasLogin:
    login: str


def _cli_stateful_auth_op(state: HasLogin) -> TrustedIdentity | None:
    """Build auth op from state. None if no login yet."""
    if not state.login:
        return None
    return TrustedIdentity(login=state.login)


cli_stateful_auth_mw = stateful_middleware(
    auth_runner,
    AuthUser,
    _cli_stateful_auth_op,
    AuthErrorResponse.from_domain,
)


# ═══════════════════════════════════════════════════════════════════════════
# Wire & Compile
# ═══════════════════════════════════════════════════════════════════════════


wire_app = application().mount(
    # Public endpoints (no auth)
    endpoint(auth_runner).expose(
        CLITrigger("register", "Register a new user"),
        RequestResponseCodec(RegisterRequest, RegisterResponse),
    ),
    endpoint(auth_runner).expose(
        CLITrigger("login", "Login and save session"),
        RequestResponseCodec(LoginRequest, LoginResponse),
    ),
    # Authenticated endpoints (trusted via CLILogin compose)
    endpoint(game_runner).expose(
        CLITrigger("balance", "Check your balance"),
        rrc(BalanceRequest, BalanceResponse).use(cli_auth_mw).build(),
    ),
    endpoint(game_runner).expose(
        CLITrigger("bet", "Place a bet"),
        rrc(BetRequest, BetResponse).use(cli_auth_mw).build(),
    ),
    # Interactive betting flow
    endpoint(game_runner).expose(
        CLITrigger("bet-flow", "Interactive betting"),
        stateful(BetFlow, BetResponse).key(CLISession).use(cli_stateful_auth_mw).build(),
    ),
)

parser = wire_cli.from_application(wire_app, prog="roulette")


if __name__ == "__main__":
    import sys

    # Handle logout specially (not wired through application)
    if len(sys.argv) > 1 and sys.argv[1] == "logout":
        clear_cli_session()
        print("Logged out. Session cleared.")
        sys.exit(0)

    # Run normal commands
    if len(sys.argv) > 1 and sys.argv[1] == "login" and len(sys.argv) >= 4:
        login_name = sys.argv[2]
        result = wire_cli.run_parser(parser)
        if result == 0:
            save_cli_session(login_name)
            print(f"Session saved for {login_name}")
    else:
        wire_cli.run_parser(parser)
