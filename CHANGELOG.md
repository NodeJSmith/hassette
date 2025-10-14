# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added
- `Subscription` now has ``cancel`` method to unsubscribe from events, to be consistent with ``ScheduledJob``.
- `App.send_event_sync` method added for synchronous event sending.

### Changed
- **Breaking:** ``Scheduler.run_once`` has been updated to use ``start`` instead of ``run_at`` to be consistent with other helpers.
- **Breaking:** ``cleanup`` method is now marked as final and cannot be overridden in subclasses.

### Removed
- **Breaking:** Removed deprecated `set_logger_to_debug` and `set_logger_to_level` Resource methods.
- **Breaking:** Removed deprecated `run_sync`, `run_on_loop_thread`, and `create_task` methods from Hassette.
- **Breaking:** Removed `run_at` alias for `run_once` in Scheduler.

### Internal
- Remove scheduled jobs that are cancelled or do not repeat, instead of just marking them as cancelled and leaving them in the job queue.

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
- `_SchedulerService` now delegates scheduling to `_ScheduledJobQueue`, which uses a fair async lock to coordinate concurrent writers before dispatching due jobs.
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
- **Breaking:** The `hassette.core.apps` package moved under `hassette.core.classes.app`, and the service singletons are now `_BusService` and `_SchedulerService`; import apps from `hassette.core`/`hassette.core.classes` and treat the underscored services as private.
- **Deprecated:** `set_logger_to_debug` has been renamed to `set_logger_to_level`, and all core services now default to `INFO` level logging. `set_logger_to_debug` is still available but will be removed in a future release.
- App handlers now mark apps as ready after `initialize` completes.
- The API now waits for WebSocket readiness before creating its session, and classifies common client errors as non-retryable.

### Fixed
- App reloads clean up owned listeners and jobs, preventing leaked callbacks between reload cycles.
- Startup failures now emit the list of resources that never became ready, making it easier to diagnose configuration mistakes.

### Internal
- Test harness integrates TaskBucket support, adds a `hassette_with_nothing` fixture, and continues to provision mock services so CI can run without a Home Assistant container.
- Tightened local tooling: expanded `pyrightconfig.json`, enabled Ruff's `TID252`, and taught the nox test session to run `pytest` with `-W error`.
- Scheduler coordination now flows through `_SchedulerService`, which reads min/default/max delays from config, waits for Hassette readiness, and tags spawned jobs in the task bucket for easier cancellation.
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
  - See [Scheduler documentation](https://hassette.readthedocs.io/en/latest/scheduler.html) for details

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
- `_HealthService` config - allow setting port and allow disabling health service
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
- Handle bug in `_HealthService` config - sometimes `web.AppKey` raises an `UnboundLocalError` (only seen in testing so far), fallback to string in this case

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
