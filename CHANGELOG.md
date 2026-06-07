# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.41.0](https://github.com/NodeJSmith/hassette/compare/v0.40.0...v0.41.0) (2026-06-07)


### Features

* split health endpoint into liveness, readiness, and aggregate status ([#982](https://github.com/NodeJSmith/hassette/issues/982)) ([1853b8f](https://github.com/NodeJSmith/hassette/commit/1853b8f4c4b70e4cff2b9e2028813252487724af))

## [0.40.0](https://github.com/NodeJSmith/hassette/compare/v0.39.1...v0.40.0) (2026-06-06)


### ⚠ BREAKING CHANGES

* `GET /api/health` now returns HTTP 200 (not 503) while the process is serving — for `starting` and `degraded` as well as `ok`. The handler never returns 503. Any healthcheck or restart automation pointed at `/api/health` should move to `/api/health/live` (liveness, HA-independent) for restart decisions, or `/api/health/ready` (200 only when fully connected) for traffic routing. Separately, a fatal, unrecoverable shutdown now exits with a non-zero status code instead of 0, so supervisors using `Restart=on-failure` will restart after a fatal crash; a clean operator shutdown (SIGTERM / `docker stop`) still exits 0.

### Features

* add liveness/readiness health endpoints and non-zero fatal exit ([#978](https://github.com/NodeJSmith/hassette/issues/978)) ([3c84005](https://github.com/NodeJSmith/hassette/commit/3c84005b37730da85171a2d335d6eb8f303ab0d9))

## [0.39.1](https://github.com/NodeJSmith/hassette/compare/v0.39.0...v0.39.1) (2026-06-05)


### Bug Fixes

* health endpoint returns 200 for degraded status, 503 only for starting ([#975](https://github.com/NodeJSmith/hassette/issues/975)) ([d09b709](https://github.com/NodeJSmith/hassette/commit/d09b7095f435f601e38817c726d4d68fe1b3764d))

## [0.39.0](https://github.com/NodeJSmith/hassette/compare/v0.38.0...v0.39.0) (2026-06-01)


### ⚠ BREAKING CHANGES

* `App.send_event(topic, data)` and `AppSync.send_event_sync(topic, data)` are removed. Use `self.bus.emit(topic, data)` instead — same arguments, same behavior, now on the bus where subscriptions live.
* `HassettePayload` no longer accepts an `event_type` parameter. Remove `event_type=` from any `HassettePayload(...)` or `HassetteServiceEvent(...)` construction. `EventPayload` base class also no longer has `event_type` — use `HassPayload.event_type` for HA events, or `event.topic` for routing.

### Features

* broadcast custom events between apps with `Bus.emit()` and receive typed payloads via `D.EventData[T]` ([#952](https://github.com/NodeJSmith/hassette/issues/952)) ([082a59e](https://github.com/NodeJSmith/hassette/commit/082a59ec2cc9d1841bec8648116c865813d47721))


### Bug Fixes

* prevent aiosqlite worker threads from blocking interpreter exit ([#923](https://github.com/NodeJSmith/hassette/issues/923)) ([#948](https://github.com/NodeJSmith/hassette/issues/948)) ([a17b57b](https://github.com/NodeJSmith/hassette/commit/a17b57b449bb473971f57f3b5fc5cd0e9ccd4d6a))


### Refactoring

* remove event_type from EventPayload base and HassettePayload ([#947](https://github.com/NodeJSmith/hassette/issues/947)) ([8037297](https://github.com/NodeJSmith/hassette/commit/8037297ac33e3854740b7ce7dd4629a5f980bfa5))
* remove redundant event_name parameter from send_event ([#946](https://github.com/NodeJSmith/hassette/issues/946)) ([e282f81](https://github.com/NodeJSmith/hassette/commit/e282f8116e35008dc171d4594131261e8546acc3)), closes [#943](https://github.com/NodeJSmith/hassette/issues/943)

## [0.38.0](https://github.com/NodeJSmith/hassette/compare/v0.37.0...v0.38.0) (2026-05-31)


### Features

* add Python 3.14 support ([#939](https://github.com/NodeJSmith/hassette/issues/939)) ([86049f2](https://github.com/NodeJSmith/hassette/commit/86049f299dded23b25d9c41eec4d61f2c1cc1437))
* add missing synchronous Bus and Scheduler methods for AppSync ([#931](https://github.com/NodeJSmith/hassette/issues/931)) ([962631f](https://github.com/NodeJSmith/hassette/commit/962631f7db4dd69ff3e05d557b8df17dce14abde))

## [0.37.0](https://github.com/NodeJSmith/hassette/compare/v0.36.0...v0.37.0) (2026-05-30)

### ⚠ BREAKING CHANGES

This release redesigns registration and telemetry. Most existing apps need code changes.

#### Registration is now async

Bus and scheduler registration methods are now `async` and must be awaited.

`name=` is now required on every bus registration (it was optional). Omitting it raises `ListenerNameRequiredError`.

```python
# before
self.bus.on_state_change("light.kitchen", handler=self.on_change)
self.scheduler.run_in(self.task, 5)

# after
await self.bus.on_state_change("light.kitchen", handler=self.on_change, name="kitchen_light")
await self.scheduler.run_in(self.task, 5)
```

Affected bus methods: `on_state_change`, `on_attribute_change`, `on_call_service`, `on_component_loaded`, `on`.

Affected scheduler methods: `schedule`, `run_in`, `run_once`, `run_every`, `run_minutely`, `run_hourly`, `run_daily`, `run_cron`.

`Subscription.registration_task` is removed. Registration completes inline now, so `sub.listener.db_id` is a valid integer as soon as the awaited call returns.

#### Unified executions model

`HandlerInvocation` and `JobExecution` are replaced by a single `Execution` model with a `kind` discriminator (`"listener"` or `"job"`).

The REST endpoint `/api/telemetry/handler/{id}/invocations` is now `/api/telemetry/listener/{id}/executions`. The WebSocket signals are unified under the same `executions` shape.

#### Migration runner replaces Alembic

The Alembic migration stack is replaced by a PRAGMA `user_version` runner with plain SQL files. Existing databases are migrated automatically on first startup. No manual migration steps required, but any tooling that reads `alembic_version` will need updating.

#### Removed: `dropped_no_session`

The `dropped_no_session` counter is removed from the API response, the dashboard status badge, and the `sessions` table.

### Features

* redesign telemetry database around a unified executions table ([#922](https://github.com/NodeJSmith/hassette/issues/922)) ([b97a495](https://github.com/NodeJSmith/hassette/commit/b97a4953a326584790576d37aecb5a5fc00cb4ff))

### Bug Fixes

* fix starlette host header injection (CVE-2026-48710) ([#907](https://github.com/NodeJSmith/hassette/issues/907)) ([c9ad12f](https://github.com/NodeJSmith/hassette/commit/c9ad12f4e15b5ee047c3249c241bab0c8b96a0e3))

### Internal

* decompose bus_service.py into focused modules ([#919](https://github.com/NodeJSmith/hassette/issues/919))
* extract Service and RestartSpec from resources/base.py ([#921](https://github.com/NodeJSmith/hassette/issues/921))
* docs voice guide, quality rules, and audit ([#910](https://github.com/NodeJSmith/hassette/issues/910), [#917](https://github.com/NodeJSmith/hassette/issues/917), [#920](https://github.com/NodeJSmith/hassette/issues/920))

## [0.36.0](https://github.com/NodeJSmith/hassette/compare/v0.35.0...v0.36.0) (2026-05-28)


### Features

* **ui:** apply design rules — typography, spacing, radii, tables, and visual cleanup ([#905](https://github.com/NodeJSmith/hassette/issues/905)) ([8183d57](https://github.com/NodeJSmith/hassette/commit/8183d578b7f9a1682c87d70c7fc3c5509293a431))

## [0.35.0](https://github.com/NodeJSmith/hassette/compare/v0.34.0...v0.35.0) (2026-05-27)


### ⚠ BREAKING CHANGES

* `hassette` with no arguments no longer starts the server. Use `hassette run` instead. The `hassette service` command and `GET /api/services` endpoint have been removed.

### Features

* require explicit `hassette run` to start the server ([#896](https://github.com/NodeJSmith/hassette/issues/896)) ([d8bbaa3](https://github.com/NodeJSmith/hassette/commit/d8bbaa3e90f4b97c88063984a21680d0b33dbae7))

## [0.34.0](https://github.com/NodeJSmith/hassette/compare/v0.33.0...v0.34.0) (2026-05-27)

### Breaking Changes

- `state._has_feature(SomeFeature.FLAG)` renamed to `state.has_feature()` — remove the leading underscore. The `supports_*` convenience properties (e.g., `state.supports_brightness`) are unchanged. ([#891](https://github.com/NodeJSmith/hassette/issues/891))
- `Api.get_states_iterator()` and `ApiSyncFacade.get_states_iterator()` removed — the generator-based iterator does not work correctly in sync code. Use `get_states()` instead. ([#891](https://github.com/NodeJSmith/hassette/issues/891))

### Logging

- Logging pipeline managed as a `LoggingService` Resource with lifecycle ordering — the async pipeline starts during service initialization and shuts down before the database, ensuring pending log records flush cleanly. ([#887](https://github.com/NodeJSmith/hassette/issues/887))
- Timer-based flush bounds how long log records sit in the write queue under low load (default 5s), instead of waiting for the next batch to fill. ([#890](https://github.com/NodeJSmith/hassette/issues/890))
- Failed write batches retry with linear backoff (1s, 2s, 3s) instead of immediately, giving the database time to recover. ([#890](https://github.com/NodeJSmith/hassette/issues/890))

### CLI

- Improved `hassette status`/`hassette query` output formatting — nested sub-models render as labeled sections instead of raw JSON, `None` shows as `—`, booleans show lowercase, and panel titles are humanized. ([#880](https://github.com/NodeJSmith/hassette/issues/880))
- Job and listener tables show App column, actual schedule text, method-only handler names, and entity targets. ([#880](https://github.com/NodeJSmith/hassette/issues/880))
- `fmt_relative_time` shows `in 3h` for future timestamps instead of `soon`. ([#880](https://github.com/NodeJSmith/hassette/issues/880))

### Bug Fixes

- Fix 3 bugs in example apps where `BinarySensorState.value` and `LightState.value` (both `bool`) were compared against string `"on"`/`"off"`. ([#872](https://github.com/NodeJSmith/hassette/issues/872))

## [0.33.0](https://github.com/NodeJSmith/hassette/compare/v0.32.0...v0.33.0) (2026-05-26)

### Breaking Changes

- `GET /api/logs/by-execution/{execution_id}` has been removed. Use `GET /api/executions/{execution_id}` instead. The response shape (`LogsByExecutionResponse`) is unchanged. ([#865](https://github.com/NodeJSmith/hassette/issues/865))

### CLI

- `hassette query` subcommand for querying all read-only API endpoints from the command line — apps, handlers, jobs, invocations, executions, logs, config, and sessions. ([#838](https://github.com/NodeJSmith/hassette/issues/838))
- `--generate-completion` replaces `--install-completion` — outputs the shell completion script to stdout instead of modifying shell config files. Pipe to a file in your `$fpath` to install. ([#870](https://github.com/NodeJSmith/hassette/issues/870))
- Fix zsh completion function name with cyclopts 4.16+ — `hassette --generate-completion zsh` now produces the correct `_hassette` function name instead of `_cyclopts_hassette`. ([#871](https://github.com/NodeJSmith/hassette/issues/871))

### Web UI

- Redesigned accent color system and improved visual depth with systematized design tokens. ([#842](https://github.com/NodeJSmith/hassette/issues/842))
- Mobile navigation integrated into the status bar with a hamburger menu. ([#857](https://github.com/NodeJSmith/hassette/issues/857))
- Unified table sort headers across all pages and fixed mobile table column rendering. ([#853](https://github.com/NodeJSmith/hassette/issues/853))
- Aria-live announcements for WebSocket connection status changes. ([#827](https://github.com/NodeJSmith/hassette/issues/827))

### Configuration

- TOML `[hassette]` section now deep-merges, preserving top-level app definitions alongside nested sections. ([#826](https://github.com/NodeJSmith/hassette/issues/826))
- Auto-migrate legacy `HASSETTE__APP_DIR` environment variable to `HASSETTE__APPS__DIRECTORY`. ([#831](https://github.com/NodeJSmith/hassette/issues/831))
- Environment variables correctly override config file values for legacy flat config keys. ([#836](https://github.com/NodeJSmith/hassette/issues/836))

### Performance

- Telemetry database queries now have a configurable read timeout, preventing indefinite hangs on slow or locked databases. ([#860](https://github.com/NodeJSmith/hassette/issues/860))

### Documentation

- Rewrite web UI documentation with full page coverage. ([#806](https://github.com/NodeJSmith/hassette/issues/806))
- Update configuration references to post-v0.32.0 nested key format. ([#818](https://github.com/NodeJSmith/hassette/issues/818))
- Clean up docs site navigation — remove redundant tabs, fix mid-viewport layout. ([#858](https://github.com/NodeJSmith/hassette/issues/858))

## [0.32.0](https://github.com/NodeJSmith/hassette/compare/v0.31.0...v0.32.0) (2026-05-20)


### Breaking Changes

- TOML app configuration path changed from `[hassette.app.apps.<name>]` to `[hassette.apps.<name>]`. The app settings section changed from `[hassette.app]` to `[hassette.apps]`. Environment variables changed from `HASSETTE__APP__*` to `HASSETTE__APPS__*`. Python access changed from `config.app.*` to `config.apps.*`. The API response field changed from `app` to `apps`. Update your hassette.toml, environment variables, and any code that accesses the config object.

### Refactoring

- flatten app config path from [hassette.app.apps] to [hassette.apps] ([#792](https://github.com/NodeJSmith/hassette/issues/792)) ([a4251f1](https://github.com/NodeJSmith/hassette/commit/a4251f1640fe6350c90e14e7f9804f50172435f7))

## [0.31.0](https://github.com/NodeJSmith/hassette/compare/v0.30.0...v0.31.0) (2026-05-20)

### Breaking Changes

- **`HassetteConfig` restructured into nested groups** — all configuration fields moved under group prefixes. Environment variables change from `HASSETTE__LOG_LEVEL` to `HASSETTE__LOGGING__LOG_LEVEL`, `HASSETTE__DB_PATH` to `HASSETTE__DATABASE__PATH`, etc. TOML/YAML config files and programmatic `config.*` access follow the same pattern (`config.log_level` → `config.logging.log_level`). Old flat keys are detected at startup with a deprecation warning but will not take effect — update your env vars, config files, and any direct `HassetteConfig` field access to the nested format. See `src/hassette/config/legacy.py` for the full old→new mapping. (#789)

### Logging

- Replace `coloredlogs` with a structlog-based logging pipeline — structured, context-rich log records with console and JSON formatters. All log I/O routed through an async queue so `emit()` never blocks the event loop. (#744)
- Log records persisted to the telemetry database with configurable retention (`log_retention_days`) and persistence level (`log_persistence_level`). (#744)
- New log viewer page in the web UI with server-side level filtering, search, column picker, and expand-to-detail. (#744)

### Scheduler

- `if_exists="replace"` option on all scheduler registration methods — when a job with the same name already exists, `"replace"` cancels the old job and registers the new one in its place. Useful when job configuration changes between app reloads. (#780)

### Web UI

- Complete UI redesign with apps-focused layout — sidebar navigation with live status dots, collapsible status groups, multi-instance app expansion, and command palette (Ctrl+K / Cmd+K). New app detail tabs: overview, handlers, code, config, and per-app logs. Global pages: cross-app handler/job table, diagnostics, and session history. (#710)
- Real-time updates for handler/job invocation counts, health metrics, last-fired timestamps, and dashboard stats via WebSocket — no page refresh needed. Relative timestamps ("5m ago") tick forward on a 30-second interval. (#735)
- Handler health table replaced with responsive card grid — each card shows status, handler name, kind, run stats (count, avg duration, error rate, last active), and error details. Keyboard accessible, responsive columns, scroll after 3 rows. (#761)
- Consistent table pattern across apps, handlers, and logs pages with shared sort headers, inline column filter popovers, and unified table shell. (#767)
- Multi-instance app parent page now shows shared tabs (overview, code, logs, config) with an instance column in the logs tab, instead of only an instance card grid. (#753)
- API errors surfaced via toast notifications (sonner) instead of silently swallowed — users now see a notification when data fails to load. (#751)
- Real-time handler updates on overview tab with failing-row background tint and blended hover state. (#748)

### Configuration

- `HassetteConfig` organized into 8 nested groups: `DatabaseConfig`, `WebSocketConfig`, `LoggingConfig`, `LifecycleConfig`, `WebApiConfig`, `AppConfig`, `SchedulerConfig`, `FileWatcherConfig`. The `/api/config` REST endpoint and frontend config page reflect the nested structure. (#789)

### Bug Fixes

- Handler cancel-then-resubscribe race and replacement ordering bugs fixed — Bus routing operations now execute synchronously in deterministic order, eliminating task interleaving between cancel and re-register. (#785, #658, #781)
- Log table REST API level filter fixed — was sending exact-match filter to the server instead of fetching all levels; column picker checkbox alignment, filter panel overflow, and mobile "reset filters" button also fixed. (#755)
- PyPI package now includes SPA frontend assets — `pip install hassette` was missing the web UI since v0.30.0. Also backported to v0.30.1. (#790, #788)

## [0.30.0](https://github.com/NodeJSmith/hassette/compare/v0.29.0...v0.30.0) (2026-05-10)

### Breaking Changes

- **Field type narrowing (StrEnum)** — Fields previously typed as `str` are now typed with their domain StrEnum. StrEnums accept string construction so `state.attributes.hvac_mode == "heat"` still works, but type checkers will flag comparisons against raw strings. Affected fields: `ClimateAttributes.hvac_action`, `hvac_mode`, `hvac_modes`; `LightAttributes.color_mode`, `supported_color_modes`. (#716)
- **Field type changes (runtime)** — `MediaPlayerAttributes.media_position_updated_at`: `str | None` → `ZonedDateTime | None` (validator now parses the ISO string). `ClimateAttributes.current_temperature`: `int | float | None` → `float | None`. (#716)
- **Removed deprecated fields** — Fields typed as `None` in HA source (deprecated) are no longer declared on the model. Values still land in `model_extra` (accessible via `.extra("field_name")`): `LightAttributes.color_temp`, `max_mireds`, `min_mireds`, `xy_color`; `MediaPlayerAttributes.entity_picture_local`. (#716)
- **Removed constraints** — `LightAttributes.brightness` no longer has `gt=-1, lt=256` field validators. (#716)
- **`hassette.models.states.features` deleted** — IntFlag enums moved to per-domain files. All enums are still re-exported from `hassette.models.states` so `from hassette.models.states import LightEntityFeature` continues to work. (#716)

### State Models

- State model attributes are now code-generated from Home Assistant core source via AST analysis, replacing the previous hand-maintained models. 34 entity domains have generated state models with proper `@field_validator` for ZonedDateTime wire conversion, StrEnum attribute types, and `supports_*` boolean properties. (#716)
- The codegen pipeline includes a CI freshness check — if the pinned HA version falls behind, CI warns so models stay aligned with upstream. (#716)

## [0.29.0](https://github.com/NodeJSmith/hassette/compare/v0.28.0...v0.29.0) (2026-05-09)

### Breaking Changes

- **`state.value` type change for toggle entities** — `state.value` for light, switch, fan, automation, humidifier, remote, script, siren, and update entities now returns `bool` instead of `str`. Code using `state.value == "on"` must change to `state.value is True`. (#711)

### State Models

- Audited all 50 `BaseState` subclasses against HA core source — corrected value types (9 toggle entities → `BoolBaseState`, 5 timestamp entities → `DateTimeBaseState`, air_quality → `NumericBaseState`), added missing attributes (person location fields, timer transitions, valve position, script/cover/device_tracker fields), and removed stale attributes not present in HA core. (#711)

### Web UI

- Handler and condition summaries in the dashboard now display human-readable text (e.g., `entity light.kitchen and state → on`) instead of Python repr output. (#700)
- Service readiness (not just status) now visible in the frontend monitoring dashboard — services show whether they are actually ready to serve, not just that they started. (#688)

### Bug Fixes

- WebSocket `CancelledError` no longer swallowed during task cancellation (#682)
- REST API returns 404 (not 500) for non-existent `app_key` on start/stop/reload endpoints (#603, #680)
- Immediate-fire synthetic events now display "---" instead of a misleading UUID in telemetry (#640, #680)

## [0.28.0](https://github.com/NodeJSmith/hassette/compare/v0.27.0...v0.28.0) (2026-05-02)

### Breaking Changes

- **`HassettePayload.event_id` changed from `int` to `str` (UUID4)** — any user code comparing `event.payload.event_id` against integers will silently fail. Update comparisons to use string UUIDs. (#641)

### Telemetry

- Every handler invocation and job execution now receives a globally unique `execution_id` (UUID4) for end-to-end tracing, with the triggering event's `context_id` and `origin` captured alongside it. (#641)
- `CURRENT_EXECUTION_ID` ContextVar is set for the duration of each execution, enabling future causal chain tracking. (#641)
- Frontend shows "Trace ID", "Trigger", and "Origin" columns in handler invocation and job execution tables — truncated monospace UUIDs with full value on hover. (#641)

## [0.27.0](https://github.com/NodeJSmith/hassette/compare/v0.26.0...v0.27.0) (2026-04-29)

### Service Supervision

- Per-service `RestartSpec` replaces the global one-size-fits-all restart policy — each service declares its own restart type (`PERMANENT`, `TRANSIENT`, or `TEMPORARY`), sliding-window budget, backoff parameters, and error classification. The 5 global `service_restart_*` config fields are removed. (#638)
- `EXHAUSTED_DEAD` and `EXHAUSTED_COOLING` service statuses with frontend rendering including a countdown timer for cooling services. (#638)

### WebSocket Resilience

- Early-drop retry loop detects post-ready connection drops within a configurable stable window (default 30s) and retries transparently — Home Assistant restarts no longer burn the ServiceWatcher restart budget or crash hassette after 5 cycles. (#631)
- Total recovery timeout cap (default 5 minutes) prevents multiplicative worst-case retry windows. 8 new config fields externalize all retry parameters. (#631)

### Bug Fixes

- App bootstrap now completes before the app is marked ready, preventing premature requests against partially-initialized apps (#635)

## [0.26.0](https://github.com/NodeJSmith/hassette/compare/v0.25.0...v0.26.0) (2026-04-28)

### Bug Fixes

- Graceful shutdown no longer crashes on `ClosedResourceError` (#627)
- `ZonedDateTime` values in REST API responses no longer include IANA timezone suffix (`[America/Chicago]`), fixing URL interpolation in `get_history` and `get_logbook` (#619, #626)
- `TaskBucket` crash logs now show meaningful task names (e.g., `AppLifecycleService.bootstrap_apps`) instead of `Task-42` (#623, #626)
- `wait_for` utility supports async predicates, eliminating hand-rolled async polling loops (#622, #626)
- `AppTestHarness` per-class lock narrowed for concurrent same-class harnesses — multiple tests using the same app class can now run in parallel (#614)

## [0.25.0](https://github.com/NodeJSmith/hassette/compare/v0.24.0...v0.25.0) (2026-04-26)

### Breaking Changes

- **Scheduler API redesigned around trigger objects** — `run_cron("0 7 * * 1-5")`, `run_daily(at="07:00")` replace the old keyword-per-field API. Custom triggers must implement `TriggerProtocol`. See the updated [scheduler docs](https://hassette.readthedocs.io/en/stable/pages/core-concepts/scheduler/). (#517)
- **`RecordingApi.get_entity` requires explicit model argument** — the previous `BaseState`-sentinel default silently aliased to `get_state()` and hid real bugs. Callers that want registry-converted state without a specific entity model should call `get_state(entity_id)` instead. (#525)
- **Docker startup uses constraints-based dependency protection** — runtime `uv sync` replaced with a constraints file generated at build time. User dependency installs that conflict with hassette's pinned version now error instead of silently downgrading the framework. (#480)

### Test Utilities

- `AppTestHarness` — async context manager that wires a user's `App` class into test `Bus`, `Scheduler`, `StateManager`, and `RecordingApi` with zero boilerplate: `async with AppTestHarness(MyApp, config={...}) as harness:` (#492)
- `RecordingApi` records write calls for assertions and delegates reads to `StateProxy`, with `ApiProtocol` conformance checking at import time (#492)
- Time control for scheduler tests: `freeze_time()`, `advance_time()`, `trigger_due_jobs()` via custom `_TestClock` (#492)
- Event simulation: `simulate_state_change`, `simulate_attribute_change`, `simulate_call_service` with reliable task-bucket drain (#492, #525)
- State seeding: `set_state`, `set_states` via `StateProxy._test_seed_state()` (#492)

### Scheduler

- Built-in trigger types: `After`, `Once`, `Every`, `Daily`, `Cron` — all importable from `hassette.scheduler.triggers` (#517)
- Job groups (`group=`, `cancel_group()`, `list_jobs(group=)`) and jitter support (`jitter=`) (#517)
- Frontend shows structured trigger labels, group filter chips (URL-persisted), jitter tags, cancelled badges, and expandable job rows with "Next: fires in..." countdown (#517)

### Bus

- `immediate=True` fires handlers at registration time when the target entity already matches predicates. Synthetic event has `old_state=None`. Composes with `once`, `debounce`, `throttle`. (#570)
- `duration=N` holds require the entity to remain in the matching state for N continuous seconds before the handler fires. Consults `last_changed` on restart for resilience. (#570)
- `Bus.on_error(handler)` and `Scheduler.on_error(handler)` register app-level error handlers; per-registration `on_error=` parameter takes priority. Both sync and async handlers supported. (#575)

### Error Handling

- Execution timeout enforcement (600s default) for all scheduled jobs and event handlers via `asyncio.timeout()` — `timed_out` shown as a distinct status in telemetry with amber warning badges (#552)
- `timeout` and `timeout_disabled` parameters on all `Scheduler` and `Bus` registration methods (#552)
- Error tracebacks visible in the dashboard error feed with expand/collapse toggle; framework-tier errors separated from app-tier errors (#537)

### API

- Typed Home Assistant helper CRUD methods for `input_boolean`, `input_number`, `input_select`, `input_text`, `input_datetime`, `counter`, and `timer` entities (#506)

### Web UI

- Dashboard hierarchy redesign with app detail polish, quiet-canvas status indicators, and sorted grids (#485, #523)
- Listener and job registrations now persist across session restarts — telemetry no longer loses data on reconnect (#466, #487)

### Bug Fixes

- Subscription race between `cancel()` and in-flight dispatch fixed; cancel semantics prevent double-fire (#451, #518, #520)
- Dashboard no longer shows zero handlers/jobs after page refresh (#578)
- Docker uv cache pruned on startup to prevent unbounded volume growth (#542)
- SIGTERM handled for graceful Docker shutdown (#479)

### Documentation

- Comprehensive docs rewrite with scheduler parameter tables, troubleshooting index, security admonition for unauthenticated web API, and simplified getting-started first app (#507)
- System internals page with architecture deep-dive diagrams (#605)

## [0.24.0](https://github.com/NodeJSmith/hassette/compare/v0.23.0...v0.24.0) - 2026-04-03

### Breaking Changes

- **`TriggerProtocol` split** — custom triggers must now implement both `first_run_time(current_time)` and `next_run_time(previous_run, current_time)` instead of a single method. Triggers are now stateless. (#452)
- **`/api/healthz` removed** — update Docker Compose health checks from `/api/healthz` to `/api/health`, which returns structured JSON and 503 for non-ok status. (#448)
- **Scheduler enforces job name uniqueness** — duplicate job names per instance raise `ValueError`. Pass `if_exists="skip"` for idempotent registration. (#297)
- **`once=True` + rate limiting raises `ValueError`** — combining `once=True` with `debounce` or `throttle` is no longer silently accepted. Remove the rate-limiting parameter from affected listeners. (#430)

### Web UI

- Complete rebuild as a Preact SPA with 5 pages: Dashboard, Apps, App Detail, Sessions, Logs (#343)
- Graphite + Emerald design token system with light/dark mode toggle and `[data-theme]` persistence (#343, #442)
- Session list page with status badges, "This Session" / "All Time" scope toggle, and localStorage persistence (#464)
- Source location display in handler/job detail panels and log table (#464, #410)
- Handler/job drill-down with invocation history, plain-language handler summaries, and error feed with exception type names (#343, #411)
- Dashboard app cards show invocation/execution counts, error rate percentage, instance count badge, and multi-instance telemetry aggregation (#392, #410, #411, #448)
- Multi-column sort on log table with live-streaming auto-pause and click-to-expand messages (#411, #381)
- Keyboard accessibility: focus-visible indicators, skip-nav link, ARIA roles, keyboard-navigable log table (#442, #390)
- Self-hosted fonts (DM Sans, JetBrains Mono, Space Grotesk) — no external CDN requests (#442)
- Real-time log streaming via WebSocket with server-side level filtering and deduplication (#409)
- WebSocket reconnection automatically refreshes all REST-fetched data without page reload (#379)
- Status bar "DB degraded" indicator with exponential backoff polling (#448)

### Database & Telemetry

- Persistent SQLite telemetry storage for sessions, handler invocations, and job executions with automatic schema migrations (#305, #329)
- Configurable retention (`db_retention_days`) and size limit (`db_max_size_mb`, default 500 MB) with automatic oldest-record deletion (#464)
- Telemetry status endpoint (`/api/telemetry/status`) returns 503 when degraded, usable by Docker HEALTHCHECK (#448)
- `/api/health` returns 503 for non-ok system status while preserving structured JSON (#448)

### Bus & Scheduler

- Rate limiter redesign: throttle no longer blocks concurrent dispatch, debounced handlers produce accurate telemetry, `once=True` listeners cannot double-fire under rapid events (#430)
- Zero or negative `debounce` and `throttle` values rejected with `ValueError` at registration (#430)
- `if_exists` parameter on all `Scheduler.run_*` methods — `"error"` (default) or `"skip"` for idempotent registration (#297)
- `IntervalTrigger` rejects zero/negative intervals with `ValueError` at construction (#452)

### Logging

- Per-service log level tuning via 13 dedicated `*_log_level` config fields (e.g., `api_log_level`, `bus_service_log_level`) — no service falls through to global default (#463)

### Configuration

- `total_shutdown_timeout_seconds` — caps total shutdown wall-clock time (default: 30s) (#453)
- `db_path`, `db_retention_days`, `db_max_size_mb` — telemetry database location, retention, and size limit (#305, #464)

### Bug Fixes

- Startup race condition: phased startup ensures session exists before handlers fire, eliminating "Dropping N handler invocation record(s)" warnings (#343)
- `CommandExecutor` startup crash resolved — registration methods wait for `DatabaseService` readiness before DB access (#330)
- SQLite write serialization eliminates `OperationalError: cannot commit transaction` races at startup (#333)
- Stale listener/job registrations cleaned up on app restart; telemetry no longer shows removed handlers (#390)
- Connection status bar no longer flashes "Disconnected" on page refresh (#390)
- WebSocket hook no longer causes infinite reconnect loop (#379)
- App start/stop/reload endpoints work in production mode without `dev_mode` flag (#390)
- Strip literal quote characters from `base_url`, fixing Docker Compose connection failures (#298)
- ServiceWatcher triggers shutdown on max restart failures instead of silently giving up (#301)
- Scheduler auto-generated job names include trigger info, preventing name collisions (#446)
- Scheduler job and listener filters return correct results after `owner_id`/`app_key` mismatch fix (#335, #336)

### Documentation

- Fixed broken code examples: `run_hourly(minute=15)` TypeError, invalid `api_port` field, wrong `instance_name` key in config snippet (#469, #472)
- Added parameter tables to all scheduler methods with types, defaults, and cross-references (#469, #472)
- Corrected `data_dir` default from `~/.hassette` to actual platform-dependent path (#469, #472)
- Added troubleshooting index page with symptom-based navigation (#469, #472)
- Added security admonition for unauthenticated web API (#469, #472)
- Extracted duplicated config file-discovery table into a shared snippet (#469, #472)
- Simplified getting-started first app to use raw events; added typed-handler forward reference (#469, #472)
- Removed ghost `getting-started/configuration.md` page (#469, #472)

## [0.23.0] - 2026-02-19

### Changed
- Replaced Bulma CSS framework with a custom `ht-` prefixed design system featuring cool slate surfaces, warm amber accent, and Space Grotesk + JetBrains Mono typography (#262)
- Extracted all design tokens into `tokens.css` with `[data-theme]` selector support for future theming (#262)
- Redesigned dashboard with app status chip grid, activity timeline, and streamlined layout (#262)
- App detail pages now use a flat single-page layout with collapsible metadata, inline tracebacks, and instance switcher dropdown (#262)
- Bus listener and scheduler job tables show expanded detail rows with predicate, rate-limiting, and trigger information (#262)
- Replaced hardcoded CSS fallback colors in alerts and detail panels with proper design tokens (`--ht-surface-inset`, `--ht-surface-code`, `--ht-warning-*`, `--ht-danger-*`)
- Toggle buttons now show fallback text before Alpine.js initializes and expose `aria-expanded` for accessibility (#262)
- E2E tests now run by default with `uv run pytest` instead of requiring `-m e2e`; added `nox -s e2e` session for CI
- `HassetteHarness` now uses a fluent builder API (`with_bus()`, `with_state_proxy()`, etc.) with automatic dependency resolution instead of boolean flags (#253)
- Consolidated duplicate mock Hassette, DataSyncService, and web test helper fixtures into shared factories in `test_utils/` (#253)
- All test helper functions now exported from `hassette.test_utils` public API; tests import from the package instead of submodules (#253)
- Replaced 28 `asyncio.sleep()` synchronization calls across 8 integration test files with `wait_for` polling helper for deterministic, faster tests (#253)
- Renamed `create_mock_hassette()` to `create_hassette_stub()` and `mock_hassette.py` to `web_mocks.py` to clarify web/API stub vs harness distinction (#259)
- Added autouse cleanup fixtures for bus, scheduler, and mock API to prevent test pollution in module-scoped fixtures (#256)

### Fixed
- WebSocket service now fires disconnect event and marks not-ready immediately on unexpected connection loss, preventing stale state in StateProxy (#270)
- App detail page now uses the actual instance index instead of hardcoded 0, fixing data/URL desync for non-zero instances (#262)
- Detail panel labels now have proper text contrast on dark `--ht-surface-code` background (#262)
- Collapsible panels and tracebacks no longer flash visible before Alpine.js initializes (#262)
- Entity browser "Load more" button now appends rows instead of replacing existing ones on domain-filtered views (#247)
- `model_dump()` and `model_dump_json()` on `AppManifest` and `HassetteConfig` no longer leak extra fields (e.g. tokens from environment variables)

### Added
- Aligned all state model attributes with Home Assistant core — added missing fields to sensor, humidifier, light, climate, weather, fan, camera, and media_player; created dedicated `LockState` module with `LockAttributes` and `LockEntityFeature` (#294)
- `supports_*` boolean properties on light, climate, cover, fan, media_player, and vacuum attribute classes for checking entity capabilities without manual bitmask operations (#272)
- `IntFlag` enums (`LightEntityFeature`, `ClimateEntityFeature`, etc.) matching Home Assistant core feature flags (#272)
- Global alert banner showing HA disconnect warnings and failed app errors with expandable tracebacks (#262)
- `ht-btn--ghost` and `ht-btn--xs` button modifier classes (#262)
- `extras` property and `extra()` helper on `BaseState` and `AttributesBase` for safe access to integration-specific attributes (#271)
- JSDoc comments across all web UI JavaScript files (#251)
- ESLint linting, TypeScript type-checking, and `mise run lint:js` / `mise run typecheck:js` tasks (#251)

### Removed
- Bulma CSS CDN dependency (#262)
- Entity Browser page and related partials (#262)

## [0.22.1] - 2026-02-15

### Added
- Issue template migration from Markdown to YAML form templates (bug report, feature request, task, documentation)
- `/triage-issues` Claude command for auditing and cleaning up GitHub issues against project conventions
- Updated CLAUDE.md with GitHub Issues conventions (title, labels, milestones, body sections)
- `web_ui_hot_reload` config option — watches web UI static files and templates for changes, pushing live reloads to the browser via WebSocket. CSS changes are hot-swapped without a page reload; template and JS changes trigger a full reload.
- Collapsible sidebar with persistent icon rail on desktop and mobile — click the toggle or press Escape to expand/collapse
- SPA-like page navigation via HTMX boost — page transitions without full reloads

### Changed
- Live dashboard/page updates now use WebSocket push with idiomorph DOM morphing instead of 30-second polling intervals

## [0.22.0] - 2026-02-13

### Added
- **Web UI** — server-rendered monitoring dashboard at `/ui/` using Jinja2, HTMX, Alpine.js, and Bulma CSS
  - **Dashboard** — system health, apps summary, bus metrics, and recent events with WebSocket-driven live updates
  - **Apps page** — shows all configured app manifests with status badges, start/stop/reload controls, and status filter tabs; single-instance apps link directly to instance detail
  - **App detail** (`/ui/apps/{key}`) — manifest config, bus listener metrics, scheduled jobs, and filtered log viewer; multi-instance apps show expandable instance table
  - **Instance detail** (`/ui/apps/{key}/{index}`) — per-instance bus listeners, jobs, and logs
  - **Log viewer** (`/ui/logs`) — client-side filtering by level/app/text, sortable columns, and real-time WebSocket log streaming
  - **Scheduler page** (`/ui/scheduler`) — scheduled jobs and execution history, filterable by app
  - **Entity browser** (`/ui/entities`) — browse entities by domain with text search and pagination
  - **Event Bus page** (`/ui/bus`) — bus listener metrics, filterable by app
  - `run_web_ui` config option to enable/disable the UI independently from the API
  - Added section to docs covering the web UI
- **FastAPI web backend** replacing the standalone `HealthService` with a full REST API and WebSocket server
  - `GET /api/health`, `GET /api/healthz` — system health and container healthchecks
  - `GET /api/entities`, `GET /api/entities/{entity_id}`, `GET /api/entities/domain/{domain}` — entity state access
  - `GET /api/apps`, `GET /api/apps/{app_key}`, `GET /api/apps/manifests` — app status and manifests
  - `POST /api/apps/{app_key}/start|stop|reload` — app management
  - `GET /api/scheduler/jobs`, `GET /api/scheduler/history` — scheduled jobs and execution history
  - `GET /api/bus/listeners`, `GET /api/bus/metrics` — per-listener execution metrics and aggregate summary
  - `GET /api/events/recent`, `GET /api/logs/recent`, `GET /api/services`, `GET /api/config` — events, logs, HA services, config
  - `GET /api/ws` — WebSocket endpoint for real-time state/event/log streaming with subscription controls
  - `GET /api/docs` — interactive OpenAPI documentation
- **Event handler execution metrics** — per-listener aggregate counters (invocations, successes, failures, DI failures, timing) exposed via REST API and web UI
- **Scheduler job execution history** — per-job execution records with timing and error details
- Configurable service restart with exponential backoff in `ServiceWatcher`
  - `service_restart_max_attempts`, `service_restart_backoff_seconds`, `service_restart_max_backoff_seconds`, `service_restart_backoff_multiplier` config options
- `scheduler_behind_schedule_threshold_seconds` config option (default: 5) — configurable threshold before a "behind schedule" warning is logged for a job (previously hard-coded to 1 second)
- Playwright e2e test suite for the web UI (34 tests; run with `pytest -m e2e`)

### Changed
- **Breaking:** Replaced `HealthService` with `WebApiService` backed by FastAPI
- **Breaking:** Config renames: `run_health_service` → `run_web_api`, `health_service_port` → `web_api_port`, `health_service_log_level` → `web_api_log_level`
- New config options: `web_api_host`, `web_api_cors_origins`, `web_api_event_buffer_size`, `web_api_log_buffer_size`, `web_api_job_history_size`
- `Service` base class now properly sequences `serve()` task lifecycle: spawns after `on_initialize()`, cancels before `on_shutdown()`

### Fixed
- WebSocket disconnect handling no longer produces spurious ERROR logs during normal page navigation
- Scheduler dispatch loop uses single lock acquisition per cycle, reducing scheduling latency

### Removed
- `HealthService` (`src/hassette/core/health_service.py`) — replaced by FastAPI web backend

## [0.21.0] - 2026-02-06

### Changed
- Refactored `AppHandler` into four focused components: `AppRegistry` (state tracking), `AppFactory` (instance creation), `AppLifecycleManager` (init/shutdown orchestration), and `AppChangeDetector` (configuration diffing)
- File watcher now batches multiple file change events to prevent race conditions (`changed_file_path` payload is now `changed_file_paths: frozenset[Path]`)
- Renamed `active_apps_config` to `active_manifests` on `AppRegistry`
- `AppManifest.app_config` now accepts both `"config"` and `"app_config"` keys

### Added
- `HassetteAppStateEvent` emitted when app instances change status (includes app_key, status, previous_status, exception details)
- New `Bus` convenience methods: `on_app_state_changed()`, `on_app_running()`, `on_app_stopping()`
- `BlockReason` enum and blocked app tracking in `AppRegistry` to distinguish "enabled but excluded by `@only_app`" from "not configured"
- `ResourceStatus.STOPPING` enum value
- `enabled_manifests` property on `AppRegistry` for querying enabled apps regardless of `only_app` filter
- `StateManager.get(entity_id)` for generic entity access with automatic domain-type resolution and `BaseState` fallback

### Fixed
- Removing `@only_app` decorator now correctly starts previously-blocked apps during hot reload

## [0.20.4] - 2026-02-05

### Fixed
- Fixed finding of requirements files in Docker image, thanks @mlsteele!

### Added
- Added tests to ensure requirements files are found correctly in Docker image

## [0.20.3] - 2026-02-01

### Fixed
- `source` now optional in `AutomationTriggeredPayload`

## [0.20.2] - 2026-02-01

### Changed
- rename parameter `comparator` to `op` in `Comparison` condition

## [0.20.1] - 2026-02-01

### Fixed
- add back activation of virtualenv in docker startup script

## [0.20.0] - 2026-02-01

### Added
- Add --version/-v argument to Hassette to allow displaying the current version
- Add `__iter__`, `__contains__`, `keys`, `values`, and `items` methods to StateManager and StateRegistry
- Add functionality to route `state_change` events to more specific handlers based on domain and/or entity_id
  - This is done automatically by the `Bus` by adding the entity_id to the topic when creating the listener
  - Matched listeners are deduplicated to ensure delivery only happens one time
  - Events are dispatched to the most specific route if there are multiple matches
- Add `AnnotationConverter` class and `TypeMatcher` class for more robust validation/conversion during DI
- Add A, P, C, and D aliases to `hassette.__init__` for simpler imports
  - `A` = `hassette.event_handling.accessors`
  - `P` = `hassette.event_handling.predicates`
  - `C` = `hassette.event_handling.conditions`
  - `D` = `hassette.event_handling.dependencies`
- Add new `Comparison` condition for basic operators (e.g. `==`, `!=`, `<`, `>`, etc.) to compare values in state/attribute change listeners
- Add new accessors for getting multiple/all attributes at once from state change events
  - `get_attrs_<old|new|old_new>` - specify a list of attrs
  - `get_all_attrs_<old|new|old_new>` - get all attributes as a dict
- Add `get_all_changes` accessor that returns a dictionary of all changes, including state and all attributes

### Fixed
- Fix AppHandler reporting failed apps as successful by using status attribute
  - This is due to some issues with how we're tracking apps, further fixes will need to happen in future releases
- Fix StateManager using `BaseState` when we do not find a class in the `StateRegistry`
  - This does not work because `BaseState` doesn't have a `domain`
  - Error is now raised instead
- Log level is now used by Apps if set directly in AppConfig in Python code (as opposed to config file)
- Fix HassPayload's context attribute not being a HassContext instance
- `MediaPlayerState` now has `attributes` using the correct type

### Changed
- BREAKING: Replaced `StateManager.get_states` with `__getitem__` that accepts a state class
  - The error raised in StateManager when a state class is not found in the `StateRegistry` now advises to use this method
- Renamed `LOG_LEVELS` to `LOG_LEVEL_TYPE`
- Renamed `get_default_dict` to `get_defaults_dict` to be more clear this is not referring to `defaultdict` class
- Use same validation for `AppConfig` log level as we do for `Hassette` config log level
- Extracted nested Attributes classes for each state out of class definition to make them first class citizens
  - e.g. `MediaPlayerState.Attributes` is now `MediaPlayerAttributes`

### Docs
- Remove `Why Hassette` page
- Remove docker networking page
- Very large cleanup/reorg/addition of docs

## [0.19.2] - 2026-01-25

### Fixed
- Change log level for state cache loading message from INFO to DEBUG

## [0.19.1] - 2026-01-25

### Fixed
- Update `state_manager.pyi` to fix type hints

## [0.19.0] - 2026-01-25

### Fixed
- Exit `TypeRegistry.convert` early if already a valid type
- Avoid mutating state dicts when accessing via `DomainStates`

### Added
- Add `__contains__` method to DomainStates
  - Allows us to use `in` checks
- Add `to_dict`, `keys`, `values`, and `items` methods to DomainStates
  - Provides convenient access to entity IDs and typed states
- Add `yield_domain_states` to StateProxy
  - Allows iterating over all states in the proxy
  - Handles KeyError when extracting domain
- Update `DomainStates` class to accept a `StateProxy` instance instead of state dictionary to ensure it stays up to date
- Add caching to `StateManager`, holding on to each `DomainStates` instance after creation
- Add caching to `DomainStates`, using `frozendict.deepfreeze` to hash the state dict and avoid recreating the instance if it has not changed

### Removed
- BREAKING: Remove `_TypedStateGetter` class and corresponding `get` method on `StateManager` - this was never a good idea due to its confusing api
- BREAKING: Remove `all` property on `StateManager` - this is to avoid calculating all states unnecessarily

## [0.18.1] - 2025-12-13

### Changed
- Improve docker startup script and dependency handling
- Rewrite docker docs to be more clear about project structure and dependency installation

### Fixed
- Fixed a bug in autodetect apps exclusion directories
  - Previous commit had mapped the exclusion dirs to Path objects, which broke the set comparison, this has been reverted

## [0.18.0.dev3] - 2025-12-13

### Changed
- Hardcode UID/GID of 1000 for non-root user in Docker image

## [0.18.0.dev2] - 2025-12-13

### Changed
- **Breaking:** Docker image switched to Debian slim
- **Breaking:** Remove `latest` tag, latest tag will now include python version as well

### Fixed
- Use correct version of python when pulling base image
  - (e.g. image tagged with py-3.12 uses python 3.12)


## [0.18.0.dev1] - 2025-12-13

### Changed
- Allow Python 3.11 and 3.12 again!
- **Breaking:** All events now contain untyped payloads instead of typed ones
  - `StateChangeEvent` is now `RawStateChangeEvent`
  - There is a new DI handler for `TypedStateChangeEvent` to handle conversion if desired
- **Breaking:** State conversion system now uses dynamic registry instead of hardcoded unions
  - `StateUnion` type has been removed - use `BaseState` in type hints instead
  - `DomainLiteral` type has been removed - no longer needed with dynamic registration
  - State classes automatically register their domains via `__init_subclass__` hook
- **Breaking:** `try_convert_state` now typed to return `BaseState | None` instead of `StateUnion | None`
  - Uses registry lookup instead of Pydantic discriminated unions for conversion
  - Falls back to `BaseState` for unknown/custom domains
  - `try_convert_state` moved to `hassette.state_registry` module
  - `states.__init__` now only imports/exports classes, no conversion logic
- Improved dependency injection system for event handlers, including support for optional dependencies via `Maybe*` annotations
- Renamed `states.py` to `state_manager.py` (and renamed the class) to avoid confusion with `models/states` module
- Removed defaults from StateT and StateValueT type vars
- Removed type constraints from StateValueT type var to allow custom types to be used
- Moved `accessors`, `conditions`, `dependencies`, and `predicates` all to `hassette.event_handling` for consistency
- Moved DI extraction and injection modules to `hassette.bus`

### Added
- `TypeRegistry` class for handling simple value conversion (e.g. converting "off" to False)
- Handling of Union types
- Handling of None types
- Handling of type conversion for custom `Annotated` DI handlers

### Removed
- **Breaking:** Removed `StateUnion` type - replaced with `BaseState` throughout codebase
- **Breaking:** Removed `DomainLiteral` type - no longer needed with registry system
- **Breaking:** Removed manual `_StateUnion` type definition from states module
- **Breaking:** Removed StateValueOld/New, StateValueOldNew, StateOldNew, MaybeStateOldNew, AttrOld, AttrNew, AttrOldNew DI handlers
    - These can be used still by annotating with `Annotated[<type>, A.<function>]` using provided `accessors` module
    - They were too difficult to maintain/type properly across the framework


## [0.17.0] - 2025-11-22

### Changed
- **Breaking:** - Requires Python 3.13 going forward, Python 3.12 and 3.11 are no longer supported.
  - This allows use of `type`, defaults for TypeVars, and other new typing features.
- Renamed `core_config.py` to `core.py`
- Renamed `services` to `core` and move `core.py` under `core` directory
  - Didn't make sense to keep named as `services` since we have resources in here as well

### Added
- Add `diskcache` dependency and `cache` attribute to all resources
  - Each resource class has its own cache directory under the Hassette data directory
- Add `states` attribute to `App` - provides access to current states in Home Assistant
  - `states` is an instance of the new `States` class
  - `States` provides domain-based access to entity states, e.g. `app.states.light.get("light.my_light")`
  - `States` listens to state change events and keeps an up-to-date cache of states
  - New states documentation page under core-concepts
- Add `Maybe*` DI annotations for optional dependencies in event handlers
  - `MaybeStateNew`, `MaybeStateOld`, `MaybeEntityId`, etc.
  - These will allow `None` or `MISSING_VALUE` to be returned if the value is not available
  - The original dependency annotations will raise an error if the value is not available
- Add `raise_on_incorrect_dependency_type` to `HassetteConfig` to control whether to raise an error if a dependency cannot be provided due to type mismatch
  - Default is `true` in production mode, `false` in dev mode
  - When `false` a warning will be logged but the handler will still be called with whatever value was returned

### Fixed
- Fixed bug that caused apps to not be re-imported when code changed due to skipping cache check in app handler
- Fixed missing domains in `DomainLiteral` in `hassette.models.states.base`
  - Add tests to catch this in the future

## [0.16.0] - 2025-11-16

### Added
- Added `ANY_VALUE` sentinel for clearer semantics in predicates - use this to indicate "any value is acceptable"
- **Dependency Injection for Event Handlers** - Handlers can now use `Annotated` type hints with dependency markers from `hassette.dependencies` to automatically extract and inject event data as parameters. This provides a cleaner, more type-safe alternative to manually accessing event payloads.
  - Available dependencies include `StateNew`, `StateOld`, `AttrNew(name)`, `AttrOld(name)`, `EntityId`, `Domain`, `Service`, `ServiceData`, `StateValueNew`, `StateValueOld`, `EventContext`, and more
  - Handlers can mix DI parameters with custom kwargs
  - See `hassette.dependencies` module documentation and updated examples for details

### Changed
- **Breaking:** - Event handlers can no longer receive positional only args or variadic positional args
- `NOT_PROVIDED` predicate is now used only to indicate that a parameter was not provided to a function

## [0.15.5] - 2025-11-14

### Changed
- Update `HassetteConfig` defaults to differ if in dev mode
  - Generally speaking, values are extended (e.g. timeouts) and more permissive (e.g. `allow_startup_if_app_precheck_fails = true` in dev mode)
- Moved `AppManifest` and `HassetteTomlConfigSettingsSource` to `classes.py`
- Moved `LOG_LEVELS` to `hassette.types.types` instead of `const.misc`, as this is a `Literal`, not a list of constants
- Renamed `core_config.py` to `core.py`
- Bumped version of `uv` in `mise.toml`, docker image, and build backend
- Converted docs to mkdocs instead of sphinx

### Fixed
- Fixed bug in AppHandler where all apps would be lost when `handle_changes` was called, due to improper reloading of configuration
  - Now uses `HassetteConfig.reload()` to reload config instead of re-initializing the class

## [0.15.4] - 2025-11-07

### Added
- add config setting for continuing startup if app precheck fails
- add config setting for skipping app precheck entirely
- add config setting for loading found .env files into os.environ
- add `entities` back to public API exports from `hassette`

### Changed
- Cache app import failures to avoid attempting to load these again if we are continuing startup after precheck failures
- Improve app precheck logging by using `logger.error` and short traceback instead of `logger.exception`

## [0.15.3] - 2025-11-02

### Changed
- Moved more internal log lines to `DEBUG` level to reduce noise during normal operation.
- Moved `only_app` warning to only emit if `@only_app` is actually being used.
- Make `FalseySentinel` subclass to use for `NOT_PROVIDED` and `MISSING_VALUE` to simplify bool checks.
- Add `Typeguard` method to `StateChangePayload` to allow type narrowing on `old_state` and `new_state`.
  - Implemented as `self.has_state(<self.old_state|self.new_state>)`

### Documentation
- Improved documentation landing page
- Add logo
- Improve getting-started page

## [0.15.2] - 2025-11-02

### Fixed

- Fix docker_start.sh to use new entrypoint

## [0.15.0] - 2025-11-02

### Added
- `ComparisonCondition`s for comparing old and new values in state and attribute change listeners.
  - `Increased` and `Decreased` conditions added for numeric comparisons.
- Added `IsNone` and `IsNotNone` conditions for checking if a value is `None` or not.
- Hassette will now attempt to automatically detect apps and register them without any configuration being required.
  - This can be disabled by setting `auto_detect_apps = false` in the config.
  - Manually configured apps will still be loaded as normal and take precedence over auto-detected apps.
  - You cannot use auto-detect apps if you have a configuration with required values (unless they are being populated from environment variables or secrets).
    - In this case, you must manually configure the app to provide the required values.

### Fixed
- Fixed missing tzdata in Alpine-based Docker image causing timezone issues.
- Cli parsing working now, so any/all settings can be passed to override config file or env vars, using `--help` works correctly, etc.

### Removed
- Setting sources custom tracking removed, so debug level logging will no longer show where each config value was set from.
  - This was originally added due to my own confusion around config precedence, but maintaining it is not worth the extra complexity.
- Secrets can no longer be set in ``hassette.toml`` to be accessible in app config
  - This never actually made much sense, I just didn't actually think about that when adding the feature

### Changed
- You can now pass `ComparisonCondition`s to the `changed` parameter on `on_state_change` and `on_attribute_change` methods.
  - This allows for comparing the old and new values to each other, rather than checking each independently.
- You are now able to register event handlers that take no arguments, for events where you don't care about the event data.
  - The handler will simply be called without any parameters when the event is fired.
  - This works for all bus listener methods, e.g. `on_event`, `on_entity`, `on_status_change`, etc.
  - When you do require the event to be passed, you only need to ensure it is the first parameter and the name is `event`.
- No longer export anything through `predicates` module
  - Recommendation now is to import like
    - `from hassette import predicates as P`
    - `from hassette import conditions as C`
    - `from hassette import accessors as A`
- **Breaking:** - `base_url` now requires an explicit schema (http:// or https://)
  - If no schema is provided, a `SchemeRequiredInBaseUrlError` will be raised during config validation
  - This is to avoid having to guess the intended scheme, which can lead to confusion and errors
- **Breaking:** - `base_url` must have `port` included if your instance requires the port
  - Previously, we would default to port 8123 if no port was provided
  - This is not always correct, as some instances may be running on a different port, be behind a reverse proxy, or use nabu casa and not require a port at all

### Internal
- Refactor listener and add adapter to handle debounce, throttle, and variadic/no-arg handlers more cleanly.
- Rename `Hasette._websocket` to `Hassette._websocket_service` to match naming conventions.
- Refactor handler types and move types into `types` module instead of single file for better organization.
- Remove extra wrappers around `pydantic-settings`, made some improvements so these are no longer necessary.
- Flattened whole package structure for simpler imports and better organization.

## [0.14.0] - 2025-10-19

### Added
- Add validation for filename extension in AppManifest - add `.py` if no suffix, raise error if not `.py`
- Bus handlers can now accept args and kwargs to be passed to the callback when the event is fired
- `tasks.py` renamed to `task_bucket.py` to follow naming conventions
- `post_to_loop` method added to `TaskBucket` to allow posting callables to the event loop from other threads

### Changed
- **Breaking:** - Renamed `async_utils.py` to `func_utils.py`, added `callable_name` and `callable_short_name` utility functions
- **Breaking:** - Upgrade to `whenever==0.9.*` which removed `SystemDateTime` in favor of `ZonedDateTime` - all references in the code base have been updated

### Internal
- New type for handlers, `HandlerType`, as we now have additional protocols for variadic handlers

### Fixed
- Correct scheduler helpers `run_minutely`, `run_hourly`, and `run_daily` to not start immediately if no `start` was provided, but to start on the next interval instead.

### Bus/Predicate Refactor
- Refactored predicates to use composable `Predicates`, `Conditions`, and `Accessors`
  - `Predicate` is a callable that takes an event and returns a bool
    - E.g. `AttrFrom`, `AttrTo`, `DomainMatches`, `EntityMatches`, `ValueIs`, etc.
  - `Condition` is a callable that takes a value and returns a bool
    - E.g. `Glob`, `Contains`, `IsIn`, `IsOrContains`, `Intersects`, etc.
  - `Accessor` is a callable that takes an event and returns a value
    - E.g. `get_domain`, `get_entity_id`, `get_service_data`, `get_path`, etc.
- Updated Bus methods to use new predicate system
  - Only implementation changes, public API remains the same
- Updated tests to use new predicate system
- Add/update types for predicates, conditions, and accessors
- Updated documentation for predicates and bus event listening to reflect new system

## [0.13.0] - 2025-10-14

### Added
- `Subscription` now has ``cancel`` method to unsubscribe from events, to be consistent with ``ScheduledJob``.
- `App.send_event_sync` method added for synchronous event sending.
- `Bus.on_status_change`, `Bus.on_attribute_change`, `Bus.on_service_call` all take sync callables for comparison parameters.
  - For example, you can pass a lambda to `changed_from` that does a custom comparison.
- `Bus` now exposes `on_homeassistant_stop` and `on_homeassistant_start` convenience methods for listening to these common events.
- `Bus` status/attribute change entity_id parameters now accept glob patterns.

### Changed
- **Breaking:** `Scheduler.run_once` has been updated to use `start` instead of `run_at` to be consistent with other helpers.
- **Breaking:** `cleanup` method is now marked as final and cannot be overridden in subclasses.
- **Breaking:** `Bus.on_entity` renamed to `Bus.on_status_change` to match naming conventions across the codebase.
- **Breaking:** `Bus.on_status_change` `entity` parameter renamed to `entity_id` for clarity.
- **Breaking:** `Bus.on_attribute` renamed to `Bus.on_attribute_change` to match naming conventions across the codebase.
- **Breaking:** `Bus.on_attribute_change` `entity` parameter renamed to `entity_id` for clarity.

### Removed
- **Breaking:** Removed deprecated `set_logger_to_debug` and `set_logger_to_level` Resource methods.
- **Breaking:** Removed deprecated `run_sync`, `run_on_loop_thread`, and `create_task` methods from Hassette.
- **Breaking:** Removed `run_at` alias for `run_once` in Scheduler.

### Internal
- Remove scheduled jobs that are cancelled or do not repeat, instead of just marking them as cancelled and leaving them in the job queue.
- Reworked predicates to make more sense and be more composable.
- Added types for `PredicateCallable`, `KnownTypes`, and `ChangeType`.
    - `PredicateCallable` is a callable that takes a single argument of any known type and returns a bool.
    - `KnownTypes` is a union of all types that can be passed to predicates.
    - `ChangeType` is a union of all types that can be passed to change parameters.
- Use `Sentinel` from `typing_extensions` for default values.
- Rename `SENTINEL` to `NOT_PROVIDED` for clarity.
- Moved `is_async_callable` to `hassette.utils.async_utils`, now being used in more places.
- Moved glob logic from `Router` to `hassette.utils.glob_utils`, now being used in more places.

### Documentation
- Updated Apps and Scheduler documentation to reflect new features and changes.
- Improved reference docs created with autodoc.

## [0.12.1] - 2025-10-11
### Fixed
- Fixed `run_minutely`/`run_hourly`/`run_daily` scheduler helpers to run every N minutes/hours/days, not *every* minute/hour/day at 0th second/minute.

## [0.12.0] - 2025-10-11

### Added
- Lifecycle:
  - Lifecycle hooks `on/before/after_initialize` and `on/before/after_shutdown` added to `Resource` and `Service` for more granular control over startup and shutdown sequences.
  - **Breaking:** `App.initialize` and `App.shutdown` are now final methods that call the new hooks; attempting to override them will raise a `CannotOverrideFinalError`.
- Developer Experience:
    - Hassette now performs a pre-check of all apps before starting, exiting early if any apps raise an exception during import.
      - This allows earlier iteration for exceptions that can be caught at class definition/module import time.
    - Scheduler now includes convenience helpers `run_at`, `run_minutely`, `run_hourly`, and `run_daily` for common cadence patterns.
    - Add `humanize` to support human-friendly duration strings in log messages.
- Dev Mode:
  - Reintroduced `dev_mode` configuration flag (also auto-enabled when running under a debugger or `python -X dev`) to turn on asyncio debug logging and richer task diagnostics.
  - Only reload apps when in `dev_mode`, to avoid unexpected reloads in production, overridable with `always_reload_apps` config flag.
  - Only respect `@only_app` decorator when in `dev_mode`, to avoid accidentally running only one app in production - overridable with `allow_only_app_in_prod` config flag.
  - The event loop automatically switches to debug mode when `dev_mode` is enabled.
- Task Buckets:
  - Task buckets gained context helpers and `run_sync`/`run_on_loop_thread` wrappers so work spawned from worker threads is still tracked and can be cancelled cleanly.
  - Task buckets now expose `make_async_adapter`, replacing the old helper in `hassette.utils.async_utils` so sync callables are wrapped with the owning bucket's executor.
  - App-owned `Api`, `Bus`, and `Scheduler` instances share the app's task bucket and derive unique name prefixes, giving per-instance loggers and consistent task accounting.
  - All Apps (and all resources/services) should use `self.task_bucket` to spawn background tasks and to run synchronous code, to ensure proper tracking and cancellation.
    - Using `self.hassette.run_sync` or `self.hassette.run_on_loop_thread` is still supported, but will not track tasks in the app's task bucket.
- Configuration:
  - Resolve all paths in `HassetteConfig` to absolute paths.
  - Individual service log levels can be set via config, with the overall `log_level` being used if not specified.
  - New config options for individual service log levels:
      - `bus_service_log_level`
      - `scheduler_service_log_level`
      - `app_handler_log_level`
      - `health_service_log_level`
      - `websocket_log_level`
      - `service_watcher_log_level`
      - `file_watcher_log_level`
      - `task_bucket_log_level`
      - `apps_log_level`
    - Add `log_level` to `AppConfig` so apps can set their own log levels.
  - Add new configuration options for logging events on the Bus when at DEBUG level:
    - `log_all_events` - log every event that is fired.
    - `log_all_hass_events` - log every event from Home Assistant - will fall back to `log_all_events` if not set.
    - `log_all_hassette_events` - log every event from Hassette apps and core - will fall back to `log_all_events` if not set.
  - Add `app_startup_timeout_seconds` and `app_shutdown_timeout_seconds` to `HassetteConfig` to control how long to wait for apps to start and stop before giving up.
  - Allow having the Bus skip entities/domains altogether via `bus_excluded_domains` and `bus_excluded_domains` config options.
    - These take a tuple of strings and accept glob patterns.
    - Any events matching an excluded domain or entity_id will not be delivered to listeners or logged.

### Changed
- **Breaking:** Public imports now come from the root `hassette` package; the old `hassette.core` paths have been moved under `hassette.core.resources` / `hassette.core.services`, so update any direct `hassette.core...` imports to use the re-exported names on `hassette`.
- **Breaking:** `App.initialize` and `App.shutdown` have been replaced with `App.on_initialize` and `App.on_shutdown` hooks that do not need to call `super()`.
  - Attempting to override these methods will now raise a `CannotOverrideFinalError`.
- The Scheduler will now spawn tasks to run a job and reschedule a job, so jobs that take longer than their interval will not block subsequent runs.
- Resources now build a parent/child graph via `Resource.add_child` and harmonized `create()` factory methods, so services and sub-resources inherit owners and task buckets automatically.
- `Api.call_service` and the sync facade default to `return_response=False`, and the `turn_on` / `turn_off` / `toggle` are corrected to not pass `return_response` since this is not supported.
- Deprecated `set_logger_to_level` - loggers are finally working properly now so the standard `logger.setLevel(...)` should be used instead.

### Fixed
- Event bus and scheduler loops respect `shutdown_event`, allowing them to exit promptly during shutdown.
- WebSocket reconnects treat `CouldNotFindHomeAssistantError` as retryable and properly apply the retry policy, improving cold-start resilience.
- `Api.call_service` now includes `return_response` in the payload when requested, and `ServiceResponse` correctly models the returned data.

### Internal
- Improved documentation:
  - Switched to RTD theme for better readability and navigation.
  - Improved formatting of comparison guides.
  - Fixed some references.
- Reorganized most of the core code into `resources` and `services`
- Use `contextvars` instead of class variables to track global instance of `Hassette` and `HassetteConfig`
- `SchedulerService` now delegates scheduling to `_ScheduledJobQueue`, which uses a fair async lock to coordinate concurrent writers before dispatching due jobs.
- `Hassette.run_sync`/`run_on_loop_thread` now route through the global task bucket.
- **Breaking:** The `run_forever` method of the `Service` class has been replaced with `serve`. The new lifecycle hooks are valid for `Service` as well.

## [0.11.0] - 2025-10-05

### Added
- `hassette.event.app_reload_completed` now fires after reload cycles, and `HassetteEmptyPayload` provides a helper for simple internal events.
- Add `TaskBucket` class for tracking and cancelling related async tasks.
- Add `Hassette.task_bucket` for global task tracking, and `Resource.task_bucket` for per-resource task tracking.
- Introduced `TaskBucket` instances for Hassette, services, and apps; configure shutdown grace periods via the new `HassetteConfig.task_cancellation_timeout_seconds` setting.
- Added `Hassette.wait_for_ready` and `hassette.utils.wait_for_ready` helpers so resources can block on dependencies (for example, the API now waits for the WebSocket).
- Add `ResourceNotReadyError` exception to indicate that a resource is not ready for use.
- Expanded Home Assistant tuning knobs with `websocket_connection_timeout_seconds`, `websocket_total_timeout_seconds`, `websocket_response_timeout_seconds`, `websocket_heartbeat_interval_seconds`, and `scheduler_min/default/max_delay_seconds`.
- Add individual log level settings for core services.
- Add `cleanup` lifecycle method to `Resource` and `Service` for async cleanup tasks during shutdown. This generally will not need to be overridden, but is available if needed.

### Changed
- **Breaking:** Per-owner buses replace the global `hassette.bus`; listener removal must go through `BusService`, which now tracks listeners by owner under a fair async lock for atomic cleanup.
- **Breaking:** `@only` becomes `@only_app`, apps must expose a non-empty `instance_name`, and each app now owns its `Bus` and `Scheduler` handles.
- **Breaking:** The `hassette.core.apps` package moved under `hassette.core.classes.app`, and the service singletons are now `BusService` and `SchedulerService`; import apps from `hassette.core`/`hassette.core.classes` and treat the underscored services as private.
- **Deprecated:** `set_logger_to_debug` has been renamed to `set_logger_to_level`, and all core services now default to `INFO` level logging. `set_logger_to_debug` is still available but will be removed in a future release.
- App handlers now mark apps as ready after `initialize` completes.
- The API now waits for WebSocket readiness before creating its session, and classifies common client errors as non-retryable.

### Fixed
- App reloads clean up owned listeners and jobs, preventing leaked callbacks between reload cycles.
- Startup failures now emit the list of resources that never became ready, making it easier to diagnose configuration mistakes.

### Internal
- Test harness integrates TaskBucket support, adds a `hassette_with_nothing` fixture, and continues to provision mock services so CI can run without a Home Assistant container.
- Tightened local tooling: expanded `pyrightconfig.json`, enabled Ruff's `TID252`, and taught the nox test session to run `pytest` with `-W error`.
- Scheduler coordination now flows through `SchedulerService`, which reads min/default/max delays from config, waits for Hassette readiness, and tags spawned jobs in the task bucket for easier cancellation.
- Lifecycle helpers extend `Resource`/`Service` with explicit readiness flags (`mark_ready`, `mark_not_ready`, `is_ready`); Hassette spins up a global task bucket, names every background task, and blocks startup until all registered resources report ready, logging holdouts before shutting down.
- WebSocket connection handling uses Tenacity-driven retries with dedicated connect/auth/response timeouts, and the API now waits for WebSocket readiness before creating its session while classifying common client errors as non-retryable.
- Add asyncio task factory to register all tasks in the global task bucket with meaningful names to make cleanup easier.

## [0.10.0] - 2025-09-27

### Added
- Added utility functions for datetime conversion in `src/hassette/utils.py`

### Changed
- Updated state models to use `SystemDateTime` consistently instead of `Instant` or mixed types
- Replaced deprecated `InstantBaseState` with `DateTimeBaseState` for better type handling
- Remove `repr=False` for `last_changed`, `last_updated`, and `last_reported` in `BaseState` to improve logging and debugging output

### Fixed
- Fixed incorrect datetime conversion in `InputDateTimeState` to ensure proper timezone handling

## [0.9.0] - 2025-09-26

### Added
- Added ability to provide args and kwargs to scheduled jobs via scheduler helpers
  - `args` and `kwargs` keyword-only parameters added to all scheduler helper functions
  - These will be passed to the scheduled callable when it is run
  - See [Scheduler documentation](https://hassette.readthedocs.io/en/stable/pages/core-concepts/scheduler/) for details

### Changed
- Narrow date/time types accepted by `get_history`, `get_logbook`, `get_camera_image` and `get_calendar_events` to exclude `datetime`, `date`, and `ZonedDateTime` - use `PlainDateTime`, `SystemDateTime`, or `Date` instead

### Documentation
- Updated scheduler documentation to include new args/kwargs parameters for scheduling helpers
- Updated Readme to change roadmap reference to point to Github project board
- Removed roadmap.md file, using project board for tracking now

## [0.8.1] - 2025-09-23
### Fixed
- Remove opengraph sphinx extension from docs dependencies - it was causing issues with building the docs and isn't necessary for our use case

## [0.8.0] - 2025-09-23
### Added
- hot-reloading support for apps using `watchfiles` library
  - watches app files, hassette.toml, and .env files for changes
  - reloads apps on change, removes orphans, reimports apps if source files change
  - can be disabled with `watch_files = false` in config
  - add a few new configuration values to control file watcher behavior
- add utility function to wait for resources to be running with shutdown support
  - `wait_for_resources_running` function added to `Hassette` class
  - also available as standalone utility function in `hassette.utils`
- `@only` decorator to allow marking a single app to run without changing `hassette.toml`
  - importable from `hassette.core.apps`
  - useful for development when you want to only run a single app without modifying config file
  - will raise an error if multiple apps are marked with `@only`
- add `app_key` to `AppManifest` - reflects the key used to identify the app in config

### Changed
- move service watching logic to it's own service
- refactor app_handler to handle reloading apps, re-importing, removing orphans, etc.

### Fixed
- update `api.call_service` target typing to also allow lists of ids - [thanks @zlangbert](https://github.com/NodeJSmith/hassette/pull/44)!

## [0.7.0] - 2025-09-14
### Changed
- rename `cancel` on `Subscription` to `unsubscribe` for clarity

### Fixed
- improved docstrings across `Api` methods

### Added
- Documentation!

## [0.6.2] - 2025-09-14
### Fixed
- Fix logging on `App` subclasses to use `hassette.<AppClassName>` logger

## [0.6.1] - 2025-09-14
### Fixed
- Fixed `HassetteConfig` using single underscore when checking for app_dir, config_dir, and data_dir manually
  - Now checks both single and double underscore (with double underscore taking precedence) just to be safe
- Fixed `HassetteConfig` incorrectly prioritizing `HASSETTE_LOG_LEVEL` over `HASSETTE__LOG_LEVEL` (double underscore should take precedence)

## [0.6.0] - 2025-09-14

### Removed
- Removed `DEFAULT_CONFIG` constant for app config, not necessary

### Fixed
- Fixed `HassetteConfig` to properly handle `env_file` and `config_file` parameters passed in programmatically or via CLI args
  - These are now passed to the appropriate settings sources correctly
- Fixed `HassetteConfig` incorrectly prioritizing TomlConfig over environment variables and dotenv files (Pydantic docs are confusing on this point)

### Changed
#### Configuration
  - Add back ability to set top level `[hassette]` section in config file using custom `TomlConfigSettingsSource`
  - Update examples to show top level `[hassette]` section usage
  - Update README with new config usage and Docker instructions
  - Update README with example of using `docker-compose.yml` file
  - Update README with example of setting app config inline (.e.g `config = {send_alert = true}`)
  - Added relative `./config` path for config and .env files
#### App Handler
  - Improved app handler logic, apps should now be able to import other modules from the same app directory
    - **Known Issue**: Using `isinstance` does not work consistently, will be providing recommendation in docs on how to make this work better
#### Hassette
  - Update imports to be relative, same as other modules
#### Apps
  - Rename `app_manifest_cls` to `app_manifest` - was always an instance, not a class

### Added
#### HassetteConfig
  - Add `secrets` attribute to `HassetteConfig` to allow specifying secret names that will be filled from config sources
    - Secrets can be listed in the config file like `secrets = ["my_secret", "another_secret"]`
    - Secrets will be filled from config sources in order or will attempt to pull from environment variables if not found
    - Secrets are available in config as a dict, e.g. `config.secrets["my_secret"]`
  - Add `HassetteBaseSettings` to add tracking of final settings sources for all config attributes
    - `HassetteConfig.FINAL_SETTINGS_SOURCES` will show where each config attribute was set from
    - Useful for debugging config issues
  - Add `HassetteTomlConfigSettingsSource` to load config from a TOML file, supports top level `[hassette]` section
  - Add `get_config` class method to `HassetteConfig` to get global configuration without needing to access `Hassette` directly
    - E.g. `HassetteConfig.get_config()` will return the current config instance
  - Check for app required keys prior to loading apps, will skip any apps missing required keys and log a warning
    - Particularly useful if you have config values for the app in environment variables but have the app removed/disabled
#### Hassette
  - Surface `get_app` on `Hassette` class to allow getting an app instance by name and index (if necessary)
    - E.g. `hassette.get_app("MyApp")` or `hassette.get_app("MyApp", 1)`


## [0.5.0] - 2025-09-12
### Changed
- **BREAKING**: Remove logic to pop top level `[hassette]` section from config file, this has the unfortunate side effect of potentially overriding values set in environment variables
  - Update examples to remove references to top level `[hassette]` section
  - Add warning if we detect this section in the config file
  - Add TODO to get this working by implementing a custom `TomlConfigSettingsSource` that handles this
- **BREAKING**: Switch back to `__` double underscore for environment variable prefixes, prevents issues with app config that uses single underscore
- Add `env_file` to AppConfig default class config to load environment variables from `/config/.env` and `.env` files automatically
- Add examples of using `SettingsConfigDict` to set a custom `env_prefix` on AppConfig subclasses

## [0.4.2] - 2025-09-12
### Fixed
- Fixed permissions for /app and /data in Dockerfile
- Update example docker-compose.yml to use named volume for /data

## [0.4.1] - 2025-09-11
### Fixed
- Fixed Dockerfile to build for both amd64 and arm64

## [0.4.0] - 2025-09-10

### Added
#### Docker Support
- Dockerfile with Python 3.12-alpine base image for lightweight deployment
- Docker start script to set up virtual environment, install dependencies, and run Hassette
  - /apps that contain a pyproject.toml or uv.lock will be installed as a project
  - /config and /apps will be scanned for requirements.txt or hassette-requirements.txt files and merged for installation
- Example docker-compose.yml file for easy setup
- uv cache directory at /uv_cache to speed up dependency installation

#### Configuration
- New `app_dir` configuration option to specify the directory containing user apps (default: ./apps)
- Top level `[hassette]` can be used - previously had to be at the root of the file, with no header
- `HealthService` config - allow setting port and allow disabling health service
  - `health_service_port` (default: 8126)
  - `run_health_service` (default: true)


### Changed
- **BREAKING**: Moved all event models from `hassette.models.events` to `hassette.core.events` for better organization
- **BREAKING**: Updated configuration structure - flattened Hass configuration properties directly into main config
  - `config.hass.token` → `config.token`
  - `config.hass.ws_url` → `config.ws_url`
  - `config.hass.base_url` → `config.base_url`
- **BREAKING**: Changed environment variable prefix from `hassette__*` to `hassette_*` (double underscore to single)
- Change resource status prior to sending event, to ensure consistency
- Improve retry logic in `_Api` and `_Websocket` classes

### Fixed
- Improved App constructor with better parameter formatting and documentation
- Added `index` parameter documentation to App `__init__` method
- Fixed logging initialization to handle missing handlers gracefully using `contextlib.suppress`
- Enhanced state conversion with better discriminated union handling using Pydantic's `discriminator` field
- Improved error handling in `try_convert_state` function
- Updated AppConfig to allow arbitrary types (`arbitrary_types_allowed=True`)
- Handle bug in `HealthService` config - sometimes `web.AppKey` raises an `UnboundLocalError` (only seen in testing so far), fallback to string in this case

### Removed
- Removed unused `_make_unique_name` method from App class
- Removed `KNOWN_TOPICS` constant that was no longer used
- Removed `hass_config` property from Hassette class (configuration is now flattened)
- Cleaned up unused imports and redundant code
  - `ResourceSync`
  - `stop` method on Resource
  - `__init__` on `Service` that was the same as the parent class

### Internal
- Simplified configuration test files to use new flattened structure
- Updated all import statements throughout the codebase to reflect new module structure
- Simplified app handler path resolution by using `full_path` property directly
- Updated test configuration and example files to match new config structure
- Enhanced state model discriminator logic for better type resolution
- Consolidated configuration access patterns for cleaner code

## [0.3.3] - 2025-09-07

### Fixed
- Filter pydantic args correctly in `get_app_config_class` utility function so we
    don't attempt to use `typing.TypeVar` as a config class.

## [0.3.2] - 2025-09-07

### Fixed
- Removed incorrect `__init__` override in `AppSync` that was causing issues with app instantiation

## [0.3.1] - 2025-09-07

### Fixed
- Fixed timestamp conversion return types in `InputDateTimeState` attributes
- Removed custom attributes from input number states
- Get AppSync working using anyio.to_thread and `hassette.loop.create_task` to ensure we're on the right event loop

### Internal
- Consolidated input entity states into unified `input.py` module
- `BinarySensorState` now inherits from `BoolBaseState`
- Fixed inheritance issues in `SceneState`, `ZoneState`, and `NumberState`
- Update health service to use a `web.AppKey` instead of a string

### Tests
- get tests against HA instance working in Github Actions
- updated tests for fixed synchronous app handling

## [0.3.0] - 2025-09-04
### Changed
- Update exports to remove long lists of states, events, and predicates
- Still export StateChangeEvent
- Other exports are now under `states`, `events`, `predicates` exports
  - E.g. `from hassette import AttrChanged` becomes `from hassette import predicates` and `predicates.AttrChanged`

## [0.2.1] - 2025-09-04

### Added
- New examples directory with comprehensive automation examples
  - Battery monitoring example app with sync/async variants
  - Presence detection example with complex scene management
  - Sensor notification example
  - Example `hassette.toml` configuration file
- New `on_hassette_service_started` event handler
- Additional sync API methods for better synchronous app support

### Changed
- Improved README with comprehensive documentation and examples
- Updated pyproject.toml with better PyPI metadata and project URLs
- Enhanced notify service examples and API calls
- Updated roadmap with current development priorities

### Fixed
- Fixed notify service call examples in battery and presence apps
- Fixed `HassetteServiceEvent` annotation

## [0.2.0] - 2025-09-04

### Added
- Full typing support for Home Assistant entities and events
- Custom scheduler replacing APScheduler dependency
- Comprehensive state model system with typed attributes
- Event bus with powerful filtering capabilities
- Testing utilities and mock server support

### Changed
- **BREAKING**: Significant changes to state/sensor structure for better type safety
- Made sensor attributes required and always present
- Simplified state management by moving simple states to dedicated module
- Reduced complexity in state handling while maintaining full functionality
- Updated authentication and HTTP handling

### Fixed
- API parity between sync and async methods
- Sensor attribute handling and device class support
- Configuration scope and core initialization

### Internal
- Moved sensor literals into constants module
- Reorganized state models for better maintainability
- Added comprehensive test coverage for API parity
- Improved development tooling and testing setup

## [0.1.1] - 2025-09-02

### Added
- Initial public release of Hassette framework
- Basic async-first Home Assistant automation support
- Type-safe entity and event handling
- TOML-based configuration system
- Pydantic model validation for app configs

### Features
- Event-driven architecture with asyncio
- Home Assistant WebSocket API integration
- Structured logging with coloredlogs
- Scheduler for cron and interval-based tasks
- App lifecycle management (initialize/shutdown)
