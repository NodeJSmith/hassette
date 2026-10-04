# Design: Unify app health computation

**Date:** 2026-10-04
**Status:** ratified
**Mode:** sketch

## Summary

Issue #2508. The per-instance health endpoint (`GET /api/telemetry/app/{app_key}/health`, `AppHealthResponse`) and the Apps grid (`GET /api/telemetry/dashboard/app-grid`, `DashboardAppGridEntry`) compute app health separately. Two discrepancies are not explained by scope (D13), and the two queries treat executions of removed handlers and jobs differently (D14). This change gives app health one model (`AppHealth`) and one computation in `src/hassette/core/telemetry/`, before #2386 pins the shape.

The generated artifacts are regenerated with `uv run python scripts/export_schemas.py --types` (writes `frontend/openapi.json`, `frontend/ws-schema.json` and the generated TS under `frontend/src/api/`), and frontend code naming a changed schema is updated to match.

**Calibration:** hassette is greenfield with about three known users, and no consumer is known to depend on these models, the HTTP shapes, or the CLI JSON. Decisions optimize for the correct model, not for minimizing breakage. Breaks are still listed in this ledger's D9 footer.

**Origin:** split from spec 122 (`design/specs/122-wire-contract-tightening/design.md`), where every decision below was ratified, challenged and combed together. Decision numbers keep their spec-122 ids. Order of the four ledgers: 123 (vocabulary) and 124 (health) are independent; 125 (apps resource and grid) builds on 124; 126 (naming and docs) goes last. All four land before #2386.

Related: #1022 asked to exclude removed registrations' executions from the all-apps rollup. D14 supersedes it (count in both scopes); this PR closes #1022 with that reasoning. #2040 (one frontend error-rate definition) is adjacent but frontend-only and stays separate.

Out of scope: the grid's `{app, activity}` nesting, path and degradation marker (spec 125); naming of other wire classes (spec 126).

## Decisions

### D13: One shared app-health model, computed in one place

This comes from Finding 9 of the sketch challenge, which chose to extract a shared sub-model.

What the two models share today:
- `AppHealthResponse` (`wire/src/hassette_wire/telemetry.py`) is served per instance by `GET /api/telemetry/app/{app_key}/health` (`app_health` in `src/hassette/web/routes/telemetry.py`) and read by `hassette app health`.
- It and the grid's activity fields compute the same concept the same way: `compute_error_rate()` → `classify_error_rate()` / `classify_health_bar()`.
- `last_activity_ts` is the latest handler or job execution in both.

Scope is the only legitimate difference (one instance vs. all instances of an app). Two discrepancies are not explained by scope:
- The grid's `avg_duration_ms` is the handler-only average (`build_app_summaries` in `src/hassette/core/telemetry/helpers.py` takes it from the listener query alone, `COALESCE`d to `0.0`). The per-instance model has `handler_avg_duration`/`job_avg_duration`, and job averages exclude `skipped`.
- The two queries apply different removed-registration rules (D14).

**Deciding factor:** one definition of app health, computed one way, with scope as the only difference.

