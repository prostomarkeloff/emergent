# derivelib.patterns.tg — Telegram Patterns

Telegram-specific derivation patterns built on top of emergent's wire framework and telegrinder.
One `TGApp` coordinator owns all sub-patterns for an application — shared `key_node`, `theme`, and collision-safe `CallbackRegistry`.

## Quick Start

```python
from derivelib import derive
from derivelib.patterns.tg.app import TGApp
from derivelib.patterns.tg.widget import TextInput, Inline, ContactInput, Either, Pattern
from derivelib.patterns.tg.browse import query, action, ActionResult, BrowseSource
from derivelib.patterns.tg.flow import FinishResult, with_cancel

tg = TGApp(key_node=UserId)

# Multi-step conversation
@derive(tg.flow("register", description="Sign up").chain(with_cancel()))
@dataclass
class Registration:
    name: Annotated[str, TextInput("Your name?")]
    role: Annotated[str, Inline("Pick role:", admin="Admin", user="User")]

    @classmethod
    async def finish(cls, name: str, role: str) -> FinishResult:
        return FinishResult.message(f"Welcome, {name}!")

# Paginated list
@derive(tg.browse("tasks", provider_node=TaskStore, description="View tasks"))
@dataclass
class TaskCard:
    id: Annotated[int, Identity]
    title: str

    @classmethod
    @query
    async def listing(cls, store: ...) -> BrowseSource[TaskCard]: ...

    @classmethod
    @action("Complete")
    async def complete(cls, task: TaskCard) -> ActionResult:
        return ActionResult.refresh("Done!")

# Single-entity dashboard
@derive(tg.dashboard("roulette", description="Spin"))
@dataclass
class RouletteTable:
    id: Annotated[int, Identity]
    bet: int = 50

    @classmethod
    @query
    async def table(cls, uid: ...) -> RouletteTable: ...

    @classmethod
    @action("Spin")
    async def spin(cls, t: RouletteTable) -> ActionResult:
        return ActionResult.refresh("You won!")

# Settings page
@derive(tg.settings("config"))
@dataclass
class BotConfig:
    volume: Annotated[int, Counter("Volume:", min_val=0, max_val=100)]
```

---

## Module Map

```
app.py           TGApp — coordinator, creates sub-patterns
flow.py          tg_flow — multi-step conversation (StatefulCodec)
widget.py        FlowWidget protocol + 30 concrete widgets
browse.py        tg_browse — paginated entity list (DelegateCodec)
dashboard.py     tg_dashboard — single-entity card (DelegateCodec)
search.py        tg_search — search prompt + paginated results
settings.py      tg_settings — inline field editing
methods.py       tg_command / tg_callback / tg_delegate decorators
registry.py      CallbackRegistry — command/callback collision detection
_shared.py       Shared runtime helpers for browse/dashboard/search
uilib/           Configurable theme, keyboard builders, widget helpers
```

### Dependency Graph

```
app.py ──► flow.py ──► widget.py ──► uilib/helpers.py
  │                                       │
  ├──► browse.py ◄── _shared.py      uilib/keyboard.py
  │         ▲             ▲               ▲
  ├──► dashboard.py ──────┤          browse.py
  ├──► search.py ─────────┘          _shared.py
  ├──► settings.py
  ├──► registry.py
  └──► uilib/theme.py
```

Rule: `_shared.py` imports from `browse.py` (one-way). Dashboard, search, and settings import helpers from `_shared.py`.

---

## TGApp

Central coordinator. Creates sub-patterns with shared `key_node` + `theme` and validates command/callback uniqueness eagerly.

```python
tg = TGApp(
    key_node=UserId,                    # nodnod node for session routing
    theme=UITheme(action=ActionUI(done="Готово ✓")),  # optional theme override
    agent_cls=MyAgent,                  # optional custom agent
    family=my_family,                   # optional scope family
)
```

| Method | Returns | Description |
|--------|---------|-------------|
| `tg.flow(command, ...)` | `TGFlowPattern` | Multi-step conversation |
| `tg.browse(command, provider_node, ...)` | `TGBrowsePattern` | Paginated entity list |
| `tg.dashboard(command, ...)` | `TGDashboardPattern` | Single-entity card |
| `tg.settings(command, ...)` | `TGSettingsPattern` | Settings with inline editing |
| `tg.search(command, ...)` | `TGSearchPattern` | Search prompt + results |
| `tg.commands` | `Sequence[CommandEntry]` | All registered commands (for /help) |
| `tg.compile(app)` | `Dispatch` | Compile wire Application to telegrinder |

All methods accept `description: str` and `order: int` for `/help` generation.

