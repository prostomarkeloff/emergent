"""bot_builder — A Telegram bot that builds Telegram bots. Ultimate dogfooding.

Every feature of the builder is expressed through the same derivelib patterns
that the generated bots will use. The builder IS the showcase.

    /new        — create entity definition          (tg_flow + Inline)
    /field      — add field to entity               (tg_flow + DynamicInline + When)
    /entities   — browse defined entities            (tg_browse + actions)
    /code       — generate full project code        (tg_delegate)
    /preview    — preview single entity code        (tg_flow + DynamicInline)
    /transforms — toggle transforms on entity       (tg_flow + DynamicInline + Multiselect)
    /help       — command reference                 (tg_command)

Meta-moments:
    - Inline widget used to choose Inline widget
    - DynamicInline loads entities you just created
    - When() conditionally shows options field — same When() the generated bot uses
    - with_cancel/with_back on the builder — same transforms you toggle for your bot
    - tg_browse lists your entities — same pattern you can pick for your bot

    BOT_TOKEN=123:ABC uv run python derivelib/examples/bot_builder.py
"""

from __future__ import annotations

import asyncio
import html
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Annotated

from kungfu import Ok, Result
from nodnod import scalar_node  # type: ignore[import-untyped]
from telegrinder.bot.cute_types.message import MessageCute
from telegrinder.bot.rules.command import Command
from telegrinder.node import UserId

from emergent.wire.axis.schema import Identity
from emergent.wire.axis.schema.dialects import compose

