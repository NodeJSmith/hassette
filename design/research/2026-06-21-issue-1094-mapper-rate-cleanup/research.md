# Research Brief: Simplify web response mappers and unify health-rate math (Issue #1094)

**Initiated by**: Validate the three cleanup claims in issue #1094 against the code, and scout the surrounding `web/` + `telemetry` neighborhood for additional bundleable cleanups. Pure code-reading refactor investigation, no prototypes.

## Summary

The ticket is **mostly accurate but mis-scoped in its framing**, and it is a **small-to-medium** job. Verdicts:

- **Item 1 (reduce mapper boilerplate via `model_validate(from_attributes=True)` / `model_copy`)** — PARTIALLY CONFIRMED. The field-by-field copying is real and verbose, but only **two of the six mappers** are clean candidates (`instance_response_from`, `to_listener_with_summary`), and even those need post-construction overrides for computed fields. The other four mappers transform structure (merge lists, build nested children, rename fields) and won't collapse cleanly. This is a genuine but modest win, not a wholesale rewrite.
- **Item 2 (unify duplicated error-rate/success-rate math)** — CONFIRMED, and stronger than the ticket states. There are **four** rate computations, they are **inconsistent in clamping** (one clamps to 100, the dead property does not), and the `AppHealthSummary.error_rate`/`success_rate` properties are **confirmed dead code** (zero external references). This is the highest-value part of the ticket.
- **Item 3 (move inline config mapping into `mappers.py`)** — CONFIRMED. `routes/config.py` contains a 40-line hand-built nested `ConfigResponse` that is pure mapping and belongs in `mappers.py`.

**Headline recommendation**: Do all three, plus delete the dead properties and unify the inline `success_rate` math in `routes/telemetry.py`. This is one cohesive PR that keeps the JSON shape identical (low risk). Defer anything that touches response-model *shape* (none required here) and resist gold-plating the four structural mappers that don't reduce cleanly.

---

## Goal A findings

### Item 1 — Reduce mapper bodies via `model_validate(from_attributes=True)` / `model_copy` — **PARTIALLY CONFIRMED**

The field-by-field copying is present and verbose, but the auto-mapping only works cleanly where source and target field names align and there are no structural transforms. Mapper-by-mapper:

| Mapper | File:line | Source → Target | Auto-map verdict |
|---|---|---|---|
| `instance_response_from` | `mappers.py:40-51` | `AppInstanceInfo` (dataclass) → `AppInstanceResponse` | **CLEAN candidate.** All 8 target fields exist on source by the same name. Source has extra `error: Exception` (`app_snapshots.py:22`) which `from_attributes=True` simply ignores. `status` is a `ResourceStatus` enum on both sides — validates fine. |
| `to_listener_with_summary` | `mappers.py:174-230` | `ListenerSummary` → `ListenerWithSummary` | **CANDIDATE with overrides.** 33 fields copied 1:1; field names align (verified against `models.py:296-337` and `telemetry_models.py:62-106`). Four fields are NOT on the source and must be set via override: `listener_kind` (computed by `listener_kind_from_topic`), `handler_summary` (computed by `format_handler_summary`), `suppressed_count`/`dropped_count`/`backpressure_dropped_count` (from `live_counts`). Pattern: `ListenerWithSummary.model_validate(ls, from_attributes=True).model_copy(update={...4 computed...})`. Note: source field `listener_id` maps to target `listener_id` (same name — OK). |
| `app_status_response_from` | `mappers.py:54-67` | `AppStatusSnapshot` → `AppStatusResponse` | **WON'T auto-map.** Renames: `total_count→total`, `running_count→running`, `failed_count→failed`. Merges `running + failed` lists into one `apps` list (`mappers.py:60`). Structural transform — leave as-is. |
| `app_manifest_list_response_from` | `mappers.py:70-106` | `AppFullSnapshot` → `AppManifestListResponse` | **WON'T auto-map.** Builds nested `AppManifestResponse` children, each building nested `AppInstanceResponse` children (`mappers.py:78-96`), plus a pyright cast on `status`. The inner `AppManifestResponse` construction (`mappers.py:82-95`) is *itself* a near-1:1 copy of `AppManifestInfo` and could use `from_attributes` for the scalar fields with an `instances=` override — a secondary micro-win. |
| `system_status_response_from` | `mappers.py:109-136` | `SystemStatus` → `SystemStatusResponse` | **WON'T auto-map cleanly.** Builds nested `BootIssueResponse` and `ServiceInfoResponse` lists (`mappers.py:111-124`) with a pyright cast on service `status`. The top-level scalar fields align, so `from_attributes` + `model_copy(update={boot_issues, services})` would work, but the nested-list construction dominates the body — marginal benefit. |
| `connected_payload_from` | `mappers.py:147-158` | `SystemStatus` → `ConnectedPayload` | **Borderline.** 4 fields, all present on source by name. `from_attributes=True` works (ConnectedPayload is a strict subset). Tiny body already; the win is cosmetic. |

