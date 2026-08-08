---
audience: open-source library
developers: solo
data-sensitivity: personal
---

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

# Run tests with coverage (see ## Coverage section below for why NOT pytest --cov)
uv run nox -s tests_with_coverage

# Run tests with coverage (frontend)
cd frontend && npm run test:coverage

# Run a single test file
uv run pytest tests/integration/test_api.py

# Run a specific test
uv run pytest tests/integration/test_api.py::test_function_name -v

# Lint + type check (all prek hooks)
prek -a

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

# Seed a telemetry database for dev/QA
uv run python scripts/seed_db.py --scenario healthy --output /tmp/hassette-healthy.db
```

`seed_db.py` generates a deterministic SQLite telemetry database for one of 7 named
scenarios — useful for frontend QA, CLI doc generation, visual regression screenshots, and
demos that need the monitoring dashboard in a specific state without waiting on a live Home
Assistant instance. Available scenarios: `healthy`, `empty`, `degraded`, `error`,
`large-volume`, `lifecycle`, `adversarial`. Running the script twice for the same scenario
produces identical database content. See `design/specs/017-seed-db/design.md` for the full
design.

## Architecture

### Core Components

**Hassette** (`src/hassette/core/core.py`) - Main coordinator that connects to Home Assistant via WebSocket, manages app lifecycle, and coordinates all services.

**App** (`src/hassette/app/app.py`) - Base class for user automations. Generic over `AppConfig` type. Each app gets its own Bus, Scheduler, Api, and StateManager. Lifecycle hooks: `on_initialize`, `on_shutdown`.

**Bus** (`src/hassette/bus/`) - Event pub/sub with filtering. Methods: `on_state_change`, `on_attribute_change`, `on_call_service`, `on`. All registration methods are `async` and must be awaited. `name=` is required on every DB-registered listener — omitting it raises `ListenerNameRequiredError` at call time. Supports glob patterns, predicates, conditions, debounce, throttle. The internal `Listener` dataclass composes four sub-structs: `ListenerIdentity` (ownership/telemetry fields), `ListenerOptions` (behavioral timing parameters), `HandlerInvoker` (handler invocation, dispatch, rate limiting), and `DurationConfig` (duration-hold configuration and timer lifecycle). Registration is synchronous with the DB — `sub.listener.db_id` is a valid integer immediately when the awaited call returns. `Subscription` no longer has a `registration_task` field.

**Scheduler** (`src/hassette/scheduler/`) - Task scheduling via trigger objects. Primary entry: `schedule(func, trigger)`. Convenience methods: `run_in()`, `run_once()`, `run_every()`, `run_daily()`, `run_cron()`. Trigger types: `After`, `Once`, `Every`, `Daily`, `Cron` (all in `hassette.scheduler.triggers`). Custom triggers implement `TriggerProtocol`. Supports job groups (`group=`, `remove_group()`, `list_jobs(group=)`) and jitter (`jitter=`).

**Api** (`src/hassette/api/`) - Home Assistant REST/WebSocket interface. Async methods: `get_state()`, `get_states()`, `call_service()`, `set_state()`, `fire_event()`. `Api.helpers` returns a `HelperClient` (`src/hassette/api/helpers.py`) — the single entry point for CRUD on HA helper entities (`input_boolean`, `input_number`, `input_text`, `input_select`, `input_datetime`, `input_button`, `counter`, `timer`). `HelperClient` exposes 4 generic methods (`list`, `create`, `update`, `delete`) with hand-maintained `@overload` declarations per domain for full type safety, plus 3 counter shortcuts (`increment`, `decrement`, `reset`).

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

`BusService` and `SchedulerService` both declare `depends_on: [DatabaseService, SyncExecutorService]` — the database is guaranteed ready before any listener or job registration can occur. `AppBootstrapCoordinator` also declares `SyncExecutorService` in its `depends_on` (see below), which transitively keeps it available to app instances by the time `AppHandler` bootstraps them; the dedicated sync-handler executor (`SyncExecutorService`) outlives every component that submits sync work (Bus, Scheduler, and the App lifecycle hooks), so it is torn down only after them at shutdown. `SyncExecutorService` (`src/hassette/core/sync_executor_service.py`) is a thin lifecycle wrapper around `SyncExecutor` (`src/hassette/core/sync_executor.py`), a plain capability class — no `Resource`/`Service` base — that owns the thread pool and is constructed in `Hassette.__init__()` before the Resource lifecycle starts, so every `TaskBucket` has a working sync executor from birth.

`WebsocketService` marks itself lifecycle-ready unconditionally in `on_initialize()`, before `serve()` ever attempts a connection — lifecycle readiness ("the service is running") is intentionally decoupled from HA connection status. `ConnectionState.CONNECTED` (exposed via `is_connected`) has exactly one meaning — "external readiness": authentication succeeded, the receive loop is running, and Home Assistant confirmed the HA event subscription. A private, non-public send-capability event opens earlier (after auth, before the subscription confirms) so `WebsocketService` can send setup traffic like `subscribe_events` through `send_json()` without exposing premature external readiness to the rest of the framework. Each transition into external readiness gets a monotonically increasing connection generation (`get_connected_generation()` / `wait_connected_generation()`); a disconnect invalidates that generation without decrementing or reusing it, so `StateProxy` can reject synchronization work that belongs to a superseded connection. Because `WebsocketService`'s own lifecycle readiness never implies HA connectivity, `ApiResource.depends_on` is empty and `StateProxy.depends_on` is `[ApiResource, BusService, SchedulerService]` — neither lists `WebsocketService`. `RuntimeQueryService.get_system_status()` reads `ws.is_connected` (current) together with `has_ever_connected` (latch, never reverts) and `AppBootstrapCoordinator.is_released()` (`bootstrap_released`) to report "starting" (never connected), "ok" (currently connected AND bootstrap released), or "degraded" for every other case that has connected at least once — including a currently-live connection where bootstrap hasn't released yet, not just a connection that was live and is now lost.

`AppBootstrapCoordinator` (`src/hassette/core/app_bootstrap_coordinator.py`) is the single authoritative decision point for "may apps start?" It is a `Resource`, not a `Service` — no serve loop, no restart policy, no continuous enforcement. Its `depends_on` is the complete app-facing prerequisite set: `[ApiResource, BusService, SchedulerService, StateProxy, SyncExecutorService]`. Once that ordinary dependency wait completes it marks its own Resource readiness — so the finite startup wave finishes even without Home Assistant — then waits in background work for `StateProxy.wait_initial_state_capability()`. Only when that capability resolves does it open a separate, process-latched release (`wait_released()` / `is_released()`). That latch, not Resource readiness, means "apps may initialize code": it opens once, never re-closes on a later runtime disconnect, and framework shutdown cancels any outstanding wait so teardown is never delayed by a Home Assistant that never connects. `AppHandler.depends_on` is `[AppBootstrapCoordinator]` only — it does not compose the app-facing resource list itself. Every app-creation path funnels through `AppLifecycleService.start_app()`'s admission check: the initial bulk bootstrap uses `AppAdmissionMode.WAIT_FOR_RELEASE` (the one path allowed to await the latch), while manual HTTP start/reload use `AppAdmissionMode.REJECT_IF_UNRELEASED`, which raises `AppBootstrapNotReleasedError` (mapped to HTTP 409) instead of waiting. Config-change and file-watcher reconciliation that arrives before release does not retain a waiting task either — `AppLifecycleService` coalesces repeated pre-release changes into one latest desired-state record and replays it once after release opens.

`StateProxy`'s own Resource readiness means only "the synchronization coordinator is wired," not that Home Assistant data is usable. A separate `has_initial_state_capability()` / `wait_initial_state_capability()` pair — the one `AppBootstrapCoordinator` waits on — resolves only after the current externally-ready generation's initial snapshot has loaded, its Resource-lifetime state-change listener has journaled any events observed concurrently, and one generation-fenced commit has applied both. A failed or never-attempted initial snapshot never opens this capability, so app bootstrap stays blocked indefinitely while `StateProxy` keeps retrying (through the next scheduled poll, or through one coalesced generation-scoped retry timer when polling is disabled or hasn't started yet) — this is deliberate: the framework does not permit degraded app bootstrap against an unavailable state cache. Once initial capability has been reached at least once, a later runtime disconnect marks the cache `STALE` rather than `UNAVAILABLE` (see `StateCacheFreshness`), preserving stale reads for already-running apps without re-blocking `AppBootstrapCoordinator` — the coordinator's release is a one-time decision, not continuous enforcement, so a lost connection after bootstrap never stops or suspends running apps.

Together this means the dashboard and app bootstrap no longer share one readiness signal. When Home Assistant is unreachable at startup, `WebApiService` still reaches ready and serves — `RuntimeQueryService.depends_on` excludes `AppHandler`, so registry metadata (manifests, the `--app` filter) stays queryable and `get_system_status()` reports `app_count=0` — while every app instance remains unbootstrapped until Home Assistant reaches external readiness and an initial snapshot commits. Health stays `starting` for the whole time HA has never connected; there is no dedicated "apps pending" status or richer lifecycle phase beyond the existing `starting` / `degraded` / `ok` mapping.

Lifecycle state transitions (`handle_starting`, `handle_running`, `handle_stop`, `handle_failed`, `handle_crash`, `mark_ready`, `mark_not_ready`, `request_shutdown`, `start`, `cancel`, `create_service_status_event`) and structural operations (`start_children_and_wait`, `restart`, `register_task_bucket_factory`, `run_hooks`, `ordered_children_for_shutdown`) are module-level functions in `src/hassette/resources/lifecycle.py` and `src/hassette/resources/operations.py`, not methods on `Resource`/`LifecycleMixin`. They take the resource as their first argument (e.g. `mark_ready(self, reason="initialized")`) — this keeps the names out of `App`'s public surface (see `App.__dir__`) since they are framework plumbing, not app-author API. `is_ready`, `wait_ready`, and `add_child` remain methods on `Resource`.

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

**Startup races** — gate a dependency with `asyncio.Event`, and have the mock signal a second
event the instant it's awaited. Wait on that signal before asserting the task is blocked. This is
deterministic; do **not** use `await asyncio.sleep(0)` to "let the task reach the block" — a single
scheduler tick races the code under test and the assertion passes or fails by luck.
```python
gate = asyncio.Event()
entered = asyncio.Event()