---

## Patterns

### tg_flow — Multi-Step Conversation

Compiles annotated dataclass fields into a `StatefulCodec` flow. Each field becomes a conversation step with a widget for user input.

```python
@derive(tg.flow("register", description="Sign up"))
@dataclass
class Registration:
    name: Annotated[str, TextInput("Your name?")]
    role: Annotated[str, Inline("Pick role:", admin="Admin", user="User")]
    phone: Annotated[str, Either(
        ContactInput("Share your phone:"),
        TextInput("Or type it manually:"),
    ), Pattern(r"^\+?\d{10,15}$")]

    @classmethod
    async def finish(cls, name: str, role: str, phone: str) -> FinishResult:
        # Called when all fields are collected
        return FinishResult.message(f"Welcome, {name}!")
```

#### Field Annotations

Each field needs exactly one `FlowWidget` (or `Prefilled`) in its `Annotated` metadata. Validators (`MinLen`, `MaxLen`, `Pattern`) are collected separately and passed to the widget via `WidgetContext`.

| Annotation | Purpose |
|------------|---------|
| `TextInput("prompt")` | Collect text from message |
| `Inline("prompt", **options)` | Inline keyboard single selection |
| `Confirm("prompt")` | Yes/No |
| `ContactInput("prompt")` | Telegram contact share |
| `Either(primary, secondary)` | Try primary widget, fall back on Reject |
| `Prefilled()` | Pre-filled from redirect context, not prompted |
| `When(lambda v: ...)` | Conditional field — only prompted when predicate is True |
| `MinLen(n)` / `MaxLen(n)` | Text length validation |
| `Pattern(r"...")` | Regex validation |

#### FinishResult

The `finish()` classmethod returns a `FinishResult` that controls what happens after the flow completes:

```python
FinishResult.message("Done!")                          # Simple text response
FinishResult.then("Saved!", "next_command", id=42)     # Text + redirect
FinishResult.sub_flow("OK", "child_flow", parent_id=1) # Push stack, start sub-flow
FinishResult.with_keyboard("Pick:", markup)             # Text + custom keyboard
```

#### Transforms (DerivationT)

Chain transforms after `.chain()` to modify flow behavior:

```python
@derive(tg.flow("register").chain(
    with_cancel(),       # Add /cancel command
    with_back(),         # Add /back command (previous step)
    with_stacking(),     # Enable sub-flow stacking
    with_progress(),     # Show step progress bar [3/10]
    with_summary(),      # Confirmation step before finish
    with_show_mode(ShowMode.EDIT),      # Edit messages in place
    with_launch_mode(LaunchMode.RESET), # Reset on re-entry
))
```

| Transform | Effect |
|-----------|--------|
| `with_cancel()` | Adds `/cancel` to abort the flow |
| `with_back()` | Adds `/back` to go to previous step |
| `with_stacking(stack?)` | Enables `FinishResult.sub_flow()` |
| `with_progress()` | Visual step indicator |
| `with_summary()` | Auto-generated summary confirmation before finish |
| `with_show_mode(mode)` | `SEND` (default), `EDIT`, `DELETE_AND_SEND` |
| `with_launch_mode(mode)` | `STANDARD`, `RESET`, `EXCLUSIVE`, `SINGLE_TOP` |

#### ShowMode

| Mode | Behavior |
|------|----------|
| `SEND` | Always send a new message (default) |
| `EDIT` | Edit the previous message in place |
| `DELETE_AND_SEND` | Delete old + send new (for media type changes) |

#### LaunchMode

| Mode | Behavior |
|------|----------|
| `STANDARD` | Command text treated as field input (default) |
| `RESET` | Reset flow, start fresh |
| `EXCLUSIVE` | Block with "already in progress" message |
| `SINGLE_TOP` | Re-send current prompt, continue where left off |

---

### tg_browse — Paginated Entity List

Compiles annotated entity into `DelegateCodec` handlers: command shows first page, callback handles prev/next + action buttons.

```python
@derive(tg.browse("tasks", provider_node=TaskStore, page_size=5))
@dataclass
class TaskCard:
    id: Annotated[int, Identity]
    title: str
    status: str

    @classmethod
    @query
    async def listing(cls, store: ...) -> BrowseSource[TaskCard]:
        items = await store.fetch_all()
        return ListBrowseSource(items)

    @classmethod
    @action("Complete", row=0)
    async def complete(cls, task: TaskCard) -> ActionResult:
        await do_complete(task.id)
        return ActionResult.refresh("Completed!")

    @classmethod
    @action("Delete", row=0)
    async def delete(cls, task: TaskCard) -> ActionResult:
        return ActionResult.confirm("Are you sure?")

    @classmethod
    @format_card
    def render(cls, task: TaskCard) -> str:
        return f"*{task.title}*\nStatus: {task.status}"
```

