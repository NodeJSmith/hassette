from hassette.resources.base import Resource


async def inspect_teardown(resource: Resource) -> None:
    # The return value is the exact outcome of this call.
    outcome = await resource.shutdown()
    if not outcome.is_restart_safe:
        print(f"{resource.unique_name}: {outcome.result.name}")
        print(f"reason: {outcome.reason}")

    # The property reflects the current unconsumed outcome (or None).
    current = resource.shutdown_outcome
    if current is not None:
        print(f"still running: {current.still_running}")
