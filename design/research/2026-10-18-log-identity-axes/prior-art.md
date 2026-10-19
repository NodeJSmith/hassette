---
topic: "Logging identity: author, subject and execution on framework-written log lines"
date: 2026-10-18
status: Draft
---

# Prior Art: Logging Identity Axes

## The Problem

A framework writes log lines about user code all the time: "starting app X", "handler raised", "job timed out". Each line has three independent properties: who wrote it (author), which user unit it's about (subject), and which run it belongs to (execution). #2496 found that Hassette's `source_tier` merges author and subject. #3044 then showed the same gap from the console side. Trimming redundant fields broke attribution because the logger name was assumed to identify the subject, and it doesn't: framework loggers log on behalf of apps, and default instance names collide.

This brief surveys how comparable frameworks record those three axes, name multi-instance user code, decide whose log level governs a framework line about user code, and render identity on a human-read line. It builds on two earlier briefs and doesn't repeat them: `2026-05-02-logging` (contextvar correlation, per-run capture) and `2026-04-07-telemetry-tier-separation` (a source tag on every record).

## How We Do It Today

- **Author** is `source_tier`, stamped two ways. `_ResourceContextFilter` (`resources/base.py`) overwrites `record.source_tier` with the owning resource's ClassVar (`"app"` for `App`), so every line through an app's logger is app-tier, including generic lifecycle code in `resources/lifecycle.py` and the app's own Bus/Scheduler/Api children. For records with no tier, `CorrelationFilter` (`logging_.py`) infers `"app" if app_key else "framework"`, which reads author from subject.
- **Subject** is `app_key`/`instance_name`/`instance_index`, bound as structlog contextvars by `CommandExecutor.bind_execution_context` and around initialize/shutdown in `app_lifecycle_instances.py`, then stamped by `CorrelationFilter`.
- **Execution** is `execution_id`/`listener_id`/`job_id`/`execution_kind` from `CURRENT_EXECUTION_ID` and the same contextvars. This axis works.
- **Logger names** come from `Resource.unique_name` (`hassette.<instance_name>[.<Child>]`). The default `instance_name` is `ClassName.<index>`, so two config sections using the same class produce the same logger name, `unique_name` and `owner_id`. Nothing validates uniqueness.
- **Console** is structlog `ConsoleRenderer` with every bound key in a `key=value` tail, including `None` values.

## Patterns Found

### Pattern 1: Author is the logger, subject is IDs on the record

**Used by**: Celery, Temporal, Airflow 3, AppDaemon, Home Assistant, Prefect (partly)

**How it works**: No surveyed system has an explicit author field. Author is whichever logger wrote the line: Celery's `celery.app.trace` writes "Task X[id] raised unexpected", Airflow 3's Task SDK splits `supervisor` from `task`, and Temporal's worker module logger writes activation failures. Subject is carried separately as ID fields on the record: Prefect's `flow_run_id`/`task_run_id`, Temporal's `temporal_workflow` extra, Celery's `extra['data']`.

Because logger name and `extra` don't interact, the two axes are independent by construction. Prefect is the cautionary case: `get_run_logger()` serves both engine and user lines under `prefect.flow_runs`, so its logger name doesn't reliably say who wrote a line.

**Strengths**: Free with stdlib logging. Author can't be inferred from subject, because nothing connects them.

**Weaknesses**: It works only if framework code logs through framework loggers. It breaks down when one logger serves both authors, which is the Prefect case and Hassette's app-resource logger today. Subject stamping on framework lines is inconsistent in practice; some Temporal sites omit it.

**Example**: https://github.com/temporalio/sdk-python/blob/main/temporalio/worker/_workflow_instance.py, https://github.com/celery/celery/blob/main/celery/app/trace.py

### Pattern 2: Framework lines about user code use the framework's logger and level

**Used by**: AppDaemon, Home Assistant

**How it works**: AppDaemon's app manager logs "Calling initialize() for X" through its own `AppDaemon._app_management` logger, with the app name as a message argument. Home Assistant's `config_entries` logs "Error setting up entry %s for %s" with the entry title and domain. Neither borrows the user unit's logger. As a result, the user's level knob governs only user-written output, and raising an app's or integration's level doesn't surface the framework's lines about it.

**Strengths**: Framework events keep a stable, operator-owned level. This is #2496's option 2(a).

**Weaknesses**: Both put subject in free text, not structured fields. HA uses the non-unique title, so two entries of one domain give indistinguishable lines.

**Example**: https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/app_management.py, https://github.com/home-assistant/core/blob/dev/homeassistant/config_entries.py

### Pattern 3: One owner-level setting fans out to a declared set of loggers

