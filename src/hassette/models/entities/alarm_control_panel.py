from hassette.models.states import AlarmControlPanelState
from hassette.models.states.alarm_control_panel import AlarmControlPanelAttributes

from .base import BaseEntity


class AlarmControlPanelEntity(BaseEntity[AlarmControlPanelState, str]):
    @property
    def attributes(self) -> AlarmControlPanelAttributes:
        return self.state.attributes

    async def alarm_disarm(
        self,
        *,
        code: str | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="alarm_disarm",
            target={"entity_id": self.entity_id},
            code=code,
        )

    async def alarm_arm_custom_bypass(
        self,
        *,
        code: str | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="alarm_arm_custom_bypass",
            target={"entity_id": self.entity_id},
            code=code,
        )

    async def alarm_arm_home(
        self,
        *,
        code: str | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="alarm_arm_home",
            target={"entity_id": self.entity_id},
            code=code,
        )

    async def alarm_arm_away(
        self,
        *,
        code: str | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="alarm_arm_away",
            target={"entity_id": self.entity_id},
            code=code,
        )

    async def alarm_arm_night(
        self,
        *,
        code: str | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="alarm_arm_night",
            target={"entity_id": self.entity_id},
            code=code,
        )

    async def alarm_arm_vacation(
        self,
        *,
        code: str | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="alarm_arm_vacation",
            target={"entity_id": self.entity_id},
            code=code,
        )

    async def alarm_trigger(
        self,
        *,
        code: str | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="alarm_trigger",
            target={"entity_id": self.entity_id},
            code=code,
        )