from derivelib import build_application_from_decorated, derive, endpoint_count
from derivelib._errors import DomainError
from derivelib.patterns import (
    methods,
    tg_command,
    tg_delegate,
    tg_flow,
    tg_browse,
    TextInput,
    Inline,
    Confirm,
    Multiselect,
    DynamicInline,
    MinLen,
    MaxLen,
    When,
    ShowMode,
    FinishResult,
    FlowWidget,
    WidgetContext,
    with_cancel,
    with_back,
    with_show_mode,
    BrowseSource,
    ListBrowseSource,
    ActionResult,
    query,
    action,
    format_card,
    options,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Store — in-memory storage for entity/field definitions
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class StoredField:
    """A field definition within a stored entity."""

    name: str
    type: str  # "str", "int", "bool", "float"
    widget: str  # "TextInput", "Inline", "Confirm", etc.
    prompt: str
    options: dict[str, str] = field(default_factory=dict)
    is_optional: bool = False


@dataclass
class StoredEntity:
    """A complete entity definition — maps to one @derive'd class."""

    name: str
    pattern: str  # "tg_flow", "tg_browse", "tg_settings"
    command: str
    description: str
    fields: list[StoredField] = field(default_factory=list)
    transforms: list[str] = field(default_factory=list)
    finish_description: str = ""


class BuilderStore:
    """In-memory store for entity definitions."""

    def __init__(self) -> None:
        self._entities: dict[str, StoredEntity] = {}

    def add_entity(self, entity: StoredEntity) -> None:
        self._entities[entity.name] = entity

    def get(self, name: str) -> StoredEntity | None:
        return self._entities.get(name)

    def remove(self, name: str) -> bool:
        return self._entities.pop(name, None) is not None

    def all(self) -> list[StoredEntity]:
        return list(self._entities.values())

    def entity_options(self) -> dict[str, str]:
        """Build DynamicInline options: {name: "Name (/command)"}."""
        return {e.name: f"{e.name} (/{e.command})" for e in self._entities.values()}

    def add_field(self, entity_name: str, fld: StoredField) -> bool:
        entity = self._entities.get(entity_name)
        if entity is None:
            return False
        entity.fields.append(fld)
        return True

    def set_transforms(self, entity_name: str, transforms: list[str]) -> bool:
        entity = self._entities.get(entity_name)
        if entity is None:
            return False
        entity.transforms = transforms
        return True


_STORE = BuilderStore()


@scalar_node
class StoreNode:
    @classmethod
    def __compose__(cls) -> BuilderStore:
        return _STORE


# ═══════════════════════════════════════════════════════════════════════════════
# Codegen — StoredEntity → Python source code (LLM-enhanced)
# ═══════════════════════════════════════════════════════════════════════════════

_ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Widget classification (kept for AddField preview)
_OPTION_WIDGETS = frozenset({"Inline", "Radio", "Multiselect", "ScrollingInline"})
_PROMPT_ONLY_WIDGETS = frozenset({
    "TextInput", "Confirm", "Counter", "DatePicker",
    "ContactInput", "PhotoInput", "DocumentInput",
    "LocationInput", "VideoInput", "VoiceInput",
})


def _gen_widget(f: StoredField) -> str:
    """Generate widget annotation string for a single field."""
    if f.widget in _OPTION_WIDGETS and f.options:
        opts = ", ".join(f'{k}="{v}"' for k, v in f.options.items())
        return f'{f.widget}("{f.prompt}", {opts})'
    return f'{f.widget}("{f.prompt}")'


def _gen_field_line(f: StoredField) -> str:
    """Generate one field line: name: Annotated[type, Widget(...)]."""
    type_str = f"{f.type} | None" if f.is_optional else f.type
    widget_str = _gen_widget(f)
    return f"    {f.name}: Annotated[{type_str}, {widget_str}]"


def _default_for_type(type_str: str) -> str:
    """Python default literal for a type string."""
    return {"str": '""', "int": "0", "float": "0.0", "bool": "False"}.get(type_str, '""')


# ── LLM integration ──────────────────────────────────────────────────────────

_CODEGEN_SYSTEM = (
    "You generate Python method bodies for derivelib Telegram bot entities.\n"
    "Use HTML tags for Telegram formatting: <b>, <i>, <code>.\n"
    "Return ONLY valid Python code. No markdown fences. No explanations. No commentary.\n"
    "Use 4-space indentation (class-level methods).\n"
    "Available: Ok, Result, FinishResult, DomainError, BrowseSource, "
    "ListBrowseSource, compose, Annotated.\n"
    "Decorators: @classmethod, @query, @format_card, @on_save."
)


async def _llm_complete(prompt: str) -> str:
    """Call Anthropic Claude API. Returns empty string on failure."""
    if not _ANTHROPIC_KEY:
        return ""
    try:
        import rnet as _rnet

        resp = await _rnet.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": _ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            body=json.dumps({
                "model": "claude-sonnet-4-5-20250929",
                "max_tokens": 2048,
                "system": _CODEGEN_SYSTEM,
                "messages": [{"role": "user", "content": prompt}],
            }),
        )
        data = json.loads(await resp.text())
        text = data.get("content", [{}])[0].get("text", "")
        # Strip markdown fences if LLM included them
        if text.startswith("```"):
            lines = text.splitlines()
            start = 1 if lines[0].startswith("```") else 0
            end = -1 if lines[-1].strip() == "```" else len(lines)
            text = "\n".join(lines[start:end])
        return text.strip()
    except Exception:
        return ""


def _fields_description(e: StoredEntity, prefix: str = "self") -> str:
    """Human-readable field description for LLM prompts."""
    if not e.fields:
        return "(no fields)"
    lines: list[str] = []
    for f in e.fields:
        extra = ""
        if f.options:
            opts = ", ".join(f"{k}={v}" for k, v in f.options.items())
            extra = f" (choices: {opts})"
        if f.is_optional:
            extra += " [optional, may be None]"
        lines.append(f"- {prefix}.{f.name}: {f.type} — \"{f.prompt}\"{extra}")
    return "\n".join(lines)


# ── LLM method generators ────────────────────────────────────────────────────