**Used by**: Home Assistant, AppDaemon, pyscript

**How it works**: Home Assistant's "enable debug logging" expands a domain via `get_integration_loggers` to three sets: `homeassistant.components.<domain>`, the integration's package path, and the manifest's declared `loggers` (third-party libraries). It doesn't include core's `config_entries` lines about that integration. AppDaemon's per-app `log_level` sets both the app logger and that app's error logger. pyscript relies on logger-name prefix inheritance.

**Strengths**: "Turn up logging for this app" is one operation, as #462 wants. HA needed an explicit declared list because name-prefix derivation misses library loggers.

**Weaknesses**: It's tied to logger names. In all three, the set is code the owner brings (its loggers, its libraries), never the framework's own lines about it.

**Example**: https://github.com/home-assistant/core/blob/dev/homeassistant/components/logger/helpers.py

### Pattern 4: The unique config key is the identity and the log label

**Used by**: AppDaemon, pyscript

**How it works**: The user-chosen section key in `apps.yaml` is the app's name, its logger suffix (`AppDaemon.<key>`) and its log label. Running the same class with N configs means N keys, so a mapping key guarantees uniqueness structurally. The docs say the name "must be unique", but no code detects duplicates. AppDaemon forbids dots in names because its formatter renders only the last dotted segment.

Celery is the one system that prints a human name and an opaque id together (`task_name[task_id]`). Home Assistant stores `entry_id` but prints only the title.

**Strengths**: One name for grep, level config and display.

**Weaknesses**: Renaming the key renames the logs. Dotted names need care in the identity slot.

**Example**: https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/adbase.py

### Pattern 5: The human line carries one identity token; structured context goes elsewhere

**Used by**: AppDaemon, Home Assistant, Celery; Dagster for UI visibility

**How it works**: Default human formats are time, level, one identity token and the message:
- AppDaemon: `{asctime} {levelname} {appname:<20}: {message}`
- HA: `... %(levelname)s (%(threadName)s) [%(name)s] %(message)s`
- Celery switches to `%(task_name)s[%(task_id)s]: %(message)s` when a task is in scope.

None of them appends a key=value tail. structlog supports this shape through `ConsoleRenderer(columns=...)`, where a column formatter that returns `""` drops the key. It has no built-in drop-None option.

For per-unit views, Dagster shows framework events about a run by default. Its default levels are `INFO`, `WARNING`, `ERROR`, `CRITICAL` and a synthetic `EVENT`, with DEBUG hidden. Framework events carry a typed `dagster_event` payload that user logs lack, so the UI can filter on author directly.

**Strengths**: Short and scannable on narrow screens. The identity token can change with what's in scope, as Celery's format does.

**Weaknesses**: Context is lost on the console unless another sink holds it. Hassette has one already: JSON output and the DB.

**Example**: https://docs.celeryq.dev/en/stable/userguide/configuration.html, https://github.com/dagster-io/dagster/blob/master/js_modules/ui-core/src/runs/LogLevel.ts

## Anti-Patterns

- **Inferring author from ambient context.** Airflow's per-TI file and Celery's `TaskFormatter` attribute whatever is in scope; Celery falls back to `'???'` outside a task. Hassette's `CorrelationFilter` fallback is this pattern. Prefect's handler instead warns, ignores or raises when context is missing, controlled by `PREFECT_LOGGING_TO_API_WHEN_MISSING_FLOW`.
- **One logger serving both authors.** Prefect's `get_run_logger` does this, and so do Hassette's app-resource loggers used by `lifecycle.py`.
- **Title-only subject on framework lines.** HA's non-unique entry title makes two entries' setup errors indistinguishable. Hassette's `ClassName.<index>` default has the same problem.
- **Dotted names in the identity slot.** AppDaemon forbids them, because a formatter that takes the last segment misrenders them.

## Relevance to Us

