# Design Critique: ui-rebuild PR — 2026-03-20

Adversarial design critique of the ui-rebuild branch. Three independent critics (Skeptical Senior Engineer, Systems Architect, Adversarial Reviewer) analyzed the PR. Findings cross-referenced for confidence.

## Findings

### 1. SQL Query Duplication Is a Schema-Drift Time Bomb — CRITICAL

**What's wrong**: Every query method in `TelemetryQueryService` contains two full independent copies of its SQL — one session-filtered, one unfiltered. Five methods x 2 variants = 10+ SQL strings maintained in parallel.
**Why it matters**: Adding any new filter (date range, status) requires edits in two places per method. This has already produced an inconsistency: `get_recent_errors`, `get_slow_handlers`, and `get_session_list` return `list[dict]` while every other method returns typed models.
**Evidence (code)**:
- `telemetry_query_service.py:62-108` — `get_listener_summary` session/all-time fork
- `telemetry_query_service.py:163-217` — `get_all_app_summaries` duplicates entire SELECT bodies
- `telemetry_query_service.py:378-460` — `get_recent_errors`: 82 lines, 4 SQL strings for 1 method
**Raised by**: Senior + Architect + Adversarial
**Better approach**: Extract `_session_clause(alias, session_id) -> (fragment, params)` and compose one query per method.
**Design challenge**: When the next column is added to `handler_invocations`, how will the author know to update every SQL variant?

---

### 2. Stats Poll DOM Mutation Is Architectural Debt — CRITICAL

**What's wrong**: The hidden-div + 70-line manual DOM patching pattern in `live-updates.js:146-218` is a workaround for HTMX and Alpine.js being unable to coexist on stateful rows. The patching logic finds elements by text content substring (`indexOf("avg")`) and CSS class names.
**Why it matters**: Every future real-time update on a stateful row faces the same fork. The text-content search breaks on any wording change or i18n.
**Evidence (code)**:
- `live-updates.js:192` — `el.textContent.indexOf("avg")` finds element by rendered text
- `live-updates.js:168` — `.ht-meta-item[title='Total invocations']`
- `live-updates.js:173` — `.ht-meta-item--strong.ht-text-danger`
- `macros/ui.html:73-78` — the HTML these selectors target
- `app_detail.html:114-122` — hidden div exists solely for this workaround
- `partials.py:160-170` — dedicated endpoint doubling DB reads
**Raised by**: Senior + Architect + Adversarial
**Better approach**: Add `data-stat` attributes to handler row spans. JS queries `[data-stat="avg-duration"]` instead of text content. Longer term: push stat deltas through existing WebSocket channel.
**Design challenge**: If idiomorph already prevents unnecessary DOM mutation for identical content, what specifically about Alpine.js expand state makes handler rows ineligible for morphing?

---

### 3. `get_recent_errors` Returns `list[dict]` — Typed Model System Incomplete — CRITICAL

**What's wrong**: Three methods (`get_recent_errors`, `get_slow_handlers`, `get_session_list`) return `list[dict]` in a module whose stated purpose is eliminating "column rename -> silent template failure." The merged handler+job error list contains two structurally different objects distinguished only by an injected `kind` string key.
**Why it matters**: The highest-risk methods bypass the type safety the PR specifically introduced.
**Evidence (code)**:
- `telemetry_query_service.py:376` — `-> list[dict]`
- `telemetry_query_service.py:456-460` — `kind="handler"` and `kind="job"` injected into raw dicts
- `telemetry_models.py:1-5` — module docstring explicitly states the protection goal
- `telemetry_query_service.py:462, 481` — two more `list[dict]` returns
**Raised by**: Senior + Architect + Adversarial
**Better approach**: Discriminated union: `HandlerError(kind=Literal["handler"])` + `JobError(kind=Literal["job"])` with `RecentError = HandlerError | JobError`.
**Design challenge**: Is this an in-progress migration or an implicit signal that typed models were abandoned for "complex" shapes?

---

### 4. `context.py` Is a God Module — HIGH

**What's wrong**: 176 lines mixing five concerns: CSS classification, string formatting, async data fetching, template context building, and session ID access.
**Why it matters**: When a designer changes the "warn" threshold from 5% to 2%, they edit a file named "context helpers."
**Evidence (code)**:
- `context.py:25-49` — CSS classifiers registered as Jinja globals
- `context.py:91-116` — `compute_health_metrics` re-sums aggregates the DB already computed
- `context.py:147-175` — `compute_app_grid_health` is an async data fetch with exception swallowing
**Raised by**: Architect + Adversarial
**Better approach**: Split into `classifiers.py`, `formatters.py`, keep `context.py` for route-level assembly only.
**Design challenge**: When a designer wants to change the "warn" threshold, which file should they edit?

---

### 5. Phased Startup Is a Symptom Fix — HIGH

**What's wrong**: Three layers of defense for one invariant: phased startup sequencing, `_safe_session_id()` returning 0, sentinel filtering dropping records. The invariant is not structurally enforced.
**Why it matters**: A new service can violate the invariant silently. The fallback-to-zero path is the live fallback for slow-disk scenarios.
**Evidence (code)**:
- `core.py:292` — same timeout for both phases
- `command_executor.py:58-63` — `_safe_session_id()` returns 0
- `command_executor.py:504-520` — sentinel filtering, "REGRESSION" log
**Raised by**: Senior + Adversarial
**Better approach**: Inject session_id as a value or buffer records until available.
**Design challenge**: If `_safe_session_id` returning 0 "should not happen after phased startup," why does the code path exist?

---

### 6. `db_id is None` Dispatch Bifurcation — HIGH

**What's wrong**: Both `BusService._dispatch` and `SchedulerService.run_job` branch on `db_id is None`. For regular listeners, the route is added before `db_id` is set — TOCTOU race window.
**Why it matters**: First N invocations during startup may be permanently unrecorded.
**Evidence (code)**:
- `bus_service.py:127-128` — route added before `db_id` assignment
- `bus_service.py:234` — `if listener.db_id is None:`
- `scheduler_service.py:255` — `if job.db_id is None:`
**Raised by**: Senior + Architect
**Better approach**: Make `CommandExecutor.execute` own the decision via `record_telemetry` flag or Null Object executor.
**Design challenge**: Is it acceptable that early invocations are permanently unrecorded?

---

### MEDIUM Findings

| # | Finding | Raised by |
|---|---------|-----------|
| 7 | Dashboard 5 sequential async DB calls | Senior |
| 8 | `_execute_handler`/`_execute_job` identical 80-line methods | Architect |
| 9 | WebSocket delivers status instantly, stats poll lags 5s | Adversarial |
| 10 | `TelemetryQueryService` reads from write connection | Adversarial |
| 11 | 501 placeholder routes ship as API surface | Adversarial |
| 12 | `reschedule_job` bare `assert` on time source | Senior |
| 13 | Paired route duplication in partials.py | Architect |
| 14 | Health strip over-fetches full summaries for 4 scalars | Architect |
| 15 | `safe_session_id` catches `AttributeError` | Senior |

## Appendix: Individual Critic Reports

These files contain each critic's unfiltered findings and are available for the duration of this session:

- Senior Engineer: `/tmp/claude-mine-challenge-tsvMrL/senior.md`
- Systems Architect: `/tmp/claude-mine-challenge-tsvMrL/architect.md`
- Adversarial Reviewer: `/tmp/claude-mine-challenge-tsvMrL/adversarial.md`
