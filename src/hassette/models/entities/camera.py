from collections.abc import Coroutine
from typing import Any, Literal

from hassette.models.states import CameraState
from hassette.models.states.camera import CameraAttributes

from .base import BaseEntity, BaseEntitySyncFacade

Format = Literal["hls"]


class CameraEntity(BaseEntity[CameraState, str]):
    @property
    def attributes(self) -> CameraAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "CameraEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(CameraEntitySyncFacade)

    def turn_off(self) -> Coroutine[Any, Any, None]:
        """Call the camera.turn_off service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    def turn_on(self) -> Coroutine[Any, Any, None]:
        """Call the camera.turn_on service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )

    def enable_motion_detection(self) -> Coroutine[Any, Any, None]:
        """Call the camera.enable_motion_detection service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="enable_motion_detection",
            target={"entity_id": self.entity_id},
        )

    def disable_motion_detection(self) -> Coroutine[Any, Any, None]:
        """Call the camera.disable_motion_detection service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="disable_motion_detection",
            target={"entity_id": self.entity_id},
        )

    def snapshot(
        self,
        *,
        filename: str,
    ) -> Coroutine[Any, Any, None]:
        """Call the camera.snapshot service.

        Args:
            filename: Full path to filename.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="snapshot",
            target={"entity_id": self.entity_id},
            filename=filename,
        )

    def play_stream(
        self,
        *,
        media_player: str,
        format: Format | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Call the camera.play_stream service.

        Args:
            media_player: Media player to stream to.
            format: Stream format supported by the media player.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="play_stream",
            target={"entity_id": self.entity_id},
            media_player=media_player,
            format=format,
        )

    def record(
        self,
        *,
        filename: str,
        duration: int | None = None,
        lookback: int | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Call the camera.record service.

        Args:
            filename: Full path to filename. Must be mp4.
            duration: Planned duration of the recording. The actual duration may vary.
            lookback: Planned lookback period to include in the recording (in addition to the duration). Only available
                if there is currently an active HLS stream. The actual length of the lookback period may vary.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="record",
            target={"entity_id": self.entity_id},
            filename=filename,
            duration=duration,
            lookback=lookback,
        )


class CameraEntitySyncFacade(BaseEntitySyncFacade[CameraState, str]):
    """Synchronous facade for CameraEntity service methods."""

    def turn_off(self) -> None:
        """Call the camera.turn_off service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
        )

    def turn_on(self) -> None:
        """Call the camera.turn_on service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
        )

    def enable_motion_detection(self) -> None:
        """Call the camera.enable_motion_detection service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="enable_motion_detection",
            target={"entity_id": self.entity.entity_id},
        )

    def disable_motion_detection(self) -> None:
        """Call the camera.disable_motion_detection service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="disable_motion_detection",
            target={"entity_id": self.entity.entity_id},
        )

    def snapshot(
        self,
        *,
        filename: str,
    ) -> None:
        """Call the camera.snapshot service synchronously.

        Args:
            filename: Full path to filename.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="snapshot",
            target={"entity_id": self.entity.entity_id},
            filename=filename,
        )

    def play_stream(
        self,
        *,
        media_player: str,
        format: Format | None = None,
    ) -> None:
        """Call the camera.play_stream service synchronously.

        Args:
            media_player: Media player to stream to.
            format: Stream format supported by the media player.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="play_stream",
            target={"entity_id": self.entity.entity_id},
            media_player=media_player,
            format=format,
        )

    def record(
        self,
        *,
        filename: str,
        duration: int | None = None,
        lookback: int | None = None,
    ) -> None:
        """Call the camera.record service synchronously.

        Args:
            filename: Full path to filename. Must be mp4.
            duration: Planned duration of the recording. The actual duration may vary.
            lookback: Planned lookback period to include in the recording (in addition to the duration). Only available
                if there is currently an active HLS stream. The actual length of the lookback period may vary.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="record",
            target={"entity_id": self.entity.entity_id},
            filename=filename,
            duration=duration,
            lookback=lookback,
        )
