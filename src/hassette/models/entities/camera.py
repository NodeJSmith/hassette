from collections.abc import Coroutine
from typing import Any, Literal

from hassette.models.states import CameraState
from hassette.models.states.camera import CameraAttributes

from .base import BaseEntity

Format = Literal["hls"]


class CameraEntity(BaseEntity[CameraState, str]):
    @property
    def attributes(self) -> CameraAttributes:
        return self.state.attributes

    def turn_off(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    def turn_on(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )

    def enable_motion_detection(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="enable_motion_detection",
            target={"entity_id": self.entity_id},
        )

    def disable_motion_detection(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
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
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
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
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
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
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
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
