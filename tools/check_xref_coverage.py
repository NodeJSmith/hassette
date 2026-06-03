"""Sweep docs to add mkdocstrings cross-references on first backtick mention per page."""

import re
from pathlib import Path

DOCS = Path("/home/jessica/source/hassette/.claude/worktrees/928/docs/pages")

# Symbol -> mkdocstrings reference path
# Only symbols mentioned 2+ times across docs, plus key exceptions
XREF_MAP = {
    # User-facing core
    "AppSync": "hassette.app.app.AppSync",
    "RawStateChangeEvent": "hassette.events.hass.hass.RawStateChangeEvent",
    "CallServiceEvent": "hassette.events.hass.hass.CallServiceEvent",
    "DomainStates": "hassette.state_manager.state_manager.DomainStates",
    "TaskBucket": "hassette.task_bucket.task_bucket.TaskBucket",
    "TypeRegistry": "hassette.conversion.type_registry.TypeRegistry",
    "StateRegistry": "hassette.conversion.state_registry.StateRegistry",
    "AnnotationDetails": "hassette.event_handling.dependencies.AnnotationDetails",
    "LightState": "hassette.models.states.light.LightState",
    "SensorState": "hassette.models.states.sensor.SensorState",
    "BinarySensorState": "hassette.models.states.binary_sensor.BinarySensorState",
    "SunState": "hassette.models.states.sun.SunState",
    "CounterState": "hassette.models.states.counter.CounterState",
    "TimeState": "hassette.models.states.time.TimeState",
    # State base classes (custom states docs)
    "StringBaseState": "hassette.models.states.base.StringBaseState",
    "NumericBaseState": "hassette.models.states.base.NumericBaseState",
    "BoolBaseState": "hassette.models.states.base.BoolBaseState",
    "DateTimeBaseState": "hassette.models.states.base.DateTimeBaseState",
    "TimeBaseState": "hassette.models.states.base.TimeBaseState",
    "AttributesBase": "hassette.models.states.base.AttributesBase",
    # Triggers
    "After": "hassette.scheduler.triggers.After",
    "Once": "hassette.scheduler.triggers.Once",
    "Every": "hassette.scheduler.triggers.Every",
    "Daily": "hassette.scheduler.triggers.Daily",
    "Cron": "hassette.scheduler.triggers.Cron",
    "TriggerProtocol": "hassette.types.types.TriggerProtocol",
    # Exceptions
    "ListenerNameRequiredError": "hassette.exceptions.ListenerNameRequiredError",
    "InvalidAuthError": "hassette.exceptions.InvalidAuthError",
    "FatalError": "hassette.exceptions.FatalError",
    "SchemaVersionError": "hassette.exceptions.SchemaVersionError",
    "ResourceNotReadyError": "hassette.exceptions.ResourceNotReadyError",
    "DuplicateListenerError": "hassette.exceptions.DuplicateListenerError",
    "DependencyResolutionError": "hassette.exceptions.DependencyResolutionError",
    "HassetteError": "hassette.exceptions.HassetteError",
    "SchemeRequiredInBaseUrlError": "hassette.exceptions.SchemeRequiredInBaseUrlError",
    "InvalidDataForStateConversionError": "hassette.exceptions.InvalidDataForStateConversionError",
    "InvalidEntityIdError": "hassette.exceptions.InvalidEntityIdError",
    "UnableToConvertStateError": "hassette.exceptions.UnableToConvertStateError",
    "UnableToConvertValueError": "hassette.exceptions.UnableToConvertValueError",
    "FailedMessageError": "hassette.exceptions.FailedMessageError",
    "RetryableConnectionClosedError": "hassette.exceptions.RetryableConnectionClosedError",
    # Internals (for internals/operating docs)
    "ServiceWatcher": "hassette.core.service_watcher.ServiceWatcher",
    "WebsocketService": "hassette.core.websocket_service.WebsocketService",
    "BusService": "hassette.core.bus_service.BusService",
    "DatabaseService": "hassette.core.database_service.DatabaseService",
    "SchedulerService": "hassette.core.scheduler_service.SchedulerService",
    "StateProxy": "hassette.core.state_proxy.StateProxy",
    "WebApiService": "hassette.core.web_api_service.WebApiService",
    "EventStreamService": "hassette.core.event_stream_service.EventStreamService",
    "CommandExecutor": "hassette.core.command_executor.CommandExecutor",
    "ApiResource": "hassette.core.api_resource.ApiResource",
    "RestartSpec": "hassette.resources.restart.RestartSpec",
    "RestartType": "hassette.types.enums.RestartType",
    "ResourceStatus": "hassette.types.enums.ResourceStatus",
    "Hassette": "hassette.core.core.Hassette",
    # Error contexts
    "BusErrorContext": "hassette.bus.error_context.BusErrorContext",
    "SchedulerErrorContext": "hassette.scheduler.error_context.SchedulerErrorContext",
    # Config
    "AppManifest": "hassette.config.classes.AppManifest",
    # Listener internals
    "Listener": "hassette.bus.listeners.Listener",
    "ListenerIdentity": "hassette.bus.listeners.ListenerIdentity",
    "ListenerOptions": "hassette.bus.listeners.ListenerOptions",
    "HandlerInvoker": "hassette.bus.listeners.HandlerInvoker",
    "DurationConfig": "hassette.bus.listeners.DurationConfig",
    # Testing
    "ComponentLoadedEvent": "hassette.events.hass.hass.ComponentLoadedEvent",
    "ServiceRegisteredEvent": "hassette.events.hass.hass.ServiceRegisteredEvent",
}

