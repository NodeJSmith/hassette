import asyncio

import aiohttp
from hassette_client import HassetteClient

BASE_URL = "http://127.0.0.1:8126"
TOKEN = "your-web-api-token"


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        client = HassetteClient(session, BASE_URL, token=TOKEN)

        health = await client.get_health()
        print(f"Hassette {health.version}: {health.status}")

        for app in (await client.get_apps()).apps:
            print(f"{app.app_key}: {app.status}")


asyncio.run(main())
