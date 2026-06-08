import asyncio

import requests

from hassette import App, AppConfig


class MyConfig(AppConfig):
    api_url: str = "http://example.com/api"


class MyApp(App[MyConfig]):
    # --8<-- [start:sync]
    def periodic_sync_task(self):
        data = requests.get("http://example.com/api").json()  # pyright: ignore[reportUnusedVariable]
        ...
    # --8<-- [end:sync]

    # --8<-- [start:async]
    async def periodic_async_task(self):
        data = await asyncio.to_thread(  # pyright: ignore[reportUnusedVariable]
            requests.get, "http://example.com/api"
        )
        ...
    # --8<-- [end:async]
