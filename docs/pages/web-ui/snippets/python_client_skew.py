# --8<-- [start:check-imports]
from hassette_client import HassetteClient, UnsupportedServerVersionError, check_server_version

# --8<-- [end:check-imports]
# --8<-- [start:unknown-imports]
from hassette_wire import UnknownValue

# --8<-- [end:unknown-imports]


async def print_statuses(client: HassetteClient) -> None:
    # --8<-- [start:unknown]
    for app in (await client.get_apps()).apps:
        match app.status:
            case UnknownValue() as unknown:
                print(f"{app.app_key}: {unknown.value!r} is newer than this client")
            case status:
                print(f"{app.app_key}: {status}")
    # --8<-- [end:unknown]


# --8<-- [start:check]
async def server_is_supported(client: HassetteClient) -> bool:
    health = await client.get_health()
    try:
        check_server_version(health)
    except UnsupportedServerVersionError as exc:
        print(exc)
        return False
    return True


# --8<-- [end:check]
