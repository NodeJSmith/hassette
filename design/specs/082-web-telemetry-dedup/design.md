# Design: Collapse web/telemetry duplication (#1107, #1108, #1095, #1114)

**Status:** approved
**Issues:** #1107, #1108, #1114 (storage-exception seam), #1095
**Origin:** SPLIT candidates #6 and #7 from the #1094 research brief
(`design/research/2026-06-21-issue-1094-mapper-rate-cleanup/research.md`), plus a
related neighborhood cleanup (#1095).

## Problem

Three independent duplications have accumulated in the `web/` and `core/telemetry/`
layers (items 1-3 below). Each is behavior-preserving to remove, but every copy is a place where
a policy can drift out of sync with its twin. Collapsing item 2 surfaced a fourth, deeper problem
(item 4): the duplicated boilerplate is catching raw storage exceptions in the HTTP layer.

1. **#1107 — Live-heap enrichment wrapper.** The `all_jobs`
   (`web/routes/scheduler.py:36-52`) and `app_jobs` (`web/routes/telemetry.py:228-247`)
   handlers both inline the same sequence: fetch DB rows, snapshot the live scheduler
   heap, enrich the rows, fall back to the unenriched DB rows if the snapshot fails.
   The fallback policy — `except (OSError, RuntimeError, ValueError)` plus a warning log —
   is copied verbatim in both handlers. The underlying `enrich_jobs_with_heap`
   (`web/utils.py:16`) is already shared; the *wrapper around it* is not.

2. **#1108 — DB-error degradation boilerplate.** A
   `try: <query> except DB_ERRORS: LOGGER.warning(...); response.status_code = 503; return <default>`
   block appears **17 times across 6 route files** (`telemetry.py` x11, `executions.py` x2,
   `apps.py`/`bus.py`/`logs.py`/`scheduler.py` x1 each). The status code, the log call, and
   the default value are re-typed at every site, so a change to the degradation contract
   means editing 17 places.

3. **#1095 — Telemetry summary-query duplication and package boundary.** Two pairs of CTE
   query methods in `core/telemetry/registration_queries.py` differ only by a WHERE clause:
   `get_listener_summary`/`get_all_listeners_summary` (lines 23-169) and
   `get_job_summary`/`get_all_jobs_summary` (lines 171-310). Each pair is ~140 lines of
   duplicated SQL. Separately, the 2026-06-19 audit (N4/N5) observed the telemetry *write* helper
   `core/telemetry_repository.py` sitting in `core/` while the *read* side already lives in
   `core/telemetry/`. (The audit also named `schemas/telemetry_models.py` and SessionManager's
   SQL, but on inspection those are correctly placed — shared models belong in the `schemas/`
   cycle-breaker, and session-lifecycle SQL belongs to `SessionManager`. See Non-Goals.)

4. **NEW — Storage exceptions leak raw into the HTTP layer.** The `TelemetryQueryService` mixins
   catch nothing; raw `sqlite3.Error`, `OSError`, `asyncio.TimeoutError`, and a closed-connection
   `ValueError` propagate from aiosqlite straight to 14 HTTP handlers. `DB_ERRORS`
   (`dependencies.py:43`) is the de-facto storage→HTTP translation layer, but it lives in every
   handler instead of at the service boundary, and it over-catches `ValueError` — a non-DB
   `ValueError` inside any handler's `try` (a bad `model_validate`, a key error) silently becomes
   a 503-with-empty-data instead of a 500. This is the architectural root the #1108 boilerplate
   sits on. (Surfaced during the #1108 challenge follow-up; tracked as #1114 — see Sequencing.)

## Goals

- Each duplicated policy lives in exactly one place.
- JSON response shape and HTTP status behavior are byte-for-byte unchanged. These are pure
  refactors; the existing test suite is the pin. (The one deliberate behavior change is the
  storage-exception seam: a non-DB `ValueError` now surfaces as a 500 instead of being swallowed
  as a 503 — see the seam section.)
- Storage exceptions translate to a single narrow domain exception (`TelemetryUnavailableError`)
  at the `TelemetryQueryService` boundary; the HTTP layer catches that, not raw storage types.
- The misplaced telemetry write helper (`telemetry_repository.py`) moves under `core/telemetry/`
  alongside the read side.

## Non-Goals

- No response-model field is added, removed, or renamed. `scripts/export_schemas.py` output
  (`openapi.json`, `generated-types.ts`, `ws-types.ts`) must be byte-identical — verified, not
  assumed.
- No change to the degradation *contract*. #1108 relocates the 503-degradation policy; it does
  not redesign it, and it does **not** touch the silent-200 best-effort sites (see #1108
  Architecture).
- `telemetry_models.py` does **not** move. It lives in `schemas/` deliberately — that package is
  the cycle-breaker that lets `core/`, `web/`, and `cli/` all import shared models without a
  dependency cycle (`schemas/__init__.py:1-11` forbids `schemas` importing `core`). Moving the
  models into `core/telemetry/` would force the `schemas/__init__.py` re-export to import `core`,
  violating that invariant. (Resolved in challenge — see Challenge Resolutions.)
- SessionManager's inline session-lifecycle SQL is **not** extracted behind a repository. It is
  not duplicated, has a single consumer, and carries an explicit-transaction atomicity constraint
  (`session_manager.py:236-240`). (Resolved in challenge.)
- The #1094 mapper/rate-math cleanup itself is out of scope — that is its own PR.

## Sequencing

Four units now, sharing write targets, so they serialize rather than run in parallel:

1. **#1107** — heap-enrich wrapper. Independent, smallest.
2. **#1108a** — `db_degrades_to` CM + migrate the 14 handlers (still catching `DB_ERRORS`).
   Behavior byte-for-byte identical. This step *centralizes* the catch.
3. **#1108b (#1114)** — storage→domain exception seam. Because 1108a centralized the catch,
   swapping what it catches is a near-one-line change, not 14 edits. This is the one step with a
   deliberate (small) behavior change (the `ValueError` footgun fix).
4. **#1095** — query consolidation + repository move. Last; rebases on already-simplified routes.

Order: **#1107 → #1108a → #1108b → #1095.** Rationale for 1108a-before-1108b: the seam swap is
cheap *only after* the catch is centralized — doing the seam first would mean editing 14 handlers
twice. `bus.py:get_listener_metrics` is intentionally deferred from 1108a and migrated in #1095
(branch-collapse + CM in one step). Each unit lands as its own commit with the full suite green at
every boundary, per `sequence-verifiable-units.md`. The new #1108b issue is filed and labeled per
the repo conventions; the cluster branch carries all four.

## Functional Requirements

### #1107 — heap-enrich wrapper

- **FR#1** — `web/utils.py` gains `enrich_jobs_with_live_heap(db_jobs, scheduler_service)` that
  snapshots the heap once via `scheduler_service.get_all_jobs()`, enriches `db_jobs` via the
  existing `enrich_jobs_with_heap`, and returns the unenriched `db_jobs` (logging a warning) when
  the snapshot raises `OSError | RuntimeError | ValueError`. The fallback exception set and warning
  text are lifted unchanged from the current handlers.
- **FR#2** — `all_jobs` (`web/routes/scheduler.py`) and `app_jobs` (`web/routes/telemetry.py`)
  call the helper instead of inlining the snapshot/enrich/fallback block. The DB fetch +
  `DB_ERRORS` handling stays in each route (it is #1108a's concern; the two handlers fetch from
  different query methods).

### #1108a — `db_degrades_to` context manager

- **FR#3** — A per-site classification table covering all 17 `except DB_ERRORS` sites, produced
  **before any code**, sorting each into category A (one-line wrap), B (post-query work moves
  inside the block — criterion: *must be skipped on failure*), C (silent-200, excluded), or D
  (multi-failure, excluded). The table is committed as part of #1108a (in `web/CLAUDE.md` or the
  task notes).
- **FR#4** — `web/dependencies.py` gains `db_degrades_to(response)` — a context manager that
  catches `DB_ERRORS`, logs a warning with `exc_info`, and sets `response.status_code = 503`.
  Callers pre-initialize the result to the failure default and return it at the tail.
- **FR#5** — Every category-A and category-B site adopts `db_degrades_to`; category-B sites move
  their post-query work inside the `with` block. Category-C and category-D sites are left as their
  current `try/except` (status codes unchanged). `bus.py:get_listener_metrics` is left untouched
  in #1108a (migrated in #1095).
- **FR#6** — `web/CLAUDE.md` "DB_ERRORS Catch Pattern" section documents the minimal shape, the
  post-query-work shape, an explicit warning that code between the `with` block and the tail return
  runs on both paths against the default, and names the category-C/D sites as intentional
  exceptions that do not use `db_degrades_to`.

### #1108b (#1114) — storage→domain exception seam

- **FR#7** — `src/hassette/exceptions.py` gains `TelemetryUnavailableError(HassetteError)`.
- **FR#8** — Every `TelemetryQueryService` read path translates storage exceptions
  (`sqlite3.Error`, `OSError`, `ValueError`, `TimeoutError`) into `TelemetryUnavailableError`.
  This includes the `execute()` context manager (`query_service.py`) *and* every direct
  `self._db.execute` read that bypasses it — confirmed via a `self._db.execute`-outside-`execute()`
  audit; `get_all_app_summaries` (`summary_queries.py:215-228`) is the known bypass and must be
  covered.
- **FR#9** — `db_degrades_to` and the category-C/D inline catches switch from `except DB_ERRORS`
  to `except TelemetryUnavailableError`; `DB_ERRORS` is deleted from the HTTP layer (the storage
  tuple is named only at the translation boundary).
- **FR#10** — A non-DB `ValueError` raised in a handler body surfaces as HTTP 500, not a swallowed
  503. This is the cluster's one intended behavior change.

### #1095 — query consolidation + repository move

Scope after challenge: **query consolidation + the `telemetry_repository.py` move only.** The
`telemetry_models.py` move and the SessionManager write-repo are dropped (see Non-Goals).

- **FR#11** — `get_listener_summary` absorbs `get_all_listeners_summary`: signature becomes
  `get_listener_summary(app_key=None, instance_index=None, since=None, source_tier="app")`. When
  `app_key is None`, the WHERE clause omits the `app_key`/`instance_index` filter and
  `instance_index` is ignored. Same pattern for `get_job_summary` absorbing `get_all_jobs_summary`.
  The two `get_all_*` methods are deleted.
- **FR#12** — The `bus.py` dispatch guard tightens from `if not app_key:` to `if app_key is None:`
  so an empty-string `?app_key=` cannot fall through to the all-apps path. `get_listener_metrics`
  is migrated to `db_degrades_to` here (branch-collapse + CM in one step).
- **FR#13** — Production callers migrate (`web/routes/{bus,telemetry,scheduler}.py`,
  `test_utils/web_mocks.py`) and the ~25 test call sites. A dedicated audit rewrites
  **dispatch-assertion** tests (`assert_called_once`/`assert_not_called`/`assert_called_with`/
  `call_count` on the four method names, plus the `AsyncMock` attribute assignments in
  `web_mocks.py` and `tests/e2e/mock_fixtures.py`) into argument-based assertions on the unified
  methods — these cannot be mechanically codemod'd.