async def _llm_flow_methods(e: StoredEntity) -> str:
    return await _llm_complete(
        f"Generate the finish() method for Telegram bot flow \"{e.name}\".\n"
        f"Description: {e.description}\n"
        f"Command: /{e.command}\n\n"
        f"Fields collected from user (access via self.field_name):\n"
        f"{_fields_description(e)}\n\n"
        f"Signature:\n"
        f"    async def finish(self) -> Result[FinishResult, DomainError]:\n\n"
        f"Return Ok(FinishResult.message(\"...\")) with HTML summary of collected data.\n"
        f"Include ALL field values. Make it informative and user-friendly.\n"
        f"Return the complete method with 4-space indent."
    )


async def _llm_browse_methods(e: StoredEntity) -> str:
    store_node = f"{e.name}StoreNode"
    store_type = f"list[{e.name}]"
    return await _llm_complete(
        f"Generate two methods for browse entity \"{e.name}\" — {e.description}.\n\n"
        f"Card fields:\n{_fields_description(e, prefix='card')}\n\n"
        f"Method 1:\n"
        f"    @classmethod\n"
        f"    @query\n"
        f"    async def load(\n"
        f"        cls,\n"
        f"        store: Annotated[{store_type}, compose.Node({store_node})],\n"
        f"    ) -> BrowseSource[{e.name}]:\n"
        f"Return ListBrowseSource(store) to serve items from the injected store.\n\n"
        f"Method 2:\n"
        f"    @classmethod\n"
        f"    @format_card\n"
        f"    def render(cls, card: {e.name}) -> str:\n"
        f"Format all fields into nice HTML.\n\n"
        f"Return both methods, 4-space indent. Include decorators."
    )


async def _llm_settings_methods(e: StoredEntity) -> str:
    defaults = ", ".join(
        f"{f.name}={_default_for_type(f.type)}" for f in e.fields
    )
    return await _llm_complete(
        f"Generate two methods for settings entity \"{e.name}\" — {e.description}.\n\n"
        f"Fields:\n{_fields_description(e)}\n\n"
        f"Method 1:\n"
        f"    @classmethod\n"
        f"    @query\n"
        f"    async def load(cls) -> {e.name}:\n"
        f"Return {e.name}({defaults}) with sensible defaults.\n\n"
        f"Method 2:\n"
        f"    @classmethod\n"
        f"    @on_save\n"
        f"    async def save(cls, settings: {e.name}) -> None:\n"
        f"Log or pass.\n\n"
        f"Return both methods, 4-space indent. Include decorators."
    )


# ── Fallback generators (no LLM) ─────────────────────────────────────────────

def _fallback_flow_methods(e: StoredEntity) -> str:
    lines = ["    async def finish(self) -> Result[FinishResult, DomainError]:"]
    if not e.fields:
        lines.append(f'        return Ok(FinishResult.message("<b>{e.name}</b> submitted!"))')
    else:
        lines.append(f'        msg = "<b>{e.name}</b> submitted!\\n"')
        for f in e.fields:
            lines.append(f'        msg += f"\\n<b>{f.name}:</b> {{self.{f.name}}}"')
        lines.append("        return Ok(FinishResult.message(msg))")
    return "\n".join(lines)


def _fallback_browse_methods(e: StoredEntity) -> str:
    store_type = f"list[{e.name}]"
    store_node = f"{e.name}StoreNode"
    lines = [
        "    @classmethod",
        "    @query",
        "    async def load(",
        "        cls,",
        f"        store: Annotated[{store_type}, compose.Node({store_node})],",
        f"    ) -> BrowseSource[{e.name}]:",
        "        return ListBrowseSource(store)",
        "",
        "    @classmethod",
        "    @format_card",
        f"    def render(cls, card: {e.name}) -> str:",
    ]
    if e.fields:
        lines.append("        return (")
        lines.append(f'            f"<b>{e.name}</b>\\n"')
        for f in e.fields:
            lines.append(f'            f"<b>{f.name}:</b> {{card.{f.name}}}\\n"')
        lines.append("        )")
    else:
        lines.append(f'        return f"<b>{e.name}</b>"')
    return "\n".join(lines)