**Blocking specifics the ticket should know:**
- `from_attributes=True` reads attributes by name; it will silently leave target defaults in place for any field the source lacks. The existing test `test_to_listener_with_summary_thread_leaked_passthrough` (`test_mappers.py:338-348`) explicitly exists to catch "field added to source but not copied here → silently 0 in the API." **`model_validate(from_attributes=True)` would make that silent-default failure mode *easier* to hit, not harder** — because the explicit field list (the thing that currently makes a missing copy a visible omission) disappears. This is a real trade-off, not a pure win. The mitigation is that the existing passthrough tests stay green only if names align.
- The pyright `cast(...)` calls on `status` fields (`mappers.py:89`, `mappers.py:118`) exist because the source `status` is a plain `str` while the target is a `Literal`. `model_validate` would validate the literal at runtime instead, removing the need for the cast on those nested models — a small bonus.

**Conclusion**: Real but modest. Two clean candidates (`instance_response_from`, `to_listener_with_summary`), two borderline (`connected_payload_from`, the nested `AppManifestResponse` build), two that should stay field-by-field (`app_status_response_from`, the list-building parts of `system_status_response_from`). Do not force the structural ones.

### Item 2 — Unify duplicated error-rate/success-rate math — **CONFIRMED (stronger than stated)**

There are **four** distinct rate computations, and they are **inconsistent**:

1. **`compute_error_rate()`** — `telemetry_helpers.py:24-51`. The canonical helper. Denominator = `total_invocations + total_executions`; returns `min((failures / total) * 100, 100.0)` — **clamped to 100**.
2. **`AppHealthSummary.error_rate` property** — `telemetry_models.py:44-51`. Same formula (`failures = total_errors + total_timed_out + total_job_errors + total_job_timed_out`), but returns `failures / total * 100` — **NOT clamped**. Inconsistent with #1.
3. **`AppHealthSummary.success_rate` property** — `telemetry_models.py:53-59`. `100.0 - self.error_rate` (so also unclamped on the low end; can go negative if error_rate > 100).
4. **Inline `success_rate` in `routes/telemetry.py`** — computed by hand in **two** route spots:
   - `health_status_from_summary` (`telemetry.py:97-102`): `success_rate = ((total - failures) / total) * 100`, then `classify_health_bar`.
   - `app_health` route body (`telemetry.py:147-157`): recomputes `total`, `handler_errors`, `job_errors`, calls `compute_error_rate`, then **separately** computes `success_rate = ((total - errors) / total * 100) if total > 0 else 100.0` inline rather than deriving it from the error rate.