async def blocked_wait(_):
    entered.set()             # signal the moment the dependency is awaited
    await gate.wait()

mock_service.wait_for_ready = AsyncMock(side_effect=blocked_wait)
task = asyncio.create_task(executor.register_listener(...))
await asyncio.wait_for(entered.wait(), timeout=1)  # deterministic: task reached the block
assert not task.done()                             # confirms the gate is actually blocking it
gate.set()
result = await task
assert result > 0                                  # confirms registration succeeded after unblocking
```

**Config-driven real-clock timeouts** — a test that overrides a production timeout config (e.g.
`websocket.total_timeout_seconds`) races that value in real wall-clock time against any deliberate
delay in the same test — an `asyncio.wait_for(..., timeout=1)` wrapped in
`pytest.raises(TimeoutError)` to prove something hasn't happened yet, an `asyncio.sleep()`, or
scheduling overhead. The two are independent real-time clocks the test author rarely reasons about
together; CI's noisier scheduling is what finally exposes the collision, so it passes locally for
months. This happened: `test_app_bootstrap_waits_for_first_websocket_connection_and_state_sync` set
`total_timeout_seconds=2` for speed while a nested `asyncio.wait_for(..., timeout=1)` deliberately
held ~1 real second to prove state wasn't loaded early — under a second of margin, which CI jitter
eventually ate.

Reproduce by driving the overridden timeout down far enough to fail on any machine (e.g. `0`),
confirm the failure signature matches CI, then widen the override to give the deliberate real-time
hold generous headroom. The plain Pydantic field default is usually the right value to reuse (here,
`HassetteConfig`'s `total_timeout_seconds` default of 30) — not because it happens to match, but
because it's already the value the framework considers "give this operation a reasonable real-world
chance to finish," which is exactly the property the test needs too. Do not "fix" it by shrinking
the competing delay instead — the delay is the thing under test.

**Sentinel filtering** — verify that records with unregistered IDs (listener_id=0, job_id=0, session_id=0) are silently dropped and not written to the database.

**Error isolation** — confirm that exceptions raised inside `execute()` do not propagate out of the method; the caller (TaskBucket) must not crash.

## Coverage

Do **not** use `pytest --cov` for backend coverage — it under-reports by 15-40 percentage points. See `tests/TESTING.md` (Coverage Measurement) for the full explanation. Use the nox coverage sessions instead (see Common Commands above).

Both backend and frontend enforce an 80% floor — backend via `fail_under` in `pyproject.toml`, frontend via `thresholds` in `vitest.config.ts`. Codecov's `target: auto` additionally catches per-PR regressions.

### Comparing coverage between branch and main

Don't run full coverage suites locally to compare — download the `coverage-xml` artifact from CI instead:

```bash
# Find the CI run IDs
gh run list --branch 1285 --workflow tests.yml --status success --limit 1 --json databaseId -q '.[0].databaseId'
gh run list --branch main --workflow tests.yml --status success --limit 1 --json databaseId -q '.[0].databaseId'