def _fallback_settings_methods(e: StoredEntity) -> str:
    defaults = ", ".join(
        f"{f.name}={_default_for_type(f.type)}" for f in e.fields
    )
    return "\n".join([
        "    @classmethod",
        "    @query",
        f"    async def load(cls) -> {e.name}:",
        f"        return {e.name}({defaults})",
        "",
        "    @classmethod",
        "    @on_save",
        f"    async def save(cls, settings: {e.name}) -> None:",
        "        pass",
    ])


# ── Main generators ──────────────────────────────────────────────────────────

async def _get_methods(e: StoredEntity) -> str:
    """Get methods for entity — LLM if available, fallback otherwise."""
    if _ANTHROPIC_KEY:
        llm_fn = {
            "tg_flow": _llm_flow_methods,
            "tg_browse": _llm_browse_methods,
            "tg_settings": _llm_settings_methods,
        }.get(e.pattern)
        if llm_fn is not None:
            result = await llm_fn(e)
            if result:
                return result

    fallback_fn = {
        "tg_flow": _fallback_flow_methods,
        "tg_browse": _fallback_browse_methods,
        "tg_settings": _fallback_settings_methods,
    }.get(e.pattern)
    if fallback_fn is not None:
        return fallback_fn(e)
    return "    pass"


async def generate_entity_code(e: StoredEntity) -> str:
    """Generate Python code for a single entity."""
    fields_code = "\n".join(_gen_field_line(f) for f in e.fields) if e.fields else "    pass"

    if e.pattern == "tg_flow":
        pattern = f'tg_flow(command="{e.command}", key_node=ChatIdNode'
        if e.description:
            pattern += f', description="{e.description}"'
        pattern += ")"
        if e.transforms:
            chain_args = ", ".join(f"{t}()" for t in e.transforms)
            pattern = f"{pattern}.chain(\n        {chain_args},\n    )"

    elif e.pattern == "tg_browse":
        store_node = f"{e.name}StoreNode"
        pattern = (
            f"tg_browse(\n"
            f'        command="{e.command}",\n'
            f"        provider_node={store_node},\n"
            f"        key_node=ChatIdNode"
        )
        if e.description:
            pattern += f',\n        description="{e.description}"'
        pattern += ",\n    )"
        # Ensure id field for browse
        if not any(f.name == "id" for f in e.fields):
            fields_code = "    id: Annotated[int, Identity] = 0\n" + fields_code

    elif e.pattern == "tg_settings":
        pattern = f'tg_settings(command="{e.command}", key_node=ChatIdNode'
        if e.description:
            pattern += f', description="{e.description}"'
        pattern += ")"

    else:
        pattern = f'# unknown pattern "{e.pattern}"'

    methods = await _get_methods(e)
    return f"@derive({pattern})\n@dataclass\nclass {e.name}:\n{fields_code}\n\n{methods}"


def _gen_browse_store(e: StoredEntity) -> str:
    """Generate in-memory store + scalar_node for a browse entity."""
    var = f"_{e.name.lower()}_data"
    node = f"{e.name}StoreNode"
    return (
        f"\n{var}: list[{e.name}] = []\n\n\n"
        f"@scalar_node\n"
        f"class {node}:\n"
        f"    @classmethod\n"
        f"    def __compose__(cls) -> list[{e.name}]:\n"
        f"        return {var}\n"
    )


