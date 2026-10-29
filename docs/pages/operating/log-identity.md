# Where an App's Logs Go

Every log line Hassette records carries three labels: who wrote it, which app it is about, and which run it belongs to. These labels decide which log views show a line, and whether it shows by default.

## Three Labels on Every Line

| Label | Field | Question it answers | Values |
|-------|-------|---------------------|--------|
| Author | `author` | Who wrote the line? | `app` or `framework` |
| Subject | `app_key`, `instance_name` | Which app is the line about? | An app key and instance, or empty |
| Execution | `execution_id` | Which handler or job run was in progress? | An execution ID, or empty |

The three labels are independent. A line Hassette writes about an app, such as a handler failure, has author `framework` and that app as its subject.

### Author

The author comes from the logger that wrote the line. An app's `self.logger` writes `app` lines, and so does any logger made from it with `self.logger.getChild(...)`. Loggers outside the `hassette.` tree also write `app` lines once [`extra_loggers`](log-levels.md#attaching-loggers-outside-the-hassette-tree) attaches them, such as an app module's own logger or a library's.

Every other `hassette.*` logger writes `framework` lines. That includes an app's own `Bus`, `Scheduler`, `Api` and `StateManager`, because Hassette's code writes their lines.

Captured Python warnings take their author from the warning itself. Warnings of Hassette's own classes, or raised from Hassette's code, are `framework`. All other warnings are `app`.

### Subject

The subject names the app instance a line is about. An app owns its own logger, its `Bus`, `Scheduler`, `Api` and `StateManager` loggers, and its lifecycle logger. These loggers stamp the app on every line they write.

Loggers no app owns take the subject from the work in progress. These include shared services, such as the command executor that runs every app's handlers and jobs, and module or library loggers. Inside an app's handler, job, `on_initialize` or `on_shutdown`, their lines carry that app. Outside those, their lines carry no subject.

An app's log view and `hassette log --app <key>` select lines by subject, whichever author wrote them.

### Execution

The execution ID marks one run of a handler or job. Every line written during that run carries it, whichever logger wrote it. Console output shows its last eight characters after an `@`. The [Debug Handler](../web-ui/debug-handler.md) page lists every line from one run. [`hassette execution <id>`](../cli/commands.md#hassette-execution) does the same on the command line. It takes the full ID. `hassette listener <id>` and `hassette job <id>` list it in their Execution ID column, but a terminal table shortens it. Add `--json` or pipe the output to get the full ID.

## What Log Views Show by Default

Every log view and `hassette log` apply one default: app-authored lines, plus framework lines at ERROR and above. The Logs page, an app's logs, an execution's logs, `hassette log` and `hassette execution` all show the same set. A Hassette error never hides behind the default.

Framework lines below ERROR take one opt-in. The **all framework lines** checkbox adds them to every web UI log view, and the browser remembers it. `--author all` does the same for `hassette log` and `hassette execution`. `--author app` and `--author framework` each show one author only, with no ERROR floor.

The web UI marks framework lines with a **Framework** badge. The CLI's Author column reads `framework`. Console output prefixes the subject with `hassette:`, as in `[hassette:garage_door]`.

### The Opt-In and `framework_log_level`

The opt-in and an app's `framework_log_level` control different stages. `framework_log_level` sets how much detail Hassette writes about that app. The opt-in sets whether log views show it.

With `framework_log_level = "DEBUG"` and the opt-in off, Hassette writes its debug lines about the app, but log views hide them. Seeing them takes three settings:

- `framework_log_level = "DEBUG"` on the app
- `log_persistence_level = "DEBUG"` under `[hassette.logging]`
- the opt-in: the **all framework lines** checkbox in the web UI, or `--author all` on the CLI

The first two live in `hassette.toml`:

```toml
--8<-- "pages/operating/snippets/see_framework_debug_lines.toml"
```

The log views read from the telemetry database, which stores only lines at or above `log_persistence_level`. That defaults to the global `log_level`, so debug lines need the lower floor too. [Log Level Tuning](log-levels.md#hassettes-lines-about-one-app) covers both config keys.

## Hassette's Problem or the App's

The author and subject of an error line point to where the problem lives.

- **An `app` line** comes from the app's own code or a library it attached. The fix belongs in the app.
- **A `framework` ERROR with an app subject** is Hassette reporting on that app. "Handler error" and "Job error" lines are this kind. The traceback below the message shows where the exception started. A traceback ending in the app's file points at the app. One ending inside `hassette` points at Hassette, or at the app call just above it.
- **A `framework` ERROR with no subject** concerns Hassette itself, such as the Home Assistant connection or the database.

Framework WARNING lines about an app, such as a handler timeout, stay hidden until the opt-in is on. The Handlers tab records every timeout and error regardless of log settings.

When the default view shows nothing wrong, the opt-in plus `framework_log_level = "DEBUG"` and `log_persistence_level = "DEBUG"` (see [The Opt-In and `framework_log_level`](#the-opt-in-and-framework_log_level)) is the next step. Hassette's lifecycle, listener, job and API detail about the app then appears beside the app's own lines.

## Limits for Loggers No App Owns

Loggers no app owns take their subject from the work in progress. Two cases give them the wrong subject or none.

### Raw Threads

A thread started with `threading.Thread` begins with no work in progress. Its lines carry no execution ID. An app's own loggers still stamp their subject, because the logger carries it. Module and library loggers stamp no subject, so their lines miss the app's log view. They still appear on the Logs page and in `hassette log` without `--app`.

`self.task_bucket.run_in_thread` copies the caller's context into the thread, so every line keeps its subject and execution ID. [Offloading Blocking Code](../core-concepts/apps/task-bucket.md#offloading-blocking-code) covers it.

### Inherited Context

A task started during a handler or job inherits that run's subject and execution ID. Its lines keep both even after the run that started it ends. An app's background task spawned from a handler shows up in that handler's execution logs for as long as it runs. The app's log view shows all of its lines either way.

A Hassette task started during an app's run inherits the same context. Its lines from loggers no app owns then name an app they aren't about. These lines still read `framework`, so the default view hides them below ERROR. The logger name, shown in JSON output and matched by the Logs page search, identifies the service that wrote them.

## See Also

- [Log Level Tuning](log-levels.md): per-service levels, `framework_log_level`, persistence and console formats
- [Read and Filter Logs](../web-ui/logs.md): the Logs page and its filters
- [`hassette log`](../cli/commands.md#hassette-log): the CLI log commands
