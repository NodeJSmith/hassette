# Logs Tab

The Logs tab shows the same log viewer as the [global Logs page](../logs.md), filtered to
this app. Use it when you are already in App Detail and want to read log output without
navigating away.

## Log table

The log table uses the same component as the global Logs page. Since the view is already
scoped to one app, the **App** column is omitted and an **Execution** column is shown
instead. The default visible columns are:

| Column | Description |
|--------|-------------|
| **Level** | Colored badge — green for `INFO`, grey for `DEBUG`, yellow for `WARNING`, red for `ERROR`/`CRITICAL` |
| **Timestamp** | Time the log entry was recorded |
| **Execution** | Short execution ID linking this entry to a specific handler invocation |
| **Function** | Function name where the log was emitted |
| **Module** | Module and line number (`module:lineno`) |
| **Message** | Log message text |

Columns are sortable by clicking their header. **Level** and **Message** are always visible;
the other columns can be hidden via the column picker.

## Search

The **Search logs…** input at the top of the tab filters entries by message content.
Filtering is applied as you type with a short debounce to avoid flickering.

## Live streaming

New log entries from this app appear in real time as they are emitted, via WebSocket. No
manual refresh is needed. The entry count in the footer updates as new messages arrive.

!!! note
    This tab shares the log table component used on the global Logs page and in the
    **Recent logs** section of the [Overview tab](overview.md). Filters set here do not
    affect the global Logs page.

## Related pages

- [Logs page](../logs.md) — cross-app log view with app filter, level filter, and column picker
- [Overview tab](overview.md) — the Overview tab includes an embedded log preview for this app
- [App Detail](index.md) — shared elements: breadcrumb, header, instance switcher, and tab strip
