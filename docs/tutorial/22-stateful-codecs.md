# Conversations

HTTP is request-response. One question, one answer. The client sends everything in a single POST body, the server replies, done. But a Telegram bot doesn't work like that. It asks "What's your name?" and waits. The user types "Alice." It asks "What's your email?" and waits again. The user types "alice@example.com." It asks "Confirm?" and waits a third time. Three turns, accumulating state across messages, before the domain operation can even run.

A CLI wizard does the same thing. A multi-step form does the same thing. And the `rrc` codec --- request in, response out, one shot --- can't express any of it.

---

## The shape of a conversation

The stateful codec lives in `emergent/wire/axis/surface/codecs/stateful.py`. Where `rrc` is `request -> op -> response` (one turn), the stateful codec is `state x input -> state' | Done` (many turns). A conversation is just a state machine that eventually finishes.

Here's what one looks like:

```python
from dataclasses import dataclass, field, replace
from kungfu import Option, Some, Nothing
from emergent.wire.axis.surface.codecs import Done

@dataclass
class RegistrationFlow:
    name: Option[str] = field(default_factory=Nothing)
    email: Option[str] = field(default_factory=Nothing)

    async def __transition__(self, msg) -> "RegistrationFlow | tuple[RegistrationFlow, str] | Done":
        if not self.name:
            return replace(self, name=Some(msg.text)), "Got it. What's your email?"
        if not self.email:
            return replace(self, email=Some(msg.text)), "Confirm registration?"
        return Done()

    def to_domain(self) -> RegisterUser:
        return RegisterUser(
            name=self.name.unwrap(),
            email=self.email.unwrap(),
        )
```

Three things to notice.

First: `__transition__` receives a message and returns either a new state (continue the conversation) or `Done()` (finish it). Returning `replace(self, name=Some(msg.text))` creates a new flow instance with the name filled in --- frozen immutable updates, same pattern as everything else in emergent.

Second: you can return a tuple `(new_state, response)` to send an intermediate message back to the user. "Got it. What's your email?" goes out between turns. Or return just the new state if there's nothing to say.

Third: `to_domain()` is the bridge back to the domain layer. When `Done()` is returned, the codec calls `state.to_domain()` to produce the domain Op, hands it to the runner, and uses the response type's `from_domain()` to produce the final answer. Same pipeline as `rrc`, just preceded by a conversation.

## The execution flow

When `__transition__` returns `Done`:

1. Middlewares run (build scope extras like `AuthUser`)
2. `state.to_domain()` produces the Op
3. `runner.run(op, scope_extras)` executes it, returns a Result
4. `response.from_domain(result)` formats the final response

The first N turns are pure state accumulation. The last turn triggers the full RRC pipeline. Everything between is just the codec holding state.

## There's also `Cancelled`

Sometimes the user changes their mind. `Cancelled` is a subclass of `Done` that skips the Op execution entirely --- state gets deleted, the flow ends, no domain logic runs:

```python
if msg.text == "/cancel":
    await msg.answer("Cancelled.")
    return Cancelled()
```

The transition itself is responsible for sending any cancellation message before returning `Cancelled()`.

## Multi-transport transitions

Here's where it gets interesting. A Telegram bot shows inline keyboards. A CLI prompts with text. An HTTP endpoint might accept all fields at once. The conversation logic is the same, but the interaction mechanics differ per transport.

The `@transition` decorator lets you define multiple transition methods on a single flow class. nodnod routes to the first one whose parameter types are resolvable in the current scope:

```python
from emergent.wire.axis.surface.codecs import transition, Done

@dataclass
class BetFlow:
    bet_type: Option[str] = field(default_factory=Nothing)
    amount: Option[int] = field(default_factory=Nothing)

    @transition
    async def telegram(self, bet_type: Option[BetType], msg: MessageCute) -> "BetFlow | Done":
        if not self.bet_type:
            await msg.answer("Choose your bet:", reply_markup=keyboard)
            match bet_type:
                case Some(bt):
                    return replace(self, bet_type=Some(bt))
            return self
        return Done()

    @transition
    async def cli(self, bet_type: Option[str], amount: Option[int]) -> "BetFlow | tuple[BetFlow, str] | Done":
        match (self.bet_type, bet_type):
            case (Nothing(), Some(bt)):
                return replace(self, bet_type=Some(bt)), "Enter amount:"
        return self

    def to_domain(self) -> PlaceBet:
        return PlaceBet(bet=self.bet_type.unwrap(), amount=self.amount.unwrap())
```

When the flow runs in a Telegram context, `MessageCute` is resolvable in the nodnod scope, so `telegram()` gets called. In a CLI context, `MessageCute` isn't available but the CLI arguments are, so `cli()` wins. First resolvable transition fires. Same flow class, same `to_domain()`, different interaction patterns.

If no `@transition` decorators are found, the codec falls back to `__transition__`. You don't need multi-transport if you only target one.

## Wiring it up

The `stateful()` builder connects everything:

```python
from emergent.wire.axis.surface.codecs import stateful

endpoint(runner).expose(
    TelegrinderTrigger(...),
    stateful(RegistrationFlow, UserResponse).key(ChatId).build(),
)
```

`.key(ChatId)` sets the session routing --- each Telegram chat gets its own flow instance. `.store(...)` optionally sets a custom state store (defaults to `MemoryStorage`). `.build()` produces the `StatefulCodec`, which validates that your flow class has either `__transition__` or `@transition` methods and a `to_domain()`.

The builder enforces the contract at wiring time, not at runtime. Missing `to_domain()`? Error before the server starts.

## The insight

The `rrc` codec assumes all input arrives at once. The stateful codec assumes it arrives across turns. But the endpoint structure is identical --- a runner, a trigger, a codec, capabilities. The only difference is the codec type. HTTP gets `rrc`. Telegram gets `stateful`. Same endpoint definition, different codec. The sheaf in action: one abstract endpoint, projected differently onto each transport fiber.

Conversations aren't a special feature bolted onto the side. They're a codec --- the same kind of codec as `rrc`, `immediate`, or `delegate`. The surface axis doesn't know or care how many turns it takes to collect the input. It just knows: codec in, Op out.

---

**Next:** [Putting It All Together ->](23-roulette.md)
