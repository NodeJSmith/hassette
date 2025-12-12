# Copilot Instructions for Hassette

These notes make AI coding agents productive quickly in this repo. Focus on the patterns below; prefer the referenced files for details and examples.

## Big Picture

- Purpose: Framework for building Home Assistant automations with async-first design and strong typing. See `README.md`.
- Runtime: `src/hassette/core/core.py` (`Hassette`) builds a tree of `Resource`/`Service` instances defined in `core/resources/base.py`; task orchestration lives in `core/resources/tasks.py` (`TaskBucket`).
- Background services (`src/hassette/core/services/`): `_Websocket` streams HA events, `BusService` routes them, `ApiResource` manages REST/WS clients, `SchedulerService` runs jobs, `AppHandler` loads user apps, `FileWatcherService` listens for file/config changes, `ServiceWatcher` supervises dependencies, `HealthService` exposes status.
- App-facing resources: each app owns `Api` (`core/resources/api/api.py`), `Bus` (`core/resources/bus/bus.py`), `Scheduler` (`core/resources/scheduler/scheduler.py`), and its own `TaskBucket`.
- Data flow: `_Websocket` → `events.create_event_from_hass` → `BusService.dispatch` → per-owner `Bus` resources → app handlers. API calls reuse both the shared WebSocket and REST client managed by `ApiResource`.

## Configuration & App Loading

- Config model: `src/hassette/config/core.py` (`HassetteConfig`). Source priority (highest→lowest): CLI args, init kwargs, environment variables, `.env` files, secrets files, TOML (`/config/hassette.toml`, `./hassette.toml`, `./config/hassette.toml`). `model_post_init` registers the config in `core/context.py`, ensures `config_dir`/`data_dir` exist.
- Helpers derive URLs and auth headers (`ws_url`, `rest_url`, `headers`, `truncated_token`). Flags such as `allow_reload_in_prod`, `allow_only_app_in_prod`, `log_all_events`, `bus_excluded_domains/entities`, `task_bucket_log_level`, etc. tweak runtime behaviour.
- Apps live under `[apps.<name>]` in TOML and use `AppManifest` from `src/hassette/config/classes.py` for validation.
  - Required keys: `filename`, `class_name`; optional: `app_dir`, `enabled`, `display_name`, `config` (dict or list for multi-instance apps).
  - Loader (`src/hassette/utils/app_utils.py`) runs `run_apps_pre_check`, builds a namespace named after `config.app_dir.name` (e.g. `apps.*`), caches app classes, and surfaces `CannotOverrideFinalError` if lifecycle methods marked `@final` are overridden.
  - `AppHandler` (`core/services/app_handler.py`) waits for core services, honors `@only_app` (dev-mode unless `allow_only_app_in_prod`), listens to `FileWatcherService`, and restarts apps when manifests or env files change.

## App Pattern (typed)

- Base classes: `src/hassette/core/resources/app/app.py` exposes `App[AppConfigT]` (async) and `AppSync`. Override lifecycle hooks (`before_initialize`, `on_initialize`, `after_initialize`, and matching shutdown hooks); `initialize()` / `shutdown()` are final.
- Example async app with dependency injection:

  ```python
  from typing import Annotated
  from hassette import App, AppConfig, states
  from hassette import dependencies as D

  class MyConfig(AppConfig):
      light: str

  class MyApp(App[MyConfig]):
      async def on_initialize(self):
          self.bus.on_state_change(
              self.app_config.light,
              handler=self.on_light_change,
              changed_to="on",
          )

      async def on_light_change(
          self,
          new_state: D.StateNew[states.LightState],
          entity_id: D.EntityId,
      ):
          friendly_name = new_state.attributes.friendly_name or entity_id
          await self.api.call_service("notify", "mobile_app_me", message=f"{friendly_name} turned on")
  ```

- Sync apps inherit `AppSync` and implement `on_initialize_sync` / `on_shutdown_sync`; use `self.api.sync.*` for blocking calls. `self.task_bucket` offers helpers (`spawn`, `run_in_thread`, `run_sync`) for background work.

## Dependency Injection for Event Handlers

- **Module**: `src/hassette/dependencies/` provides DI system for event handlers
- **Purpose**: Automatically extract and inject event data into handler parameters using `Annotated` type hints
- **Key files**:
  - `__init__.py` - Public API and examples
  - `classes.py` - Dependency marker classes (`StateNew`, `StateOld`, `AttrNew`, etc.)
  - `extraction.py` - Signature inspection and parameter extraction logic
- **Usage pattern**:

  ```python
  from typing import Annotated
  from hassette import dependencies as D, states
  from hassette import accessors as A

  async def handler(
      new_state: D.StateNew[states.LightState],
      entity_id: D.EntityId,
      # For attributes, use custom extractors:
      brightness: Annotated[int | None, A.get_attr_new("brightness")],
  ):
      # Parameters automatically extracted and injected
      pass
  ```

- **Available dependencies**: `StateNew`, `StateOld`, `MaybeStateNew`, `MaybeStateOld`, `EntityId`, `MaybeEntityId`, `Domain`, `MaybeDomain`, `EventContext`, `TypedStateChangeEvent`. For attribute extraction and other advanced cases, use custom extractors with `Annotated` and accessors from `hassette.bus.accessors`.
- **Integration**: `Bus` resource (`core/resources/bus/bus.py`) uses `extract_from_signature` and `validate_di_signature` to process handler signatures and inject values at call time

