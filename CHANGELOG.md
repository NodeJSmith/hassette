# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

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
- update `api.call_service` target typing to also allow lists of ids - thanks @zlangbert!

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
