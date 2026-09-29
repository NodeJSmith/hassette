from typing import Any, Literal

from pydantic import BaseModel, Field

from hassette_wire.enums import ManifestStatus, ResourceStatus


class AppInstanceResponse(BaseModel):
    app_key: str
    index: int
    instance_name: str
    class_name: str
    status: ResourceStatus
    error_message: str | None = None
    error_traceback: str | None = None
    owner_id: str | None = None


class AppStatusResponse(BaseModel):
    total: int
    running: int
    failed: int
    apps: list[AppInstanceResponse]
    only_apps: list[str] = Field(default_factory=list)


class AppManifestResponse(BaseModel):
    app_key: str
    class_name: str
    display_name: str
    filename: str
    enabled: bool
    auto_loaded: bool
    autostart: bool = True
    status: ManifestStatus
    block_reason: str | None = None
    instance_count: int = Field(
        default=0,
        description="Configured instances, including ones not currently tracked (never started, "
        "or independently stopped). Always len(instances).",
    )
    instances: list[AppInstanceResponse] = Field(default_factory=list)
    error_message: str | None = None
    error_traceback: str | None = None
    recent_invocations_1h: int = Field(
        default=0,
        description="Total handler invocations in the last hour across all instances.",
    )
    in_current_config: bool = Field(
        default=True,
        description="True if the app is present in the currently-loaded config; False for DB-only/removed apps.",
    )


class AppManifestListResponse(BaseModel):
    total: int
    status_counts: dict[str, int] = Field(default_factory=dict)
    manifests: list[AppManifestResponse]
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
    action: str
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
