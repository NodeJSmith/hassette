# Doc Coverage Review — Area Prompts

One block per area. Each defines the inventory scope for that area's agent; append the shared instructions from SKILL.md after it. Do not reference further files from here.

## bus

Your area is the event bus and event handling. Inventory: every public registration method on `Bus` (src/hassette/bus/bus.py) and each of its parameters with user-visible behavior (handler, name, changed, changed_from/to, where, immediate, duration, debounce, throttle, once, timeout, timeout_disabled, priority, on_error, kwargs); `Subscription` and its methods; `BusErrorContext` fields; the predicate (`P`), condition (`C`), accessor (`A`), and dependency (`D`) modules in src/hassette/event_handling/ — every public class/alias an app author can use; event types and topic strings in src/hassette/events/ and src/hassette/types/enums.py that handlers subscribe to; `bus.emit` and `BusSyncFacade`.

## scheduler

Your area is scheduling. Inventory: every public method on `Scheduler` (src/hassette/scheduler/scheduler.py) and its parameters (name, group, jitter, timeout, timeout_disabled, on_error, if_exists, args, kwargs); all trigger classes in triggers.py and `TriggerProtocol`; `ScheduledJob` public attributes and methods; `SchedulerErrorContext`; `SchedulerSyncFacade`; scheduler-related config keys (`[hassette.scheduler]`, job_timeout_seconds).

## api

Your area is the Home Assistant API surface. Inventory: every public method on `Api` (src/hassette/api/api.py) including the helper CRUD families and counter shortcuts; `ApiSyncFacade`; entity models in src/hassette/models/entities/ that `get_entity` accepts; `ServiceResponse`; the exceptions Api methods raise that callers would catch.

## states

Your area is state access and conversion. Inventory: `StateManager` access patterns (domain properties, `[CustomState]`, get/bracket access, iteration methods) in src/hassette/state_manager/; the state model base classes and `BaseState`/`AttributesBase` public fields and helpers (is_unknown, is_unavailable, is_group, extras, extra, has_feature) in src/hassette/models/states/base.py; `STATE_REGISTRY`/`TYPE_REGISTRY`, `register_type_converter_fn`, `register_simple_type_converter`, `TypeConverterEntry` in src/hassette/conversion/; sentinels in src/hassette/const.py (ANY_VALUE, MISSING_VALUE, NOT_PROVIDED).

## app

Your area is the App base classes. Inventory: `App`/`AppSync` lifecycle hooks and public attributes/handles (logger, bus, scheduler, api, states, cache, task_bucket, app_config, now(), instance_name, app_key) in src/hassette/app/; `AppConfig` built-in fields and settings behavior (env_prefix, extra policy); `only_app`; `TaskBucket` public methods (src/hassette/task_bucket/); the `.sync` facades reachable from AppSync.

## config

Your area is configuration. Inventory: every field on `HassetteConfig` (src/hassette/config/config.py) and on each nested config model in src/hassette/config/models.py (AppsConfig, LoggingConfig, WebApiConfig, DatabaseConfig, WebsocketConfig, LifecycleConfig, FileWatcherConfig, SchedulerConfig, and any others), with its TOML section; env var mechanics (prefix, nested delimiter, token aliases); file discovery locations in defaults.py. A config field a user could set but never learn about is the canonical gap for this area.

## cli

Your area is the `hassette` CLI (src/hassette/cli/). Inventory: every command and subcommand, every flag and alias, accepted value formats (--since formats, --instance resolution), env vars the CLI reads, exit codes, --json output mode, shell completion.

## exceptions

Your area is src/hassette/exceptions.py. Inventory: every exception class an app author might catch, see in logs, or trigger from their own code or config. For each: is it documented anywhere a user would find it (troubleshooting page, concept page, docstring-only)? Framework-internal exceptions that user code can never observe are excluded — justify exclusions by where they are raised.

## test-utils

Your area is src/hassette/test_utils/. Inventory: everything in `__all__` — harness classes, factory functions, recording API, simulation methods (set_state, simulate_*, drain_task_bucket, freeze_time, advance_time, trigger_due_jobs), drain exceptions, config helpers. The testing docs section (docs/pages/testing/) is the expected home.

## web

Your area is the web API surface in src/hassette/web/routes/. Inventory: every REST endpoint and the WebSocket endpoint an operator might script against (path, method, what it returns, error statuses), plus web-related config the routes honor (CORS, buffers). The web-ui docs section and cli/configuration pages are the expected homes. Frontend component internals are out of scope — the accuracy review owns those.
