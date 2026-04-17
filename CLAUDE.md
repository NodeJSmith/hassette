# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Hassette is an async-first Python framework for building Home Assistant automations. It emphasizes type safety (Pydantic models), dependency injection (FastAPI-style), and async/await patterns. Python 3.11+ required.

## Common Commands

```bash
# Install dependencies
uv sync

# Run tests locally (preferred for development)
uv run nox -s dev

# Run tests via nox (CI — tests across Python 3.11, 3.12, 3.13)
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

**Bus** (`src/hassette/bus/`) - Event pub/sub with filtering. Methods: `on_state_change`, `on_attribute_change`, `on_call_service`, `on`. Supports glob patterns, predicates, conditions, debounce, throttle.

**Scheduler** (`src/hassette/scheduler/`) - Task scheduling via trigger objects. Primary entry: `schedule(func, trigger)`. Convenience methods: `run_in()`, `run_once()`, `run_every()`, `run_daily()`, `run_cron()`. Trigger types: `After`, `Once`, `Every`, `Daily`, `Cron` (all in `hassette.scheduler.triggers`). Custom triggers implement `TriggerProtocol`. Supports job groups (`group=`, `cancel_group()`, `list_jobs(group=)`) and jitter (`jitter=`).

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

## Bug Investigation Workflow (TDD)

When investigating a crash or regression, follow this sequence before writing any fix:

1. **Reproduce first** — confirm the bug is real and understand what triggers it (logs, crash output, minimal repro)
2. **Write a failing test** — write a test that captures the exact failure mode; run it and confirm it fails (RED)
3. **Fix the code** — write the minimal change that makes the test pass (GREEN)
4. **Verify** — run the full test file to ensure no regressions; check the new test passes and existing tests still pass

This discipline matters most for startup races, timing bugs, and subtle state issues — categories where "it seemed to work" is not trustworthy evidence.

### Regression test patterns for this project

**Startup races** — use `asyncio.Event` as a gate to simulate a dependency not yet ready:
```python
gate = asyncio.Event()
mock_service.wait_for_ready = AsyncMock(side_effect=lambda _: gate.wait())
task = asyncio.create_task(executor.register_listener(...))
await asyncio.sleep(0)         # let the task run until it blocks on gate
assert not task.done()         # confirms the gate is actually blocking it
gate.set()
await task
assert result > 0              # confirms registration succeeded after unblocking
```

**Sentinel filtering** — verify that records with unregistered IDs (listener_id=0, job_id=0, session_id=0) are silently dropped and not written to the database.

**Error isolation** — confirm that exceptions raised inside `execute()` do not propagate out of the method; the caller (TaskBucket) must not crash.

## Test Infrastructure

Two mock strategies serve different testing needs. See `tests/TESTING.md` for the full guide, decision table, and code examples.

- **`HassetteHarness`** — wires real components (bus, scheduler, state proxy) for integration tests
- **`create_hassette_stub()`** — builds a MagicMock stub for web/API tests (HTTP, HTML, WebSocket)

## E2E Tests (Playwright)

Browser-based tests live in `tests/e2e/` and run as part of the default `pytest` suite. Playwright and Chromium must be installed first.

```bash
# Install browser (one-time setup — requires sudo for system deps)
uv run playwright install --with-deps chromium

# Run e2e tests via nox (used by CI)
uv run nox -s e2e

# Run e2e tests only (useful with xdist: -n auto for parallelism)
uv run pytest -m e2e -v -n auto

# Debug with headed browser
uv run pytest -m e2e --headed

# Single test with trace
uv run pytest -m e2e --headed --tracing on -k test_sidebar_navigation
```

System dependencies for Chromium require `sudo`. If `playwright install --with-deps` fails, run `sudo uv run playwright install-deps chromium` manually.

## GitHub Issues

### Title Conventions

- Plain imperative description: "Add timeout logic for scheduler"
- No type prefixes — labels convey type, not the title
- Bad: `[Bug] App reload broken`, `Feature - add States resource`, `Bug: file watcher crashes`
- Good: `Fix app reload on config change`, `Add States resource proxy`, `Prevent file watcher crash on missing file`

### Required Labels

Every issue should have:

1. **Type label** (exactly one): `bug`, `enhancement`, `documentation`, `CICD`, `tests`
2. **Area label** (at least one, unless cross-cutting):
   - `area:ui` — Web UI / dashboard
   - `area:websocket` — WebSocket service
   - `area:scheduler` — Scheduler service
   - `area:bus` — Event bus
   - `area:api` — HA REST/WebSocket API
   - `area:config` — Configuration / settings
   - `area:apps` — App lifecycle / AppHandler
3. **Size label** (one): `size:small` (< 1 hour, quick win) or `size:large` (significant effort)

Optional labels applied when clearly warranted:
- `priority:high` — security issues, blockers, data loss risks
- `priority:low` — nice-to-haves, cosmetic
- `core` — internal framework plumbing, not user-facing
- `dx` — improves developer experience
- `good first issue` — suitable for newcomers

### Required Body Sections

Every non-bug issue (e.g., feature requests, tasks) must have at minimum:
- **Description** — what and why
- **Acceptance Criteria** — checklist of done conditions

Bug reports should instead focus on: Steps to Reproduce, Expected Behavior, Actual Behavior, and version info. Acceptance criteria for bug fixes may be captured later during triage or in follow-up tasks.

### Milestones

Every open issue must be assigned to a milestone:
- **Stability** — stable API and usability, aligned with 1.0.0
- **HA Addon and UI** — Add-on for HA + monitoring UI
- **HACS Integration** — custom integration for persistent entities/services
- **Enhancements** — DX improvements and nice-to-have features

### Issue Templates

YAML form templates in `.github/ISSUE_TEMPLATE/` enforce structure:
- `bug_report.yml` — required fields for reproduction
- `feature_request.yml` — required description and motivation
- `task.yml` — internal work items with acceptance criteria
- `config.yml` — disables blank issues, points questions to Discussions

## Design Artifacts

Internal design documents live in `design/`, not in `docs/` (which is the readthedocs site).

- **`design/adrs/`** — Architecture Decision Records. One per significant technical decision. Numbered sequentially (`001-short-name.md`). Created when a direction is chosen, not while still exploring.
- **`design/audits/`** — Design and architecture audits, reviews, and post-hoc evaluations of existing decisions or implementations.
- **`design/interface-design/`** — Design system specification (tokens, layout, component patterns) for the web UI.
- **`design/research/`** — Feasibility analysis and implementation planning. Organized as `YYYY-MM-DD-topic-name/` subfolders containing a main `research.md` brief and optional prereq breakdowns.

See `design/README.md` for the full guide on what goes where.

## Changelog

**Do NOT manually edit `CHANGELOG.md`.** This repo uses [release-please](https://github.com/googleapis/release-please) to generate the changelog automatically from conventional commit messages. Manual edits will conflict with release-please's PR and get overwritten.

The changelog is derived entirely from commit types (`feat`, `fix`, `perf`, etc.) — write good commit messages and the changelog takes care of itself.

## Code Style

- Line length: 120 characters
- Type hints everywhere
- Google-style docstrings
- Ruff for linting/formatting, Pyright for type checking
- Do NOT use `from __future__ import annotations`
- Do NOT use blanket `# type: ignore` comments — suppress specific Pyright rules inline with `# pyright: ignore[reportXxx]` instead