# Download both
gh run download <branch-run-id> -n coverage-xml -D /tmp/branch-cov
gh run download <main-run-id> -n coverage-xml -D /tmp/main-cov
```

Then diff the two `coverage.xml` files (standard Cobertura format) to find which files gained or lost hits.

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

## Demo Stack & Doc Screenshots

### Live demo stack (visual QA)

For visual/UI work, run the demo stack — **not** the e2e mock server. It starts a real HA container + Hassette (with the example apps) + a Vite dev server with hot reload, so you see real behavior and CSS/TSX edits apply live.

```bash
# One-command live UI (requires Docker Compose; ~60-90s to come up)
mise run demo            # or: uv run python scripts/hassette_demo.py
```

`hassette_demo.py` is a thin wrapper around `scripts/demo_stack.py`'s `DemoStack` context manager — it starts all three services (HA, hassette, Vite) via `docker compose up -d --wait`, prints their URLs, and blocks until signaled. Ports are fixed by default (HA `18123`, hassette `18126`, Vite `15173`) and overridable via `DEMO_HA_PORT`, `DEMO_HASSETTE_PORT`, `DEMO_VITE_PORT`. Stop the process (Ctrl-C or SIGTERM) to tear the stack down — `docker compose down --remove-orphans` cleans up all containers. `mise run demo-verify` does a non-interactive health check (all apps reach running, listeners registered) by polling the configured hassette health endpoint.

Gotchas:
- **Stale app code:** reloading a *failed* app via the REST API reuses the stale module — after editing app code, restart the whole stack.
- **Stale telemetry:** `.demo-data/` persists between runs. If the dashboard shows old errors or inflated counts, stop the stack, `rm -rf .demo-data`, and restart.

### Regenerating doc screenshots

The docs site embeds `docs/_static/web_ui_*.png`. These are generated, not hand-captured. `docs/screenshots.yml` is the single source of truth — adding a screenshot needs only a manifest entry, no script change. The capture tool starts its own demo stack, so Docker + Playwright + shot-scraper (`uv sync --group dev`) must be available.

```bash
# Regenerate all doc screenshots
uv run python scripts/capture_screenshots.py

