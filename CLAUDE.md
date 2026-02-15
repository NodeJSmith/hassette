# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Hassette is an async-first Python framework for building Home Assistant automations. It emphasizes type safety (Pydantic models), dependency injection (FastAPI-style), and async/await patterns. Python 3.11+ required.

## Common Commands

```bash
# Install dependencies
uv sync

# Run tests locally (preferred for development)
uv run pytest

# Run tests via nox (CI only — slower, tests across Python 3.11, 3.12, 3.13)
uv run nox -s tests

# Run tests with coverage
uv run nox -s tests_with_coverage

# Run a single test file
uv run pytest tests/integration/test_api.py

# Run a specific test
uv run pytest tests/integration/test_api.py::test_function_name -v

# Type checking
uv run pyright

# Serve documentation locally
uv run mkdocs serve
```

## Architecture

### Core Components

**Hassette** (`src/hassette/core/core.py`) - Main coordinator that connects to Home Assistant via WebSocket, manages app lifecycle, and coordinates all services.

**App** (`src/hassette/app/app.py`) - Base class for user automations. Generic over `AppConfig` type. Each app gets its own Bus, Scheduler, Api, and StateManager. Lifecycle hooks: `on_initialize`, `on_ready`, `on_shutdown`.

**Bus** (`src/hassette/bus/`) - Event pub/sub with filtering. Methods: `on_state_change`, `on_attribute_change`, `on_call_service`, `on_event`. Supports glob patterns, predicates, conditions, debounce, throttle.

**Scheduler** (`src/hassette/scheduler/`) - Task scheduling with `run_in()`, `run_once()`, `run_every()`, `run_hourly()`, `run_daily()`, `run_cron()`.

**Api** (`src/hassette/api/`) - Home Assistant REST/WebSocket interface. Async methods: `get_state()`, `get_states()`, `call_service()`, `set_state()`, `fire_event()`.

**StateManager** (`src/hassette/state_manager/`) - State access and caching with type conversion. Supports domain access (`self.states.light`), generic access (`self.states[CustomState]`), and direct entity lookup (`self.states.get("light.kitchen")`).

### Event Handling Modules

Located in `src/hassette/event_handling/`:
- `predicates.py` (aliased as `P`) - Event matching predicates
- `conditions.py` (aliased as `C`) - Value comparison conditions
- `accessors.py` (aliased as `A`) - Field extraction helpers
- `dependencies.py` (aliased as `D`) - Dependency injection

### Type Conversion Registries

- `STATE_REGISTRY` - Maps Home Assistant entity types to Python model classes
- `TYPE_REGISTRY` - Maps scalar types for field conversion

### Resource Hierarchy

`Resource` (`src/hassette/resources/base.py`) is the base class for app components (Bus, Scheduler, Api, StateManager). `Service` extends it for background services. Both have lifecycle hooks and child resource tracking with priority-based initialization/shutdown.

## App Pattern

```python
class MyConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="my_")
    setting_name: str = "default"

class MyApp(App[MyConfig]):
    async def on_initialize(self):
        self.bus.on_state_change("light.kitchen", handler=self.on_light_change)
        self.scheduler.run_in(self.my_task, 5)

    async def on_light_change(self, event: RawStateChangeEvent):
        pass
```

## E2E Tests (Playwright)

Browser-based tests live in `tests/e2e/` and are excluded from default `pytest` runs via the `e2e` marker.

```bash
# Install browser (one-time setup — requires sudo for system deps)
uv run playwright install --with-deps chromium

# Run e2e tests
uv run pytest -m e2e -v

# Debug with headed browser
uv run pytest -m e2e --headed

# Single test with trace
uv run pytest -m e2e --headed --tracing on -k test_sidebar_navigation
```

System dependencies for Chromium require `sudo`. If `playwright install --with-deps` fails, run `sudo uv run playwright install-deps chromium` manually.

## Code Style

- Line length: 120 characters
- Type hints everywhere
- Google-style docstrings
- Ruff for linting/formatting, Pyright for type checking
- Do NOT use `from __future__ import annotations` — this project uses runtime type evaluation
