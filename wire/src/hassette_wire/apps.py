from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from hassette_wire.enums import OpenAppStatus, OpenResourceStatus
from hassette_wire.literals import OpenAcceptedStatus, OpenAppAction, OpenInstanceResult, OpenIntegrationPlatformName


class NeedsRestart(BaseModel):
    """Why an app instance needs a hassette restart: a teardown left work that may still be running.

    Python can't stop a coroutine that ignores cancellation, so the only recovery is restarting hassette. Until
    then the instance reports ``failed``. Nested in ``AppInstance`` and in the ``app_status_changed`` WS event.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    reason: str
    """What the teardown left behind, such as the tasks still pending or why its evidence is incomplete."""
    pending_tasks: list[str] = Field(default_factory=list)
    """Names of the tasks still running when the teardown ended, including an initializer that hadn't stopped
    (``resource:initialize:<unique name>``). Can be empty when the evidence is incomplete (the instance was
    force-terminated, or its shutdown raised); ``reason`` says which."""
    flagged_at: float
    """When the instance was flagged, in epoch seconds. The first flag stands until restart."""


class DeclaredEntity(BaseModel):
    """A Home Assistant button, switch or sensor an app instance declares through ``self.integration``.

    Nested in ``AppInstance.entities`` on ``GET /api/apps``. Every platform shares one flat shape so a client
    that meets a platform it doesn't know can skip that entity and keep the rest: ``unit``, ``device_class``,
    ``state_class`` and ``options`` are set for a sensor only.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    key: str
    """The entity's key: lowercase letters, digits and ``_``, unique within its instance."""
    platform: OpenIntegrationPlatformName
    """``button``, ``switch`` or ``sensor``."""
    name: str
    """The entity's display name."""
    default_entity_id: str | None = None
    """The entity id the app suggests, applied only when the entity is first created in Home Assistant."""
    unit: str | None = None
    """A sensor's unit of measurement."""
    device_class: str | None = None
    """A sensor's Home Assistant device class."""
    state_class: str | None = None
    """A sensor's Home Assistant state class."""
    options: list[str] | None = None
    """An enum sensor's allowed values."""
    value: int | float | str | bool | None = None
    """A switch's on/off state or a sensor's value; ``None`` for a button and for a sensor that is unknown. A
    timestamp sensor's value is an ISO 8601 string with offset, a date sensor's an ISO 8601 date."""
    attributes: dict[str, Any] = Field(default_factory=dict)
    """The state attributes the app last set with the value."""


class AppInstance(BaseModel):
    """One configured instance of an app and its lifecycle status.

    Nested in ``AppSummary.instances``: configured instances in config order, then orphans by name.
    ``error_message`` and ``error_traceback`` describe why the instance failed, and are ``None`` unless ``status`` is
    ``failed``.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    app_key: str
    instance_name: str
    class_name: str
    status: OpenResourceStatus
    error_message: str | None = None
    error_traceback: str | None = None
    owner_id: str | None = None
    in_current_config: bool = True
    """False for an instance still tracked under a name outside the app's config, such as one left running
    after its config block was removed. Such an instance accepts only ``stop``; ``start`` and ``reload``
    return 404."""
    needs_restart: NeedsRestart | None = None
    """Set when a teardown of this instance left work that may still be running. ``status`` is then ``failed``
    until hassette restarts."""
    debug_capture: bool = False
    """Whether debug capture is on: the instance and the framework loggers it owns log at ``DEBUG``, and every line
    is stored. Set by ``PUT /api/apps/{app_key}/debug``; it ends when turned off or when hassette restarts. Held for a
    stopped instance too, whose levels apply when it starts. Fresh only when read: no WebSocket event reports a
    change, so a client caching app state refetches ``GET /api/apps`` to see it."""
    entities: list[DeclaredEntity] | None = None
    """The Home Assistant entities the instance declares, in key order, with their last committed state. Filled
    only by ``GET /api/apps`` (``[]`` for an instance that declares nothing); ``None`` on every other response,
    meaning not included rather than none. A stopped instance keeps its last declared entities, which are usable
    only while ``status`` is ``running``."""


class AppSummary(BaseModel):
    """What an app is: its config identity, lifecycle status and instances.

    Served by ``GET /api/apps`` (in ``AppListResponse``) and ``GET /api/apps/{app_key}``, and
    nested as ``app`` in each ``AppGridEntry``. Activity over a time window lives in
    ``AppActivity``, never here.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    app_key: str
    class_name: str
    display_name: str
    filename: str
    enabled: bool
    autostart: bool = True
    description: str | None = None
    """One-line description of what the app does, from the app's config as last recorded (an app removed from
    config keeps its last description); ``None`` when unset."""
    status: OpenAppStatus
    block_reason: str | None = None
    instance_count: int = 0
    """Number of entries in ``instances``: every configured instance, including ones never started or
    independently stopped, plus any instance still running beyond the configured count (e.g. after the config
    was reduced). Always len(instances).

    An app removed from the config lists instances only while one is flagged needs-restart; then this counts
    every instance it still tracks (``needs_restart_count`` counts the flagged ones). Otherwise it is 0."""
    instances: list[AppInstance] = Field(default_factory=list)
    error_message: str | None = None
    error_traceback: str | None = None
    in_current_config: bool = True
    """True if the app is present in the currently-loaded config; False for an app removed from it. App lists
    return a removed app only while one of its instances is flagged needs-restart; ``GET /apps/{app_key}``
    returns it until its recorded history ages out."""
    needs_restart_count: int = 0
    """Number of ``instances`` flagged ``needs_restart``. Nonzero means hassette must restart to recover them."""


