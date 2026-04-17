# Design: Scheduler Frontend Integration

**Date:** 2026-04-16
**Status:** archived
**Spec:** _(no spec.md — v2 convention expects one; this design was scoped inline as a direct follow-on to spec 2038)_
**Research:** `/tmp/claude-mine-design-research-HQ6Giu/brief.md` (ephemeral; copy into `design/research/` before merge if you want it preserved)
**Related:** `design/specs/032-scheduler-api-redesign/design.md`
**Challenge:** `/tmp/claude-mine-design-challenge-wU9RCc/findings.md` (15 findings; all resolved)

## Problem

Spec 2038 rewrote the scheduler around a public `TriggerProtocol` and added groups, jitter, `fire_at`, and a `trigger_label`/`trigger_detail` split. Its design doc marks frontend work as "Completed" because `frontend/src/components/app-detail/job-row.tsx:57-59` renders a three-way fallback chain (`trigger_detail ?? trigger_label ?? trigger_type`).

That fallback chain is the only frontend change. The audit (see Research brief) confirms:

- `/scheduler/jobs` → `ScheduledJobResponse` has **zero consumers** anywhere in `frontend/src/`. The entire schema (`fire_at`, `jitter`, `next_run`, `cancelled`, nullable `job_id`, `trigger_label`, `trigger_detail`) is dead API surface. Only the route file, OpenAPI export, and test conftest reference it.
- `JobSummary` (the telemetry model actually consumed by the UI) lacks `fire_at`, `jitter`, `next_run`, `cancelled`, and `group` entirely — so even if the frontend wanted to surface live runtime state, the endpoint it already consumes can't deliver it.
- The semantic distinction between `trigger_label` (trigger type, e.g. "Daily") and `trigger_detail` (specifics, e.g. "07:00 in America/Chicago") is collapsed into one subtitle line.
- Scheduler's `group` feature (`Scheduler.list_jobs(group=)`, `cancel_group()`) has no UI affordance; groups cannot be seen or filtered.
- `app-detail.tsx:141` labels the section "Scheduled Jobs (N active)" — but N counts historical registrations from the telemetry DB, not live jobs.

