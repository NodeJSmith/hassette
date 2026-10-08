# --8<-- [start:imports]
from hassette_client import (
    HassetteClient,
    UnsupportedServerVersionError,
    check_server_version,
)
from hassette_wire import UnknownValue
from packaging.version import InvalidVersion, Version

# --8<-- [end:imports]


async def print_statuses(client: HassetteClient) -> None:
    # --8<-- [start:unknown]
    for app in (await client.get_apps()).apps:
        match app.status:
            case UnknownValue():
                print(f"{app.app_key}: {app.status!r} is newer than this client")
            case status:
                print(f"{app.app_key}: {status}")
    # --8<-- [end:unknown]


async def connect(client: HassetteClient) -> bool:
    # --8<-- [start:check]
    health = await client.get_health()
    try:
        check_server_version(health)
    except UnsupportedServerVersionError as exc:
        print(exc)  # names both versions and says which side to upgrade
        return False
    try:
        Version(health.version)
    except InvalidVersion:
        print(f"Hassette reports version {health.version!r}; couldn't check it's new enough")
    return True
    # --8<-- [end:check]
