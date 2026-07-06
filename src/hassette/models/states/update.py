from enum import IntFlag, StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class UpdateEntityStateAttribute(StrEnum):
    AUTO_UPDATE = "auto_update"
    DISPLAY_PRECISION = "display_precision"
    INSTALLED_VERSION = "installed_version"
    IN_PROGRESS = "in_progress"
    LATEST_VERSION = "latest_version"
    RELEASE_SUMMARY = "release_summary"
    RELEASE_URL = "release_url"
    SKIPPED_VERSION = "skipped_version"
    TITLE = "title"
    UPDATE_PERCENTAGE = "update_percentage"


class UpdateDeviceClass(StrEnum):
    FIRMWARE = "firmware"


class UpdateEntityFeature(IntFlag):
    INSTALL = 1
    SPECIFIC_VERSION = 2
    PROGRESS = 4
    BACKUP = 8
    RELEASE_NOTES = 16


class UpdateAttributes(AttributesBase):
    auto_update: bool | None = Field(default=None)
    installed_version: str | None = Field(default=None)
    device_class: UpdateDeviceClass | None = Field(default=None)
    display_precision: int | None = Field(default=None)
    in_progress: bool | None = Field(default=None)
    latest_version: str | None = Field(default=None)
    release_summary: str | None = Field(default=None)
    release_url: str | None = Field(default=None)
    title: str | None = Field(default=None)
    update_percentage: int | float | None = Field(default=None)

    @property
    def supports_install(self) -> bool:
        return self.has_feature(UpdateEntityFeature.INSTALL)

    @property
    def supports_specific_version(self) -> bool:
        return self.has_feature(UpdateEntityFeature.SPECIFIC_VERSION)

    @property
    def supports_progress(self) -> bool:
        return self.has_feature(UpdateEntityFeature.PROGRESS)

    @property
    def supports_backup(self) -> bool:
        return self.has_feature(UpdateEntityFeature.BACKUP)

    @property
    def supports_release_notes(self) -> bool:
        return self.has_feature(UpdateEntityFeature.RELEASE_NOTES)


class UpdateState(StringBaseState):
    """Representation of a Home Assistant update state.

    See: https://www.home-assistant.io/integrations/update/
    """

    domain: Literal["update"]

    attributes: UpdateAttributes