Four challenge-loop findings from spec 2038 (iter-2 F#7 "jitter invisible", iter-2 F#9 "monitoring blind", iter-3 F#11 "two schemas, one component", iter-3 F#16 "dead API contract") went unresolved because they required frontend architectural work that spec 2038 didn't plan for.

Since the scheduler redesign has not shipped to users yet (branch `worktree-scheduler-api-prior-art` is pre-merge), this design ships alongside spec 2038 in the same PR. No backwards compatibility is required.

## Architecture

### Principle: one endpoint, one shape

Delete `/scheduler/jobs` and `ScheduledJobResponse` wholesale. They are orphaned route surface added during spec 2038 (WP06) for a consumer that never materialized. Removing them eliminates the schema-split tension that iter-3 Finding 11 flagged.

Enrich `JobSummary` (returned by `/telemetry/app/{app_key}/jobs`) to carry every field the frontend needs, both historical and live. Since backend changes are in scope for this PR, the per-query join cost is acceptable.

### Backend changes

**1. Extend `JobSummary`** (`src/hassette/core/telemetry_models.py`):

Add fields:
- `group: str | None` — the scheduler group name (persisted at registration; see below)
- `next_run: float | None` — Unix epoch seconds of the next scheduled fire time (unjittered); sourced from live heap via `job.next_run.timestamp()`. Matches the existing `last_executed_at: float | None` convention.
- `fire_at: float | None` — Unix epoch seconds of actual dispatch time when jitter applied; sourced from live heap; present iff `jitter is not None`. Serialized via `job.fire_at.timestamp()`.
- `jitter: float | None` — seconds of random offset from live heap
- `cancelled: bool` — `True` when a live-heap match has `cancelled=True`, OR when no live match exists but `cancelled_at IS NOT NULL` in the DB row (see Backend #3 for persistence). `False` otherwise.

Remove field:
- `repeat: int` — always 0 post-migration-002 (triggers handle recurrence); `trigger_type` conveys whether a job recurs. Remove from the SQL SELECT, Pydantic model, and let OpenAPI/TypeScript regeneration clean it up.

Rationale for sourcing: `group` is set at registration and never changes, so persist in the `scheduled_jobs` table. `next_run`, `fire_at`, `jitter` are live runtime state that shifts per scheduler cycle — joining them at query time is cheaper than persisting every scheduler mutation to DB. `cancelled` is hybrid: transient from the live heap, durable from the DB `cancelled_at` column.

Rationale for epoch floats (not ISO strings): The `whenever` library's `ZonedDateTime.__str__()` and `format_iso()` emit RFC 9557 extended format with a `[IANA/timezone]` suffix (e.g., `2026-04-16T07:00:00+00:00[UTC]`), which `new Date()` cannot parse in all browsers. The existing `last_executed_at` field already uses epoch floats. Consistent float timestamps across all time fields eliminates frontend parsing concerns and lets `useRelativeTime` work unchanged.

**2. Persist `group` and `cancelled_at` at registration** (`src/hassette/core/registration.py`, `src/hassette/core/scheduler_service.py`, `src/hassette/core/telemetry_repository.py`, migration `003`):

- Add `group TEXT NULL` and `cancelled_at REAL NULL` columns to `scheduled_jobs` table (new migration `003_scheduler_frontend_columns.py`). Migration follows the table-recreation pattern from 002 (not `ALTER TABLE ADD COLUMN`) for consistency with the established project convention and SQLite downgrade compatibility.
- Add `group: str | None` field to `ScheduledJobRegistration`.
- Update `SchedulerService._enqueue_then_register()` to forward `job.group` when constructing `ScheduledJobRegistration`.
- Update `telemetry_repository.register_job()` to INSERT the `group` value.
- Add a new repository method `mark_job_cancelled(db_id: int)` that sets `cancelled_at = time.time()` on the DB row. Called from the cancel path in `SchedulerService` (either `cancel_group()` or `job.cancel()`).

Rationale for `cancelled_at` persistence: Without it, `cancelled=False` is returned for three semantically distinct job states — active/uncancelled, completed normally, and cancelled-then-removed-from-heap — making the UI's cancelled badge unreliable. Persisting `cancelled_at` provides a durable signal that survives heap removal. Write frequency is low (user-initiated cancellations only).

**3. Enrich jobs in the `app_jobs` route handler** (`src/hassette/web/routes/telemetry.py`):

The live-heap join lives in the **route handler**, not in `TelemetryQueryService`. This preserves `TelemetryQueryService` as a clean DB-only read model (its module docstring explicitly declares this boundary). The route handler already has access to both `TelemetryDep` and `SchedulerDep` via FastAPI DI.

Enrichment procedure in the `app_jobs` route:
1. Fetch `JobSummary` rows from `telemetry_query_service.get_job_summary()` (DB-only, unchanged).
2. Call `scheduler_service.get_all_jobs()` to get a snapshot of live `ScheduledJob` instances. **INVARIANT**: `get_all_jobs()` acquires the `FairAsyncRLock` internally and returns a list copy. All enrichment work MUST happen on the returned snapshot, never inside the lock context, to avoid contention with the scheduler dispatch loop.
3. Build a lookup dict keyed by `db_id`: `{job.db_id: job for job in live_jobs if job.db_id is not None}`.
4. For each `JobSummary` row, look up the matching live job by `job_summary.job_id == live_job.db_id`. If a match exists, populate `next_run`, `fire_at`, `jitter`, `cancelled` from the live job. If no match, leave `next_run`/`fire_at`/`jitter` as `None`. For `cancelled`: if no live match and DB row has `cancelled_at IS NOT NULL`, set `cancelled=True`; otherwise `cancelled=False`.
5. **Join key**: use `db_id` only. Jobs in the registration-race window (`db_id=None`, i.e., enqueued but not yet persisted) are silently skipped for enrichment — they won't appear in the SQL results either since they haven't been registered yet. The `(app_key, instance_index, job_name)` fallback is explicitly rejected due to silent mismatch risk with non-unique names.
6. **Error handling**: Wrap the `get_all_jobs()` call in `try/except Exception` with `live_jobs = []` as the fallback. On failure, return DB rows without live enrichment (degraded but functional) and log a warning. This is consistent with the existing `except DB_ERRORS → empty list` degradation pattern in the same route file.

**4. Delete `/scheduler/jobs` route and `ScheduledJobResponse` model:**

- Remove `src/hassette/web/routes/scheduler.py` (or empty the file and leave a TOMBSTONE comment that the global live endpoint was removed).
- Remove `ScheduledJobResponse` from `src/hassette/web/models.py`.
- Remove `_job_to_dict` from `src/hassette/web/routes/scheduler.py` (its enrichment logic now lives in the route handler's join).
- Remove the route registration wherever it's wired (likely `src/hassette/web/__init__.py` or equivalent).
- Delete any tests targeting the removed endpoint (`tests/integration/test_web_api.py`, `tests/integration/test_dispatch_unification.py`, etc.).
- Add a `fix!` breaking-change conventional commit entry so release-please generates a CHANGELOG entry noting `/scheduler/jobs` removal (CHANGELOG already documents the endpoint as shipped).

**5. Regenerate OpenAPI + TypeScript types:**

- `uv run python scripts/export_schemas.py` → updates `frontend/openapi.json`
- `cd frontend && npm run types` → updates `frontend/src/api/generated-types.ts`

### Frontend changes

All changes are inside existing pages/components. No new routes, no new top-level navigation entries, no new pages.

**1. `frontend/src/components/app-detail/job-row.tsx`** (primary surface):

Replace the current subtitle fallback chain with a structured presentation. Proposed render shape:

```
[dot] {job_name}                                     [group-pill] {runs} {failed} {avg} {last-executed} [chevron]
      {trigger_label} · {trigger_detail (when non-null, dimmed)}
      [jitter-tag ±15s] [cancelled-badge]     ← only when applicable
      Next: fires in 3m (±15s jitter)          ← only when next_run present
```

- **Title**: `job_name` (unchanged)
- **Subtitle line 1**: `trigger_label` as primary; `trigger_detail` as secondary in a dimmer style (e.g., `ht-text-muted`). When `trigger_label` is empty string (edge case for custom triggers that return `""`), fall back to `trigger_type`.
- **Subtitle line 2** (conditional, shown only when any apply): `group` as a clickable `ht-badge` pill (click sets group filter — see #2); `jitter` as "±{jitter}s" tag; `cancelled=true` renders a muted/struck-through row treatment (this is a durable signal backed by DB `cancelled_at`).
- **Stats row**: unchanged (`runs`, `failed`, `avg`, `last_executed_at`) — these remain historical values.
- **When expanded**: existing source_location / registration_source block; existing execution history. Add a "Next: {relative time} (±{jitter}s jitter)" line at the top of the expanded detail when `next_run` is non-null, using `useRelativeTime`. Since `next_run` is now an epoch float (matching `last_executed_at`), `useRelativeTime` works unchanged.

Keying: `job-list.tsx:15` currently uses `job.job_id` as the React key. `JobSummary.job_id` is non-nullable (stays that way after this change — it's set at registration by the telemetry repo), so keying is unaffected.

**2. `frontend/src/components/app-detail/job-list.tsx`** (group filter with URL persistence):

- Compute `groupCount` = count of distinct non-null `group` values among `jobs`.
- When `groupCount >= 2`: render a horizontal filter chip bar above the list with one chip per group plus an "All" chip. Active chip is visually pressed; clicking a chip filters the displayed jobs. Use the same `ht-badge`/chip styling as the in-row group pills so clicking either gives identical behavior.
- When `groupCount < 2`: no filter bar; cleaner page for the typical case.

Filter state: local component signal (`@preact/signals` `signal<string | null>`) in `job-list.tsx`. Initialized from `?group=` URL search param on mount via `wouter`'s `useSearch`. On chip click, update the URL param. This makes filters bookmarkable and survive instance switches — the multi-instance debugging path where groups are most useful.

When `jobs` prop changes (e.g., instance switch triggers `useScopedApi` refetch): reset the active filter signal to `null` via `useEffect([jobs])` — prevents a stale filter from producing an empty list. Show a "No jobs match this filter" empty state when a filter is active but returns zero rows.

**3. `frontend/src/components/app-detail/job-row.tsx` group pill click behavior:**

Clicking an in-row group pill sets the list's filter to that group via a callback prop (`onGroupClick: (group: string) => void`) passed from `job-list.tsx`. This makes badges and chips interchangeable surfaces for the same filter. `job-list.tsx` owns the signal and the callback; `job-row.tsx` receives the callback prop and calls it on click.

**4. `frontend/src/pages/app-detail.tsx`:**

- Line 141: rename heading to "Scheduled Jobs ({registered} registered)". Add a secondary computed label: "N currently scheduled" derived from `jobs.filter(j => j.next_run != null).length`. This gives users both counts with clear semantics — registered (DB total) vs. currently scheduled (have a live `next_run`).
- No other structural changes. `app-detail.tsx` does not manage the filter signal (that's local to `job-list.tsx`).

**5. Types + endpoint helper:**

- `frontend/src/api/endpoints.ts`: `JobData` type alias still points to `components["schemas"]["JobSummary"]` — nothing to change. The new fields come through automatically via the regenerated types.
- No new endpoint helper needed.

**6. `src/hassette/web/CLAUDE.md` — trim to Python conventions:**

This file describes the pre-Preact Jinja/HTMX architecture (`templates/pages/`, `templates/partials/`, Alpine.js patterns). None of that infrastructure exists anymore. However, it also contains live Python-layer conventions: dependency aliases (`RuntimeDep`, `TelemetryDep`, `SchedulerDep`), the `DB_ERRORS` catch pattern, and route registration patterns. Trim to ~30 lines covering only the Python conventions; delete all Jinja/HTMX/Alpine.js content.

### Live-updates strategy

Match the existing handler row pattern exactly:

- `useScopedApi(getAppJobs, { deps: [appKey, instanceIndex] })` — already in place at `app-detail.tsx:32`.
- This refetches on session scope/id change and on WS reconnect (the latter is free via `useApi`'s reconnect hook).
- No dedicated `scheduler_changed` WS message. No polling interval.

Consequence: a job that fires or is cancelled between the user's last load and their next focus will not live-update. This matches what happens for event-handler invocations today and is considered acceptable for the monitoring use case. If users request true live updates, adding a WS broadcast channel (backend) + WS-triggered refetch (frontend) is a follow-up issue, not v1.

### Scope explicitly excluded from v1

| Deferred item | Reason | Follow-up |
|---|---|---|
| Cancel/reschedule mutations from UI | Requires new REST endpoints + UI confirmation flows; not needed for initial monitoring value | File GitHub issue labelled `area:scheduler`, `area:ui`, `enhancement`, `size:large` |
| Dashboard "scheduler at a glance" panel | Dashboard was recently polished (commit `dfdbc61`); adding a sixth surface without a layout design pass risks regression | Follow-up issue with `area:ui`, `enhancement` |
| `scheduler_changed` WS push message | Matches handler pattern; premature for v1 | Follow-up if users complain of stale data |
| Global/cross-app scheduler view | Per-app view via app-detail covers the realistic investigation path | Re-evaluate if data shows cross-app need |

## Alternatives Considered

### Alt 1: Keep both endpoints; add a dedicated `/scheduler` page

What the research brief's Option B recommended. Rejected because:

- `/scheduler/jobs` has no current consumer — adding a page to consume a dead endpoint is solving the problem backwards.
- Adds navigation (5th sidebar item, 5th bottom-nav item) that crowds the rail-optimized layout.
- Introduces two different job components (`LiveJobRow` vs `JobRow`) with subtly different props and styling obligations — long-term maintenance debt the research brief itself flagged.
- Per-app view on app-detail already answers "what's scheduled for this app?" which is the realistic user question; "what's scheduled globally?" is an administrative question without a clear asker.

### Alt 2: Keep both endpoints; make them return the same shape

Rejected because it preserves the underlying schema split without buying the frontend anything. One component still has to choose between the two, and the duplication of live heap → response serialization exists in two places (the global route's `_job_to_dict` and the telemetry query service's live-join).

### Alt 3: Add fields to `JobSummary` but persist live state to DB

Instead of joining heap state at query time, persist `next_run`/`fire_at`/`jitter` to the `scheduled_jobs` table on every scheduler cycle. Rejected:

- Write amplification: every rescheduling (cron advance, etc.) would require a DB round-trip.
- Staleness: even with writes-on-change, the DB lags the heap. The heap is always more accurate.
- The telemetry DB is a historical aggregate store by design — injecting mutable runtime state into it muddies that contract.

Query-time join is simpler, reads only, no write pressure. Note: `cancelled_at` is the exception — it's a user-initiated, low-frequency write that provides a durable signal the heap cannot (see Backend #2).

### Alt 4: Cancel/reschedule mutations in v1

Rejected per user direction. Reasoning: the monitoring use case is answerable without mutation; mutation adds confirmation-flow design, error surface, and permissions considerations that expand scope beyond what's needed to close the spec-2038 gaps. Defer.

### Alt 5: Collapsible group sections (instead of filter chips)

For groups UI. Rejected:

- App-detail already nests one level (app → handlers + jobs + logs). Adding another expand level (app → jobs → groups → rows) is cognitively heavy.
- Typical automation apps have 0–5 jobs across 0–2 groups; filter chips are lighter.

### Alt 6: Enrich `JobSummary` inside `TelemetryQueryService`

Rejected (challenge finding F#1, 5/5 critic agreement): `TelemetryQueryService` is a historical DB-only read model (its module docstring explicitly declares this). Injecting a `Scheduler` dependency violates that boundary and forces every consumer (including `app_health`, which doesn't need live data) to drag in the scheduler. The route handler is the correct seam for cross-resource joins.

### Alt 7: `(app_key, instance_index, job_name)` as live-heap join key

Rejected (challenge finding F#2, 5/5 critic agreement): The triple-key has silent mismatch risk — two jobs with the same callable and no explicit name generate identical `job_name`. Wrong live data that looks plausible is worse than absent data during the bounded registration-race window.

## Test Strategy

### Backend tests

- `tests/unit/core/test_telemetry_models.py` — extend to assert the new `JobSummary` fields exist with correct defaults (`group=None`, `next_run=None`, `fire_at=None`, `jitter=None`, `cancelled=False`). Assert `repeat` field is removed.
- `tests/integration/test_telemetry_query_service.py` — add cases covering: (a) job in DB with live heap match → all live fields populated; (b) job in DB with no live match (de-registered) → live fields all `None`, `cancelled=False`; (c) job in DB with `jitter` set → `fire_at` populated; (d) job in DB with `cancelled_at IS NOT NULL` and no live match → `cancelled=True`.
- `tests/integration/test_registration.py` — assert `group` is persisted when set.
- `tests/unit/core/test_telemetry_repository.py` — extend column set assertion, add `group` INSERT test, add `mark_job_cancelled` test.
- `tests/integration/test_dispatch_unification.py` / `test_web_api.py` — remove any assertions targeting `/scheduler/jobs`; update to hit the telemetry route.
- Migration `003` — no unit tests (migrations are excluded from codecov per memory), but should have a manual upgrade/downgrade sanity check via `alembic`.
- Route-handler enrichment — test the `app_jobs` route handler enrichment logic: (a) happy-path merge; (b) heap call failure → graceful degradation (DB rows returned without live fields); (c) `db_id=None` live jobs silently skipped.

### Frontend tests

- `frontend/src/components/app-detail/job-row.test.tsx` (new file — first of its kind in `components/app-detail/`, follows `components/dashboard/app-card.test.tsx` pattern): cover title/subtitle split, group pill rendering, jitter tag rendering, cancelled treatment, `next_run` relative display.
- `frontend/src/components/app-detail/job-list.test.tsx` (new): cover filter chip bar presence when `groupCount >= 2`, absence otherwise, chip click filters list, "All" chip resets, URL-param persistence, filter reset on jobs prop change, "No jobs match this filter" empty state.
- `frontend/src/pages/app-detail.test.tsx` — update existing assertions for heading (registered count + currently scheduled count).

### E2E tests

Optional but recommended: one Playwright test under `tests/e2e/test_app_detail.py` (if it exists) asserting a job's subtitle shows both label and detail, and a group badge is visible when a grouped job is seeded. Precedent: `sessions.tsx` has no E2E coverage, so this is a net-new investment.

### Coverage target

Maintain the 80% project threshold. Migration file excluded from codecov per project policy. No caplog-based tests (project policy).

## Open Questions

- [ ] **Migration numbering.** This work adds migration `003_scheduler_frontend_columns.py` (adds both `group TEXT NULL` and `cancelled_at REAL NULL`). Confirm no other in-flight branch is claiming that number.

## Impact

### Files changed (backend)

- `src/hassette/core/telemetry_models.py` — add 5 fields to `JobSummary`; remove `repeat`
- `src/hassette/core/registration.py` — add `group` field to `ScheduledJobRegistration`
- `src/hassette/core/scheduler_service.py` — forward `job.group` when constructing `ScheduledJobRegistration`; call `mark_job_cancelled` from cancel paths
- `src/hassette/core/telemetry_repository.py` — INSERT `group`; add `mark_job_cancelled(db_id)`; update column list assertions; remove `repeat` from SELECT
- `src/hassette/core/telemetry_query_service.py` — no changes (DB-only boundary preserved)
- `src/hassette/web/routes/telemetry.py` — live-heap enrichment join in `app_jobs` route handler
- `src/hassette/migrations/versions/003_scheduler_frontend_columns.py` — new migration (adds `group TEXT NULL`, `cancelled_at REAL NULL`; table-recreation pattern)
- `src/hassette/web/routes/scheduler.py` — delete route + helper (or tombstone)
- `src/hassette/web/models.py` — delete `ScheduledJobResponse`
- `src/hassette/web/CLAUDE.md` — trim to ~30 lines of Python conventions
- Test files: see Test Strategy section

### Files changed (frontend)

- `frontend/openapi.json` — regenerated
- `frontend/src/api/generated-types.ts` — regenerated (adds `JobSummary.group`, `next_run`, `fire_at`, `jitter`, `cancelled`; removes `repeat`, `ScheduledJobResponse`)
- `frontend/src/components/app-detail/job-row.tsx` — major rework of subtitle/tags/expand-detail render; accepts `onGroupClick` callback prop
- `frontend/src/components/app-detail/job-list.tsx` — add conditional filter chip bar with URL persistence; filter reset on jobs prop change; "no matches" empty state
- `frontend/src/pages/app-detail.tsx` — rename heading to "Scheduled Jobs (N registered)" + secondary "N currently scheduled" count
- `frontend/src/components/app-detail/job-row.test.tsx` — new
- `frontend/src/components/app-detail/job-list.test.tsx` — new
- `frontend/src/pages/app-detail.test.tsx` — update heading assertion

### Blast radius

Contained: `scheduler.py`/`scheduler_service.py` runtime changes are limited to forwarding `group` at registration and calling `mark_job_cancelled` on cancel paths. The scheduler's live heap is read-only from the route handler's perspective (snapshot taken outside the lock). No mutations introduced to the web layer. No WS broadcasts added. No navigation changes. All changes are additive on `JobSummary`, subtractive on `/scheduler/jobs`, and cosmetic on the UI.

### Dependencies that will need updates

- `scripts/export_schemas.py` will need to run once to regenerate OpenAPI after backend edits.
- `npm run types` will need to run once after `openapi.json` regeneration.
- `alembic` migration committed manually as `003_scheduler_frontend_columns.py`.

### Breaking changes

- `/scheduler/jobs` endpoint removed (no external consumers known; search the docs site before merge to confirm). Add a `fix!` conventional commit so release-please generates a CHANGELOG entry.
- `ScheduledJobResponse` schema removed from public OpenAPI (same — no external consumers).
- `JobSummary.repeat` field removed (always 0; `trigger_type` conveys recurrence).
- `JobSummary.next_run` and `fire_at` use epoch floats, not ISO strings — consistent with existing `last_executed_at` convention.
- `JobSummary` gains 5 new optional fields — backward compatible for anyone consuming the older schema (all fields default to `None`/`False`).

Since spec 2038 hasn't shipped yet, these "breaking changes" are internal to an unreleased branch and carry no user impact at merge time.