# Regenerate only matching outputs (faster) — substring match on the output filename
uv run python scripts/capture_screenshots.py --only web_ui_apps,web_ui_config
```

Workflow for a new screenshot:
1. Add an entry to `docs/screenshots.yml` (URL path, output filename, optional `selector` crop and `wait_for` gate). Always crop via `data-testid` — CSS module classes are hashed at build time and can't be selected here.
2. Embed `![alt](../../_static/web_ui_<name>.png)` in the relevant `docs/pages/` page.
3. Run the capture tool (scope with `--only`).

Some UI states need demo setup before they render. The "no autostart" chip, for example, only appears for an app with `autostart = false`, so `examples/hassette.toml` configures one (`cover_scheduler`) to make that state capturable.

After a UI change that alters a view documented with a screenshot, regenerate the affected `web_ui_*.png` (scope with `--only`). This is the mechanism behind the PR visual-evidence requirement in `.claude/rules/design-completeness.md`.

## Pre-Ship Verification for Core Changes

When a branch modifies core service infrastructure — files in `src/hassette/core/`, `src/hassette/resources/`, or `src/hassette/types/enums.py` — the system and e2e suites are the real safety net: unit and integration tests mock the very boundaries where these regressions hide. **CI runs both on every push/PR** — `nox -s system_with_coverage` (`.github/workflows/tests.yml`) and `nox -s e2e` (`.github/workflows/e2e-tests.yml`) — so you do **not** need to run them locally before pushing. The local dev gate for a core change is the cheaper set: the unit/integration suite, lint (`prek -a` — runs ruff, pyright, and all other prek hooks), and the schema-freshness check.

Run the heavy suites locally only when you want a faster signal on a core change you're actively debugging:

```bash
# System tests (requires Docker — validates WS, reconnection, service lifecycle)
uv run nox -s system