async def generate_full_project(entities: Sequence[StoredEntity]) -> str:
    """Generate a complete bot.py file from all stored entities."""
    widgets_used: set[str] = set()
    patterns_used: set[str] = set()
    transforms_used: set[str] = set()
    has_browse = False

    for e in entities:
        patterns_used.add(e.pattern)
        if e.pattern == "tg_browse":
            has_browse = True
        for t in e.transforms:
            transforms_used.add(t)
        for f in e.fields:
            widgets_used.add(f.widget)

    # Build import block
    imports = [
        "from __future__ import annotations\n",
        "from dataclasses import dataclass",
        "from typing import Annotated\n",
        "from kungfu import Ok, Result",
        "from nodnod import scalar_node",
        "from telegrinder.node import UserId\n",
        "from emergent.wire.axis.schema import Identity",
    ]

    if has_browse:
        imports.append("from emergent.wire.axis.schema.dialects import compose")

    imports.extend([
        "from derivelib import build_application_from_decorated, derive",
        "from derivelib._errors import DomainError",
    ])

    pattern_imports: list[str] = []
    for p in sorted(patterns_used):
        pattern_imports.append(p)
    for w in sorted(widgets_used):
        pattern_imports.append(w)
    for t in sorted(transforms_used):
        pattern_imports.append(t)

    if "tg_flow" in patterns_used:
        pattern_imports.append("FinishResult")
    if "tg_browse" in patterns_used:
        pattern_imports.extend(["BrowseSource", "ListBrowseSource", "query", "format_card"])
    if "tg_settings" in patterns_used:
        pattern_imports.extend(["query", "on_save"])

    imports.append(
        "from derivelib.patterns import (\n"
        + "".join(f"    {p},\n" for p in sorted(set(pattern_imports)))
        + ")"
    )

    imports.append("\n\nChatIdNode = UserId\n")

    # Generate browse store nodes
    browse_stores: list[str] = []
    for e in entities:
        if e.pattern == "tg_browse":
            browse_stores.append(_gen_browse_store(e))

    # Generate entity code in parallel
    entity_codes = list(await asyncio.gather(*[generate_entity_code(e) for e in entities]))

    # Build application
    entity_names = ", ".join(e.name for e in entities)
    build_block = (
        "\n\napp = build_application_from_decorated(" + entity_names + ")\n"
        "\nfrom emergent.wire.compile.targets import telegrinder as tg_compile\n"
        "dispatch = tg_compile.compile(app)\n"
        "\nif __name__ == \"__main__\":\n"
        "    import os\n"
        "    from telegrinder import API, Telegrinder, Token\n"
        "\n"
        '    token = os.environ.get("BOT_TOKEN", "")\n'
        "    if not token:\n"
        '        print("Set BOT_TOKEN=... to run")\n'
        "    else:\n"
        "        bot = Telegrinder(API(Token(token)), dispatch=dispatch)\n"
        "        bot.run_forever()\n"
    )

    parts = ["\n".join(imports)]
    parts.extend(browse_stores)
    parts.append("\n\n\n".join(entity_codes))
    return "\n".join(parts) + build_block


# ═══════════════════════════════════════════════════════════════════════════════
# Browse card — view model for /entities
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class EntityCard:
    """Browse card for the entity browser."""

    id: Annotated[int, Identity]
    name: str
    pattern: str
    command: str
    field_count: int


# ═══════════════════════════════════════════════════════════════════════════════
# /new — tg_flow: create a new entity definition
#
# Meta: Inline widget is used to choose which pattern (tg_flow/tg_browse/...)
# the generated entity will use.
# ═══════════════════════════════════════════════════════════════════════════════


@derive(tg_flow(command="new", key_node=UserId, description="Create entity").chain(
    with_cancel(), with_back(), with_show_mode(ShowMode.EDIT),
))
@dataclass
class NewEntity:
    name: Annotated[str, TextInput("Entity name (PascalCase, e.g. UserProfile):"), MinLen(2), MaxLen(50)]
    pattern: Annotated[str, Inline("Pattern type:",
        tg_flow="tg_flow — multi-step form",
        tg_browse="tg_browse — paginated list + actions",
        tg_settings="tg_settings — editable settings",
    )]
    cmd: Annotated[str, TextInput("Telegram command (without /, e.g. register):"), MinLen(1), MaxLen(32)]
    description: Annotated[str, TextInput("Short description for /help:"), MaxLen(100)]

    async def finish(
        self,
        store: Annotated[BuilderStore, compose.Node(StoreNode)],
    ) -> Result[FinishResult, DomainError]:
        if store.get(self.name) is not None:
            return Ok(FinishResult.message(
                f"Entity '{self.name}' already exists.\n"
                f"Use /entities to manage existing entities."
            ))

        store.add_entity(StoredEntity(
            name=self.name,
            pattern=self.pattern,
            command=self.cmd,
            description=self.description,
        ))
        return Ok(FinishResult.message(
            f"Entity <b>{self.name}</b> created!\n\n"
            f"Pattern: {self.pattern}\n"
            f"Command: /{self.cmd}\n\n"
            f"Now add fields: /field\n"
            f"Or browse: /entities"
        ))