# Pattern: `ClassName` not already inside [...] link syntax, not in heading
# Matches `ClassName` but not [`ClassName`] or [`ClassName`](...)
BACKTICK_RE = re.compile(r"(?<!\[)`([A-Z][A-Za-z]+)`(?!\])")


def is_in_code_block(text: str, pos: int) -> bool:
    """Check if position is inside a fenced code block."""
    before = text[:pos]
    fence_count = len(re.findall(r"^```", before, re.MULTILINE))
    return fence_count % 2 == 1


def is_in_heading(text: str, pos: int) -> bool:
    """Check if position is on a heading line."""
    line_start = text.rfind("\n", 0, pos) + 1
    line = text[line_start:pos]
    return line.lstrip().startswith("#")


def is_in_table_row(text: str, pos: int) -> bool:
    """Check if position is in a markdown table row (starts with |)."""
    line_start = text.rfind("\n", 0, pos) + 1
    line_end = text.find("\n", pos)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    return line.strip().startswith("|") and line.strip().endswith("|")


def process_page(path: Path) -> list[str]:
    """Add cross-refs to first backtick mention of each symbol. Returns list of changes."""
    text = path.read_text()
    changes = []
    linked_symbols = set()

    # First pass: find which symbols are already linked on this page
    already_linked = re.findall(r"\[`?([A-Z][A-Za-z]+)`?\]\[hassette\.", text)
    already_linked += re.findall(r"\[`?([A-Z][A-Za-z]+)`?\]\(", text)
    linked_symbols.update(already_linked)

    # Second pass: replace first unlinked backtick mention
    for symbol, ref_path in XREF_MAP.items():
        if symbol in linked_symbols:
            continue

        for match in BACKTICK_RE.finditer(text):
            if match.group(1) != symbol:
                continue
            pos = match.start()

            if is_in_code_block(text, pos):
                continue
            if is_in_heading(text, pos):
                continue
            # Skip state classes in table rows (domain state tables)
            if symbol.endswith("State") and is_in_table_row(text, pos):
                continue

            old = f"`{symbol}`"
            new = f"[`{symbol}`][{ref_path}]"
            # Replace only this occurrence
            text = text[:pos] + new + text[pos + len(old) :]
            changes.append(f"  {symbol} -> [{symbol}][{ref_path}]")
            linked_symbols.add(symbol)
            break

    if changes:
        path.write_text(text)
    return changes


total_changes = 0
for md in sorted(DOCS.rglob("*.md")):
    if "snippets" in str(md):
        continue
    changes = process_page(md)
    if changes:
        rel = md.relative_to(DOCS)
        print(f"\n{rel} ({len(changes)} edits):")
        for c in changes:
            print(c)
        total_changes += len(changes)

print(f"\n--- Total: {total_changes} cross-references added ---")