#### Decorators

| Decorator | Marks | Signature |
|-----------|-------|-----------|
| `@query` | Data source factory | `(cls, ...) -> BrowseSource[T]` |
| `@action("Label", row=0)` | Entity action button | `(cls, entity: T) -> ActionResult` |
| `@format_card` | Custom card renderer | `(cls, entity: T) -> str` |
| `@view_filter("Label", key="k")` | Filter tab | Stacks on `@query` method |

#### BrowseSource Protocol

```python
@runtime_checkable
class BrowseSource[T_co](Protocol):
    async def fetch_page(self, offset: int, limit: int) -> Sequence[T_co]: ...
    async def count(self) -> int: ...
```

`ListBrowseSource[T]` is an in-memory implementation wrapping a `list[T]`.

#### ActionResult

```python
ActionResult.refresh("Updated!")           # Re-render current page
ActionResult.stay("Noted.")               # Show message, keep page
ActionResult.redirect("other_command")    # Redirect to another command
ActionResult.confirm("Are you sure?")     # Confirmation dialog first
```

#### View Filters (Tabs)

```python
@classmethod
@query
@view_filter("All", key="all")
@view_filter("Active", key="active")
@view_filter("Done", key="done")
async def listing(cls, store: ...) -> BrowseSource[TaskCard]:
    # filter_key injected via DI when filter is active
    ...
```

Tabs appear as a row of buttons above the navigation.

---

### tg_dashboard — Single-Entity Card

Like `tg_browse` but without pagination. The `@query` returns the entity directly (not `BrowseSource`). Ideal for dashboards, game tables, status pages.

```python
@derive(tg.dashboard("roulette"))
@dataclass
class RouletteTable:
    id: Annotated[int, Identity]
    bet: int = 50
    balance: int = 1000

    @classmethod
    @query
    async def table(cls, uid: ...) -> RouletteTable:
        return RouletteTable(id=1, bet=50, balance=1000)

    @classmethod
    @action("Spin")
    async def spin(cls, t: RouletteTable) -> ActionResult:
        return ActionResult.refresh("You won 100!")

    @classmethod
    @action("Change bet")
    async def change_bet(cls, t: RouletteTable) -> ActionResult:
        return ActionResult.redirect("set_bet")
```

Same decorators as browse: `@query`, `@action`, `@format_card`, `@view_filter`.

---

### tg_search — Search-First Browsing

Like `tg_browse`, but starts with a text prompt. User sends a query, then browses paginated results.

```python
@derive(tg.search("find", prompt="What are you looking for?"))
@dataclass
class SearchResult:
    id: Annotated[int, Identity]
    title: str

    @classmethod
    @query
    async def results(cls, store: ...) -> BrowseSource[SearchResult]:
        # search_query injected via DI
        ...
```

Creates three exposures: command handler (sends prompt), text handler (captures query, shows results), callback handler (nav + actions).

---

### tg_settings — Inline Field Editing

Shows current values, tap a field to edit with its widget, save on confirm.

```python
@derive(tg.settings("config"))
@dataclass
class BotConfig:
    volume: Annotated[int, Counter("Volume:", min_val=0, max_val=100)]
    language: Annotated[str, Inline("Language:", en="English", ru="Russian")]

    @classmethod
    @query
    async def current(cls) -> BotConfig:
        return BotConfig(volume=50, language="en")

    @classmethod
    @on_save
    async def save(cls, config: BotConfig) -> None:
        await db.save(config)
```

The overview keyboard shows one button per field with its current value. Tapping enters edit mode with the field's widget. Saving calls `@on_save`.

| Decorator | Purpose |
|-----------|---------|
| `@query` | Load current settings |
| `@on_save` | Persist after edit |
| `@format_settings` | Custom overview renderer |

---

### methods — Trigger Decorators

Thin wrappers for exposing individual classmethods as TG handlers without a full pattern.

```python
@derive(some_pattern)
@dataclass
class MyBot:
    # Standard RRC-based command
    @classmethod
    @tg_command("start", description="Start the bot", order=1)
    async def start(cls) -> Result[str, DomainError]:
        return Ok("Hello!")

    # Typed callback payload
    @classmethod
    @tg_callback(MoveCard)
    async def move(cls, data: MoveCard) -> Result[str, DomainError]: ...

    # Full telegrinder access (DelegateCodec)
    @classmethod
    @tg_delegate(Command("comments"), description="Show comments")
    async def show_comments(cls, message: MessageCute, db: ...) -> None:
        await message.answer("Comments:", reply_markup=kb.get_markup())
```