# ═══════════════════════════════════════════════════════════════════════════════
# /field — tg_flow: add a field to an entity
#
# Meta:
# - DynamicInline loads entities you just created via @options
# - Inline widget lets you choose a widget type (selecting Inline via Inline!)
# - When() conditionally shows options field for Inline/Radio/Multiselect
# ═══════════════════════════════════════════════════════════════════════════════



@derive(tg_flow(command="field", key_node=UserId, description="Add field to entity").chain(
    with_cancel(), with_back(), with_show_mode(ShowMode.EDIT),
))
@dataclass
class AddField:
    entity: Annotated[str, DynamicInline("Select entity to add field to:")]
    field_name: Annotated[str, TextInput("Field name (snake_case, e.g. user_email):"), MinLen(1), MaxLen(50)]
    field_type: Annotated[str, Inline("Python type:",
        str="str — text",
        int="int — whole number",
        bool="bool — yes/no",
        float="float — decimal number",
    )]
    widget: Annotated[str, Inline("Widget type:",
        TextInput="TextInput — free text input",
        Inline="Inline — button selection",
        Confirm="Confirm — yes/no buttons",
        Counter="Counter — +/- stepper",
        Radio="Radio — select with preview",
        DatePicker="DatePicker — calendar picker",
        ContactInput="ContactInput — share phone",
        PhotoInput="PhotoInput — send a photo",
    )]
    prompt: Annotated[str, TextInput("Prompt text shown to user:"), MinLen(1)]
    optional: Annotated[bool, Confirm("Is this field optional (/skip-able)?")]
    options_raw: Annotated[
        str | None,
        TextInput("Enter options, one per line: key=Label\n\nExample:\nadmin=Administrator\nuser=Regular User"),
        When(lambda v: v.get("widget") in ("Inline", "Radio", "Multiselect", "ScrollingInline")),
    ]

    @classmethod
    @options("entity")
    async def load_entities(
        cls,
        store: Annotated[BuilderStore, compose.Node(StoreNode)],
    ) -> dict[str, str]:
        return store.entity_options()

    async def finish(
        self,
        store: Annotated[BuilderStore, compose.Node(StoreNode)],
    ) -> Result[FinishResult, DomainError]:
        # Parse options from raw text
        field_options: dict[str, str] = {}
        if self.options_raw:
            for line in self.options_raw.strip().splitlines():
                line = line.strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    field_options[k.strip()] = v.strip()

        stored_field = StoredField(
            name=self.field_name,
            type=self.field_type,
            widget=self.widget,
            prompt=self.prompt,
            options=field_options,
            is_optional=self.optional,
        )

        if not store.add_field(self.entity, stored_field):
            return Ok(FinishResult.message(f"Entity '{self.entity}' not found."))

        entity = store.get(self.entity)
        count = len(entity.fields) if entity else 0
        widget_preview = _gen_widget(stored_field)

        return Ok(FinishResult.message(
            f"Field added to <b>{self.entity}</b>!\n\n"
            f"<code>{self.field_name}: Annotated[{self.field_type}, {widget_preview}]</code>\n\n"
            f"Total fields: {count}\n\n"
            f"Add more: /field\n"
            f"Set transforms: /transforms\n"
            f"Generate code: /code"
        ))


