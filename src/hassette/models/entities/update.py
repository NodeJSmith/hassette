from hassette.models.states import UpdateState
from hassette.models.states.update import UpdateAttributes

from .base import BaseEntity


class UpdateEntity(BaseEntity[UpdateState, str]):
    @property
    def attributes(self) -> UpdateAttributes:
        return self.state.attributes

    async def install(
        self,
        *,
        backup: bool | None = None,
        version: str | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="install",
            target={"entity_id": self.entity_id},
            backup=backup,
            version=version,
        )

    async def skip(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="skip",
            target={"entity_id": self.entity_id},
        )

    async def clear_skipped(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="clear_skipped",
            target={"entity_id": self.entity_id},
        )