## Event Bus Usage

- Topics are defined in `src/hassette/topics.py` (`HASS_EVENT_STATE_CHANGED`, `HASSETTE_EVENT_SERVICE_STATUS`, `HASSETTE_EVENT_APP_LOAD_COMPLETED`, etc.).
- `Bus` (`core/resources/bus/bus.py`) fronts `BusService`; sync handlers are wrapped automatically and subscriptions return `Subscription` handles. Predicates live in `core/resources/bus/predicates`.
- Useful helpers:
  ```python
  self.bus.on_state_change("binary_sensor.motion", handler=self.on_motion, changed_to="on")
  self.bus.on_attribute_change("mobile_device.me", "battery_level", handler=self.on_battery_drop)
  self.bus.on_call_service(domain="light", service="turn_on", handler=self.on_turn_on)
  ```
- `BusService` skips HA `system_log` debug spam and respects config exclusions (`bus_excluded_domains`, `bus_excluded_entities`). Service lifecycle events flow over the same topics for observability.

## API Conventions

- `Api` (`core/resources/api/api.py`) is async-first; methods cover WS helpers, REST helpers, states, services, events, history/logbook, and template rendering. REST requests retry with jitter and raise `EntityNotFoundError` on 404s.
- `ApiSyncFacade` (`core/resources/api/sync.py`) provides blocking mirrors via `TaskBucket.run_sync` and raises if invoked inside an active event loop.
- Frequently used calls: `get_states()`, `get_states_raw()`, typed `get_state(entity_id, StateType)`, `call_service(domain, service, target=..., **data)`, `fire_event(...)`, `set_state(...)`, `render_template(...)`.

## Scheduler

- `Scheduler` (`core/resources/scheduler/scheduler.py`) delegates to `SchedulerService`; jobs are `ScheduledJob` objects from `core/resources/scheduler/classes.py`, with helpers `CronTrigger` and `IntervalTrigger`.
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
  uv run hassette -c ./config/hassette.toml -e ./config/.env
  ```
- Tests (start a Home Assistant Docker container via fixtures):
  ```bash
  uv run nox -s tests
  uv run nox -s tests_with_coverage
  ```
- Tooling and scripts: entry point `hassette` (see `pyproject.toml` → `project.scripts`); tool versions pinned in `mise.toml`; pre-commit hooks in `.pre-commit-config.yaml`; lint/type settings in `ruff.toml` and `pyrightconfig.json`.

## Conventions & Pitfalls

- Lifecycle hooks only: `initialize()` / `shutdown()` are `@final`; overriding them triggers `CannotOverrideFinalError`. Use `on_initialize`, `before_shutdown`, etc.
- Use `self.task_bucket.spawn/run_in_thread/run_sync` for background work; Hassette cleans up these tasks on shutdown.
- `@only_app` (from `hassette.App`) limits execution to a single app; only honored in dev mode unless `allow_only_app_in_prod` is set.
- File watching is enabled when `watch_files=True` and (`dev_mode` or `allow_reload_in_prod=True`). Watch paths include manifests, `.env` sources, and every configured app module.
- Log levels cascade: `log_level` seeds per-resource `*_log_level`, and `log_all_events` seeds `log_all_hass_events` / `log_all_hassette_events`. Adjust them in config rather than hardcoding.
- `app_dir`’s leaf name becomes the import namespace; keep it stable to avoid breaking module paths.

## Pointers

- Core runtime: `src/hassette/core/core.py`, `src/hassette/core/resources/{base.py,tasks.py}`, `src/hassette/core/context.py`
- Services: `src/hassette/core/services/{websocket_service.py,api_resource.py,bus_service.py,scheduler_service.py,app_handler.py,file_watcher.py,service_watcher.py,health_service.py}`
- App resources: `src/hassette/core/resources/{api/api.py,api/sync.py,bus/bus.py,scheduler/scheduler.py,app/app.py}`
- Config: `src/hassette/config/{core.py,classes.py,helpers.py,defaults.py}`
- Events & models: `src/hassette/events/**`, `src/hassette/models/**`, `src/hassette/enums.py`
- Examples & tests: `examples/`, `tests/` (fixtures in `tests/conftest.py`)

## Code Conventions

- Type hints: Strong typing is a first-class citizen. Use `typing` and `typing_extensions` features liberally (e.g. `TypeVar`, `Generic`, `Protocol`, `runtime_checkable`, `final`, `Literal`, `TypedDict`, etc.). Leverage existing types in `src/hassette/types.py` and domain-specific models in `src/hassette/models/`.
- Pyrigh and Ruff: Type checking is enforced via Pyright (`pyrightconfig.json`) and linting via Ruff (`ruff.toml`). Follow their rules and fix violations promptly. Do not use mypy style type comments.
- Docstrings: Document all public classes, methods, and functions with clear docstrings. Follow the Google style guide for consistency.
- Examples: Include usage examples in docstrings where applicable, especially for complex methods or classes.
- Documentation is written in reStructuredText (`.rst`) format and lives in the `docs/` directory. Update docs alongside code changes to keep them in sync. Docstring examples should be formatted for inclusion in the docs.
