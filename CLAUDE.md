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

# Start the server
hassette run

# Query a running instance
hassette status
hassette app
hassette listener --app <key> --since 1h
hassette log --app <key> --since 1h --limit 20
hassette job --json

# Instance-specific queries
hassette listener --app <key> --instance 0
hassette app health <key> --instance office
```

## Architecture

### Core Components

**Hassette** (`src/hassette/core/core.py`) - Main coordinator that connects to Home Assistant via WebSocket, manages app lifecycle, and coordinates all services.

**App** (`src/hassette/app/app.py`) - Base class for user automations. Generic over `AppConfig` type. Each app gets its own Bus, Scheduler, Api, and StateManager. Lifecycle hooks: `on_initialize`, `on_ready`, `on_shutdown`.

**Bus** (`src/hassette/bus/`) - Event pub/sub with filtering. Methods: `on_state_change`, `on_attribute_change`, `on_call_service`, `on`. All registration methods are `async` and must be awaited. `name=` is required on every DB-registered listener — omitting it raises `ListenerNameRequiredError` at call time. Supports glob patterns, predicates, conditions, debounce, throttle. The internal `Listener` dataclass composes four sub-structs: `ListenerIdentity` (ownership/telemetry fields), `ListenerOptions` (behavioral timing parameters), `HandlerInvoker` (handler invocation, dispatch, rate limiting), and `DurationConfig` (duration-hold configuration and timer lifecycle). Registration is synchronous with the DB — `sub.listener.db_id` is a valid integer immediately when the awaited call returns. `Subscription` no longer has a `registration_task` field.

**Scheduler** (`src/hassette/scheduler/`) - Task scheduling via trigger objects. Primary entry: `schedule(func, trigger)`. Convenience methods: `run_in()`, `run_once()`, `run_every()`, `run_daily()`, `run_cron()`. Trigger types: `After`, `Once`, `Every`, `Daily`, `Cron` (all in `hassette.scheduler.triggers`). Custom triggers implement `TriggerProtocol`. Supports job groups (`group=`, `cancel_group()`, `list_jobs(group=)`) and jitter (`jitter=`).

**Api** (`src/hassette/api/`) - Home Assistant REST/WebSocket interface. Async methods: `get_state()`, `get_states()`, `call_service()`, `set_state()`, `fire_event()`.

**StateManager** (`src/hassette/state_manager/`) - State access and caching with type conversion. Supports domain access (`self.states.light`), generic access (`self.states[CustomState]`), and direct entity lookup (`self.states.get("light.kitchen")`).

**LoggingService** (`src/hassette/core/logging_service.py`) - Manages the async logging pipeline lifecycle. A Resource with `depends_on=[DatabaseService]` that upgrades logging from synchronous (console-only) to asynchronous (console + capture + persistence) during `on_initialize()`. Owns the QueueListener, LogCaptureHandler, and LogPersistenceHandler. The async pipeline starts unconditionally; persistence degrades gracefully on failure.

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

`BusService` and `SchedulerService` both declare `depends_on: [DatabaseService]` — the database is guaranteed ready before any listener or job registration can occur.

## App Pattern

```python
class MyConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="my_")
    setting_name: str = "default"

class MyApp(App[MyConfig]):
    async def on_initialize(self):
        await self.bus.on_state_change("light.kitchen", handler=self.on_light_change, name="kitchen_light")
        await self.scheduler.run_in(self.my_task, 5)

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
2. **Area label** (at least one, unless cross-cutting) — which codebase module does this touch? Answers "where in the code do I look?":
   - `area:api` — HA REST/WebSocket API
   - `area:apps` — App lifecycle / AppHandler
   - `area:bus` — Event bus
   - `area:cli` — CLI commands and output (`src/hassette/cli/`)
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
- **Topic labels** — what conceptual concern is involved? Cross-cuts areas. Answers "what kind of problem is this?" (an issue can have multiple):
   - `topic:a11y` — Accessibility: focus, keyboard navigation, screen readers
   - `topic:architecture` — Module decomposition, coupling reduction, internal structure
   - `topic:cli` — hassette CLI commands (init, build, migrate)
   - `topic:codegen` — Code/type generation pipelines, typed models from HA, schema export
   - `topic:concurrency` — Semaphores, rate limiting, timeouts, task management
   - `topic:design-system` — Visual tokens, theming, color scales, typography, spacing
   - `topic:dx` — App-author developer experience: API ergonomics, convenience methods, testing helpers
   - `topic:errors` — Error handling, retries, error display, exception design
   - `topic:events` — Event system design, signals, dispatch, filtering, backpressure
   - `topic:lifecycle` — Startup/shutdown sequences, state machines, readiness, cleanup
   - `topic:responsive` — Mobile and responsive layout
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