# E2E tests (requires Playwright — validates frontend against real backend)
uv run nox -s e2e
```

These suites run with the same warning configuration as CI (`filterwarnings` in `pyproject.toml`).

### Run fixed tests before committing

When fixing or modifying any test, run that test locally and confirm it passes before committing. For unit/integration tests, run at minimum the affected test file. If you actually modified a system or e2e test, verify it with the nox sessions above (or rely on CI, which runs both) — don't commit test fixes based on code inspection alone, since a test that looks correct can still fail due to marker filtering, warning configuration, fixture scoping, or async timing.

## Pre-Ship Verification for Docs Changes

When a branch adds or edits docs-site pages under `docs/pages/`, run both doc-review skills on the touched pages before opening the PR — `doc-persona-review` (followability) and `doc-accuracy-review` (prose-vs-code truth). Scope each run to the changed page slugs. A `lost`/`stuck-at-step-N` persona verdict, or a confirmed `WRONG`/`OUTDATED_API` accuracy finding, on lines you touched is a ship blocker. See `.claude/rules/doc-rules.md` (Verify with Persona and Accuracy Reviews) for scope and verdict details.

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
- **Topic labels** — what conceptual concern is involved? Cross-cuts areas. Answers "what kind of problem is this?" (an issue can have multiple — except `topic:architecture`/`topic:code-quality`, which are mutually exclusive; see below):
   - `topic:a11y` — Accessibility: focus, keyboard navigation, screen readers
   - `topic:architecture` — Module decomposition, coupling reduction, internal structure. Mutually exclusive with `topic:code-quality` — see `.claude/rules/clean-code-findings.md` for the dividing line
   - `topic:cli` — hassette CLI commands (init, build, migrate)
   - `topic:code-quality` — Pre-existing mechanical/hygiene findings (naming, duplication, dead code) surfaced by `/mine-clean-code`. Mutually exclusive with `topic:architecture` — see `.claude/rules/clean-code-findings.md`
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
- **`design/context.md`** — Durable design direction: users, visual baseline, principles, semantic roles, layout behavior, and anti-patterns. Read by all i-* design skills as the canonical design context; implementation mechanics belong in `CLAUDE.md` and the frontend source.
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
- Ruff for linting/formatting, Pyright for type checking — run all checks at once with `prek -a`
- Do NOT use `from __future__ import annotations`
- Do NOT use blanket `# type: ignore` comments — suppress specific Pyright rules inline with `# pyright: ignore[reportXxx]` instead

