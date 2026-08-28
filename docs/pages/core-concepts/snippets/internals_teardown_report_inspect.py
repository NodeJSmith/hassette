from hassette.resources.base import Resource


async def inspect_teardown(resource: Resource) -> None:
    # The return value is the exact report from this call.
    report = await resource.shutdown()
    if not report.is_restart_safe:
        print(f"{resource.unique_name} refused to restart: {report.causes}")

    # The property reflects the current unconsumed report (or None).
    current = resource.teardown_report
    if current is not None:
        print(f"pending tasks: {current.pending_tasks}")
