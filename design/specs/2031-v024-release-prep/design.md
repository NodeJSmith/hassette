# Design: v0.24.0 Release Preparation

**Date:** 2026-04-01
**Status:** approved
**Research:** /tmp/claude-mine-design-research-lgQuOI/brief.md

## Problem

Hassette has 47 commits since v0.23.0 spanning a full UI rewrite (Preact SPA), database/telemetry layer, architecture hardening, and numerous bug fixes — but the version hasn't been bumped and the documentation hasn't kept pace. The docs contain broken code examples, reference removed pages, omit major new features, and the changelog is a ~200-line wall of PR-by-PR implementation details. The project can't credibly publish v0.24.0 until the docs accurately reflect the codebase.

## Non-Goals

- **No code changes** — docs and metadata only
- **No new features or implementation changes**
- **No API reference changes** — auto-generated via mkdocstrings, already accurate
- **No internal implementation docs** — things like how Alembic migrations work, `mark_ready()` timing, domain model layer internals, etc. are developer internals, not user-facing. Don't document them.

## Guiding Principle: User-Facing Lens

Every changelog entry and every doc page should be evaluated from the perspective of someone *using* hassette to write automations or *configuring* hassette via `hassette.toml`. Internal architecture details (service decomposition, stateless triggers, `mark_ready()` lifecycle changes, domain model extraction) are invisible to end users and should be omitted from the changelog and docs unless they affect user-visible behavior or configuration.

The same applies to "breaking changes" — if the break only affects internal framework code (not user-written apps or config), it's not a user-facing breaking change.

## Architecture

This is a two-phase PR. Phase 1 covers docs, changelog, and cleanup. Phase 2 adds fresh screenshots and the version bump. Both phases land in the same PR.

### Phase 1: Documentation & Changelog

#### 1. Changelog Compression

**File:** `CHANGELOG.md`

The Unreleased section has ~200 lines with duplicated `### Added`/`### Changed`/`### Fixed` headings across 6+ PRs. Compress into themed groups with a flat bullet list per theme. Only include user-facing changes.