# ═══════════════════════════════════════════════════════════════════════════════
# /transforms — tg_flow: configure entity transforms
#
# Meta: Multiselect widget used to toggle transforms — the same transforms
# that will appear in the generated .chain() call.
# ═══════════════════════════════════════════════════════════════════════════════


@derive(tg_flow(command="transforms", key_node=UserId, description="Set entity transforms").chain(
    with_cancel(), with_show_mode(ShowMode.EDIT),
))
@dataclass
class SetTransforms:
    entity: Annotated[str, DynamicInline("Select entity:")]
    transforms: Annotated[str, Multiselect("Enable transforms:",
        with_cancel="with_cancel — /cancel support",
        with_back="with_back — /back support",
        with_progress="with_progress — step progress bar",
        with_summary="with_summary — review before submit",
    )]

    @classmethod
    @options("entity")
    async def load_entities(
        cls,
        store: Annotated[BuilderStore, compose.Node(StoreNode)],
    ) -> dict[str, str]:
        return store.entity_options()

    async def finish(
        self,
        store: Annotated[BuilderStore, compose.Node(StoreNode)],
    ) -> Result[FinishResult, DomainError]:
        # Parse comma-separated selected keys
        selected = [t.strip() for t in self.transforms.split(",") if t.strip()]
        store.set_transforms(self.entity, selected)

        labels = ", ".join(selected) if selected else "(none)"
        return Ok(FinishResult.message(
            f"Transforms for <b>{self.entity}</b> updated!\n\n"
            f"{labels}\n\n"
            f"Generate code: /code"
        ))


# ═══════════════════════════════════════════════════════════════════════════════
# /entities — tg_browse: browse and manage entity definitions
#
# Meta: tg_browse pattern used to list entities that will themselves
# be tg_browse, tg_flow, or tg_settings patterns.
# ═══════════════════════════════════════════════════════════════════════════════


@derive(tg_browse(
    command="entities",
    provider_node=StoreNode,
    key_node=UserId,
    page_size=5,
    empty_text="No entities yet. Create one: /new",
    description="Browse entities",
))
@dataclass
class EntityBrowser:
    id: Annotated[int, Identity] = 0

    @classmethod
    @query
    async def all_entities(
        cls,
        store: Annotated[BuilderStore, compose.Node(StoreNode)],
    ) -> BrowseSource[EntityCard]:
        cards = [
            EntityCard(
                id=i,
                name=e.name,
                pattern=e.pattern,
                command=e.command,
                field_count=len(e.fields),
            )
            for i, e in enumerate(store.all())
        ]
        return ListBrowseSource(cards)

    @classmethod
    @format_card
    def render(cls, c: EntityCard) -> str:
        return (
            f"<b>{c.name}</b>\n"
            f"/{c.command} — {c.pattern}\n"
            f"Fields: {c.field_count}"
        )

    @classmethod
    @action("📋 Preview")
    async def preview_code(
        cls,
        c: EntityCard,
        store: Annotated[BuilderStore, compose.Node(StoreNode)],
    ) -> ActionResult:
        entity = store.get(c.name)
        if entity is None:
            return ActionResult.stay("Entity not found")
        code = await generate_entity_code(entity)
        # Telegram callback alert max ~200 chars — truncate
        preview = code[:180] + "..." if len(code) > 180 else code
        return ActionResult.stay(preview)

    @classmethod
    @action("🗑 Delete")
    async def delete_entity(
        cls,
        c: EntityCard,
        store: Annotated[BuilderStore, compose.Node(StoreNode)],
    ) -> ActionResult:
        return ActionResult.confirm(f"Delete '{c.name}' and all its fields?")


# ═══════════════════════════════════════════════════════════════════════════════
# /code — tg_delegate: generate full project source
# /preview — tg_delegate: preview single entity code
# /help — tg_command: command reference
# ═══════════════════════════════════════════════════════════════════════════════


