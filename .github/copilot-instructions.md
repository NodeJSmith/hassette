# Copilot Instructions for Hassette

These notes make AI coding agents productive quickly in this repo. Focus on the patterns below; prefer the referenced files for details and examples.

## Big Picture

- Purpose: Framework for building Home Assistant automations with async-first design and strong typing. See `README.md`.
- Runtime: `src/hassette/core/core.py` (`Hassette`) builds a tree of `Resource`/`Service` instances defined in `core/resources/base.py`; task orchestration lives in `core/resources/tasks.py` (`TaskBucket`).
- Background services (`src/hassette/core/services/`): `_Websocket` streams HA events, `_BusService` routes them, `_ApiService` manages REST/WS clients, `_SchedulerService` runs jobs, `_AppHandler` loads user apps, `_FileWatcher` listens for file/config changes, `_ServiceWatcher` supervises dependencies, `_HealthService` exposes status.
- App-facing resources: each app owns `Api` (`core/resources/api/api.py`), `Bus` (`core/resources/bus/bus.py`), `Scheduler` (`core/resources/scheduler/scheduler.py`), and its own `TaskBucket`.
- Data flow: `_Websocket` → `events.create_event_from_hass` → `_BusService.dispatch` → per-owner `Bus` resources → app handlers. API calls reuse both the shared WebSocket and REST client managed by `_ApiService`.

## Configuration & App Loading

- Config model: `src/hassette/config/core_config.py` (`HassetteConfig`). Source priority (lowest→highest): CLI args, init kwargs, TOML (`/config/hassette.toml`, `./hassette.toml`, `./config/hassette.toml`), environment variables, `.env` files, secrets files. `model_post_init` registers the config in `core/context.py`, ensures `config_dir`/`data_dir` exist, and loads additional `.env` files it discovers.
- Helpers derive URLs and auth headers (`ws_url`, `rest_url`, `headers`, `truncated_token`). Flags such as `allow_reload_in_prod`, `allow_only_app_in_prod`, `log_all_events`, `bus_excluded_domains/entities`, `task_bucket_log_level`, etc. tweak runtime behaviour.
- Apps live under `[apps.<name>]` in TOML and use `src/hassette/config/app_manifest.py` for validation.
  - Required keys: `filename`, `class_name`; optional: `app_dir`, `enabled`, `display_name`, `config` (dict or list for multi-instance apps).
  - Loader (`src/hassette/utils/app_utils.py`) runs `run_apps_pre_check`, builds a namespace named after `config.app_dir.name` (e.g. `apps.*`), caches app classes, and surfaces `CannotOverrideFinalError` if lifecycle methods marked `@final` are overridden.
  - `_AppHandler` (`core/services/app_handler.py`) waits for core services, honors `@only_app` (dev-mode unless `allow_only_app_in_prod`), listens to `_FileWatcher`, and restarts apps when manifests or env files change.

## App Pattern (typed)

- Base classes: `src/hassette/core/resources/app/app.py` exposes `App[AppConfigT]` (async) and `AppSync`. Override lifecycle hooks (`before_initialize`, `on_initialize`, `after_initialize`, and matching shutdown hooks); `initialize()` / `shutdown()` are final.
- Example async app:

  ```python
  from hassette import App, AppConfig

  class MyConfig(AppConfig):
      light: str

  class MyApp(App[MyConfig]):
      async def on_initialize(self):
          self.bus.on_state_change(
              self.app_config.light,
              handler=self.on_light_change,
              changed_to="on",
          )

      async def on_light_change(self, event):
          await self.api.call_service("notify", "mobile_app_me", message="Light turned on")
  ```

- Sync apps inherit `AppSync` and implement `on_initialize_sync` / `on_shutdown_sync`; use `self.api.sync.*` for blocking calls. `self.task_bucket` offers helpers (`spawn`, `run_in_thread`, `run_sync`) for background work.

## Event Bus Usage

- Topics are defined in `src/hassette/topics.py` (`HASS_EVENT_STATE_CHANGED`, `HASSETTE_EVENT_SERVICE_STATUS`, `HASSETTE_EVENT_APP_LOAD_COMPLETED`, etc.).
- `Bus` (`core/resources/bus/bus.py`) fronts `_BusService`; sync handlers are wrapped automatically and subscriptions return `Subscription` handles. Predicates live in `core/resources/bus/predicates`.
- Useful helpers:
  ```python
  self.bus.on_state_change("binary_sensor.motion", handler=self.on_motion, changed_to="on")
  self.bus.on_attribute_change("mobile_device.me", "battery_level", handler=self.on_battery_drop)
  self.bus.on_call_service(domain="light", service="turn_on", handler=self.on_turn_on)
  ```
- `_BusService` skips HA `system_log` debug spam and respects config exclusions (`bus_excluded_domains`, `bus_excluded_entities`). Service lifecycle events flow over the same topics for observability.

