# Read and Filter Logs

The Logs page streams log entries from every app and framework component in real time. Filter and search controls narrow the view to specific entries.

![Logs page](../../_static/web_ui_logs.png)

## Filtering and Search

The filter controls narrow the table to the entries you care about.

**Level** sets the minimum severity shown. It defaults to INFO. Options are: All levels, DEBUG+, INFO+, WARNING+, ERROR+, and CRITICAL only.

**App** limits entries by source. Toggle between All, Apps, and Framework. The default is Apps. When All or Apps is selected, a dropdown narrows to a specific app key.

**Function** filters the function name column by substring. Type any part of a function name to match.

**Search** matches against both message content and logger name.

The footer shows how many entries match. When the result exceeds 500, the footer reads "showing 500 of N". Narrow the filters to see the specific entries you need.

## Trace a Single Execution

Append `?execution_id=<id>` to the URL to filter the table to entries from one handler or job execution. The [Debug Handler](debug-handler.md) page links here automatically from execution history. You can also construct the URL manually if you have an execution ID from logs or the CLI.

When an execution ID filter is active, the other filters use local state. They do not modify the URL, so the execution ID stays intact as you refine your view.

## Log Table Columns

The table is sorted by timestamp descending by default. Sortable columns toggle between descending and ascending on click.

| Column | Sortable | Filterable | Description |
|---|---|---|---|
| Level | Yes | Yes (dropdown) | Severity badge: DEBUG, INFO, WARNING, ERROR, CRITICAL |
| Timestamp | Yes (default desc) | No | Time the entry was recorded |
| App | Yes | Yes (dropdown) | App key, or blank for framework logs |
| Instance | No | No | Instance name for multi-instance apps |
| Execution | No | No | Execution ID linking to a handler invocation |
| Function | Yes | Yes (text input) | Python function that emitted the log |
| Module | No | No | Python module name |
| Message | Yes | No | Log message text |

## Column Picker

Click the grid icon in the table footer to choose which columns are visible. Check or uncheck any column to toggle it. Level and Message are required and cannot be hidden.

Some columns auto-hide at narrow viewport widths. Those columns appear disabled in the popover with a "Hidden at this screen size" tooltip. They cannot be toggled until the viewport widens. Click **Reset to defaults** to restore the default column set.

!!! note
    The column picker does not appear on mobile viewports. The table uses a compact layout there instead.

## Log Detail Drawer

Click any row to open the detail drawer with the complete entry.

The drawer shows a severity badge, full timestamp, and a metadata grid. The grid includes app (linked to its detail page), instance, execution ID, function name, module, line number, and logger name. The execution ID has a copy button.

Below the grid, the full message appears in a scrollable block with a copy button. Entries with exception info show a separate code block beneath the message.

Press the arrow keys to move between entries without closing the drawer. Press Escape to close.

On desktop the drawer opens as a side panel. On mobile and tablet it appears as a bottom sheet.

## Live Streaming

New entries appear as they arrive. No refresh needed.

Streaming is active only when the table is sorted by timestamp, the default. Sorting by any other column pauses streaming so incoming entries do not disrupt the sort order. A "paused" button appears in the footer. Click it to reset the sort to timestamp-descending and resume live updates.

## Related pages

- [Web UI overview](index.md) — layout, navigation, and how to enable the UI
- [Debug a Failing Handler](debug-handler.md) — execution history with links to filtered logs for each run
- [Database and Telemetry](../core-concepts/database-telemetry.md) — how log entries are persisted and retained