**Breaking Changes** (only those affecting user-written code or config):
- `TriggerProtocol` split into `first_run_time(current_time)` and `next_run_time(previous_run, current_time)` — custom triggers must implement both (#452)
- `/api/healthz` removed — update docker-compose health checks to `/api/health` (#448)
- Scheduler enforces job name uniqueness per instance, raises `ValueError` on duplicates; use `if_exists="skip"` for idempotent registration (#297)
- Combining `once=True` with `debounce` or `throttle` now raises `ValueError` at registration — remove the rate-limiting parameter from affected listeners (#430)

Internal-only breaks to *omit* from the user-facing changelog:
- `mark_ready()` timing (internal Resource lifecycle, invisible to app authors)
- `ExecutionResult.started_at` → `monotonic_start` (internal telemetry model, not exposed to users)

**Themed groups (user-facing only):**
- **Web UI** — Preact SPA rebuild with 4 pages (Dashboard, Apps, Logs, Sessions), design token system with light/dark mode, session scope toggle, source location display in handler/job detail panels, keyboard accessibility, self-hosted fonts
- **Database & Telemetry** — persistent telemetry storage (handler invocations, job executions, sessions), configurable retention (`db_retention_days`) and size limit (`db_max_size_mb`), degraded mode indicator in UI
- **Bus & Scheduler** — rate limiter redesign (throttle no longer blocks concurrent dispatch, debounce produces accurate telemetry), `once=True` + rate limiting raises `ValueError`, zero/negative debounce/throttle rejected, `if_exists` parameter on `Scheduler.run_*` methods
- **Logging** — per-service log level tuning via 14 dedicated `*_log_level` config fields
- **Configuration** — `total_shutdown_timeout_seconds`, `db_path`, `db_retention_days`, `db_max_size_mb` config fields
- **Bug Fixes** — user-visible fixes only: startup race conditions, WebSocket reconnect stability, stale telemetry cleanup on app restart, connection status bar flash fix, URL quote parsing

Items to *omit* (internal-only):
- Domain model layer extraction, core/web decoupling
- OpenAPI TypeScript codegen, CI schema validation
- Automatic child lifecycle propagation
- `mark_ready()` timing changes
- Stateless `TriggerProtocol` internals (the break is documented; the implementation detail isn't)
- `Listener.matches()` sync conversion
- `callable_name()` LRU cache removal
- Dead endpoint/column cleanup
- Test infrastructure changes

Leave as `## Unreleased` — version stamp happens in Phase 2.

#### 2. Fix Broken/Stale Documentation

##### 2a. `docs/pages/core-concepts/persistent-storage.md`

Three code examples pass `P.to_state.is_on` as a bare positional arg to `on_state_change()`. The method is keyword-only after `entity_id` (`bus.py:274`). Fix to `where=P.to_state.is_on`.

Locations: lines ~138-142, ~177-180, ~216-220.

##### 2b. `docs/pages/core-concepts/index.md`

Update the service map to reflect the current architecture. Keep it at a level useful to users — focus on the services they interact with or configure, not every internal service. Replace `DataSyncService` (removed) in the Mermaid diagram. Add `DatabaseService` since users configure it via `db_*` fields.

Source of truth: `src/hassette/core/core.py` lines 95-115.

##### 2c. `docs/pages/core-concepts/apps/configuration.md`

Fix type annotations:
- `instance_name: str | None` → `instance_name: str = ""`
- `log_level: str | None` → `log_level: LOG_LEVEL_TYPE` (with factory default)

Source: `src/hassette/app/app_config.py`.

##### 2d. `docs/pages/core-concepts/configuration/global.md`

~15 of 65+ `HassetteConfig` fields are documented. Add subsections with tables for user-relevant fields:
- **Database** — `db_path`, `db_retention_days`, `db_max_size_mb`
- **Timeouts** — `startup_timeout_seconds`, `app_startup_timeout_seconds`, `app_shutdown_timeout_seconds`, `total_shutdown_timeout_seconds`, websocket timeouts
- **Scheduler** — `scheduler_min_delay_seconds`, `scheduler_max_delay_seconds`, `scheduler_default_delay_seconds`
- **Logging** — all 14 `*_log_level` fields as a single table, with link to log-level tuning page
- **Bus Filtering** — `bus_excluded_domains`, `bus_excluded_entities`
- **Production** — `allow_reload_in_prod`, `allow_only_app_in_prod`
- **App Detection** — `autodetect_apps`, `run_app_precheck`, `allow_startup_if_app_precheck_fails`
- **Web UI** — (existing section, add `web_ui_hot_reload`)
- **Advanced** — `hassette_event_buffer_size`, `asyncio_debug_mode`, `watch_files`

Skip deeply internal fields that users would never touch (e.g., `file_watcher_step_milliseconds`, `service_restart_backoff_multiplier`, `scheduler_behind_schedule_threshold_seconds`). These are tuning knobs for edge cases — they exist in the config model but don't need user docs.

Source of truth: `src/hassette/config/config.py`.

##### 2e. Web UI pages

**`docs/pages/web-ui/index.md`** — Replace 6-item nav list with actual 4 routes: Dashboard, Apps, Logs, Sessions.

**`docs/pages/web-ui/dashboard.md`** — Rewrite to describe current layout: KPI strip, app grid with telemetry, recent errors feed with session scope. Remove references to old Scheduled Jobs and Event Bus panels. Remove "View All" links to scheduler.md (line 35) and event-bus.md (line 47) — those pages are being deleted.

**`docs/pages/web-ui/apps.md`** — Update for Preact SPA. Remove note about `dev_mode` requirement for actions (fixed in #390). Update column descriptions.

**`docs/pages/web-ui/logs.md`** — Add Source column (`func_name:lineno` with hover), multi-column sort, auto-pause on sort.

**`docs/pages/core-concepts/bus/index.md`** — Add one-line note to the rate-limiting section: "Both `debounce` and `throttle` must be positive; zero or negative values raise `ValueError` at registration."

##### 2f. Scheduler docs

**`docs/pages/core-concepts/scheduler/methods.md`** — Add brief "Idempotent Registration" section covering:
- Job names must be unique per app instance; duplicate names raise `ValueError`
- `if_exists="skip"` parameter on all `run_*` methods for idempotent registration (e.g., safe to call in `on_initialize` which may run multiple times on reload)
- Default behavior is `if_exists="error"`

##### 2g. Getting-started and entry pages

**`docs/pages/getting-started/docker/index.md`** — Remove the "Hassette does not yet have a UI" note (line ~155) and the Dozzle recommendation. Replace with a brief mention of the built-in web dashboard with link to `web-ui/index.md`.

**`README.md`** — Update the Web UI feature description (line 32) to list the actual 4 pages (Dashboard, Apps, Logs, Sessions). Remove references to entity browser, event bus, and scheduler pages.

**`docs/index.md`** — Update the feature description (line ~49) to match: remove entity browser/event bus/scheduler references, add Sessions and telemetry.

#### 3. Delete Orphaned Pages

Delete these files (pages no longer exist in Preact SPA):
- `docs/pages/web-ui/scheduler.md`
- `docs/pages/web-ui/event-bus.md`
- `docs/pages/web-ui/entities.md`

Delete orphaned screenshot assets:
- `docs/_static/web_ui_scheduler.png`
- `docs/_static/web_ui_event_bus.png`
- `docs/_static/web_ui_entities.png`

Note: `autocomplete.*` and `filtered_events.*` are referenced in `docs/index.md` — do NOT delete. `app-logs.png` has zero references — delete it.

**Implementation note:** Nav entry removal, file deletions, and cross-link removals (e.g., dashboard.md "View All" links to scheduler.md/event-bus.md at lines 35/47) must land in the same commit to avoid intermediate `mkdocs build --strict` failures.

#### 4. New Documentation Pages

##### 4a. `docs/pages/web-ui/sessions.md`

Cover: `/sessions` route, session list with status badges and timestamps, session scope toggle ("This Session" / "All Time") in the status bar, how sessions relate to Hassette restarts.

Source: `frontend/src/pages/sessions.tsx`, `src/hassette/core/session_manager.py`.

##### 4b. `docs/pages/core-concepts/database-telemetry.md`

Cover from the user's perspective: what telemetry is collected (handler invocations, job executions, sessions), how to configure retention and size limits (`db_path`, `db_retention_days`, `db_max_size_mb`), what the degraded indicator means, how to monitor via `/api/telemetry/status`.

Do NOT cover: Alembic migration internals, `TelemetryRepository` class design, `CommandExecutor` architecture, migration chain details.

Source: `src/hassette/core/database_service.py`, `src/hassette/config/config.py`.

##### 4c. `docs/pages/advanced/log-level-tuning.md`

Cover: table of all per-service `*_log_level` config fields with TOML keys, how to set them in `hassette.toml`, fallback behavior (service-level → global `log_level`).

Do NOT cover: the three-mode convention (dedicated/cross-bound/app-owned) — that's a developer-internal design pattern, not a user concern. Users just need to know which TOML keys exist and what they control.

Source: `src/hassette/config/config.py`.

#### 5. Navigation & Metadata

**`mkdocs.yml`** — Update nav:
- Web UI section: remove Scheduler/Event Bus/Entities, add Sessions
- Core Concepts section: add Database & Telemetry
- Advanced section: add Log Level Tuning

**`README.md`** — covered in section 2g above (feature description update). Also review roadmap section for stale items.

### Phase 2: Screenshots & Version Bump

Done in the same PR, after Phase 1 is committed.

#### 6. Fresh Screenshots

- Clone/update the demo repo on this machine
- Bring down hautomate service (conflicts with demo)
- Run dev server with representative data
- Take fresh screenshots: Dashboard, Apps, App Detail, Logs, Sessions
- Replace stale screenshots: `web_ui_dashboard.png`, `web_ui_apps.png`, `web_ui_logs.png`
- Add new: `web_ui_sessions.png`
- Delete stale screenshots for removed pages (already done in Phase 1)
- Bring hautomate service back up

#### 7. Version Bump

**`pyproject.toml`** — Bump `version = "0.23.0"` to `"0.24.0"`.

**`CHANGELOG.md`** — Stamp `## Unreleased` → `## [0.24.0] - <date>`.

## Alternatives Considered

**Ship without docs updates** — Would let us bump the version faster but leaves users with broken examples and references to pages that don't exist. Not acceptable for a published release.

**Version bump in Phase 1, screenshots later** — Rejected because publishing a version with stale/missing screenshots undermines the docs quality we're trying to achieve. Better to do it all in one PR.

**Document internal architecture** — Could write docs for Alembic migrations, domain models, service decomposition, etc. Rejected — these are developer internals, not useful to end users writing automations. The API reference (auto-generated) covers the public surface.

**Full config coverage** — Could document all 65+ config fields. Rejected — many are deep tuning knobs (`file_watcher_step_milliseconds`, `service_restart_backoff_multiplier`) that users would never touch. Document the ones users actually configure.

## Test Strategy

This is a documentation-only change. Testing:

- **`uv run mkdocs build --strict`** — catches broken cross-references, missing nav entries, broken snippet includes
- **Grep for stale references** — `DataSyncService`, `/healthz`, `/api/healthz`, `scheduler.md`, `event-bus.md`, `entities.md` should have zero hits in docs after changes
- **Behavioral claim check** — confirm no doc page claims app actions require `allow_reload_in_prod` or `dev_mode` (the field itself is still valid config, just not required for UI actions post-#390)
- **Code example validation** — verify `where=P.to_state.is_on` matches the actual `on_state_change()` signature
- **CHANGELOG review** — verify every entry passes the "would a user care about this?" test
- **Link validation** — mkdocs strict mode + manual check of cross-page links

## Open Questions

None — all resolved during challenge review.

**Resolved:** `autocomplete.mp4/.webm` and `filtered_events.mp4/.webm` are referenced in `docs/index.md` lines 29-42 and must NOT be deleted. `app-logs.png` has zero references across the docs tree — delete it.

## Impact

**Phase 1 — files modified:**
- `CHANGELOG.md` — compress Unreleased section (no version stamp yet)
- `README.md` — update Web UI feature description (remove entity/event-bus/scheduler, add Sessions)
- `mkdocs.yml` — nav restructure
- `docs/index.md` — update feature description to match current UI
- `docs/pages/core-concepts/index.md` — service map
- `docs/pages/core-concepts/persistent-storage.md` — code example fixes
- `docs/pages/core-concepts/apps/configuration.md` — type fixes
- `docs/pages/core-concepts/configuration/global.md` — major expansion
- `docs/pages/core-concepts/bus/index.md` — debounce/throttle ValueError note
- `docs/pages/core-concepts/scheduler/methods.md` — `if_exists` and job name uniqueness
- `docs/pages/web-ui/index.md` — nav list and descriptions
- `docs/pages/web-ui/dashboard.md` — rewrite
- `docs/pages/web-ui/apps.md` — update
- `docs/pages/web-ui/logs.md` — update
- `docs/pages/getting-started/docker/index.md` — remove "no UI" note and Dozzle recommendation

**Phase 1 — files created:**
- `docs/pages/web-ui/sessions.md`
- `docs/pages/core-concepts/database-telemetry.md`
- `docs/pages/advanced/log-level-tuning.md`

**Phase 1 — files deleted:**
- `docs/pages/web-ui/scheduler.md`
- `docs/pages/web-ui/event-bus.md`
- `docs/pages/web-ui/entities.md`
- `docs/_static/web_ui_scheduler.png`
- `docs/_static/web_ui_event_bus.png`
- `docs/_static/web_ui_entities.png`
- `docs/_static/app-logs.png` (zero references, safe to delete)
- `docs/pages/getting-started/docker/snippets/dozzle-service.yml` (orphaned after Dozzle section removal — verify no other references first)

**Phase 2 — files modified:**
- `pyproject.toml` — version bump to 0.24.0
- `CHANGELOG.md` — stamp version + date
- `docs/_static/web_ui_dashboard.png` — fresh screenshot
- `docs/_static/web_ui_apps.png` — fresh screenshot
- `docs/_static/web_ui_logs.png` — fresh screenshot

**Phase 2 — files created:**
- `docs/_static/web_ui_sessions.png` — new screenshot

**Blast radius:** Documentation only. No code changes. No test changes. No CI changes.