**Dead-code verification (the ticket's specific claim):**

The `AppHealthSummary.error_rate` and `success_rate` properties are **CONFIRMED DEAD CODE**:
- `success_rate` — grep across `src/` and `tests/` finds **zero** references outside its own definition (`telemetry_models.py:54`). Not used anywhere.
- `error_rate` (the property) — the **only** reference is `success_rate` itself (`telemetry_models.py:59: return 100.0 - self.error_rate`). No route, no template, no test, no e2e mock reads it. The `frontend/src/utils/app-data.ts:60` hit (`error_rate: g?.error_rate ?? 0`) is a **different** `error_rate` — the `DashboardAppGridEntry.error_rate` *field* (`models.py:371`), populated by `error_rate_from_summary` (`telemetry.py:105-112`, which calls `compute_error_rate`, the clamped helper), not by the dead property.
- The live code path that produces every user-visible error rate is `error_rate_from_summary` → `compute_error_rate` (clamped). The two model properties are an orphaned parallel implementation.

**Inconsistency confirmed**: the dead property (#2) is unclamped while the live helper (#1) is clamped. If anything ever wired the property back up, it would produce >100% rates on mismatched counters — exactly the case `compute_error_rate` was written to prevent (see `test_compute_error_rate_clamped_to_100_when_errors_exceed_total`, `test_telemetry_helpers.py:104-112`). Deleting the properties removes the inconsistency at the source.

**Conclusion**: CONFIRMED. Delete the two dead properties; route the inline `success_rate` math in `routes/telemetry.py` through a single shared helper (e.g. add `compute_success_rate()` next to `compute_error_rate` in `telemetry_helpers.py`, or derive success from the clamped error rate). Both inline spots (`telemetry.py:101` and `telemetry.py:157`) should use it.

### Item 3 — Move inline config mapping out of `routes/config.py` — **CONFIRMED**

`routes/config.py:23-63` builds a `ConfigResponse` by hand, including six nested sub-responses (`WebApiConfigResponse`, `LoggingConfigResponse`, `LifecycleConfigResponse`, `AppsConfigResponse`, `SchedulerConfigResponse`, `FileWatcherConfigResponse`). It is ~40 lines of pure field-copying from `hassette.config` (`cfg`) — exactly the kind of mapping that lives in `mappers.py` per the module's own docstring (`mappers.py:1-6`: "Web routes call these instead of receiving pre-mapped response objects"). The route has no other logic; the whole body is the mapping.

A `config_response_from(cfg)` mapper would move all of `config.py:23-62` into `mappers.py`, leaving the route as a one-liner like the `health.py` routes (`health.py:13-15`). Note this is mostly **renamed/restructured** fields (`cfg.web_api.run → run`, etc.) with `str()` coercions on paths (`config.py:28-29`, `config.py:52`) and a `list(...)` copy (`config.py:36`) — so `from_attributes` won't fully collapse it, but it still belongs in `mappers.py` regardless of whether it shrinks.

**Conclusion**: CONFIRMED. Pure relocation; keeps JSON shape identical.

---

## Goal B findings — additional bundleable cleanups

### BUNDLE candidates (same neighborhood, low risk, JSON shape unchanged)

1. **Delete `AppHealthSummary.error_rate` + `success_rate` properties** — `telemetry_models.py:44-59`. Confirmed dead (see Item 2). **BUNDLE** — it is the cleanest behavior-preserving deletion in the whole investigation and directly serves the ticket's "unify rate math" goal. Update: no callers to migrate; `subtract-first` applies.

2. **Add `compute_success_rate()` helper and route the two inline computations through it** — `telemetry.py:101`, `telemetry.py:157`. Both hand-roll `((total - failures) / total) * 100` with a zero guard. **BUNDLE** — directly the ticket's Item 2; small and testable (the helper test file `test_telemetry_helpers.py` already exists and is the natural home).

3. **`instance_response_from` + `to_listener_with_summary` via `model_validate(from_attributes=True)`** — `mappers.py:40-51`, `mappers.py:174-230`. **BUNDLE** — the two clean Item-1 candidates. Keep the existing passthrough tests as the safety net.

4. **`config_response_from` mapper extraction** — `config.py:23-62` → `mappers.py`. **BUNDLE** — Item 3.

5. **`app_health` route body duplicates `error_rate_from_summary`'s logic inline** — `telemetry.py:147-156` recomputes `total`, `handler_errors = agg.handler_errors + agg.handler_timed_out`, `job_errors = agg.job_errors + agg.job_timed_out`, then calls `compute_error_rate`. Meanwhile `error_rate_from_summary` (`telemetry.py:105-112`) does the same `+timed_out` folding from an `AppHealthSummary`. The two operate on different source types (`AppHealthAggregates` vs `AppHealthSummary`) so they can't be literally merged, but the `errors + timed_out` folding pattern is repeated. **BUNDLE (light touch)** — at minimum derive `success_rate` from the already-computed `error_rate` here instead of a second inline formula, so the route has one rate computation, not two.

### SPLIT candidates (real, but their own ticket — larger/riskier or touches shape)

6. **`enrich_jobs_with_heap` duplication between `routes/scheduler.py` and `routes/telemetry.py`** — both `all_jobs` (`scheduler.py:36-52`) and `app_jobs` (`telemetry.py:236-255`) run the identical "fetch DB rows → snapshot live heap → enrich, fall back to DB rows on heap failure" sequence with the same `except (OSError, RuntimeError, ValueError)` block and the same warning. This is genuine duplication but it lives in **route handlers across two files** and involves the scheduler dependency, not the mapper/rate neighborhood. **SPLIT** — out of scope for a "mappers + rate math" PR; file as its own small refactor.

7. **`DB_ERRORS` try/except boilerplate repeated in ~12 route handlers** — `telemetry.py` alone has it 8+ times; also in `apps.py`, `bus.py`, `logs.py`, `executions.py`, `scheduler.py`. Each is `try: ... except DB_ERRORS: LOGGER.warning(...); response.status_code = 503; return []`. A decorator or context manager could collapse it. **SPLIT** — large blast radius (every route), changes error-handling control flow (risk), unrelated to the ticket theme.

8. **`health_status_from_summary` / `error_rate_from_summary` live in `routes/telemetry.py`, not in a mapper/helper module** — these are pure functions over `AppHealthSummary` (`telemetry.py:91-112`). They arguably belong in `telemetry_helpers.py` (alongside `classify_health_bar`/`classify_error_rate`) or `mappers.py`. **BORDERLINE → lean SPLIT.** Moving them is low-risk and on-theme, but they are only used within `telemetry.py`, so relocating them is reader-load-neutral. Include only if the PR is already touching their bodies for the rate-unification (#2); otherwise leave them.

9. **`_redact_secrets` / `_redact_dict` in `apps.py:25-32`** — small inline transform in a route, but it is security logic, not response mapping, and has no duplication. **Leave alone** (not a cleanup).

### Not a problem (checked, no action)

- **`LogEntryResponse.model_validate(r)`** (`logs.py:53`, `executions.py:89`) already uses Pydantic validation — these mappers are *already* idiomatic. No field-by-field copying to fix.
- **`_build_app_summaries`** (`helpers.py:109-157`) is aggregation, not response mapping. Correctly placed in `core/telemetry`. Out of scope.

---

## Recommended PR scope

**Include in this PR** (cohesive theme: simplify mappers + unify rate math, JSON shape unchanged):

1. Delete `AppHealthSummary.error_rate` and `success_rate` dead properties (`telemetry_models.py:44-59`).
2. Add `compute_success_rate()` to `telemetry_helpers.py` and route both inline `success_rate` formulas (`telemetry.py:101`, `telemetry.py:157`) through it; in `app_health`, derive success from the already-computed clamped `error_rate` so the route has a single rate path.
3. Convert `instance_response_from` and `to_listener_with_summary` to `model_validate(from_attributes=True)` + `model_copy(update=...)` for the computed fields.
4. Extract `config_response_from` mapper from `routes/config.py` into `mappers.py`; reduce the route to a one-liner.
5. (Optional, if cheap) Apply `from_attributes` to the nested `AppManifestResponse` and `ConnectedPayload` builds where it doesn't obscure the structural transform.

**Defer to follow-up tickets:**

- `enrich_jobs_with_heap` route duplication (#6) — separate small refactor.
- `DB_ERRORS` try/except decorator/context-manager (#7) — separate, larger, control-flow change.
- Relocating `health_status_from_summary`/`error_rate_from_summary` (#8) unless already touched by #2.

**Explicitly do NOT do:**

- Force `model_validate` onto `app_status_response_from` or the list-building portions of `system_status_response_from` — they perform structural transforms (list merge, nested-child construction, field renames) and rewriting them adds reader load without reducing it.

---

## Risks / watch-outs

**Behavior-preservation traps:**

- **`from_attributes=True` silences the "missing field copy" failure mode.** The current explicit field lists make an un-copied field a visible omission; the existing `test_to_listener_with_summary_thread_leaked_passthrough` (`test_mappers.py:338`) was written precisely because that omission silently zeroes a field. After conversion, a future source-only field would silently fall to its target default. Keep every existing passthrough test green and consider adding a test that asserts source/target field-name parity for the auto-mapped models.
- **Clamping change is a real behavior question.** The dead property was *unclamped*; the live helper is *clamped*. Deleting the property keeps live behavior identical (live paths already use the clamped helper). But when adding `compute_success_rate`, decide deliberately: success should be `100 - clamped_error_rate` (stays in [0,100]) rather than an independent unclamped formula, to match the existing clamp guarantee. The inline `app_health` success formula (`telemetry.py:157`) is currently unclamped on the high end but bounded in practice because `errors <= total`; preserve that exact output (it can't exceed 100 given `errors <= total`, so deriving from clamped error rate is equivalent for valid inputs and *safer* for mismatched counters).
- **Enum/literal validation differences.** `model_validate` validates `status` literals at runtime where the current code uses `cast(...)` to silence pyright without runtime checks. A source value outside the `Literal` set would now raise at validation time instead of passing through. For `AppManifestInfo.status` (a free `str`, `app_snapshots.py:71`) this is a *stricter* behavior — verify the status-derivation logic only ever produces the 5 valid `ManifestStatus` values, or the change could turn a previously-silent bad value into a 500.

**Frontend / codegen implications:**

- **None expected** if the JSON shape is preserved. All recommended changes are internal mapper/helper refactors; no response-model field is added, removed, or renamed. `scripts/export_schemas.py` output (`openapi.json`, `generated-types.ts`, `ws-types.ts`) should be byte-identical. **Verify** by regenerating (`uv run python scripts/export_schemas.py --types`) and confirming no diff — the pre-push hook `tools/check_schemas_fresh.py` and the CI git-diff check will catch drift, but check locally first.
- The `frontend/src/utils/app-data.ts:60` `error_rate` consumer reads the `DashboardAppGridEntry.error_rate` field, which is unaffected (it comes from `error_rate_from_summary`, not the deleted property).

**Test coverage gaps:**

- **Strong coverage exists** for the two clean mappers: `tests/unit/web/test_mappers.py` (462 lines) covers `to_listener_with_summary` field passthrough extensively, and `tests/unit/web/test_telemetry_helpers.py` covers `compute_error_rate` including the clamp case. These are the safety net for the refactor.
- **Gap: no direct test for the dead properties** (because they're dead) — deleting them needs no test change, but confirm no e2e mock constructs them (verified: `tests/e2e/mock_fixtures.py` builds `AppHealthSummary` instances at lines 673-699 but never reads `.error_rate`/`.success_rate`).
- **Gap: `config_response_from` has no existing mapper test** — `routes/config.py` mapping is only covered (if at all) via `tests/integration/web_api/test_endpoints.py`. Add a unit test for the new mapper to pin the field-by-field config translation (especially the `str()` path coercions and `list()` copy).
- **Gap: no test pins `app_health` success_rate output** specifically — when unifying #2, add a test that the route's `health_status` is unchanged for representative aggregates, since the success-rate derivation is the riskiest behavioral touch.
