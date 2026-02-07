# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

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
  - See [Scheduler documentation](https://hassette.readthedocs.io/en/stable/scheduler.html) for details

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
