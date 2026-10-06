from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from hassette_wire.enums import OpenAppStatus, OpenResourceStatus
from hassette_wire.literals import OpenAppAction


class AppInstanceResponse(BaseModel):
    app_key: str
    index: int
    instance_name: str
    class_name: str
    status: OpenResourceStatus
    error_message: str | None = None
    error_traceback: str | None = None
    owner_id: str | None = None


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
    auto_loaded: bool
    autostart: bool = True
    status: OpenAppStatus
    block_reason: str | None = None
    instance_count: int = 0
    """Number of entries in ``instances``: every configured instance (including untracked ones, never started
    or independently stopped) plus any still-tracked instance outside the configured range. 0 for DB-only or
    removed apps. Always len(instances)."""
    instances: list[AppInstanceResponse] = Field(default_factory=list)
    error_message: str | None = None
    error_traceback: str | None = None
    in_current_config: bool = True
    """True if the app is present in the currently-loaded config; False for DB-only/removed apps."""


class AppListResponse(BaseModel):
    """Response for ``GET /api/apps``: every app with status counts."""

    total: int
    status_counts: dict[OpenAppStatus, int] = Field(default_factory=dict)
    apps: list[AppSummary]
    only_apps: list[str] = Field(default_factory=list)


class ActionResponse(BaseModel):
    """Response for app mutation endpoints (start/stop/reload).

    ``instance_index`` is the server-confirmed instance the action ran against — ``None`` for
    an app-level action, the validated index for an instance-scoped one. Callers (the CLI and
    the frontend toast) compare this against the index they requested rather than trusting
    their own request data, since a routing bug would otherwise still look like a plain 202.
    """

    status: Literal["accepted"] = "accepted"
    app_key: str
    action: OpenAppAction
    instance_index: int | None


class AppConfigResponse(BaseModel):
    """Response model for GET /apps/{app_key}/config."""

    app_key: str
    filename: str
    class_name: str
    enabled: bool
    autostart: bool
    app_config: dict[str, Any] | list[dict[str, Any]]
    config_toml: str
    config_schema: dict[str, Any] | None = None
    framework_fields: list[str]


class AppSourceResponse(BaseModel):
    """Response model for GET /apps/{app_key}/source."""

    app_key: str
    filename: str
    content: str
    line_count: int