The changelog includes `feat`, `fix`, `perf`, `refactor`, and `docs` types only. Use `chore:` for internal work (`design/`, `.claude/`, research, tooling) — it won't appear in the changelog. See `.claude/rules/changelog-quality.md` for the full guide.

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

## CSS Architecture

The frontend uses CSS Modules for component-specific styles, with a single shared `frontend/src/global.css` for the design system.

### Module pattern

Each component/page has a co-located `.module.css` file. Classes are imported and applied with `clsx`:

```tsx
import styles from "./my-component.module.css";
import clsx from "clsx";

<div class={clsx(styles.wrapper, isActive && styles.active)}>
```

### When to use styles/ vs a module vs a shared component

- **`styles/`**: Shared design system classes used across 3+ unrelated files that don't have a component wrapper. All classes use the `ht-` prefix. Organized by domain: `fonts.css`, `reset.css`, `typography.css`, `layout.css`, `tables.css`, `utilities.css`. Imported via `global.css`. Buttons, badges, chips, and cards have been migrated to shared components (see below).
- **Shared components** (`components/shared/`): `Button`, `Badge`, `Chip`, and `Card` are reusable components with co-located `.module.css` files. Use these instead of raw `ht-btn`, `ht-badge`, `ht-chip`, or `ht-card` class strings. Import and use via props (e.g., `<Button variant="ghost" size="sm">`, `<Badge variant="danger" size="sm">`).
- **`.module.css`**: Everything else — component-specific layout, state variants, animations tied to a single component.

### Referencing global classes from module CSS

Use `:global()` to target global classes from within a module:

```css
/* Scope a global class to this component's context */
.tableWrapper :global(.ht-table) tbody tr:hover { background: var(--bg-sunken); }

/* Global class as an ancestor condition */
:global(.ht-main) > .alert { margin-top: 0; }
```

Do NOT use bare class names (`.ht-table`) in module CSS — they will be scoped and broken at runtime.

### CI guards

Three scripts enforce CSS hygiene, all wired into `.github/workflows/lint.yml`:

- **`tools/check_global_css_allowlist.py`** — blocks any `.ht-*` selector not on the allowlist from entering shared CSS (`styles/*.css`). Run locally: `uv run python tools/check_global_css_allowlist.py`. Add new shared prefixes to `ALLOWLIST` in that file.
- **`tools/check_dead_global_css.py`** — blocks unreferenced class selectors in shared CSS (`styles/*.css`). Run locally: `uv run python tools/check_dead_global_css.py`. Add dynamically-assembled class prefixes to `EXEMPTIONS` in that file.
- **`tools/check_css_module_globals.py`** — validates that `:global()` usage in module CSS is correct.
- **`tools/check_undefined_css_refs.py`** — blocks raw `ht-*` class references in TSX that have no matching CSS definition in `global.css` or `styles/*.css`. The inverse of the dead-CSS checker. Run locally: `uv run python tools/check_undefined_css_refs.py`. Add false positives (ARIA IDs, test selectors, JS-only classes) to `EXEMPTIONS` in that file.

### Adding a new shared class

For classes that don't warrant a component (layout utilities, typography helpers):

1. Confirm it is used in 3+ unrelated files (not just BEM descendants of one component)
2. Add it to the appropriate file in `frontend/src/styles/`
3. Add its prefix to `ALLOWLIST` in `tools/check_global_css_allowlist.py`
4. Run `uv run python tools/check_global_css_allowlist.py` to verify

For new reusable visual elements (like buttons, badges), create a shared component with a co-located `.module.css` file in `components/shared/` instead of adding global classes.

### tokens.css

`frontend/src/tokens.css` contains all design tokens (colors, spacing, typography, radii, z-index). Do not add raw hex or pixel values to `global.css` — always reference a token variable. Do not modify `tokens.css` during CSS refactoring work.
