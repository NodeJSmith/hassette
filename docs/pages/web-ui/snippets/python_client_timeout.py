import aiohttp
from hassette_client import HassetteClient

BASE_URL = "http://127.0.0.1:8126"
TOKEN = "your-web-api-token"  # noqa: S105 - a placeholder


async def reload_slow_app(session: aiohttp.ClientSession) -> None:
    # --8<-- [start:slow]
    client = HassetteClient(session, BASE_URL, token=TOKEN)
    slow_client = HassetteClient(
        session, BASE_URL, token=TOKEN, request_timeout=120
    )

    await slow_client.action("solar_forecast", "reload")
    # --8<-- [end:slow]
    await client.get_health()
