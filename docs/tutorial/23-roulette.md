# Putting It All Together

Your product manager walks over on a Monday morning and says: "We're building a roulette game. Users register, log in, place bets, spin the wheel. Standard stuff."

Fine.

"The web team wants an HTTP API."

Sure.

"The ops team wants a CLI for admin stuff."

Okay.

"And the marketing team wants a Telegram bot so people can play from their phones."

Three UIs. One game. And you have until Friday.

The traditional approach: three codebases, or one codebase with three adapter layers that drift apart every sprint. The handlers for the HTTP version do things slightly differently from the Telegram version. Someone fixes a bug in the CLI adapter but forgets to port it. The authentication logic gets copy-pasted, then tweaked, then the copies diverge.

The emergent approach: write the game once. Compile it three times.

---

## The domain

Start where every application should start --- with the domain, naked and clean:

```python
@dataclass(frozen=True, slots=True)
class Register(O.Returning[str, str]):
    login: str
    password: str

@dataclass(frozen=True, slots=True)
class Login(O.Returning[str, str]):
    login: str
    password: str

@dataclass(frozen=True, slots=True)
class PlaceBet(O.Returning[BetResult, str]):
    bet: str
    amount: int

@dataclass(frozen=True, slots=True)
class GetBalance(O.Returning[int, str]):
    pass
```

No HTTP. No Telegram. No CLI. Just frozen dataclasses that say "here's an operation, here's what it returns on success, here's what it returns on failure." Pure algebra. The roulette wheel doesn't know what a REST endpoint is, and it shouldn't.

The handlers are equally clean --- async functions that take an op and its dependencies, return a `Result`:

```python
async def handle_place_bet(
    op: PlaceBet, auth_user: AuthUser, game_store: GameStore
) -> Result[BetResult, str]:
    bet = parse_bet(op.bet)
    number = random.randint(0, 36)
    # ... calculate payout, update balance ...
    return Ok(BetResult(won=payout > 0, number=number, payout=payout, new_balance=new_balance))
```

`AuthUser` and `GameStore` appear in the signature. The runner resolves them automatically. The handler doesn't know where `AuthUser` came from --- could be an HTTP token, a Telegram chat ID, a trusted CLI session. Doesn't matter. It just gets an authenticated user.

## The runners

Compose the ops into runners:

```python
auth_runner = (
    O.ops()
    .on(Register, handle_register)
    .on(Login, handle_login)
    .on(Authenticate, handle_authenticate)
    .on(TelegramIdentity, handle_telegram_identity)
    .compile()
    .inject(AuthStore, auth_store)
    .inject(GameStore, game_store)
)

game_runner = (
    O.ops()
    .on(GetBalance, handle_get_balance)
    .on(PlaceBet, handle_place_bet)
    .compile()
    .inject(GameStore, game_store)
)
```

Still no HTTP. Still no Telegram. Just domain operations wired to handlers with their dependencies injected.

## The wiring

Now --- and only now --- we tell the framework how users reach these operations. This is where the sheaf unfolds into its fibers:

```python
endpoint(auth_runner)
    .expose(
        HTTPRouteTrigger("POST", "/register"),
        rrc(RegisterRequest, TokenResponse),
    )
    .expose(
        CLITrigger("register", "Register new user"),
        rrc(RegisterRequest, TokenResponse),
    ),
```

One endpoint, two exposures. The HTTP compiler sees `HTTPRouteTrigger` and creates a FastAPI route. The CLI compiler sees `CLITrigger` and creates an argparse subcommand. Neither knows the other exists.

Telegram gets its own endpoints because the request types differ --- a Telegram user authenticates via chat ID binding, not tokens:

```python
endpoint(game_runner)
    .expose(
        TelegrindTrigger(Command("bet")),
        rrc(TelegramBetRequest, BetResponse),
        Auth(TelegramBetRequest),
        HelpMeta("Place a bet", order=4),
    ),
```

The `TelegramBetRequest` knows how to extract a `chat_id` from the Telegram context and convert it into a `TelegramIdentity` op. The auth enricher runs it through the auth runner, gets back an `AuthUser`, injects it into scope. Same auth logic, different entry point.

## The request types

Here's where annotations earn their keep. One field, multiple projections:

```python
@dataclass
class RegisterRequest:
    login: Annotated[str,
        cli.Help("Username"),
        cli.Positional(),
        Doc("Username for registration"),
        tg.CommandArg(),
    ]
    password: Annotated[str,
        cli.Help("Password"),
        cli.Positional(),
        Doc("Account password"),
        tg.CommandArg(),
    ]
```

`cli.Help` tells the CLI compiler what to print in `--help`. `cli.Positional` makes it a positional argument instead of a flag. `Doc` feeds the OpenAPI description. `tg.CommandArg` tells the Telegram compiler to parse it from the command text. Four annotations, one field, three targets. The field itself is written once.

## Three compilers, one application

```python
app = Application().mount(*_build_endpoints())

fastapi_app = fastapi.compile(app)
cli_parser = cli.compile(app, prog="roulette")
telegram_dp = telegrinder.compile(app)
```

Three lines. Three complete applications. The FastAPI app has routes, Pydantic models, OpenAPI docs. The CLI parser has subcommands, arguments, help text. The Telegram dispatcher has command handlers, input parsing, formatted responses with `tg.Bold()` and `tg.Code()` annotations.

Run them:

```bash
# HTTP
uvicorn roulette.wiring:fastapi_app --reload

# CLI
python -m roulette register alice secret
python -m roulette bet red 50

# Telegram
python -m roulette --bot
```

## Auth across targets

The `Auth` enricher deserves a closer look. It's a frozen dataclass that implements `ScopeEnricher`:

```python
@dataclass(frozen=True, slots=True)
class Auth(SurfaceCapability, ScopeEnricher):
    request_cls: type[HasAuth]

    async def enrich(self, call, scope):
        req = scope.get(self.request_cls).value
        auth_op = req.to_auth()  # Authenticate or TelegramIdentity
        result = await auth_runner.run(auth_op)
        match result:
            case Ok(user):
                scope.inject(AuthUser, user)
                return await call(scope)
            case Error(e):
                return AuthErrorResponse(error=e)
```

The enricher calls `to_auth()` on whatever request type it's given. An HTTP `BetRequest` returns `Authenticate(token=...)`. A Telegram `TelegramBetRequest` returns `TelegramIdentity(chat_id=...)`. Different ops, same runner, same `AuthUser` out the other side. The handler just asks for `AuthUser` in its signature and gets it.

No `if request.is_http: ... elif request.is_telegram: ...`. The polymorphism lives in the request types, not in conditional branches.

## The point

Traditionally, three UIs means three codebases. Or one codebase with three adapter layers that someone has to keep in sync manually. With emergent, it's one domain, one set of request/response types, and three compiler calls. The sheaf isn't a metaphor --- it's literally what's happening. One global section (the ops + handlers), multiple fibers (HTTP, CLI, Telegram), each fiber projected via compilation.

The roulette example is about 400 lines total across all files. A traditional approach with three separate adapter layers would be at least twice that, with the ongoing tax of keeping them synchronized. Here, synchronization is guaranteed by construction. There's nothing to keep in sync --- there's only one source of truth, and the compilers derive the rest.

---

**Next:** [The Shape of the Whole Thing ->](24-design.md)