## API Conventions

- `Api` (`core/resources/api/api.py`) is async-first; methods cover WS helpers, REST helpers, states, services, events, history/logbook, and template rendering. REST requests retry with jitter and raise `EntityNotFoundError` on 404s.
- `ApiSyncFacade` (`core/resources/api/sync.py`) provides blocking mirrors via `TaskBucket.run_sync` and raises if invoked inside an active event loop.
- Frequently used calls: `get_states()`, `get_states_raw()`, typed `get_state(entity_id, StateType)`, `call_service(domain, service, target=..., **data)`, `fire_event(...)`, `set_state(...)`, `render_template(...)`.

## Scheduler

- `Scheduler` (`core/resources/scheduler/scheduler.py`) delegates to `_SchedulerService`; jobs are `ScheduledJob` objects from `core/resources/scheduler/classes.py`, with helpers `CronTrigger` and `IntervalTrigger`.
- APIs: `run_in`, `run_every`, `run_minutely`/`hourly`/`daily`, `run_once`, and `schedule` accept sync or async callables plus cron/interval triggers.
  ```python
  self.scheduler.run_in(self.poll_devices, 30)
  self.scheduler.run_every(self.flush_cache, interval=300)
  self.scheduler.run_cron(self.morning_job, hour=6, minute=0, name="wake_up")
  ```
- Config fields (`scheduler_min_delay_seconds`, `scheduler_max_delay_seconds`, `scheduler_default_delay_seconds`) bound cadence and sleep behaviour.

## Developer Workflows

- Run Hassette locally:
  ```bash
  uv pip install -e .
  uv run run-hassette -c ./config/hassette.toml -e ./config/.env
  ```
- Tests (start a Home Assistant Docker container via fixtures):
  ```bash
  uv run nox -s tests
  uv run nox -s tests_with_coverage
  ```
- Tooling and scripts: entry point `run-hassette` (see `pyproject.toml` → `project.scripts`); tool versions pinned in `mise.toml`; pre-commit hooks in `.pre-commit-config.yaml`; lint/type settings in `ruff.toml` and `pyrightconfig.json`.

## Conventions & Pitfalls

- Lifecycle hooks only: `initialize()` / `shutdown()` are `@final`; overriding them triggers `CannotOverrideFinalError`. Use `on_initialize`, `before_shutdown`, etc.
- Use `self.task_bucket.spawn/run_in_thread/run_sync` for background work; Hassette cleans up these tasks on shutdown.
- `@only_app` (from `hassette.App`) limits execution to a single app; only honored in dev mode unless `allow_only_app_in_prod` is set.
- File watching is enabled when `watch_files=True` and (`dev_mode` or `allow_reload_in_prod=True`). Watch paths include manifests, `.env` sources, and every configured app module.
- Log levels cascade: `log_level` seeds per-resource `*_log_level`, and `log_all_events` seeds `log_all_hass_events` / `log_all_hassette_events`. Adjust them in config rather than hardcoding.
- `app_dir`’s leaf name becomes the import namespace; keep it stable to avoid breaking module paths.

## Pointers

- Core runtime: `src/hassette/core/core.py`, `src/hassette/core/resources/{base.py,tasks.py}`, `src/hassette/core/context.py`
- Services: `src/hassette/core/services/{websocket_service.py,api_service.py,bus_service.py,scheduler_service.py,app_handler.py,file_watcher.py,service_watcher.py,health_service.py}`
- App resources: `src/hassette/core/resources/{api/api.py,api/sync.py,bus/bus.py,scheduler/scheduler.py,app/app.py}`
- Config: `src/hassette/config/{core_config.py,app_manifest.py,sources_helper.py}`
- Events & models: `src/hassette/events/**`, `src/hassette/models/**`, `src/hassette/topics.py`
- Examples & tests: `examples/`, `tests/` (fixtures in `tests/conftest.py`)

## Code Conventions

- Type hints: Strong typing is a first-class citizen. Use `typing` and `typing_extensions` features liberally (e.g. `TypeVar`, `Generic`, `Protocol`, `runtime_checkable`, `final`, `Literal`, `TypedDict`, etc.). Leverage existing types in `src/hassette/types.py` and domain-specific models in `src/hassette/models/`.
- Pyrigh and Ruff: Type checking is enforced via Pyright (`pyrightconfig.json`) and linting via Ruff (`ruff.toml`). Follow their rules and fix violations promptly. Do not use mypy style type comments.
- Docstrings: Document all public classes, methods, and functions with clear docstrings. Follow the Google style guide for consistency.
- Examples: Include usage examples in docstrings where applicable, especially for complex methods or classes.
- Documentation is written in reStructuredText (`.rst`) format and lives in the `docs/` directory. Update docs alongside code changes to keep them in sync. Docstring examples should be formatted for inclusion in the docs.
