"""derivelib.patterns — Derivation dialects built from generic primitives.

CRUD = schema × query × surface (via Op descriptors from derivelib._dialect)

Provider resolved at runtime via compose.Node (nodnod node composition).
CRUD is just ONE dialect — anyone can build their own.

    from derivelib import derive, build_application
    from derivelib.patterns import http_crud

    @derive(http_crud("/api/users", provider_node=UserProvider))
    @dataclass
    class User:
        id: Annotated[int, Identity]
        email: str

    app = build_application_from_decorated(User)
"""

from .crud import (
    # CRUD Ops (the building blocks)
    LIST,
    GET,
    CREATE,
    UPDATE,
    PATCH,
    DELETE,
    ALL_CRUD_OPS,
    MUTATION_CRUD_OPS,
    READ_CRUD_OPS,
    CRUD_ERROR_CAPS,
    # Errors + RFC 7807
    ProblemDetail,
    ProblemResponse,
    CRUDErrorTransform,
    NotFound,
    AlreadyExists,
    InvalidData,
    CRUDError,
    # Handler templates
    FetchMany,
    FetchOneById,
    InsertNew,
    UpdateExisting,
    DeleteOne,
    # Pattern
    crud,
    # Presets
    http_crud,
    cli_crud,
)

from .nested import (
    NestedCrudPattern,
    nested_http_crud,
)

from .methods import (
    methods,
    MethodsPattern,
    method,
    post,
    get,
    put,
    delete,
    patch,
    command,
    ExposeMethod,
)

from .tg.methods import (
    tg_command,
    tg_callback,
    tg_delegate,
    ExposeDelegateMethod,
)

from .tg.flow import (
    tg_flow,
    TGFlowPattern,
    AnyKeyboard,
    TextInput,
    Inline,
    Confirm,
    Prefilled,
    Counter,
    Multiselect,
    Toggle,
    PhotoInput,
    DocumentInput,
    LocationInput,
    VideoInput,
    VoiceInput,
    ContactInput,
    Radio,
    DatePicker,
    ScrollingInline,
    EnumInline,
    Rating,
    TimePicker,
    NumberInput,
    ListBuilder,
    Slider,
    PinInput,
    MediaGroupInput,
    TimeSlotPicker,
    RecurrencePicker,
    SummaryReview,
    DynamicInline,
    DynamicRadio,
    DynamicMultiselect,
    options,
    Case,
    ShowMode,
    LaunchMode,
    MinLen,
    MaxLen,
    Pattern,
    When,
    FlowStackStorage,
    FlowStack,
    StackFrame,
    FinishResult,
    FlowSurfaceStep,
    with_cancel,
    with_back,
    with_stacking,
    with_show_mode,
    with_launch_mode,
    with_progress,
    with_summary,
)

from .tg.widget import (
    FlowWidget,
    WidgetContext,
    Stay,
    Advance,
    Reject,
    NoOp,
)

from .tg.uilib.helpers import (
    reject_text,
    no_options_reject,
    no_options_text,
    option_keyboard,
    radio_keyboard,
    checked_keyboard,
    handle_radio_cb,
    handle_checked_cb,
    parse_selected,
)

from .tg.app import (
    TGApp,
    # UILib (through TGApp — single entry point)
    UITheme,
    DEFAULT_THEME,
    NavUI,
    SelectionUI,
    ActionUI,
    DisplayUI,
    ErrorUI,
)

from .tg.registry import (
    CallbackRegistry,
    CallbackCollision,
    CallbackNamespace,
    CommandCollision,
    CommandEntry,
)

from .tg.browse import (
    tg_browse,
    TGBrowsePattern,
    BrowseSource,
    ListBrowseSource,
    ActionResult,
    query,
    action,
    format_card,
    view_filter,
    BrowseSession,
    BrowseCB,
    BrowseSurfaceStep,
)

from .tg.dashboard import (
    tg_dashboard,
    TGDashboardPattern,
    DashboardSurfaceStep,
)