| Decorator | Codec | Access Level |
|-----------|-------|-------------|
| `tg_command(name)` | RRC (Request→Run→Codec) | Op + Result types |
| `tg_callback(model)` | RRC | Op + Result types |
| `tg_delegate(*rules)` | DelegateCodec | Raw telegrinder types + compose.Node DI |

---

## Widgets

All widgets implement the `FlowWidget` protocol:

```python
@runtime_checkable
class FlowWidget(Protocol):
    @property
    def prompt(self) -> str: ...

    @property
    def needs_callback(self) -> bool: ...

    async def render(self, ctx: WidgetContext) -> tuple[str, AnyKeyboard | None]: ...
    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> WidgetResult: ...
    async def handle_callback(self, value: str, ctx: WidgetContext) -> WidgetResult: ...
```

Adding a new widget = one new class, zero changes to `flow.py`.

### Result Algebra

Every `handle_message` / `handle_callback` returns one of:

| Type | Effect |
|------|--------|
| `Advance(value, summary)` | Store value, move to next field |
| `Stay(new_value)` | Re-render without advancing (Counter +/-, Multiselect toggle) |
| `Reject(message)` | Show error, re-prompt |
| `NoOp()` | Do nothing (e.g. Counter noop button) |

### Widget Catalog

#### Text & Number

| Widget | Constructor | Value Type | Description |
|--------|-------------|------------|-------------|
| `TextInput` | `TextInput("Name?")` | `str/int/float/bool` | Collect text, auto-coerces to field type |
| `NumberInput` | `NumberInput("Amount?", shortcuts=[10, 50, 100])` | `int/float` | Numeric input with optional quick-select buttons |
| `PinInput` | `PinInput("Enter PIN:", length=4)` | `str` | PIN/code entry with numpad keyboard |

#### Selection

| Widget | Constructor | Value Type | Description |
|--------|-------------|------------|-------------|
| `Inline` | `Inline("Pick:", a="A", b="B")` | `str` | Inline keyboard single selection |
| `Radio` | `Radio("Pick:", a="A", b="B")` | `str` | Single-select with visible state + Done |
| `Confirm` | `Confirm("Sure?")` | `bool` | Yes/No |
| `Toggle` | `Toggle("Enabled:", on="On", off="Off")` | `bool` | One-tap boolean flip |
| `EnumInline` | `EnumInline("Status:", MyEnum)` | `Enum` | Auto-generated from Python Enum |
| `ScrollingInline` | `ScrollingInline("Pick:", items, page_size=5)` | `str` | Paginated inline for large sets |

#### Multi-Selection

| Widget | Constructor | Value Type | Description |
|--------|-------------|------------|-------------|
| `Multiselect` | `Multiselect("Tags:", a="A", b="B")` | `str` | Toggle multiple items, comma-separated keys |

#### Date & Time

| Widget | Constructor | Value Type | Description |
|--------|-------------|------------|-------------|
| `DatePicker` | `DatePicker("When?")` | `date` | Calendar with day/month/year views |
| `TimePicker` | `TimePicker("Time?")` | `time` | Hour then minute selection |
| `TimeSlotPicker` | `TimeSlotPicker("Slot?")` | `str` | Available slots grouped by date (via `@options`) |
| `RecurrencePicker` | `RecurrencePicker("Schedule?")` | `str` | Weekdays + time (e.g. `"0,2,4@10:30"`) |

#### Numeric Controls

| Widget | Constructor | Value Type | Description |
|--------|-------------|------------|-------------|
| `Counter` | `Counter("Volume:", min_val=0, max_val=100, step=5)` | `int` | Interactive +/- stepper |
| `Slider` | `Slider("Brightness:", min_val=0, max_val=100)` | `int` | Visual range slider with progress bar |
| `Rating` | `Rating("Rate:", max_stars=5)` | `int` | Star rating selection |

#### Media

| Widget | Constructor | Value Type | Description |
|--------|-------------|------------|-------------|
| `PhotoInput` | `PhotoInput("Send photo:")` | `str` | Photo file_id |
| `DocumentInput` | `DocumentInput("Send file:")` | `str` | Document file_id |
| `VideoInput` | `VideoInput("Send video:")` | `str` | Video file_id |
| `VoiceInput` | `VoiceInput("Record voice:")` | `str` | Voice file_id |
| `LocationInput` | `LocationInput("Share location:")` | `tuple[float, float]` | Latitude, longitude |
| `ContactInput` | `ContactInput("Share phone:")` | `str` | Phone number from contact |
| `MediaGroupInput` | `MediaGroupInput("Send media:", max_items=5)` | `list[str]` | Multiple media file_ids |

