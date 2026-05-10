from typing import Any, Literal

from hassette.models.states import RemoteState
from hassette.models.states.remote import RemoteAttributes

from .base import BaseEntity

CommandType = Literal["ir", "rf"]


class RemoteEntity(BaseEntity[RemoteState, str]):
    @property
    def attributes(self) -> RemoteAttributes:
        return self.state.attributes

    async def turn_on(
        self,
        *,
        activity: str | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
            activity=activity,
        )

    async def toggle(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )

    async def turn_off(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    async def send_command(
        self,
        *,
        command: Any,
        delay_secs: float | None = None,
        device: str | None = None,
        hold_secs: float | None = None,
        num_repeats: int | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="send_command",
            target={"entity_id": self.entity_id},
            command=command,
            delay_secs=delay_secs,
            device=device,
            hold_secs=hold_secs,
            num_repeats=num_repeats,
        )

    async def learn_command(
        self,
        *,
        alternative: bool | None = None,
        command: Any | None = None,
        command_type: CommandType | None = None,
        device: str | None = None,
        timeout: int | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="learn_command",
            target={"entity_id": self.entity_id},
            alternative=alternative,
            command=command,
            command_type=command_type,
            device=device,
            timeout=timeout,
        )

    async def delete_command(
        self,
        *,
        command: Any,
        device: str | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="delete_command",
            target={"entity_id": self.entity_id},
            command=command,
            device=device,
        )
