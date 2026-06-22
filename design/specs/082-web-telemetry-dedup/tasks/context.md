# Context: Collapse web/telemetry duplication (#1107, #1108, #1114, #1095)

## Problem & Motivation

Three duplications and one architectural root have accumulated in the `web/` and
`core/telemetry/` layers. #1107: the live-heap enrichment wrapper is copied across two job
routes. #1108: a `try/except DB_ERRORS → 503/200` block is repeated 17 times across 6 route
files. #1095: two pairs of ~140-line CTE query methods differ only by a WHERE clause, and a
telemetry write helper sits outside `core/telemetry/`. Collapsing #1108 surfaced the root
(#1114): the HTTP layer catches raw storage exceptions, and `DB_ERRORS` over-catches `ValueError`,
silently converting non-DB errors into 503s. Each duplication is a place a policy can drift out of
sync; the root is a layering leak. All changes are behavior-preserving except one deliberate fix
(non-DB `ValueError` → 500).

## Visual Artifacts

None.

## Key Decisions

1. **Strict sequencing, four units:** #1107 → #1108a → #1108b (#1114) → #1095. They share write
   targets (`scheduler.py`, `telemetry.py`, `bus.py`, `dependencies.py`), so they serialize — never
   parallelize. Each unit is its own commit with the full suite green at its boundary.
2. **#1108a before #1108b is load-bearing.** Centralizing the catch into `db_degrades_to` first
   makes the #1108b seam swap a near-one-line change instead of editing 14 handlers twice.
3. **Per-site classification before any #1108 code.** All 17 `except DB_ERRORS` sites sort into
   A (one-line wrap), B (post-query work moves inside the `with`), C (silent-200, EXCLUDED), or
   D (multi-failure, EXCLUDED). The criterion for B is *"does code after the query need to be
   skipped on failure?"* — not "is there code after the query?"
4. **`db_degrades_to` shape:** a context manager that swallows the degradation exception, logs,
   and sets 503. Callers pre-initialize the result to the failure default and return at the tail.
   No decorator, no forced return.
5. **Storage→domain translation at the service boundary (#1114).** `TelemetryUnavailableError`
   is raised from every `TelemetryQueryService` read path; the HTTP layer catches only that narrow
   type. Catching the broad storage tuple is safe *only* at `execute()`, where nothing but DB I/O
   runs — which is why the per-handler `except DB_ERRORS` (over-catching `ValueError`) was wrong.
6. **#1095 scope trimmed by challenge:** query consolidation + `telemetry_repository.py` move only.
   The `telemetry_models.py` move and the SessionManager write-repo were dropped (see Non-Goals).
7. **The 503-vs-200 split is a real, principled contract, not drift.** Sites whose response has a
   non-DB "spine" (from `runtime.get_all_manifests_snapshot()`) degrade to 200-partial; sites where
   the DB query *is* the whole response degrade to 503. The frontend deliberately reads 503
   (`use-telemetry-health.ts`) to show a "telemetry degraded" banner. Preserve this exactly.

## Constraints & Anti-Patterns

- **Behavior-preserving refactor.** The existing test suite is the pin (`refactoring-discipline`).
  Do NOT change any response shape or HTTP status except the one intended change (FR#10: non-DB
  `ValueError` → 500). Category-C/D sites keep their exact current status codes.
- **Do NOT** move `telemetry_models.py` (it belongs in `schemas/`, the cycle-breaker — moving it
  would force `schemas/__init__.py` to import `core`, violating `schemas/__init__.py:1-11`).
- **Do NOT** extract SessionManager's inline SQL behind a repository (single consumer; the
  `_do_cleanup_once_listeners` `BEGIN`/two-DELETE transaction at `session_manager.py:236-240` has a
  real atomicity constraint).
- **Do NOT** apply `db_degrades_to` to category-C sites (`apps.py:get_app_manifests`, the three
  `dashboard_app_grid` sub-queries) or category-D (`executions.py:get_execution_logs`) — that would
  change their status code from 200 to 503.
- **Do NOT** leave a compat shim when moving `telemetry_repository.py` (`coding-style.md`: migrate
  callers then delete).
- **Do NOT** parallelize the four units or reorder them.
- No `from __future__ import annotations`; no `Optional[X]` (use `X | None`); no lazy imports.

## Design Doc References

- `## Problem` — the four problems (items 1-3 duplications, item 4 the storage-exception leak).
- `## Sequencing` — the four-unit order and why 1108a precedes 1108b.
- `## Architecture → #1108a` — the four-category site classification table and the CM shape.
- `## Architecture → #1108b (#1114)` — the translation seam, code sketch, and the
  `get_all_app_summaries` coverage gap.
- `## Architecture → #1095` — query consolidation, the `app_key is None` guard, dispatch-assertion
  tests, repository move.
- `## Test Strategy (pin-behavior)` — what each unit must keep green and what to add.
- `## Non-Goals` — the dropped `telemetry_models` move and SessionManager repo, with rationale.
- `## Challenge Resolutions` — the eight findings and how each was resolved.

## Convention Examples

None — no convention examples captured during discovery. Follow existing patterns in the touched
files: `web/utils.py` for helper style, `web/dependencies.py` for the `DB_ERRORS` definition and
dependency aliases, `exceptions.py` (`HassetteError` base at line 33, multi-inheritance precedent
like `EntityNotFoundError(ValueError, HassetteError)`), and `core/telemetry/query_service.py` for
the `execute()` context manager.

## Verification (all units)

- Per unit: `uv run pyright` clean; the affected test files green.
- At each unit boundary (core-touching): `uv run python scripts/export_schemas.py --types` produces
  zero diff; `uv run nox -s system` and `uv run nox -s e2e` pass locally (per CLAUDE.md, required
  for `core/` changes). Use an explicit `-n N` for any xdist run, never `-n auto`.
