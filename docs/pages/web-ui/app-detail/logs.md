# Logs Tab

The Logs tab shows the same log viewer as the [global Logs page](../logs.md), filtered to
this app. It has the same filtering, column picker, and detail drawer features — the only
differences are that the **App** column is replaced by an **Execution** column, and all
entries are scoped to the current app.

## Log table

The default visible columns are:

| Column | Description |
|--------|-------------|
| **Level** | Colored badge — green for `INFO`, grey for `DEBUG`, yellow for `WARNING`, red for `ERROR`/`CRITICAL` |
| **Timestamp** | Time the log entry was recorded |
| **Execution** | Short execution ID linking this entry to a specific handler invocation |
| **Function** | Function name where the log was emitted |
| **Module** | Module and line number (`module:lineno`) |
| **Message** | Log message text |

Columns are sortable by clicking their header. **Level** and **Message** are always visible;
the other columns can be hidden via the column picker (grid icon in the table footer).

## Filtering

- **Search** — the "Search logs…" input filters entries by message content as you type.
- **Level** — set the minimum log level shown (All levels, DEBUG+, INFO+, WARNING+, ERROR+,
  CRITICAL only) via the Level column filter.
- **Function** — free-text filter on the function name column.

## Detail drawer

Click any row to open the detail drawer with the full log entry — severity, timestamp,
metadata grid, full message text, and exception traceback if present. Use arrow keys to
navigate between entries. See [Logs page — Log detail drawer](../logs.md#log-detail-drawer)
for the full drawer reference.

## Execution ID filtering

Append `?execution_id=<id>` to the URL to filter to entries from a single handler execution.
The [Handlers tab](handlers.md) uses this when linking from an invocation's execution history
to its log output.

## Live streaming

New log entries from this app appear in real time via WebSocket. No manual refresh is needed.
The entry count in the footer updates as new messages arrive.

!!! note
    Filters set here do not affect the global Logs page or the embedded logs on the
    [Overview tab](overview.md).

## Related pages

- [Logs page](../logs.md) — cross-app log view with app filter and full feature reference
- [Overview tab](overview.md) — the Overview tab includes an embedded log preview with search only
- [App Detail](index.md) — shared elements: breadcrumb, header, instance switcher, and tab strip
