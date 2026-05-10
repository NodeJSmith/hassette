from hassette.models.states import LockState
from hassette.models.states.lock import LockAttributes

from .base import BaseEntity


class LockEntity(BaseEntity[LockState, str]):
    @property
    def attributes(self) -> LockAttributes:
        return self.state.attributes

    async def lock(
        self,
        *,
        code: str | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="lock",
            target={"entity_id": self.entity_id},
            code=code,
        )

    async def open(
        self,
        *,
        code: str | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="open",
            target={"entity_id": self.entity_id},
            code=code,
        )

    async def unlock(
        self,
        *,
        code: str | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="unlock",
            target={"entity_id": self.entity_id},
            code=code,
        )
