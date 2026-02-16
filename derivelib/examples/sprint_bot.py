"""sprint_bot — agile sprint board, fully derived from domain types.

6 entities. 3 patterns. 25+ Telegram endpoints. Zero routing, zero keyboards.

    /story     — create user story             (flow + EnumInline + NumberInput + Rating
                                                 + DynamicMultiselect + ListBuilder + Radio
                                                 + DatePicker + Case + DynamicRadio + When)
    /bug       — report a bug                  (flow + DynamicInline + PhotoInput + VoiceInput
                                                 + VideoInput + When + DELETE_AND_SEND)
    /team      — add team member               (flow + ContactInput + EnumInline + TimePicker)
    /board     — browse sprint backlog         (paginated + multi-entity + tabs + search)
    /bugs      — browse bug tracker            (paginated + multi-entity + tabs)
    /help      — command reference             (instant reply)
    /velocity  — sprint velocity breakdown     (instant reply)
    /standup   — daily status summary          (instant reply)
    /retro     — interactive retrospective     (delegate: raw TG access)

Widget showcase:
    EnumInline      — auto-generate from Python Enum (story type, team role)
    NumberInput     — fibonacci shortcuts + typed input (story points)
    Rating          — star rating with preview (complexity)
    DynamicMultiselect — @options-loaded toggleable multi-choice (tags)
    ListBuilder     — variable-length list via Stay accumulation (acceptance criteria)
    DynamicRadio    — @options-loaded radio selection (assignee from team)
    DynamicInline   — @options-loaded inline select (link bug to story)
    ContactInput    — Telegram native contact sharing via reply keyboard (team phone)
    TimePicker      — hour:minute two-step selection (standup time)
    VoiceInput      — voice message file_id (voice repro)
    VideoInput      — video file_id (video repro)
    Counter         — [−] [val] [+] stepper (retained in browse)
    Multiselect     — toggleable multi-choice (retained in browse)
    Radio           — stateful single-select with Done (priority)
    DatePicker      — calendar date selection (deadline)
    PhotoInput      — accept photo from user (screenshot)
    Case            — conditional text display (priority message)
    ScrollingInline — paginated options (retained in browse)
    ShowMode        — EDIT / DELETE_AND_SEND
    LaunchMode      — EXCLUSIVE blocks re-entry
    When            — conditional fields
    stacking        — /story high priority → sub_flow to /bug
    @options        — dynamic options from DB

    BOT_TOKEN=123:ABC uv run python derivelib/examples/sprint_bot.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, time
from enum import Enum
from typing import Annotated
from logging import basicConfig

from kungfu import Ok, Result
from nodnod import scalar_node  # type: ignore # stubs
from telegrinder.bot.cute_types.message import MessageCute
from telegrinder.bot.rules.command import Command

from emergent.wire.axis.query import MutatingRelationalProvider, SequenceNextId, relational
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider  # concrete (has next_id)
from emergent.wire.axis.schema import Identity
from emergent.wire.axis.schema.dialects import compose, tg

from derivelib import build_application_from_decorated, derive, endpoint_count
from derivelib._errors import DomainError
from derivelib.patterns import (
    ActionResult,
    BrowseSource,
    Case,
    ContactInput,
    Counter,
    DatePicker,
    DynamicInline,
    DynamicMultiselect,
    DynamicRadio,
    EnumInline,
    FinishResult,
    FlowStack,
    Inline,
    LaunchMode,
    ListBuilder,
    ListBrowseSource,
    MaxLen,
    MinLen,
    Multiselect,
    NumberInput,
    PhotoInput,
    Radio,
    Rating,
    ScrollingInline,
    ShowMode,
    TextInput,
    TimePicker,
    VideoInput,
    VoiceInput,
    When,
    action,
    format_card,
    methods,
    options,
    query,
    tg_browse,
    tg_command,
    tg_delegate,
    tg_flow,
    view_filter,
    with_back,
    with_cancel,
    with_launch_mode,
    with_show_mode,
    with_stacking,
)

from telegrinder.node import UserId

# ═══════════════════════════════════════════════════════════════════════════════
# Domain
# ═══════════════════════════════════════════════════════════════════════════════

basicConfig(level="INFO")


class StoryType(Enum):
    """Story classification."""

    FEATURE = "feature"
    CHORE = "chore"
    SPIKE = "spike"


class TeamRole(Enum):
    """Team member role."""

    DEVELOPER = "developer"
    DESIGNER = "designer"
    PM = "pm"
    QA = "qa"


@dataclass
class Story:
    """A user story in the sprint."""

    id: int
    title: str
    story_type: str  # feature | chore | spike
    points: int
    complexity: int  # 1-5 stars
    priority: str  # high | medium | low
    tags: str = ""  # comma-separated
    criteria: str = ""  # semicolon-separated acceptance criteria
    assignee: str | None = None
    deadline: str = ""  # ISO date string
    priority_msg: str = ""  # conditional text from Case
    status: str = "todo"  # todo → doing → done


@dataclass
class Bug:
    """A bug report in the sprint."""

    id: int
    title: str
    severity: str  # critical | major | minor
    repro: str
    linked_story: str = ""  # story id
    screenshot: str = ""  # file_id from PhotoInput
    voice_repro: str = ""  # file_id from VoiceInput
    video_repro: str = ""  # file_id from VideoInput
    blocker: str | None = None  # only for critical (When)
    status: str = "open"  # open → fixing → closed


@dataclass
class TeamMember:
    """A team member."""

    id: int
    name: str
    phone: str
    role: str  # developer | designer | pm | qa
    standup_time: str = ""  # HH:MM


# ═══════════════════════════════════════════════════════════════════════════════
# Store — one provider per entity, shared by all patterns
# ═══════════════════════════════════════════════════════════════════════════════


_db: MemoryRelationalProvider[Story] = MemoryRelationalProvider(
    key_fn=lambda s: s.id, next_id=SequenceNextId(),
)

_bug_db: MemoryRelationalProvider[Bug] = MemoryRelationalProvider(
    key_fn=lambda b: b.id, next_id=SequenceNextId(),
)

_team_db: MemoryRelationalProvider[TeamMember] = MemoryRelationalProvider(
    key_fn=lambda t: t.id, next_id=SequenceNextId(),
)


@scalar_node
class Stories:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider[Story]:
        return _db


@scalar_node
class Bugs:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider[Bug]:
        return _bug_db


@scalar_node
class TeamMembers:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider[TeamMember]:
        return _team_db


# Shared flow stack — sub-flow navigation across /story ↔ /bug
_flow_stack = FlowStack()


# ═══════════════════════════════════════════════════════════════════════════════
# /story — create user story (tg_flow)
#
# Showcases: EnumInline, NumberInput, Rating, DynamicMultiselect + @options,
#            ListBuilder, Radio, Case, DynamicRadio + @options, When,
#            DatePicker, stacking, ShowMode.EDIT, /cancel, /back
# ═══════════════════════════════════════════════════════════════════════════════


@derive(tg_flow(command="story", key_node=UserId, description="New user story", order=1).chain(
    with_cancel(), with_back(), with_stacking(_flow_stack), with_show_mode(ShowMode.EDIT),
))
@dataclass
class NewStory:
    """Multi-step: /story <title> → type → points → complexity → tags → criteria
    → priority → [assignee] → deadline → created.

    EnumInline for story type (auto-generated from StoryType enum).
    NumberInput for story points (fibonacci shortcuts).
    Rating for complexity (1–5 stars with preview).
    DynamicMultiselect for tags (loaded via @options).
    ListBuilder for acceptance criteria (variable-length via Stay).
    Radio for priority (stateful select with Done).
    DynamicRadio for assignee (loaded via @options from /team).
    Case for priority message (conditional text).
    DatePicker for deadline (calendar UI).
    When: assignee only prompted for high priority.
    Stacking: high priority → sub_flow to /bug.
    ShowMode.EDIT — edits previous message in place.
    """

    title: Annotated[str, tg.CommandArg(greedy=True)]
    story_type: Annotated[StoryType, EnumInline("Story type:")]
    points: Annotated[
        int,
        NumberInput("Story points:", min=1, max=21, shortcuts=(1, 2, 3, 5, 8, 13)),
    ]
    complexity: Annotated[int, Rating("Complexity:")]
    tags: Annotated[str, DynamicMultiselect("Tags:", min_selected=1)]
    criteria: Annotated[list[str], ListBuilder("Acceptance criteria:", min=1, max=10)]
    priority: Annotated[
        str,
        Radio(
            "Priority (select and confirm):",
            columns=3,
            high="High",
            medium="Medium",
            low="Low",
        ),
    ]
    priority_msg: Annotated[
        str,
        Case(
            "priority",
            high="Blocks release — will prompt for assignee next.",
            medium="Important but not blocking.",
            low="Nice to have — will be scheduled later.",
        ),
    ]
    assignee: Annotated[
        str | None,
        DynamicRadio("Assign to (select and confirm):"),
        When(lambda v: v.get("priority") == "high"),
    ]
    deadline: Annotated[
        date,
        DatePicker("Deadline:", min_date=date.today()),
    ]
    id: Annotated[int, Identity] = 0

    @classmethod
    @options("tags")
    async def load_tags(cls) -> dict[str, str]:
        """Available tags — could come from DB in real app."""
        return {
            "backend": "Backend",
            "frontend": "Frontend",
            "infra": "Infrastructure",
            "design": "Design",
            "devops": "DevOps",
        }

    @classmethod
    @options("assignee")
    async def load_assignees(cls) -> dict[str, str]:
        """Load team members from DB for assignment."""
        members = await _team_db.fetch_many(relational(TeamMember))
        return {m.name: m.name for m in members}

    async def finish(
        self,
        db: Annotated[MemoryRelationalProvider[Story], compose.Node(Stories)],
    ) -> Result[FinishResult, DomainError]:
        nid: int = await db.next_id()
        tags_display = ", ".join(self.tags.split(",")) if self.tags else "none"
        criteria_str = "; ".join(self.criteria) if isinstance(self.criteria, list) else str(self.criteria)
        deadline_str = str(self.deadline) if self.deadline else ""
        story = Story(
            nid, self.title, self.story_type.value,
            self.points, self.complexity, self.priority,
            tags=self.tags, criteria=criteria_str,
            assignee=self.assignee, deadline=deadline_str,
            priority_msg=self.priority_msg,
        )
        await db.insert(story)
        stars = "\u2605" * story.complexity + "\u2606" * (5 - story.complexity)
        assignee_line = f"Assigned: @{story.assignee}\n" if story.assignee else ""
        tags_line = f"Tags: {tags_display}\n"
        deadline_line = f"Deadline: {story.deadline}\n" if story.deadline else ""
        criteria_line = ""
        if story.criteria:
            items = story.criteria.split("; ")
            criteria_line = "Criteria:\n" + "\n".join(f"  \u2022 {c}" for c in items) + "\n"
        # High priority → sub_flow to /bug (file a related bug)
        if story.priority == "high":
            return Ok(FinishResult.sub_flow(
                f"Story #{story.id} created\n\n"
                f"{story.title}\n"
                f"{story.story_type} / {story.points}pt / {story.priority}\n"
                f"Complexity: {stars}\n"
                f"{tags_line}"
                f"{deadline_line}"
                f"{assignee_line}"
                f"{criteria_line}\n"
                f"High priority — file a related bug?",
                command="bug",
            ))
        return Ok(
            FinishResult.message(
                f"Story #{story.id} created\n\n"
                f"{story.title}\n"
                f"{story.story_type} / {story.points}pt / {story.priority}\n"
                f"Complexity: {stars}\n"
                f"{tags_line}"
                f"{deadline_line}"
                f"{criteria_line}\n"
                f"/board to manage the backlog"
            )
        )


# ═══════════════════════════════════════════════════════════════════════════════
# /bug — report a bug (tg_flow)
#
# Showcases: DynamicInline + @options, Radio, When, PhotoInput,
#            VoiceInput, VideoInput, ShowMode.DELETE_AND_SEND,
#            LaunchMode.EXCLUSIVE, stacking, /back, /cancel
# ═══════════════════════════════════════════════════════════════════════════════


@derive(tg_flow(command="bug", key_node=UserId, description="Report a bug", order=6).chain(
    with_cancel(), with_back(), with_stacking(_flow_stack),
    with_launch_mode(LaunchMode.EXCLUSIVE),
    with_show_mode(ShowMode.DELETE_AND_SEND),
))
@dataclass
class ReportBug:
    """Multi-step: /bug → title → severity → [linked story] → [blocker]
    → screenshot → [voice] → [video] → repro → filed.

    DynamicInline for linked story (loaded from stories DB via @options).
    Radio for severity (stateful select — user sees selection before confirming).
    PhotoInput for screenshot (optional).
    VoiceInput for voice repro steps (optional).
    VideoInput for video repro (optional).
    When: blocker only prompted for critical severity.
    Stacking: shared stack with /story for sub-flow return.
    LaunchMode.EXCLUSIVE — blocks re-entry while flow is active.
    ShowMode.DELETE_AND_SEND — deletes old prompt + sends new (clean for media).
    """

    title: Annotated[str, TextInput("Bug title:"), MinLen(3), MaxLen(120)]
    severity: Annotated[
        str,
        Radio(
            "Severity (select and confirm):",
            columns=3,
            critical="Critical",
            major="Major",
            minor="Minor",
        ),
    ]
    linked_story: Annotated[str | None, DynamicInline("Link to story (or /skip):")]
    blocker: Annotated[
        str | None,
        TextInput("Who is blocked by this?"),
        When(lambda v: v.get("severity") == "critical"),
    ]
    screenshot: Annotated[
        str | None,
        PhotoInput("Send a screenshot (or /skip):"),
    ]
    voice_repro: Annotated[
        str | None,
        VoiceInput("Record voice repro steps (or /skip):"),
    ]
    video_repro: Annotated[
        str | None,
        VideoInput("Send a video of the bug (or /skip):"),
    ]
    repro: Annotated[str, TextInput("Steps to reproduce:"), MinLen(5)]
    id: Annotated[int, Identity] = 0

    @classmethod
    @options("linked_story")
    async def load_stories(cls) -> dict[str, str]:
        """Load existing stories for linking."""
        stories = await _db.fetch_many(relational(Story))
        return {str(s.id): f"#{s.id} {s.title}" for s in stories}

    async def finish(
        self,
        db: Annotated[MemoryRelationalProvider[Bug], compose.Node(Bugs)],
    ) -> Result[FinishResult, DomainError]:
        nid: int = await db.next_id()
        bug = Bug(
            nid, self.title, self.severity, self.repro,
            linked_story=self.linked_story or "",
            screenshot=self.screenshot or "",
            voice_repro=self.voice_repro or "",
            video_repro=self.video_repro or "",
            blocker=self.blocker,
        )
        await db.insert(bug)
        blocker_line = f"Blocker: {bug.blocker}\n" if bug.blocker else ""
        screenshot_line = "Screenshot: attached\n" if bug.screenshot else ""
        voice_line = "Voice repro: attached\n" if bug.voice_repro else ""
        video_line = "Video repro: attached\n" if bug.video_repro else ""
        linked_line = f"Linked story: #{bug.linked_story}\n" if bug.linked_story else ""
        return Ok(
            FinishResult.message(
                f"Bug #{bug.id} filed\n\n"
                f"{bug.title}\n"
                f"Severity: {bug.severity}\n"
                f"{blocker_line}"
                f"{linked_line}"
                f"{screenshot_line}"
                f"{voice_line}"
                f"{video_line}\n"
                f"/bugs to manage the tracker"
            )
        )


# ═══════════════════════════════════════════════════════════════════════════════
# /team — add team member (tg_flow)
#
# Showcases: ContactInput (Telegram native contact sharing),
#            EnumInline (Python Enum auto-generation),
#            TimePicker (hour:minute two-step selection),
#            ShowMode.EDIT, /cancel, /back
# ═══════════════════════════════════════════════════════════════════════════════


@derive(tg_flow(command="team", key_node=UserId, description="Add team member", order=8).chain(
    with_cancel(), with_back(), with_show_mode(ShowMode.EDIT),
))
@dataclass
class AddTeamMember:
    """Multi-step: /team → name → phone → role → standup time → added.

    TextInput for name.
    ContactInput for phone (Telegram native contact sharing via reply keyboard).
    EnumInline for role (auto-generated from TeamRole Python Enum).
    TimePicker for preferred standup time (hour:minute two-step selection).
    """

    name: Annotated[str, TextInput("Team member name:"), MinLen(2)]
    phone: Annotated[str, ContactInput("Share their phone number:")]
    role: Annotated[TeamRole, EnumInline("Role:")]
    preferred_standup: Annotated[
        time,
        TimePicker("Preferred standup time:", min_hour=7, max_hour=12, step_minutes=15),
    ]
    id: Annotated[int, Identity] = 0

    async def finish(
        self,
        db: Annotated[MemoryRelationalProvider[TeamMember], compose.Node(TeamMembers)],
    ) -> Result[FinishResult, DomainError]:
        nid: int = await db.next_id()
        t = self.preferred_standup
        standup_str = f"{t.hour:02d}:{t.minute:02d}" if isinstance(t, time) else str(t)
        member = TeamMember(
            nid, self.name, self.phone, self.role.value,
            standup_time=standup_str,
        )
        await db.insert(member)
        return Ok(
            FinishResult.message(
                f"Team member #{member.id} added\n\n"
                f"{member.name}\n"
                f"Phone: {member.phone}\n"
                f"Role: {member.role}\n"
                f"Standup: {member.standup_time}"
            )
        )


# ═══════════════════════════════════════════════════════════════════════════════
# /board — browse sprint backlog (tg_browse)
# ═══════════════════════════════════════════════════════════════════════════════


@derive(tg_browse(command="board", provider_node=Stories, key_node=UserId, page_size=5, description="Browse sprint backlog", order=2))
@dataclass
class Board:
    """Paginated sprint board with tabs and search.

    page_size=5 — multi-entity per page (ListGroup).
    @view_filter — tab buttons to filter by status.
    filter_key + search_query — @query method receives filter/search params.
    """

    id: Annotated[int, Identity]
    title: str = ""
    story_type: str = ""
    points: int = 0
    complexity: int = 0
    priority: str = ""
    tags: str = ""
    criteria: str = ""
    assignee: str | None = None
    status: str = ""

    @classmethod
    @view_filter("Active", key="active")
    @view_filter("Done", key="done")
    @view_filter("All", key="all")
    @query
    async def backlog(
        cls,
        db: Annotated[MutatingRelationalProvider[Story], compose.Node(Stories)],
        filter_key: str = "",
        search_query: str = "",
    ) -> BrowseSource[Board]:
        stories = await db.fetch_many(relational(Story))
        if filter_key == "active":
            stories = [s for s in stories if s.status in ("todo", "doing")]
        elif filter_key == "done":
            stories = [s for s in stories if s.status == "done"]
        if search_query:
            q = search_query.lower()
            stories = [s for s in stories if q in s.title.lower() or q in s.tags.lower()]
        return ListBrowseSource(
            items=[
                Board(
                    s.id, s.title, s.story_type, s.points, s.complexity,
                    s.priority, s.tags, s.criteria, s.assignee, s.status,
                )
                for s in stories
            ]
        )

    @classmethod
    @action("Start")
    async def start_work(
        cls,
        card: Board,
        db: Annotated[MutatingRelationalProvider[Story], compose.Node(Stories)],
    ) -> ActionResult:
        story = await db.fetch_one(relational(Story).filter(lambda s: s.id == card.id))
        if not story:
            return ActionResult.stay("Story not found")
        if story.status != "todo":
            return ActionResult.stay(f"Can't start — already {story.status}")
        await db.update(replace(story, status="doing"))
        return ActionResult.refresh("Started!")

    @classmethod
    @action("Done")
    async def complete(
        cls,
        card: Board,
        db: Annotated[MutatingRelationalProvider[Story], compose.Node(Stories)],
    ) -> ActionResult:
        story = await db.fetch_one(relational(Story).filter(lambda s: s.id == card.id))
        if not story:
            return ActionResult.stay("Story not found")
        if story.status != "doing":
            return ActionResult.stay("Start the story first")
        await db.update(replace(story, status="done"))
        done = await db.fetch_many(relational(Story).filter(lambda s: s.status == "done"))
        vel = sum(s.points for s in done)
        return ActionResult.refresh(f"+{story.points}pt! Velocity: {vel}pt")

    @classmethod
    @action("Reopen")
    async def reopen(
        cls,
        card: Board,
        db: Annotated[MutatingRelationalProvider[Story], compose.Node(Stories)],
    ) -> ActionResult:
        story = await db.fetch_one(relational(Story).filter(lambda s: s.id == card.id))
        if not story:
            return ActionResult.stay("Story not found")
        if story.status == "todo":
            return ActionResult.stay("Already in backlog")
        prev = story.status
        await db.update(replace(story, status="todo"))
        return ActionResult.refresh(f"{prev} → todo")

    @classmethod
    @format_card
    def render(cls, card: Board) -> str:
        icon = {"todo": "[  ]", "doing": "[..]", "done": "[ok]"}
        stars = "\u2605" * card.complexity + "\u2606" * (5 - card.complexity)
        base = f"{icon.get(card.status, '[??]')} #{card.id}  {card.title}  ({card.story_type} {card.points}pt, {card.priority}) {stars}"
        if card.tags:
            base = f"{base}  [{card.tags}]"
        if card.assignee:
            return f"{base}  @{card.assignee}"
        return base


# ═══════════════════════════════════════════════════════════════════════════════
# /bugs — browse bug tracker (tg_browse)
# ═══════════════════════════════════════════════════════════════════════════════


@derive(tg_browse(command="bugs", provider_node=Bugs, key_node=UserId, page_size=5, description="Browse bug tracker", order=7))
@dataclass
class BugBoard:
    """Paginated bug tracker with tabs.

    page_size=5 — multi-entity per page (ListGroup).
    @view_filter — tab buttons to filter by status.
    """

    id: Annotated[int, Identity]
    title: str = ""
    severity: str = ""
    linked_story: str = ""
    blocker: str | None = None
    status: str = ""

    @classmethod
    @view_filter("Open", key="open")
    @view_filter("Fixing", key="fixing")
    @view_filter("All", key="all")
    @query
    async def all_bugs(
        cls,
        db: Annotated[MutatingRelationalProvider[Bug], compose.Node(Bugs)],
        filter_key: str = "",
    ) -> BrowseSource[BugBoard]:
        bugs = await db.fetch_many(relational(Bug))
        if filter_key == "open":
            bugs = [b for b in bugs if b.status == "open"]
        elif filter_key == "fixing":
            bugs = [b for b in bugs if b.status == "fixing"]
        return ListBrowseSource(
            items=[BugBoard(b.id, b.title, b.severity, b.linked_story, b.blocker, b.status) for b in bugs]
        )

    @classmethod
    @action("Fix")
    async def start_fix(
        cls,
        card: BugBoard,
        db: Annotated[MutatingRelationalProvider[Bug], compose.Node(Bugs)],
    ) -> ActionResult:
        bug = await db.fetch_one(relational(Bug).filter(lambda b: b.id == card.id))
        if not bug:
            return ActionResult.stay("Bug not found")
        if bug.status != "open":
            return ActionResult.stay(f"Can't start — already {bug.status}")
        await db.update(replace(bug, status="fixing"))
        return ActionResult.refresh("Fixing!")

    @classmethod
    @action("Close")
    async def close_bug(
        cls,
        card: BugBoard,
        db: Annotated[MutatingRelationalProvider[Bug], compose.Node(Bugs)],
    ) -> ActionResult:
        bug = await db.fetch_one(relational(Bug).filter(lambda b: b.id == card.id))
        if not bug:
            return ActionResult.stay("Bug not found")
        if bug.status != "fixing":
            return ActionResult.stay("Start fixing first")
        await db.update(replace(bug, status="closed"))
        return ActionResult.refresh("Closed!")

    @classmethod
    @action("Reopen")
    async def reopen(
        cls,
        card: BugBoard,
        db: Annotated[MutatingRelationalProvider[Bug], compose.Node(Bugs)],
    ) -> ActionResult:
        bug = await db.fetch_one(relational(Bug).filter(lambda b: b.id == card.id))
        if not bug:
            return ActionResult.stay("Bug not found")
        if bug.status == "open":
            return ActionResult.stay("Already open")
        prev = bug.status
        await db.update(replace(bug, status="open"))
        return ActionResult.refresh(f"{prev} → open")

    @classmethod
    @format_card
    def render(cls, card: BugBoard) -> str:
        icon = {"open": "[!!]", "fixing": "[..]", "closed": "[ok]"}
        sev = {"critical": "CRIT", "major": "MAJ", "minor": "min"}
        base = f"{icon.get(card.status, '[??]')} #{card.id}  {card.title}  ({sev.get(card.severity, card.severity)})"
        if card.linked_story:
            base = f"{base}  \u2192story#{card.linked_story}"
        if card.blocker:
            return f"{base}  blocks: {card.blocker}"
        return base


# ═══════════════════════════════════════════════════════════════════════════════
# /help, /velocity, /standup, /retro — quick commands (methods)
# ═══════════════════════════════════════════════════════════════════════════════


@derive(methods)
@dataclass
class SprintCmd:
    """Instant commands + delegate escape hatch."""

    id: Annotated[int, Identity] = 0

    @classmethod
    @tg_command("help", description="Command reference", order=10)
    async def help_cmd(cls) -> Result[str, DomainError]:
        from emergent.wire.compile.targets.telegrinder import generate_help_from_command_rules
        return Ok(generate_help_from_command_rules(
            app,
            template="/{name} — {description}",
            header="Sprint Planner\n",
        ))

    @classmethod
    @tg_command("velocity", description="Sprint velocity breakdown", order=3)
    async def velocity(
        cls,
        db: Annotated[MutatingRelationalProvider[Story], compose.Node(Stories)],
    ) -> Result[str, DomainError]:
        all_stories = await db.fetch_many(relational(Story))
        done = [s for s in all_stories if s.status == "done"]
        doing = [s for s in all_stories if s.status == "doing"]
        todo = [s for s in all_stories if s.status == "todo"]
        vel = sum(s.points for s in done)
        total = sum(s.points for s in all_stories)
        pct = (vel * 100 // total) if total else 0
        return Ok(
            f"Sprint Velocity\n\n"
            f"Done:        {len(done)} stories  ({vel}pt)\n"
            f"In progress: {len(doing)} stories  ({sum(s.points for s in doing)}pt)\n"
            f"Backlog:     {len(todo)} stories  ({sum(s.points for s in todo)}pt)\n"
            f"\n{pct}% complete  ({vel}/{total}pt)"
        )

    @classmethod
    @tg_command("standup", description="Daily status summary", order=4)
    async def standup(
        cls,
        db: Annotated[MutatingRelationalProvider[Story], compose.Node(Stories)],
    ) -> Result[str, DomainError]:
        all_stories = await db.fetch_many(relational(Story))
        lines = ["Daily Standup\n"]
        for label, status in [("In Progress", "doing"), ("Completed", "done")]:
            items = [s for s in all_stories if s.status == status]
            if items:
                lines.append(f"\n{label}:")
                for s in items:
                    stars = "\u2605" * s.complexity
                    lines.append(f"  #{s.id} {s.title} ({s.points}pt) {stars}")
        if not all_stories:
            lines.append("\nNo stories yet. /story to create one.")
        return Ok("\n".join(lines))

    @classmethod
    @tg_delegate(Command("retro"), description="Interactive retrospective", order=5)
    async def retro(
        cls,
        message: MessageCute,
        db: Annotated[MutatingRelationalProvider[Story], compose.Node(Stories)],
    ) -> None:
        """Retrospective — delegate gives raw telegrinder access,
        compose.Node DI still resolves parameters."""
        all_stories = await db.fetch_many(relational(Story))
        done = [s for s in all_stories if s.status == "done"]
        vel = sum(s.points for s in done)
        lines = [
            "Sprint Retrospective",
            f"\nCompleted: {len(done)} stories ({vel}pt)",
        ]
        if done:
            lines.append("\nWhat went well:")
            for s in done:
                stars = "\u2605" * s.complexity
                lines.append(f"  #{s.id} {s.title} {stars}")
        # Show team
        members = await _team_db.fetch_many(relational(TeamMember))
        if members:
            lines.append(f"\nTeam ({len(members)} members):")
            for m in members:
                lines.append(f"  {m.name} ({m.role}) standup@{m.standup_time}")
        lines.append("\nReply with your thoughts!")
        await message.answer("\n".join(lines))


# ═══════════════════════════════════════════════════════════════════════════════
# Build & run
# ═══════════════════════════════════════════════════════════════════════════════

app = build_application_from_decorated(NewStory, ReportBug, AddTeamMember, Board, BugBoard, SprintCmd)

from emergent.wire.compile.targets import telegrinder as tg_compile  # noqa: E402

dispatch = tg_compile.compile(app)

if __name__ == "__main__":
    from telegrinder import API, Telegrinder, Token

    n = endpoint_count(app)
    print(f"\n  Sprint Planner Bot")
    print(f"  ──────────────────")
    print(f"  6 domain types -> {n} Telegram endpoints.")
    print(f"  /story /bug /team /board /bugs /help /velocity /standup /retro")
    print(f"  EnumInline + NumberInput + Rating + DynamicMultiselect + ListBuilder")
    print(f"  DynamicRadio + DynamicInline + ContactInput + TimePicker")
    print(f"  VoiceInput + VideoInput + PhotoInput + Radio + DatePicker + Case")
    print(f"  @options + When + stacking + ShowMode.EDIT + DELETE_AND_SEND\n")

    api = API(Token.from_env("BOT_TOKEN"))
    bot = Telegrinder(api, dispatch=dispatch)
    bot.run_forever()