1. **Author.** Pattern 1 plus Pattern 2 is the consensus: framework code logs through framework loggers, and author follows from which logger wrote the line. That favors #2496's option 2(a) over 2(b). Option 2(b) means stamping every call site, which is the inconsistency Temporal shows. `source_tier` can stay as a stored field, because Hassette's UI tier filter needs one, and Dagster shows that a queryable author field is useful. But it should be computed from the writing logger's tree and never from `app_key`. No peer has a separate author field beyond that, so we shouldn't build more than this.
2. **Subject.** Binding app identity in contextvars around lifecycle and executions is fine. Those lines are about the app, and Prefect does the same with explicit-over-ambient precedence. The bug was only ever reading author from subject. Keep subject on framework lines, as Temporal's activation-failure line does. This also answers #2496's decision 5: `CommandExecutor` error lines stay framework-authored and keep `app_key` and `execution_id`.
3. **Log level.** Peers split this. The app's level governs code the app brings: its own logger, and in HA its libraries. The framework's lines about the app keep the framework's level. For #462, app-owned Bus/Scheduler/Api children are framework code. Under the peer model they'd be framework-authored and framework-levelled, which contradicts #462's premise that "those *are* part of the app". The sketch has to decide this explicitly. HA's "declared set" is the precedent if Hassette wants an app's level to also raise its children.
4. **Naming (#740, collision).** Every peer makes the logger name an identity-derived, human-readable label. That argues against #740's suggested opaque `hassette.Bus.<unique_id>` names. AppDaemon names the instance by its unique config key. Hassette's equivalent is deriving the default `instance_name` from `app_key` (plus the index for multi-instance), not from the class name. That removes the collision structurally, the way a mapping key does for AppDaemon. Explicitly set duplicate `instance_name`s still need a cheap check. No peer has one, but no peer allows an explicit override either.
5. **Console (#3044, #3046).** All three human formats show one identity token and no tail. That makes #3044's "drop some keys from the tail" a halfway step. The peer shape is a leading identity column whose value depends on what's in scope, like Celery's format switch: the subject's instance name when an app is bound, otherwise the logger name. The tail is dropped on the console, and JSON keeps everything. This collapses #3044 and #3046 into one rendering change, and structlog's `columns=` API supports it directly.
6. **Per-app views (#2496 decision 3).** Dagster, the only peer with per-run views and an author discriminator, shows framework events about the unit by default and distinguishes them with a filter. Per-app views filter by subject, so framework-authored lines about the app should be shown by default and marked.
7. **Requirement for the sketch: "debug my app, including Hassette's part".** A user who suspects the framework must be able to see every line about their app, at the verbosity they chose, with author marked. Separating the axes keeps this possible: per-app views and execution views filter on subject, which framework lines keep. But option 2(a) moves framework lines off the app's logger, so the app's `log_level` stops governing them. An app at DEBUG would then lose the framework's DEBUG lines about it, which it gets today by accident. The sketch has to pick how that level reaches framework lines about the app. One option is a level check that reads the record's subject, which adapts HA's per-integration debug toggle (see 3). The alternative is documenting "raise the framework levels", which is process-wide and noisy. Related, and to verify: lines from an app's own Bus/Scheduler/Api children that are emitted outside a contextvar window appear to carry no `app_key`, so they'd be missing from the per-app view today. Stamping subject from the owning resource would fix that.
8. **#739 (`owner_key`).** Peers call subject "the run" or "the task", with no owner abstraction. The rename is cosmetic against this evidence. Its value is that framework records use `__framework__.X` under a field called `app_key`. Rename only if the sketch keeps framework rows in that column.

## UX/DX Scope for the Sketch

The sketch must settle three things as explicit decisions:

1. **Author for loggers outside the framework.** User module loggers wired in via `extra_loggers`, and libraries the app calls while a handler runs, are code the app brought. They count as app-authored. Today they get `app` only through the `app_key` inference, so deleting that inference without this rule would re-tag them as framework. HA's manifest `loggers` takes the same position.
2. **Subject outside contextvar reach.** `AppSync` handlers run in threads, and users start their own threads and tasks. Context-copying paths (`asyncio.to_thread`, the task bucket) keep subject; a raw `threading.Thread` doesn't. The choice is a fallback, such as stamping subject from the owning resource, or a documented limitation.
3. **The default instance name is user-visible.** A name derived from `app_key` instead of the class changes:
   - logger names users reference in `logging:` config;
   - stored `instance_name` values;
   - what the CLI's `--instance` accepts;
   - anything users grep for.

   Pre-v1 this is a clean break with a migration note, not a shim. Old rows will mix the two naming schemes until retention removes them.

These are scope items the milestone should cover:

4. **Wire meaning of `source_tier`, plus #739.** JSON logs, the logs API, the CLI's `--source-tier`, and listener/job tiers all expose the field. A change of meaning breaks external JSON consumers and needs `client_compat` handling. Historical rows stay mis-tagged; the default is no backfill, with retention removing them.
5. **Per-app level knob (#345).** It must use whichever model the sketch picks for "the app's level reaches framework lines about the app".
6. **CLI parity.** `hassette log --app` shows the same author marker as the UI. Add-on debugging happens mostly in the terminal.
7. **User-facing docs.** A page covering where an app's logs go, what the tier means, and how to tell whether a problem is in Hassette or the app.

## Recommendation

- Adopt Pattern 1 plus Pattern 2: author comes from the writing logger, and framework lifecycle and executor lines go through framework loggers with subject fields attached (#2496 option 2(a)).
- Delete the `app_key` → tier inference. Treat `source_tier` as "which logger tree wrote this".
- Name instances after their config key, not their class. Logger names stay readable labels; don't make them opaque.
- Replace the console key=value tail with a single scope-dependent identity column. That handles #3044 and #3046 together.
- Show framework lines about an app in that app's views by default, and mark them.

The open decision is #462, whether an app's level reaches its children. Peers point toward "no, children are framework" with HA's declared-set as the opt-in exception. That's the sketch's call.

Coverage gaps:
- Which Prefect logger writes "Finished in state", and Prefect's UI log-filter defaults.
- Temporal's event-history defaults.
- AppDaemon's callback-exception logging site (source 404).
- Celery's task-state log level.
- A documented compact-format convention for HA add-on log tabs. None was found; a community thread confirms the readability complaint.

All source reads were from `main`/`dev` branches on 2026-10-18. These URLs were not live-verified.

## Sources

### Reference implementations
- https://github.com/PrefectHQ/prefect/blob/main/src/prefect/logging/loggers.py — `get_run_logger` adapters and run-identity extras
- https://github.com/PrefectHQ/prefect/blob/main/src/prefect/logging/handlers.py — `APILogHandler`: record-first, contextvar-fallback run ID
- https://github.com/dagster-io/dagster/blob/master/python_modules/dagster/dagster/_core/events/log.py — `EventLogEntry.dagster_event` discriminator
- https://github.com/dagster-io/dagster/blob/master/python_modules/dagster/dagster/_core/log_manager.py — `log_dagster_event` vs `context.log`
- https://github.com/dagster-io/dagster/blob/master/js_modules/ui-core/src/runs/LogLevel.ts — `EVENT` pseudo-level, default-visible
- https://github.com/celery/celery/blob/main/celery/app/trace.py — worker failure line logger and extras
- https://github.com/celery/celery/blob/main/celery/app/log.py — `TaskFormatter`, `'???'` fallback
- https://github.com/celery/celery/blob/main/celery/utils/log.py — `celery.task` vs `celery.worker` trees, reserved names
- https://github.com/temporalio/sdk-python/blob/main/temporalio/workflow/_sandbox.py — workflow logger `temporal_workflow` extra
- https://github.com/temporalio/sdk-python/blob/main/temporalio/worker/_workflow_instance.py — SDK failure lines with subject extra
- https://github.com/apache/airflow/blob/main/task-sdk/src/airflow/sdk/execution_time/supervisor.py — `supervisor` vs `task` logger split
- https://github.com/apache/airflow/blob/main/airflow-core/src/airflow/utils/log/file_task_handler.py — `StructuredLogMessage`, no author field
- https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/logging.py — `AppDaemon.<name>` loggers, `appname` formatter
- https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/adbase.py — per-app `log_level` sets app and error loggers
- https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/app_management.py — framework lifecycle lines on the framework logger
- https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/models/config/app.py — app name is the config key
- https://github.com/home-assistant/core/blob/dev/homeassistant/config_entries.py — entry setup errors with title and domain
- https://github.com/home-assistant/core/blob/dev/homeassistant/components/logger/helpers.py — `get_integration_loggers` fan-out
- https://github.com/home-assistant/core/blob/dev/homeassistant/bootstrap.py — HA default log format

### Blog posts & writeups
- https://community.home-assistant.io/t/wth-is-addon-log-so-bad/226284 — add-on log readability complaints
- https://hacs.xyz/docs/use/troubleshooting/logs — debug-logging button covers only the integration's own loggers

### Documentation & standards
- https://opentelemetry.io/docs/specs/otel/logs/data-model/ — InstrumentationScope (emitter) vs Resource (entity); no "emitted by X about Y" convention
- https://docs.prefect.io/v3/develop/logging — automatic run logs, per-logger levels
- https://appdaemon.readthedocs.io/en/latest/CONFIGURE.html — AppDaemon log format and config
- https://appdaemon.readthedocs.io/en/3.0.2/APPGUIDE.html — "must be unique" app names
- https://contributors.home-assistant.io/core/integrations/manifest/ — manifest `loggers`
- https://www.home-assistant.io/integrations/logger/ — per-namespace levels
- https://hacs-pyscript.readthedocs.io/en/latest/reference.html — pyscript logger names and levels
- https://docs.celeryq.dev/en/stable/userguide/configuration.html — `worker_log_format` / `worker_task_log_format`
- https://www.structlog.org/en/stable/console-output.html — `ConsoleRenderer(columns=...)`, dropping keys
- https://www.zigbee2mqtt.io/guide/configuration/logging.html — Zigbee2MQTT log config
