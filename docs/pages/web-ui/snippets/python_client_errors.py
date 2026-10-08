# --8<-- [start:imports]
import asyncio
import random

from hassette_client import (
    AppBlockedError,
    AppNotFoundError,
    BootstrapNotReleasedError,
    HassetteClient,
    HassetteClientError,
    HassetteConnectionError,
    HassetteTimeoutError,
    ServiceUnavailableError,
)

# --8<-- [end:imports]


# --8<-- [start:retry]
RETRY_ON = (
    HassetteConnectionError,
    HassetteTimeoutError,
    ServiceUnavailableError,
    BootstrapNotReleasedError,
)


async def start_with_retry(client: HassetteClient, app_key: str, attempts: int = 5) -> None:
    # start is safe to send again: starting a running app does nothing.
    for attempt in range(attempts):
        try:
            await client.action(app_key, "start")
            return
        except RETRY_ON:
            if attempt == attempts - 1:
                raise
            # Exponential backoff with jitter: 1s, 2s, 4s, 8s, each up to 50% longer.
            delay = 2**attempt
            await asyncio.sleep(delay + random.uniform(0, delay / 2))


# --8<-- [end:retry]


async def start_garage_door(client: HassetteClient) -> None:
    # --8<-- [start:handle]
    try:
        await client.action("garage_door", "start")
    except AppNotFoundError:
        print("No app with that key")
    except AppBlockedError:
        print("The server's --app filter excludes this app")
    except HassetteClientError as exc:
        print(f"Couldn't start it: {exc}")
    # --8<-- [end:handle]
