# Execution Detail

The execution detail page shows the full record of one handler invocation or job run: status, timing, trigger info, traceback, and the logs it emitted. Click any row in a handler's invocations table to open it.

![Execution detail](../../_static/web_ui_execution_detail.png)

## Header

A status shape and a truncated execution ID open the page. Status badges appear next to the ID for non-success outcomes: **failed**, **timed out**, **cancelled**, **skipped**, and **thread leaked** (the handler kept running past its timeout).

A skipped execution means the job's `where=` predicate — a function that decides whether the job should run this time (see [Conditional execution with where](../core-concepts/scheduler/methods.md#conditional-execution-with-where)) — returned `False`.

Below the header, the full execution ID appears in a monospace block with a copy button.

## Meta Stats

A stats row shows duration, timestamp, and status for the run.

## Trigger

A trigger section appears for executions that carry trigger data. It shows the trigger mode (currently only `manual`, for jobs triggered via the run-now button — absent for regular scheduled fires and handler invocations), a truncated context ID linking related executions, and the origin, when known.

## Error or Outcome

Failed executions show the full Python traceback in a dedicated viewer. Failures with no captured traceback, such as dependency-injection errors, show the error type and message instead. Timed-out and cancelled executions show a single duration line ("exceeded 5s budget", "cancelled after 2s") and no traceback. The framework doesn't capture a traceback for these outcomes. Successful executions show a single line: a green status shape and the elapsed duration.

Skipped executions get their own label instead of a duration — a scheduled job whose `where=` predicate returned `False` never ran, so there's no elapsed time to show.

![A skipped job execution's result label](../../_static/web_ui_skipped_result.png)

## Logs

An inline log table lists every entry the execution emitted, filtered to its execution ID. A **View all logs** link opens the [Logs page](logs.md) with the same filter applied, for cross-referencing against other executions or framework activity nearby.

## Navigation

The page has no back link. The browser's back button, or reselecting the handler in the Handlers tab, returns to its detail panel.

The URL follows `/apps/{appKey}/handlers/{kind}/{id}/exec/{executionId}`, where `kind` is `listener` or `job`. The URL can be shared or bookmarked directly.

## Related pages

- [Debug a Failing Handler](debug-handler.md): the invocations table that links to this page
- [Logs](logs.md): the full log view behind "View all logs"
- [Web UI overview](index.md): navigation, layout, and status bar controls