- **FR#14** — `core/telemetry_repository.py` moves to `core/telemetry/repository.py` (6 importers:
  1 prod + 5 test). All importers migrate; no compat shim (`coding-style.md`).

## Acceptance Criteria

- **AC#1** — `all_jobs` and `app_jobs` produce byte-identical responses to before, including the
  heap-failure fallback to DB rows; a unit test exercises `enrich_jobs_with_live_heap`'s fallback
  path directly. (FR#1, FR#2)
- **AC#2** — The 17-site classification table exists and every site's category is justified; no
  category-C/D site's HTTP status code changes. (FR#3, FR#5)
- **AC#3** — `db_degrades_to` exists in `dependencies.py`; a unit test confirms it catches the
  degradation exception, sets 503, and passes success through untouched. (FR#4)
- **AC#4** — All category-A/B sites use `db_degrades_to`; existing per-route 503/default and
  200/partial degradation tests stay green. (FR#5)
- **AC#5** — `web/CLAUDE.md` documents the minimal shape, post-query-work shape, the both-paths
  warning, and the category-C/D exceptions. (FR#6)
- **AC#6** — `TelemetryUnavailableError(HassetteError)` is defined and raised from every read path,
  verified by a `self._db.execute`-outside-`execute()` audit showing no uncovered path; a forced
  storage error in `get_all_app_summaries` still degrades `dashboard_app_grid` to 200-partial, not
  500. (FR#7, FR#8)
- **AC#7** — The HTTP layer catches only `TelemetryUnavailableError`; `DB_ERRORS` no longer appears
  in `web/`. A non-DB `ValueError` in a handler body now returns 500. (FR#9, FR#10)
- **AC#8** — Two summary methods replace four; `get_all_*` are deleted; all production and test
  callers updated; dispatch-assertion tests rewritten; suite green. (FR#11, FR#13)
- **AC#9** — `?app_key=` (empty string) returns empty/422, not all-apps data; a test pins this.
  (FR#12)
- **AC#10** — `telemetry_repository.py` lives under `core/telemetry/`; all 6 importers updated; no
  shim left behind; Pyright clean. (FR#14)
- **AC#11** — Across every unit: zero `scripts/export_schemas.py --types` diff, Pyright clean, and
  `nox -s system` + `nox -s e2e` pass locally. (FR#1–FR#14)

## Architecture

### #1107 — wrapper helper

```python
# web/utils.py
def enrich_jobs_with_live_heap(
    db_jobs: list[JobSummary],
    scheduler_service: "SchedulerService",
) -> list[JobSummary]:
    """Enrich DB job rows with live-heap data, falling back to DB rows on snapshot failure."""
    try:
        live_jobs = scheduler_service.get_all_jobs()
    except (OSError, RuntimeError, ValueError):
        LOGGER.warning("Live scheduler heap snapshot failed; returning DB rows", exc_info=True)
        return db_jobs
    return enrich_jobs_with_heap(db_jobs, live_jobs)
```

The exact fallback exception set and warning text are lifted from the current handlers
unchanged, so the behavior is identical at both call sites.

### #1108 — degradation construct

A context manager that swallows `DB_ERRORS`, logs, and sets `response.status_code = 503`:

```python
# web/dependencies.py
@contextmanager
def db_degrades_to(response: Response) -> Iterator[None]:
    try:
        yield
    except DB_ERRORS:
        LOGGER.warning("DB query failed; degrading to 503", exc_info=True)
        response.status_code = 503
```

Each handler pre-initializes its result to the failure default, runs the query (and any
processing that depends on it) inside the `with`, and returns at the tail:

```python
rows = []
with db_degrades_to(response):
    rows = await telemetry.get_listeners(...)
return rows
```

On `DB_ERRORS` the CM swallows the exception, sets 503, and control falls through to
`return rows` with `rows` still at its default. No decorator and no caller-side `return`
injection is needed — the default is just the pre-initialized value.

**Site classification — the first plan task, before any code.** The challenge proved a
two-shape split is wrong. Every one of the 17 `except DB_ERRORS` sites is classified into one of
four categories, in a table, with the migration decision per site:

- **A — Query-is-the-handler (one-line wrap).** Failure default equals the return value; nothing
  after the query. Wrap as above. The majority.
- **B — Post-query work that must be skipped on failure.** The classification criterion is *"does
  any code after the query need to be skipped when the query fails?"* — not merely "is there code
  after the query?" That code moves **inside** the `with` block; a single tail `return <default>`
  follows. Known members: `telemetry_status` (`telemetry.py:66`, returns a *different*
  `degraded=False` response on success), `app_health` (`telemetry.py:128`, computes `error_rate`
  from `agg`), and — flagged in challenge — `bus.py:get_listener_metrics` and
  `telemetry.py:app_listeners`, which call `live_execution_counts()` *outside* the current try
  block (today's early `return []` skips it; a tail-return CM would run it on the failure path).
- **C — Silent-200 best-effort sites — EXCLUDED from `db_degrades_to`.** These catch `DB_ERRORS`,
  log, and **return HTTP 200** with partial/empty data — they never set 503. Applying a
  503-setting CM would change their status code and break the byte-for-byte contract. They stay
  as their current explicit `try/except`. Members: `apps.py:get_app_manifests` and the three
  sub-queries in `telemetry.py:dashboard_app_grid`.
- **D — Multi-failure-mode site — EXCLUDED.** `executions.py:get_execution_logs` has two
  independent failure semantics (503 for the record fetch; silent `retention_expired=False` for
  the retention check, already handled inside `check_retention_expired_uuid4`). A single CM would
  conflate them. The record fetch *may* adopt `db_degrades_to`; the retention path stays as-is.
  Treated as a documented special case, not a clean adoption.

Each migrated site is checked against its existing 503/default (or 200/partial) test. Categories
C and D are the reason #1108 is "relocate the 503 policy," not "wrap all 17."

**Sequencing note:** `bus.py:get_listener_metrics` is touched again by #1095 (its if/else
dispatch collapses to one call). To avoid double-work, #1108a leaves it as explicit `try/except`
and #1095 migrates it in one step (branch-collapse + CM) — not migrated twice.

### #1108b (#1114) — storage→domain exception translation seam

The root issue beneath #1108: the HTTP layer catches raw storage exceptions. The
`TelemetryQueryService` mixins catch nothing, so `sqlite3.Error`, `OSError`, `asyncio.TimeoutError`,
and aiosqlite's closed-connection `ValueError` reach the routes unchanged, and `DB_ERRORS`
re-catches that broad tuple in 14 places. Catching `ValueError` in a handler that also runs
application logic is a footgun — a non-DB `ValueError` becomes a silent 503.

The fix translates at the boundary where only DB I/O happens:

```python
# exceptions.py
class TelemetryUnavailableError(HassetteError):
    """The telemetry store could not satisfy a read (down, slow, or closed)."""

# core/telemetry/query_service.py — the execute() context manager
@asynccontextmanager
async def execute(self, query, params=None):
    try:
        async with asyncio.timeout(self.hassette.config.database.read_timeout_seconds):
            async with self._db.execute(query, params) as cursor:
                yield cursor
    except (sqlite3.Error, OSError, ValueError, TimeoutError) as exc:
        raise TelemetryUnavailableError(str(exc)) from exc
```

Catching the broad tuple *here* is safe: `execute()` does nothing but DB I/O, so a `ValueError`
here can only be the closed-connection case. The HTTP layer then catches only
`TelemetryUnavailableError`:

```python
# dependencies.py — db_degrades_to now catches the narrow domain type
@contextmanager
def db_degrades_to(response: Response) -> Iterator[None]:
    try:
        yield
    except TelemetryUnavailableError:
        LOGGER.warning("Telemetry unavailable; degrading", exc_info=True)
        response.status_code = 503
```

Because #1108a already centralized the catch into `db_degrades_to`, this is one edit there plus
the category-C/D inline catches (~5 sites) switching `except DB_ERRORS` → `except
TelemetryUnavailableError`. `DB_ERRORS` is then deleted from the HTTP layer (migrate-callers-then-
delete); the only place that names the storage tuple is `execute()`.

**Coverage gap — not all reads route through `execute()`.** `get_all_app_summaries`
(`summary_queries.py:215-228`) runs a manual `BEGIN DEFERRED`/`ROLLBACK` transaction via
`self._db.execute()` directly, bypassing the `execute()` chokepoint — and it backs the
`dashboard_app_grid` 200-degradation site. The plan must **enumerate every read path** in the
three mixins and confirm each either routes through `execute()` or gets the same translation
wrapper. A grep for `self._db.execute` (outside `execute()` itself) is the audit. Missing one path
means a raw storage error still leaks to a handler that now only catches
`TelemetryUnavailableError` — turning a former 503 into a 500. This is the single highest-risk part
of #1108b and the reason it is its own verifiable unit.

### #1095 — query consolidation + repository move

Query consolidation is mechanically clean: the per-app and all variants are byte-identical apart
from the WHERE filter and the two bound params. Collapsing to an optional-filter signature is a
~140-line deletion across the two pairs.

**Data-escalation guard.** Once `app_key=None` means "all apps", the `bus.py:32` dispatch guard
`if not app_key:` becomes the only thing between a scoped query and a full-table scan — and it is
falsy, so an empty-string `?app_key=` routes to all-apps. Tighten to `if app_key is None:` and
add a test that `?app_key=` returns empty/422, not every app's listeners. Audit other dispatch
guards for the same falsy pattern.

**Dispatch-assertion tests.** Some tests assert on *which method was called*, e.g.
`test_telemetry.py:427-430` pairs `get_all_listeners_summary.assert_called_once()` with
`get_listener_summary.assert_not_called()`. After consolidation both paths call
`get_listener_summary`, so these assertions invert — a call-site codemod cannot fix them. The
plan includes an explicit audit for `assert_called*`/`assert_not_called`/`call_count` on the four
retiring names (plus the `AsyncMock` attribute assignments in `test_utils/web_mocks.py` and
`tests/e2e/mock_fixtures.py:629`) and rewrites them as argument-based assertions on the unified
method.

**Repository move.** `core/telemetry_repository.py` → `core/telemetry/repository.py`: 6 importers
(`command_executor.py` + 5 test files). Low churn, no layer conflict. Update imports; no shim.
(`telemetry_models.py` does **not** move — see Non-Goals.)

## Test Strategy (pin-behavior)

Per `refactoring-discipline.md`, behavior is pinned by the existing suite before structure moves.

- **#1107:** `tests/integration/web_api/test_telemetry_route.py` already covers heap-failure
  degradation for both endpoints (e.g. `TestAppJobsEnrichmentHeapFailureDegrades`). Keep these
  green; add one unit test for `enrich_jobs_with_live_heap`'s fallback path directly.
- **#1108a:** existing route tests assert 503 + default (categories A/B) or 200 + partial
  (category C) on DB failure. Keep them green across the migration; add a focused unit test for
  `db_degrades_to` (catches the degradation exception, sets 503, passes success through
  untouched). Category C sites keep their existing 200-degradation tests unchanged — the proof
  they were left alone.
- **#1108b:** add a test that a storage error raised inside any `execute()` read surfaces to the
  handler as `TelemetryUnavailableError` and still produces the same 503/200 the route gave
  before. Add the **footgun-fixed** test: a non-DB `ValueError` raised in a handler body now
  propagates as a 500, not a swallowed 503 (this is the one intended behavior change). Verify the
  `get_all_app_summaries` direct-`_db.execute` path is covered — a forced storage error there must
  still degrade `dashboard_app_grid` to its 200-partial, not 500.
- **#1095:** the four query methods have extensive integration coverage
  (`test_telemetry_query_service.py`, `test_global_jobs_and_service_info.py`,
  `test_health_aggregates_and_global_listeners.py`, the `web_api` route tests). Most call sites
  migrate mechanically (call changes, assertion identical). The exception is the
  dispatch-assertion tests (see #1095 Architecture) — those are rewritten as argument-based
  assertions, not kept identical. Add a test for the `app_key is None`-vs-empty-string guard.
- **Schema freshness:** run `uv run python scripts/export_schemas.py --types` and confirm zero
  diff. Run `uv run pyright`. Per CLAUDE.md, this touches `core/` so run `nox -s system` and
  `nox -s e2e` locally before the PR (the repository move and query consolidation are exactly the
  kind of boundary change those suites guard).

## Impact / Blast Radius

| Unit | Prod files | Test/mock files | Risk |
|---|---|---|---|
| #1107 | 3 (`utils.py`, `scheduler.py`, `telemetry.py`) | 1 | Low |
| #1108a | up to 7 (`dependencies.py` + 5 routes) + `web/CLAUDE.md` | ~5 | Medium — control-flow per site; categories C/D excluded |
| #1108b | 3 (`exceptions.py`, `query_service.py`, `dependencies.py`) + ~5 category-C/D catches | ~3 | Medium — coverage gap (`get_all_app_summaries` bypasses `execute()`); one intended behavior change |
| #1095 query | 4 (`registration_queries.py` + 3 route callers) | ~25 call sites + `web_mocks.py` + dispatch-assertion rewrites | Medium — wide test churn |
| #1095 repo move | 1 moved + 1 prod importer | 5 | Low — mechanical, no layer conflict |

Dropping the `telemetry_models.py` move (30+ importers) and the SessionManager write-repo removed
the two highest-cost / highest-risk parts of the original #1095 scope. The added #1108b seam is
small in file count but carries the cluster's one deliberate behavior change and the
`execute()`-bypass coverage gap — it earns its own verifiable unit.

## Challenge Resolutions

Recorded from the `/mine-challenge` pass (critics: Operational Resilience, Structural Minimalist,
Contract & Caller). Each HIGH finding and its resolution:

- **F1 (silent-200 sites):** category C added; `apps.py:get_app_manifests` and
  `dashboard_app_grid` excluded from `db_degrades_to`. **Adopted.**
- **F2 (schemas layer invariant):** `telemetry_models.py` move dropped; it stays in `schemas/`.
  **Adopted.**
- **F3 (SessionManager write-repo):** dropped entirely. **Adopted.**
- **F4 (dispatch-assertion tests):** explicit assertion-audit task added to #1095. **Adopted.**
- **F5 (`app_key` falsy guard):** tighten `bus.py:32` to `if app_key is None:` + guard test.
  **Adopted.**
- **F6 (undercounted category-B sites):** corrected the classification criterion to "must be
  skipped on failure"; added `get_listener_metrics` and `app_listeners`. **Adopted.**
- **F7 (CLAUDE.md trap):** the doc update must show the wrong-shape warning + name category-C
  exceptions. **Adopted.**
- **F9 (`bus.py` re-touched by #1095):** sequencing note added — #1108 leaves it for #1095.
  **Adopted.**

## Alternatives Considered

- **Move `telemetry_models.py` and amend the `schemas/` invariant.** Rejected — the invariant is
  the cycle-breaker that lets `core`/`web`/`cli` share models; weakening it for co-location
  tidiness is a bad trade. The file is not actually misplaced.
- **Keep `get_all_*` as thin wrappers** that call the unified method with `app_key=None`.
  Rejected — it preserves the duplicated *surface* (and all the test call sites) without
  preserving the duplicated *body*. The win is the single body; the wrappers forfeit half of it
  for no behavior gain.
- **A `db_degrades_silently()` no-status CM variant for category-C sites.** Rejected — two
  constructs to learn for ~4 sites; explicit `try/except` at those sites is clearer than a second
  near-identical CM.

## Acceptance-Criteria Deviation (#1095)

This scope satisfies AC-1 (two methods replace four) but deliberately departs from AC-2 (the
issue asked to move `telemetry_models.py` and route SessionManager writes through a repository).
The departure and its rationale (the `schemas/` cycle-breaker invariant; the speculative
single-consumer write-repo) are recorded as a comment on #1095 so the deviation from the
2026-06-19 audit is auditable, not silent.
