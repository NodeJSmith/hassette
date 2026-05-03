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

Services declare a `restart_spec` class attribute (`RestartSpec`) that controls supervision behavior: restart type (`PERMANENT`, `TRANSIENT`, or `TEMPORARY`), sliding-window budget (intensity + period), backoff parameters, and error routing (fatal vs. non-retryable error names). The `ServiceWatcher` reads this spec when a service fails.

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

## Pre-Ship Verification for Core Changes

When a branch modifies core service infrastructure — files in `src/hassette/core/`, `src/hassette/resources/`, or `src/hassette/types/enums.py` — run the system and e2e test suites locally before pushing the PR, in addition to the standard unit/integration tests:

```bash
# System tests (requires Docker — validates WS, reconnection, service lifecycle)
uv run nox -s system

# E2E tests (requires Playwright — validates frontend against real backend)
uv run nox -s e2e
```

These suites run with the same warning configuration as CI (`filterwarnings` in `pyproject.toml`). Unit and integration tests alone are insufficient for core changes — they mock the very boundaries where regressions hide.

### Run fixed tests before committing

When fixing or modifying any test, run that test locally and confirm it passes before committing. For system and e2e tests, use the nox sessions above. For unit/integration tests, run at minimum the affected test file. Do not commit test fixes based on code inspection alone — a test that looks correct can still fail due to marker filtering, warning configuration, fixture scoping, or async timing.

## GitHub Issues

### Title Conventions

- Plain imperative description: "Add timeout logic for scheduler"
- No type prefixes — labels convey type, not the title
- Bad: `[Bug] App reload broken`, `Feature - add States resource`, `Bug: file watcher crashes`
- Good: `Fix app reload on config change`, `Add States resource proxy`, `Prevent file watcher crash on missing file`

### Required Labels

Every issue should have:

1. **Type label** (exactly one): `type:bug`, `type:enhancement`, `type:documentation`, `type:CICD`
2. **Area label** (at least one, unless cross-cutting):
   - `area:api` — HA REST/WebSocket API
   - `area:apps` — App lifecycle / AppHandler
   - `area:bus` — Event bus
   - `area:config` — Configuration / settings
   - `area:core` — Internal framework plumbing, not necessarily user-facing
   - `area:database` — Telemetry DB schema, migrations, retention
   - `area:scheduler` — Scheduler service
   - `area:testing` — Test infrastructure, coverage, test helpers
   - `area:ui` — Web UI / dashboard
   - `area:websocket` — WebSocket service
3. **Size label** (one): `size:small` (< 1 hour), `size:medium` (a few hours), or `size:large` (significant effort)

### Optional Labels

Apply when clearly warranted:

- **Priority**: `priority:high` (blockers, data loss), `priority:low` (nice-to-haves)
- **Descriptors**: `good first issue`
- **Topic labels** — cross-cutting domain concerns (an issue can have multiple):
   - `topic:cli` — hassette CLI commands (init, build, migrate)
   - `topic:concurrency` — Semaphores, rate limiting, timeouts, task management
   - `topic:errors` — Error handling, retries, error display, exception design
   - `topic:events` — Event system design, signals, dispatch, filtering, backpressure
   - `topic:lifecycle` — Startup/shutdown sequences, state machines, readiness, cleanup
   - `topic:telemetry` — Observability, invocation/execution tracking, retention, statistics
- **Epic labels** — initiative-level grouping:
   - `epic:ha-addon` — Home Assistant add-on and monitoring UI initiative
   - `epic:hacs` — Custom integration for persistent entities/services
- **Release labels** — release gates:
   - `release:v1.0.0` — Must ship before 1.0 release

### Required Body Sections

Every non-bug issue (e.g., feature requests, tasks) must have at minimum:
- **Description** — what and why
- **Acceptance Criteria** — checklist of done conditions

Bug reports should instead focus on: Steps to Reproduce, Expected Behavior, Actual Behavior, and version info. Acceptance criteria for bug fixes may be captured later during triage or in follow-up tasks.

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

## Mermaid Diagram Color Scheme

All Mermaid diagrams in `docs/` use a consistent color palette. Apply these when creating or modifying diagrams:

| Role | Fill | Stroke | Use for |
|---|---|---|---|
| **User-facing** | `#e8f0ff` | `#6688cc` | App code, per-app resources, browser |
| **Data / services** | `#f0f8e8` | `#88aa66` | Data sources, caches, routing |
| **Framework internals** | `#fff0e8` | `#cc8844` | Shared services, transport, dispatch |
| **Per-app resources** | `#f8f0ff` | `#8866cc` | When distinguishing per-app from shared |
| **External / neutral** | `#f0f0f0` | `#999` | Home Assistant, terminal states |
| **Error states** | `#ffe8e8` | `#cc6666` | FAILED, CRASHED |

Layout: use `flowchart TD` (top-to-bottom) by default. Use subgraphs with background colors for visual grouping. Keep node text to 1-2 lines; move details to prose or tables below the diagram.

## Code Style

- Line length: 120 characters
- Type hints everywhere
- Google-style docstrings
- Ruff for linting/formatting, Pyright for type checking
- Do NOT use `from __future__ import annotations`
- Do NOT use blanket `# type: ignore` comments — suppress specific Pyright rules inline with `# pyright: ignore[reportXxx]` instead
