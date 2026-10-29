from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from hassette_wire.enums import OpenAppStatus, OpenResourceStatus
from hassette_wire.literals import OpenAppAction, OpenInstanceResult


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


class AppInstance(BaseModel):
    """One configured instance of an app and its lifecycle status.

    Nested in ``AppSummary.instances``. ``index`` is the instance's position in the app's config;
    ``error_message`` and ``error_traceback`` describe why the instance failed, and are ``None``
    unless ``status`` is ``failed``.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    app_key: str
    index: int
    instance_name: str
    class_name: str
    status: OpenResourceStatus
    error_message: str | None = None
    error_traceback: str | None = None
    owner_id: str | None = None
    in_current_config: bool = True
    """False for an instance still tracked at an index outside the app's configured range, such as one left
    running after the config's instance count was reduced. Such an instance accepts only ``stop``; ``start``
    and ``reload`` return 404."""
    needs_restart: NeedsRestart | None = None
    """Set when a teardown of this instance left work that may still be running. ``status`` is then ``failed``
    until hassette restarts."""


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
    auto_loaded: bool = False
    """Deprecated: always ``False``, since app autodetection is gone. Kept because released clients up to
    0.59.0 require it; removed in #3161."""
    autostart: bool = True
    description: str | None = None
    """One-line description of what the app does, from the app's config; ``None`` when unset, and for an app
    known only from recorded history (``in_current_config`` is ``False``)."""
    status: OpenAppStatus
    block_reason: str | None = None
    instance_count: int = 0
    """Number of entries in ``instances``: every configured instance, including ones never started or
    independently stopped, plus any instance still running beyond the configured count (e.g. after the config
    was reduced). Always len(instances).

    0 when ``in_current_config`` is ``False``."""
    instances: list[AppInstance] = Field(default_factory=list)
    error_message: str | None = None
    error_traceback: str | None = None
    in_current_config: bool = True
    """True if the app is present in the currently-loaded config; False for an app known only from recorded
    history, such as one removed from the config."""
    needs_restart_count: int = 0
    """Number of ``instances`` flagged ``needs_restart``. Nonzero means hassette must restart to recover them."""


class AppListResponse(BaseModel):
    """Response for ``GET /api/apps``: every app with status counts."""

    total: int
    status_counts: dict[OpenAppStatus, int] = Field(default_factory=dict)
    apps: list[AppSummary]
    only_apps: list[str] = Field(default_factory=list)


class InstanceOutcome(BaseModel):
    """What one start, stop or reload did to one instance it targeted.

    Listed in ``ActionResponse.outcomes``, and in ``ProblemDetail.outcomes`` when the action answers with an
    error. Valid pairs: ``succeeded`` with ``needs_restart`` false; ``failed`` with ``needs_restart`` true (this
    action left the instance needing a hassette restart) or false; ``refused`` with ``needs_restart`` true (the
    instance was already flagged, so nothing was done to it). A client that meets an unknown ``result`` must not
    assume success.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    instance_index: int
    instance_name: str
    result: OpenInstanceResult
    needs_restart: bool = False
    """Whether the instance is flagged as needing a hassette restart after this action."""
    reason: str | None = None
    """The failure message or refusal, or a note on a success that wasn't plain (``already running``,
    ``already stopped``, or the failed stop a reload recovered from); ``None`` for a plain success."""


class ActionResponse(BaseModel):
    """Response for a start, stop or reload that succeeded on every instance it targeted.

    Sent with 200 once the action has finished. ``instance_index`` is the server-confirmed instance the
    action ran against — ``None`` for an app-level action, the validated index for an instance-scoped one.
    Callers (the CLI and the frontend toast) compare this against the index they requested rather than
    trusting their own request data, since a routing bug would otherwise still look like a plain 200.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    app_key: str
    action: OpenAppAction
    instance_index: int | None
    outcomes: list[InstanceOutcome]
    """One entry per instance the action targeted, in index order."""


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