#### Lists & Compound

| Widget | Constructor | Value Type | Description |
|--------|-------------|------------|-------------|
| `ListBuilder` | `ListBuilder("Add items:", max_items=10)` | `list[str]` | Variable-length text list |
| `SummaryReview` | `SummaryReview()` | `bool` | Review all collected values before confirm |

#### Combinators & Conditional

| Widget | Constructor | Value Type | Description |
|--------|-------------|------------|-------------|
| `Either` | `Either(ContactInput(...), TextInput(...))` | depends | Try primary, fall back to secondary on Reject |
| `Case` | `Case("field", a=TextInput(...), b=Inline(...))` | depends | Conditional widget based on another field's value |

#### Dynamic Options (via `@options`)

| Widget | Constructor | Value Type | Description |
|--------|-------------|------------|-------------|
| `DynamicInline` | `DynamicInline("Pick:")` | `str` | Inline with options from `@options` provider |
| `DynamicRadio` | `DynamicRadio("Pick:")` | `str` | Radio with dynamic options |
| `DynamicMultiselect` | `DynamicMultiselect("Pick:")` | `str` | Multiselect with dynamic options |

Dynamic options use the `@options` decorator:

```python
@classmethod
@options("project")
async def load_projects(cls, db: ...) -> dict[str, str]:
    return {str(p.id): p.name for p in await db.all()}
```

### Either Combinator

`Either(primary, secondary)` tries the primary widget first. If primary returns `Reject`, it falls back to the secondary widget. Both widgets are rendered: primary's keyboard + secondary's prompt text.

```python
phone: Annotated[str, Either(
    ContactInput("Share your phone:"),
    TextInput("Or type it manually:"),
), Pattern(r"^\+?\d{10,15}$")]
```

Validators (`Pattern`, `MinLen`, `MaxLen`) are collected separately by the flow and passed via `WidgetContext`. ContactInput ignores validators (extracts phone directly from the contact). TextInput applies them via `_validate_text()`.

---

## UITheme

All icons, labels, error messages, and format patterns are configurable through `UITheme`. Override only what you need:

```python
ru_theme = UITheme(
    nav=NavUI(prev_label="◀️ Назад", next_label="Далее ▶️"),
    action=ActionUI(done="Готово ✓", yes="Да", no="Нет", cancel="Отменено."),
    errors=ErrorUI(
        send_text="Отправьте текстовое сообщение.",
        too_short="Минимум {length} символов.",
    ),
)

tg = TGApp(key_node=UserId, theme=ru_theme)
```

### Theme Sections

| Section | Class | Controls |
|---------|-------|----------|
| `nav` | `NavUI` | Prev/Next arrows, Back label |
| `selection` | `SelectionUI` | Check/radio/toggle/tab icons |
| `action` | `ActionUI` | Done, OK, Yes/No, Cancel, +/- labels |
| `display` | `DisplayUI` | None display, bool labels, date format, page format |
| `errors` | `ErrorUI` | All 24 error/rejection messages |

---

## CallbackRegistry

`TGApp` internally uses `CallbackRegistry` to detect command and callback prefix collisions at pattern-creation time (not at runtime):

```python
tg = TGApp(key_node=UserId)

tg.flow("start")         # OK
tg.browse("tasks")       # OK
tg.browse("start")       # CommandCollision! "start" already registered
tg.dashboard("d", cb_prefix="tasks")  # CallbackCollision! prefix "tasks" taken
```

Flow and settings use SHA256 hashes for callback data (collision-resistant). Browse, dashboard, and search use short prefixes (first 6 chars of command by default, or explicit `cb_prefix`).

---

## DI in Handlers

All pattern handlers (flow `finish()`, browse `@query`/`@action`, dashboard, search, settings) support compose.Node dependency injection:

```python
from emergent.wire.axis.schema.dialects.compose import Node

@classmethod
@query
async def listing(cls, store: Annotated[TaskStore, Node(TaskStoreNode)]) -> BrowseSource[TaskCard]:
    return ListBrowseSource(await store.all())

@classmethod
@action("Complete")
async def complete(cls, task: TaskCard, store: Annotated[TaskStore, Node(TaskStoreNode)]) -> ActionResult:
    await store.complete(task.id)
    return ActionResult.refresh("Completed!")
```

Unannotated params are resolved by type from the nodnod scope, then via nodnod node composition as fallback.
