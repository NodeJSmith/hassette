from hassette.models.states import ImageState
from hassette.models.states.image import ImageAttributes

from .base import BaseEntity


class ImageEntity(BaseEntity[ImageState, str]):
    @property
    def attributes(self) -> ImageAttributes:
        return self.state.attributes

    async def snapshot(
        self,
        *,
        filename: str,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="snapshot",
            target={"entity_id": self.entity_id},
            filename=filename,
        )
