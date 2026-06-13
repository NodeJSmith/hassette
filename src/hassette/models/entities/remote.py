from collections.abc import Coroutine
from typing import Any, Literal

from hassette.models.states import RemoteState
from hassette.models.states.remote import RemoteAttributes

from .base import BaseEntity, BaseEntitySyncFacade

CommandType = Literal["ir", "rf"]


class RemoteEntity(BaseEntity[RemoteState, str]):
    @property
    def attributes(self) -> RemoteAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "RemoteEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(RemoteEntitySyncFacade)

    def turn_on(
        self,
        *,
        activity: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Call the remote.turn_on service.

        Args:
            activity: Activity ID or activity name to be started.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
            activity=activity,
        )

    def toggle(self) -> Coroutine[Any, Any, None]:
        """Call the remote.toggle service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )

    def turn_off(self) -> Coroutine[Any, Any, None]:
        """Call the remote.turn_off service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    def send_command(
        self,
        *,
        command: Any,
        delay_secs: float | None = None,
        device: str | None = None,
        hold_secs: float | None = None,
        num_repeats: int | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Call the remote.send_command service.

        Args:
            command: A single command or a list of commands to send.
            delay_secs: The time you want to wait in between repeated commands.
            device: Device ID to send command to.
            hold_secs: The time you want to have it held before the release is send.
            num_repeats: The number of times you want to repeat the commands.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="send_command",
            target={"entity_id": self.entity_id},
            command=command,
            delay_secs=delay_secs,
            device=device,
            hold_secs=hold_secs,
            num_repeats=num_repeats,
        )

    def learn_command(
        self,
        *,
        alternative: bool | None = None,
        command: Any | None = None,
        command_type: CommandType | None = None,
        device: str | None = None,
        timeout: int | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Call the remote.learn_command service.

        Args:
            alternative: If code must be stored as an alternative. This is useful for discrete codes. Discrete codes are
                used for toggles that only perform one function. For example, a code to only turn a device on. If it is
                on already, sending the code won't change the state.
            command: A single command or a list of commands to learn.
            command_type: The type of command to be learned.
            device: Device ID to learn command from.
            timeout: Timeout for the command to be learned.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="learn_command",
            target={"entity_id": self.entity_id},
            alternative=alternative,
            command=command,
            command_type=command_type,
            device=device,
            timeout=timeout,
        )

    def delete_command(
        self,
        *,
        command: Any,
        device: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Call the remote.delete_command service.

        Args:
            command: The single command or the list of commands to be deleted.
            device: Device from which commands will be deleted.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="delete_command",
            target={"entity_id": self.entity_id},
            command=command,
            device=device,
        )


class RemoteEntitySyncFacade(BaseEntitySyncFacade[RemoteState, str]):
    """Synchronous facade for RemoteEntity service methods."""

    def turn_on(
        self,
        *,
        activity: str | None = None,
    ) -> None:
        """Call the remote.turn_on service synchronously.

        Args:
            activity: Activity ID or activity name to be started.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
            activity=activity,
        )

    def toggle(self) -> None:
        """Call the remote.toggle service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="toggle",
            target={"entity_id": self.entity.entity_id},
        )

    def turn_off(self) -> None:
        """Call the remote.turn_off service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
        )

    def send_command(
        self,
        *,
        command: Any,
        delay_secs: float | None = None,
        device: str | None = None,
        hold_secs: float | None = None,
        num_repeats: int | None = None,
    ) -> None:
        """Call the remote.send_command service synchronously.

        Args:
            command: A single command or a list of commands to send.
            delay_secs: The time you want to wait in between repeated commands.
            device: Device ID to send command to.
            hold_secs: The time you want to have it held before the release is send.
            num_repeats: The number of times you want to repeat the commands.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="send_command",
            target={"entity_id": self.entity.entity_id},
            command=command,
            delay_secs=delay_secs,
            device=device,
            hold_secs=hold_secs,
            num_repeats=num_repeats,
        )

    def learn_command(
        self,
        *,
        alternative: bool | None = None,
        command: Any | None = None,
        command_type: CommandType | None = None,
        device: str | None = None,
        timeout: int | None = None,
    ) -> None:
        """Call the remote.learn_command service synchronously.

        Args:
            alternative: If code must be stored as an alternative. This is useful for discrete codes. Discrete codes are
                used for toggles that only perform one function. For example, a code to only turn a device on. If it is
                on already, sending the code won't change the state.
            command: A single command or a list of commands to learn.
            command_type: The type of command to be learned.
            device: Device ID to learn command from.
            timeout: Timeout for the command to be learned.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="learn_command",
            target={"entity_id": self.entity.entity_id},
            alternative=alternative,
            command=command,
            command_type=command_type,
            device=device,
            timeout=timeout,
        )

    def delete_command(
        self,
        *,
        command: Any,
        device: str | None = None,
    ) -> None:
        """Call the remote.delete_command service synchronously.

        Args:
            command: The single command or the list of commands to be deleted.
            device: Device from which commands will be deleted.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="delete_command",
            target={"entity_id": self.entity.entity_id},
            command=command,
            device=device,
        )