| | A: Shared `AppHealth` record | B: Keep both shapes, document the scope difference |
|---|---|---|
| `AppHealth` fields | `error_rate`, `error_rate_class`, `health_status`, `last_activity_ts`, `handler_avg_duration_ms: float \| None`, `job_avg_duration_ms: float \| None`. The two averages are renamed from `handler_avg_duration`/`job_avg_duration`, and become `None` when nothing ran | Unchanged |
| Per-instance endpoint | Returns `AppHealth`, replacing `AppHealthResponse` (a record under spec 126's D1 rule) | Unchanged |
| Grid row (`DashboardAppGridEntry`) | Drops its loose `avg_duration_ms`, `error_rate`, `error_rate_class`, `health_status` and `last_activity_ts` and gains `health: AppHealth`. Spec 125 later nests the activity fields, including `health`, under `activity` | Today's flat fields |
| Computation | One server helper builds `AppHealth` from either aggregate (per-instance `AppHealthAggregates`, per-app `AppHealthSummary`), and the per-app summary gains a job average | Two |
| Mislabelled grid average | Replaced by the handler/job split | Documented |
| Debt left | None | Two known inconsistencies in the pinned contract |

Behavior to pin:
- For the same app, instance set and window, the per-instance and per-app health agree when the app has one instance.
- An average with no executions in the window is `None`.
- The job average excludes `skipped` executions in both scopes.

Consumers updated:
- `toAppRow()`/`AppRow` and the Apps page duration cell (`frontend/src/utils/app-data.ts`, `frontend/src/pages/apps-table-row.tsx`)
- the `hassette dashboard` and `hassette app health` columns (`src/hassette/cli/commands/status.py`, `app.py`)

**Recommendation:** A, because B publishes two known inconsistencies into the contract #2386 pins.
**Pick B instead if** you'd rather keep this change out of the telemetry queries.
**Reversibility:** hard after #2386.
**Ratified:** Chose a shared `AppHealth` record computed in one place (A) over documenting both shapes (B), to give app health one definition with scope as the only difference, accepting telemetry query changes in this PR (challenge Finding 9).

### D14: Do executions of removed handlers and jobs count toward app health?

Today `get_app_health_aggregates` (`src/hassette/core/telemetry/summary_queries.py`) excludes executions whose listener or job has `removed_at` set. `get_all_app_summaries` counts them, because its activity queries read the raw `listeners`/`scheduled_jobs` tables, while its `handler_count`/`job_count` use the `active_*` views. D13's single computation needs one rule.

**Deciding factor:** a window's health reflects what actually ran in that window.

| | A: Count them in both | B: Exclude them in both |
|---|---|---|
| Matches what ran in the window | Yes | No: errors from a handler removed mid-window vanish |
| Health right after a reload that removed a failing handler | Still shows the window's errors | Looks healthy immediately |
| `handler_count`/`job_count` | Active-only (they describe what is registered) | Active-only |

Behavior to pin: an error execution of a handler removed later in the window counts toward health in both the per-instance and per-app scopes, while `handler_count` excludes the removed handler.

**Recommendation:** A, because health over a window is a statement about executions, and a removed registration's executions still happened.
**Pick B instead if** you want health to describe only the currently registered code.
**Reversibility:** easy.
**Ratified:** Chose counting removed registrations' executions in both queries (A) over excluding them (B), so window health reflects what ran, accepting that health stays affected by a removed handler's errors until they leave the window.

### D9: Is the PR a breaking change (`feat!` with a `BREAKING CHANGE:` footer)?

**Deciding factor:** the changelog tells users what actually breaks. Spec 122's D9 ratified `feat!` with one `BREAKING CHANGE:` footer naming every break; this ledger's list is its share:
- On `GET /api/telemetry/app/{app_key}/health`, the response model becomes `AppHealth`; `handler_avg_duration`/`job_avg_duration` become `handler_avg_duration_ms`/`job_avg_duration_ms` and are `null` when nothing ran (D13)
- Grid rows replace `avg_duration_ms` (handler-only), `error_rate`, `error_rate_class`, `health_status` and `last_activity_ts` with `health: AppHealth` (D13)
- Per-instance health starts counting executions of removed handlers and jobs (D14)
- The `hassette app health` and `hassette dashboard` duration columns change to the handler/job averages (D13)

Any compat-ignore lines come from `tools/check_wire_compat.py`'s output, and the header of `tools/wire_compat_ignore.txt` pairs them with `!` plus a footer.

**Recommendation:** `feat!` with exactly one `BREAKING CHANGE:` footer at the end of the PR body, naming every item above.
**Reversibility:** easy until merge.
**Ratified:** Chose `feat!` with one footer over `refactor:`, to report the health shape, field and semantics changes.

## Assumed

- **Package isolation.** `hassette_wire` cannot import `hassette`, so any vocabulary shared with the server must be defined in wire. Evidence: `wire/src/hassette_wire/REVIEW.md` ("Package Isolation"); `wire/pyproject.toml` depends on `pydantic` only.
- **Generated TS.** `frontend/src/api/generated-types.ts`, `ws-types.ts` and `ws-validator.generated.ts` are regenerated, not hand-edited. Evidence: `scripts/export_schemas.py` docstring.
- **Open vocabularies.** `AppHealth`'s `error_rate_class` and `health_status` keep the `Open*` aliases the current models use (`OpenErrorRateClass`, `OpenHealthStatus`), as response fields do per spec 121. Evidence: `wire/src/hassette_wire/telemetry.py`; `design/specs/121-wire-lenient-unknown-enums/design.md`.
- **Required checks.** `tools/check_wire_compat.py` runs against the latest `v*` tag (v0.55.0) in both directions, and deliberate breaks go in `tools/wire_compat_ignore.txt` verbatim from its output. Evidence: the module docstring and the file header.
- **CLI column contract.** `tests/snapshots/cli_columns.json` records every CLI table's columns, and `tools/check_cli_drift.py` fails when it drifts. Evidence: `tests/snapshots/cli_columns.json` ("Invoc/1h" entry).

## Build

- [x] Implementation and tests committed
- [x] Docs
- [ ] Ship-time challenge

**Calls made during the build:**
- `AppHealthAggregates` moved from `core/telemetry/helpers.py` to `schemas/summary_models.py` as a pydantic model, and `AppHealthSummary` composes it as `aggregates` next to `handler_count`/`job_count`: both scopes then feed the one builder the same input type, and `summary_models` can't import from `core/telemetry` (`helpers.py` already imports `summary_models`).
- `build_app_health` lives in `src/hassette/web/telemetry_helpers.py`, beside the `compute_error_rate`/`classify_*` functions it composes. The aggregation itself (counts, averages, the removed-registration rule) stays in `core/telemetry/summary_queries.py`.
- The Apps page has no duration cell, so the frontend consumer is `toAppRow()` reading `health.last_activity_ts`; `AppRow.error_rate` had no reader and was dropped.
- The grid-entry vocabulary tests in `tests/unit/test_model_types.py` were removed: the grid row no longer has its own `health_status`/`error_rate_class`, and `AppHealth`'s tests cover both.

## Addendum