class AppListResponse(BaseModel):
    """Response for ``GET /api/apps``: every app with status counts.

    ``boot_id`` and ``revision`` order the declared entities it carries (``AppInstance.entities``) against other
    listings and WebSocket entity messages.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    total: int
    status_counts: dict[OpenAppStatus, int] = Field(default_factory=dict)
    apps: list[AppSummary]
    only_apps: list[str] = Field(default_factory=list)
    boot_id: str
    """Identifies this run of hassette; it changes on every restart. ``revision`` values are comparable only
    between responses carrying the same ``boot_id``: on a new one, discard every revision seen before."""
    revision: int
    """Declared-entity revision this listing was read at. Starts at 0 each boot and increases on every declaration
    commit and entity state change, skipping values. The listing reflects every change up to this revision, so a
    client may apply it to an instance whose last applied revision is equal or older."""


class InstanceOutcome(BaseModel):
    """What one start, stop or reload did to one instance it targeted.

    Listed in ``ActionResponse.outcomes``, and in ``ProblemDetail.outcomes`` when the action answers with an
    error. Valid pairs: ``succeeded`` with ``needs_restart`` false; ``failed`` with ``needs_restart`` true (this
    action left the instance needing a hassette restart) or false; ``refused`` with ``needs_restart`` true (the
    instance was already flagged, so nothing was done to it). A client that meets an unknown ``result`` must not
    assume success.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    instance_name: str
    result: OpenInstanceResult
    needs_restart: bool = False
    """Whether the instance is flagged as needing a hassette restart after this action."""
    reason: str | None = None
    """The failure message or refusal, or a note on a success that wasn't plain (``already running``,
    ``already stopped``, or the failed stop a reload recovered from); ``None`` for a plain success."""


class ActionResponse(BaseModel):
    """Response for a start, stop or reload that succeeded on every instance it targeted.

    Sent with 200 once the action has finished. ``instance_name`` is the server-confirmed instance the
    action ran against — ``None`` for an app-level action, the validated name for an instance-scoped one.
    Callers (the CLI and the frontend toast) compare this against the name they requested rather than
    trusting their own request data, since a routing bug would otherwise still look like a plain 200.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    app_key: str
    action: OpenAppAction
    instance_name: str | None
    outcomes: list[InstanceOutcome]
    """One entry per instance the action targeted: configured instances in config order, then orphans by name.

    A name a config change adds during the action comes last, so match outcomes to instances by ``instance_name``.
    """


class AppConfigResponse(BaseModel):
    """An app's configuration, served by ``GET /api/apps/{app_key}/config``.

    Bundles the current config values, their TOML rendering, and the app config's JSON schema.
    """

    app_key: str
    filename: str
    class_name: str
    enabled: bool
    autostart: bool
    app_config: dict[str, Any] | list[dict[str, Any]]
    config_toml: str
    config_schema: dict[str, Any] | None = None
    framework_fields: list[str]


class AppSource(BaseModel):
    """An app's Python source file, served by ``GET /api/apps/{app_key}/source``."""

    app_key: str
    filename: str
    content: str
    line_count: int


class DebugCaptureRequest(BaseModel):
    """Request body for ``PUT /api/apps/{app_key}/debug`` and its instance-scoped twin."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    enabled: bool
    """Whether debug capture should be on."""


class InstanceDebugCapture(BaseModel):
    """One instance's debug capture state after a ``PUT .../debug``."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    instance_name: str
    debug_capture: bool


class DebugCaptureResponse(BaseModel):
    """Response for a ``PUT .../debug``: the capture state of each instance it targeted.

    An app-wide ``enabled: true`` targets every configured instance. An app-wide ``enabled: false`` targets every
    configured instance plus any other name still captured. ``instance_name`` is the server-confirmed instance for an
    instance-scoped request, ``None`` for an app-wide one.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    app_key: str
    instance_name: str | None
    instances: list[InstanceDebugCapture]
    """Each targeted instance, configured instances in config order first."""


class EntityCommandResponse(BaseModel):
    """Response (202) for a button press or switch turn-on/off sent to an app instance's declared entity.

    ``status`` is ``"accepted"`` once the command event was published to the instance's handler. That is not
    proof the handler ran: its execution mode may drop the command, which shows only in the handler's telemetry.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    status: OpenAcceptedStatus = "accepted"
    app_key: str
    instance_name: str
    key: str
    platform: OpenIntegrationPlatformName
