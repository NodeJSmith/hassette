# Copilot Instructions for Hassette

These notes make AI coding agents productive quickly in this repo. Focus on the patterns below; prefer the referenced files for details and examples.

## Big Picture

- Purpose: Framework for building Home Assistant automations with async-first design and strong typing. See `README.md`.
- Orchestrator: `src/hassette/core/core.py` (`Hassette`) wires services and runs the loop. It registers internal services, then exposes user-facing facades:
  - WebSocket: `core/websocket.py` connects to HA, authenticates, subscribes to events, and pushes them to the internal event stream.
  - Event Bus: `core/bus/bus.py` consumes the stream and dispatches to listeners with powerful predicates and decorators.
  - API: `core/api.py` wraps HA REST and WS calls; `ApiSyncFacade` exposes sync mirrors via `hassette.run_sync`.
  - Scheduler: `core/scheduler/` provides cron/interval scheduling (croniter/whenever).
- Data flow: HA WebSocket → `create_event_from_hass` → `Bus.dispatch` → App listeners; API uses both WS and REST.

## Configuration & App Loading

- Config model: `config/core_config.py` (`HassetteConfig`). Sources priority (lowest→highest): CLI, init args, TOML (`hassette.toml`), env vars, `.env`, file secrets.
- URLs and auth headers derived from `base_url`, `api_port`, `token`. Helpers: `ws_url`, `rest_url`, `headers`, `truncated_token`.
- Apps: Declarative in `hassette.toml` under `[apps.<name>]` validated by `config/app_manifest.py`.
  - Required: `filename`, `class_name`, `app_dir`. Optional: `enabled`, `display_name`, `config` (dict or list for multiple instances).
  - Loader: `core/apps/app_handler.py` imports modules under a dynamic namespace: top-level package name is `Path(app_dir).name`. Example: `app_dir="src/apps"` → modules importable as `apps.*`.
  - Instances are validated using the app’s `AppConfig` class and initialized after WebSocket service is running.

## App Pattern (typed)

- Base classes: `core/apps/app.py` exports `App[AppConfigT]` and `AppSync`.
- Minimal async app:
  ```python
  from hassette import App, AppConfig
  class MyCfg(AppConfig): pass
  class MyApp(App[MyCfg]):
      async def initialize(self):
          self.bus.on_entity("light.*", handler=self.changed)
      async def changed(self, event):
          await self.api.turn_on("light.bedroom")
  ```
- Synchronous apps use `AppSync` and implement `initialize_sync`; use `self.api.sync.*` inside sync code.

## Event Bus Usage

- Topics: see `core/topics.py` (e.g., `HASS_EVENT_STATE_CHANGED`, `HASSETTE_EVENT_SERVICE_STATUS`).
- Subscriptions (with predicates, debounce, throttle):
  ```python
  self.bus.on_entity("binary_sensor.motion", handler=self.on_motion, changed_to="on")
  self.bus.on_attribute("mobile_device.me", "battery_level", handler=self.on_batt)
  # Custom service call filter
  self.bus.on_call_service(domain="light", service="turn_on", handler=self.on_turn_on)
  ```
- Notes: Bus ignores HA system_log debug events; use `Subscription` returned to unsubscribe if needed.

## API Conventions

- Async-first. Do not call `ApiSyncFacade` methods from inside an event loop; they raise. Use `await self.api.*` inside apps.
- REST helpers convert params to strings and retry with jitter (tenacity). 404 maps to `EntityNotFoundError`.
- Useful calls: `get_states()`, `get_state_raw(entity_id)`, `get_state(entity_id, StateType)`, `call_service(domain, service, target=..., **data)`, `fire_event(...)`, `set_state(...)`, history/logbook methods, `render_template(...)`.

## Scheduler

- Import from `core/scheduler`: `Scheduler`, `CronTrigger`, `IntervalTrigger`.
  ```python
  self.scheduler.run_cron(self.daily_job, hour=6)
  self.scheduler.run_every(self.poll, interval=30)
  ```

## Developer Workflows

- Run the app locally:
  ```bash
  uv pip install -e .
  uv run run-hassette -c ./config/hassette.toml -e ./config/.env
  ```
- Tests:
  ```bash
  # All tests (requires Docker and will start a Home Assistant container)
  uv run nox -s tests
  # Skip HA-dependent tests
  uv run nox -s tests_no_ha
  # Or with pytest directly
  uv run pytest -m "not requires_ha"
  ```
- Entry point: `run-hassette` (see `pyproject.toml` -> `project.scripts`). Pinned tool versions in `mise.toml`.

## Conventions & Pitfalls

- `app_dir` determines the import package name (its leaf directory). Keep `app_dir` stable to avoid confusing module names.
- Provide `AppConfig` to get typed `self.app_config`; Pydantic settings features (env prefixes, validation) are used.
- Sync API methods block on the main loop; prefer async forms in apps.
- Service lifecycle events are published on the bus; `Hassette` restarts services on failure and shuts down on crash.

## Pointers

- Core: `src/hassette/core/{core.py, websocket.py, api.py, bus/bus.py}`
- Config: `src/hassette/config/{core_config.py, app_manifest.py}`
- Models: `src/hassette/models/**` (typed states/entities)
- Examples: `examples/`
- Tests: `tests/` (see `pytest.ini` markers in `pyproject.toml` and HA fixtures in `tests/conftest.py`)
