from typing import ClassVar

from hassette.resources.service import Service


class MyWatcher(Service):
    # Optional: if serve() fails, this service stays dead in place and
    # Hassette keeps running. A service owned by an app must use False.
    required: ClassVar[bool] = False

    async def serve(self) -> None:
        await self.shutdown_event.wait()