from .tg.settings import (
    tg_settings,
    TGSettingsPattern,
    SettingsSurfaceStep,
    on_save,
    format_settings,
)

from .tg.search import (
    tg_search,
    TGSearchPattern,
    SearchSurfaceStep,
)

__all__ = (
    # CRUD Ops
    "LIST",
    "GET",
    "CREATE",
    "UPDATE",
    "PATCH",
    "DELETE",
    "ALL_CRUD_OPS",
    "MUTATION_CRUD_OPS",
    "READ_CRUD_OPS",
    "CRUD_ERROR_CAPS",
    # Errors + RFC 7807
    "ProblemDetail",
    "ProblemResponse",
    "CRUDErrorTransform",
    "NotFound",
    "AlreadyExists",
    "InvalidData",
    "CRUDError",
    # Handler templates
    "FetchMany",
    "FetchOneById",
    "InsertNew",
    "UpdateExisting",
    "DeleteOne",
    # Pattern
    "crud",
    # Presets
    "http_crud",
    "cli_crud",
    # Nested
    "NestedCrudPattern",
    "nested_http_crud",
    # Methods
    "MethodsPattern",
    "methods",
    "method",
    "post",
    "get",
    "put",
    "delete",
    "patch",
    "command",
    "ExposeMethod",
    # TG Methods
    "tg_command",
    "tg_callback",
    "tg_delegate",
    "ExposeDelegateMethod",
    # TG Flow
    "tg_flow",
    "TGFlowPattern",
    "TextInput",
    "Inline",
    "Confirm",
    "Prefilled",
    "Counter",
    "Multiselect",
    "Toggle",
    "PhotoInput",
    "DocumentInput",
    "LocationInput",
    "VideoInput",
    "VoiceInput",
    "ContactInput",
    "Radio",
    "DatePicker",
    "ScrollingInline",
    "EnumInline",
    "Rating",
    "TimePicker",
    "NumberInput",
    "ListBuilder",
    "Slider",
    "PinInput",
    "MediaGroupInput",
    "TimeSlotPicker",
    "RecurrencePicker",
    "SummaryReview",
    "DynamicInline",
    "DynamicRadio",
    "DynamicMultiselect",
    "options",
    "Case",
    "ShowMode",
    "LaunchMode",
    "MinLen",
    "MaxLen",
    "Pattern",
    "When",
    "FlowStackStorage",
    "FlowStack",
    "StackFrame",
    "FinishResult",
    "FlowSurfaceStep",
    "with_cancel",
    "with_back",
    "with_stacking",
    "with_show_mode",
    "with_launch_mode",
    "with_progress",
    "with_summary",
    # Widget protocol
    "FlowWidget",
    "AnyKeyboard",
    "WidgetContext",
    "Stay",
    "Advance",
    "Reject",
    "NoOp",
    # TG Browse
    "tg_browse",
    "TGBrowsePattern",
    "BrowseSource",
    "ListBrowseSource",
    "ActionResult",
    "query",
    "action",
    "format_card",
    "view_filter",
    "BrowseSession",
    "BrowseCB",
    "BrowseSurfaceStep",
    # TG Dashboard
    "tg_dashboard",
    "TGDashboardPattern",
    "DashboardSurfaceStep",
    # TG Settings
    "tg_settings",
    "TGSettingsPattern",
    "SettingsSurfaceStep",
    "on_save",
    "format_settings",
    # TG Search
    "tg_search",
    "TGSearchPattern",
    "SearchSurfaceStep",
    # Widget helpers
    "reject_text",
    "no_options_reject",
    "no_options_text",
    "option_keyboard",
    "radio_keyboard",
    "checked_keyboard",
    "handle_radio_cb",
    "handle_checked_cb",
    "parse_selected",
    # UILib
    "UITheme",
    "DEFAULT_THEME",
    "NavUI",
    "SelectionUI",
    "ActionUI",
    "DisplayUI",
    "ErrorUI",
    # TGApp
    "TGApp",
    "CallbackRegistry",
    "CallbackCollision",
    "CallbackNamespace",
    "CommandCollision",
    "CommandEntry",
)