@derive(methods)
@dataclass
class BuilderCommands:
    id: Annotated[int, Identity] = 0

    @classmethod
    @tg_delegate(Command("code"), description="Generate full bot.py", order=10)
    async def gen_code(
        cls,
        message: MessageCute,
        store: Annotated[BuilderStore, compose.Node(StoreNode)],
    ) -> None:
        entities = store.all()
        if not entities:
            await message.answer("No entities defined yet.\n\nStart with /new")
            return

        if _ANTHROPIC_KEY:
            await message.answer("Generating code with AI...")

        code = await generate_full_project(entities)

        if len(code) > 4000:
            # Send as document for large codebases
            from io import BytesIO
            buf = BytesIO(code.encode("utf-8"))
            buf.name = "bot.py"
            await message.answer_document(
                document=buf,
                caption=(
                    f"Generated bot.py\n"
                    f"{len(entities)} entities, "
                    f"{sum(len(e.fields) for e in entities)} fields"
                ),
            )
        else:
            escaped = html.escape(code)
            await message.answer(f"<pre>{escaped}</pre>")

    @classmethod
    @tg_delegate(Command("preview"), description="Preview single entity code", order=11)
    async def preview_entity(
        cls,
        message: MessageCute,
        store: Annotated[BuilderStore, compose.Node(StoreNode)],
    ) -> None:
        entities = store.all()
        if not entities:
            await message.answer("No entities defined yet.\n\nStart with /new")
            return

        # Show all entity previews — generate in parallel
        codes = list(await asyncio.gather(*[generate_entity_code(e) for e in entities]))
        parts: list[str] = []
        for e, code in zip(entities, codes):
            escaped = html.escape(code)
            parts.append(f"<b>{e.name}</b>\n<pre>{escaped}</pre>")

        text = "\n\n".join(parts)
        if len(text) > 4000:
            for e, code in zip(entities, codes):
                escaped = html.escape(code)
                await message.answer(f"<b>{e.name}</b>\n<pre>{escaped}</pre>")
            return

        await message.answer(text)

    @classmethod
    @tg_command("start", description="Welcome", order=0)
    async def start(cls) -> Result[str, DomainError]:
        return Ok(
            "<b>Bot Builder</b> — build Telegram bots via Telegram\n\n"
            "1. /new — create an entity\n"
            "2. /field — add fields with widgets\n"
            "3. /transforms — configure transforms\n"
            "4. /entities — browse & manage\n"
            "5. /code — generate bot.py\n\n"
            "<i>This bot is itself built with derivelib.</i>"
        )

    @classmethod
    @tg_command("help", description="All commands", order=99)
    async def help_cmd(cls) -> Result[str, DomainError]:
        from emergent.wire.compile.targets.telegrinder import generate_help_from_command_rules
        return Ok(generate_help_from_command_rules(
            app, template="/{name} — {description}",
            header="<b>Bot Builder</b>\n\n",
        ))


# ═══════════════════════════════════════════════════════════════════════════════
# Build & run
# ═══════════════════════════════════════════════════════════════════════════════


app = build_application_from_decorated(
    NewEntity,
    AddField,
    SetTransforms,
    EntityBrowser,
    BuilderCommands,
)

from emergent.wire.compile.targets import telegrinder as tg_compile  # noqa: E402

dispatch = tg_compile.compile(app)

if __name__ == "__main__":
    from telegrinder import API, Telegrinder, Token

    n = endpoint_count(app)
    print(f"\n  🔧 Bot Builder")
    print(f"  {n} endpoints derived from 5 entities\n")
    print("  /start       — welcome")
    print("  /new         — create entity")
    print("  /field       — add field")
    print("  /transforms  — set transforms")
    print("  /entities    — browse entities")
    print("  /code        — generate bot.py")
    print("  /preview     — preview entity code")
    print("  /help        — all commands\n")

    import os

    token = os.environ.get("BOT_TOKEN", "")
    if not token:
        print("  Set BOT_TOKEN=... to run\n")
    else:
        bot = Telegrinder(API(Token(token)), dispatch=dispatch)
        bot.run_forever()