## CSS Architecture

The frontend uses Tailwind CSS v4 via `@tailwindcss/vite` as the styling system. Tailwind Preflight is enabled through `@import "tailwindcss"` in `frontend/src/global.css`, which is the single CSS entry point for theme registration, token definitions, base element styles, and any rare shared component-layer rules. The only other CSS file is `frontend/src/styles/fonts.css`, imported by `global.css` for self-hosted `@font-face` declarations.

`global.css` owns both Hassette source tokens (`--bg-page`, `--ink-1`, spacing, typography, status colors, z-index values) and shadcn-compatible aliases (`--background`, `--foreground`, `--primary`, `--border`, `--muted-foreground`, etc.). New code should reference the shadcn-named tokens where possible so custom markup and shadcn/ui primitives read the same design roles. Custom Tailwind screens are registered in `@theme inline` for the project's non-standard breakpoints: `tablet` 1024px, `sidebar` 900px, `mobile` 768px, and `small-mobile` 480px.

One aliasing detail matters enough to call out explicitly: shadcn's `--accent` is a subtle highlighted-background role (hover/active row state), a different concept from Hassette's pre-existing `--accent` custom property, which means the brand/action color. Instead:
- Hassette's brand color continues to be `--accent` and is additionally exposed to shadcn components as `--primary` (`oklch(0.5 var(--accent-chroma) var(--accent-hue))`), which shadcn's own button/badge/etc. variants read.
- shadcn's highlighted-background role is exposed under a new, non-colliding property, `--highlight-bg` (mapped to `--bg-active`), never under the literal name `--accent`.

See `global.css`'s `:root` block (the comment above the shadcn variable aliases) for the full mechanism if extending this further.

### Component Styling

Use Tailwind utilities directly in JSX. Compose conditional class names with `cn()` from `@/lib/utils`; do not import `clsx` directly and do not add CSS Modules.

```tsx
import { cn } from "@/lib/utils";

<div className={cn("rounded-md border border-border p-4", isActive && "bg-[var(--highlight-bg)]")}>
```

Use arbitrary values for project tokens that do not have a named Tailwind utility, for example `text-[var(--handler-job)]`, `max-w-[var(--size-content-narrow)]`, or `z-[var(--z-status-bar-layer)]`. Do not use `@apply`; if a pattern is too awkward for inline utilities and is genuinely shared, put a small named rule in `@layer components` in `global.css`.

### shadcn Components

`components.json` configures the New York style with `@/components/ui` as the component directory, which holds the shadcn primitives: `button.tsx`, `badge.tsx`, `card.tsx`, `tooltip.tsx`, `dialog.tsx`, `alert-dialog.tsx`, `popover.tsx`, `command.tsx`, `drawer.tsx`, `table.tsx`.

Use these primitives instead of rebuilding standard controls with raw markup: `import { Button } from "@/components/ui/button"`, `<Button variant="ghost" size="sm">`, `<Badge variant="danger" size="sm">`. Their tests remain co-located in `components/shared/` (e.g. `components/shared/button.test.tsx` imports from `@/components/ui/button`) rather than moving alongside the `ui/` source, matching shadcn's convention of treating `components/ui/` as vendored/generated primitives.

### CI guards

Two frontend CSS hygiene scripts remain in `tools/frontend/` and are wired into the frontend prek group:

- **`tools/frontend/check_breakpoint_drift.py`** — validates that JS breakpoint constants in `use-media-query.ts` match the Tailwind screen registrations in `global.css`.
- **`tools/frontend/check_dead_tokens.py`** — scans `global.css` for unused CSS custom properties.

There are no CSS Modules, no `ht-*` global utility classes, and no separate `tokens.css` file.
