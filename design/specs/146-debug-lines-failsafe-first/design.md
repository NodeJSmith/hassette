# Design: Delete persisted DEBUG lines first when over the size limit

**Date:** 2026-11-05
**Status:** built
**Mode:** sketch
**Issues:** #3675
**Parent:** design/specs/142-diagnostic-evidence/design.md
**Prior art:** design/research/2026-11-01-diagnostic-evidence/prior-art.md

## Summary

`log_records` is exempt from the size failsafe as a whole (`src/hassette/core/retention_targets.py`, the `log_records` entry in `_RETENTION_TABLES`, `failsafe_exempt=True`). That holds only while DEBUG lines aren't persisted. Once they are (today through `logging.log_persistence_level`, later through per-app capture, #3679), the failsafe deletes executions to make room and never touches the lines. This change implements the parent's D9, as amended by D3 below. DEBUG lines become their own failsafe target, deleted first and bounded per D3, and they age out on `logging.log_retention_days` like other log lines. INFO and above stay exempt.

Where each new piece lives:

- **DEBUG target:** a new `RetentionTarget` labelled `debug log records`, placed first in `_RETENTION_TABLES` (`retention_targets.py`; the age pass walks the list in order) at `priority=0`, ahead of `framework executions` at 1, so the existing numbers don't change and the tier is alone in its group. It is selected by a new level filter on `RetentionTarget` (D1). The WHERE builders in the same file (`build_tier_where`, `build_age_where`) apply the filter, so the failsafe delete, the stale-row probe and the age delete all honor it without changes at their call sites. `_check_size_failsafe` (`src/hassette/core/database_failsafe.py`) needs no change: the tier spends the shared budget and caps like any other (D3).
- **Index:** a partial index on DEBUG rows' timestamps in a new migration, `src/hassette/migrations_sql/022.sql` (D2).
- **Docs:** every docs and docstring passage that calls `log_records` failsafe-exempt or lists the failsafe order: in `docs/pages/core-concepts/database-telemetry.md`, the `max_size_mb` row of the settings table and, in "How Retention Works", the failsafe order sentence and the "rounding error" paragraph; the retention paragraph of `docs/pages/core-concepts/internals/service-details.md` ("`log_records` is exempt"); and the `max_size_mb` docstring in `src/hassette/config/models.py`. `database-telemetry.md` states that DEBUG capture is best-effort against `max_size_mb`: on an install near the limit the lines last about one failsafe interval, and since each run deletes at most `size_failsafe_max_iterations` × `size_failsafe_delete_batch` rows, a faster capture keeps the database over the limit until capture stops (those two settings raise the rate).

Out of scope: a database dominated by INFO-and-above lines, which stay exempt (#2755 owns that decision); an offline drain for large one-time backlogs (#2775); a separate debug age or any new setting (D9 ruled these out), per-app capture (#3679), the other new tables' failsafe targets (later pickups, per parent D12), and web UI changes.

## Posture

- **Failure handling:** happy path with loud failure, as the existing failsafe does. A DELETE failure on the DEBUG tier is logged with its label and the tier is skipped for the cycle. Nothing new.
- **Compatibility:** clean break; the project is pre-V1. INFO and above keep their exemption. The only visible change is that DEBUG rows can now be deleted by size.
- **Scope:** minimal, D9 plus the docs correction. No new settings.
- **Rollout:** ships outright, no flag; any schema change follows D2.
- **Hardening:** project defaults; no new bounds or metrics.
- **Altitude:** `build`; one session builds it.

## Decisions

### D1: How does the registry express a DEBUG-only target next to the exempt log target?

**Situation:** `retention_targets.py` declares one list, `_RETENTION_TABLES`, which the age pass walks (`database_retention.py`, the loop over `_RETENTION_TABLES`). `_FAILSAFE_TABLES` is that list minus the `failsafe_exempt` targets, and the module docstring states this invariant: the two lists differ only by that flag. The only row filter today is `source_tier`. D9 wants DEBUG lines deleted by the failsafe and INFO+ lines exempt from it, with both on the same age (`log_retention_days`). The age pass also keys its results by `failsafe_label`, so every target needs a unique label.

**Deciding factor:** fewest new concepts in the registry, keeping its one stated invariant.

| | A: overlapping targets: a new DEBUG target with a `level` filter in both lists; the existing log target unchanged | B: partitioning targets: split log records into `level = DEBUG` and `level != DEBUG` targets, via `level` plus a negated-level field | C: failsafe-only target: a new flag keeps the DEBUG target out of the age pass |
|---|---|---|---|
| New `RetentionTarget` fields | `level` | `level` plus a negated-level field (`level_not`); `source_tier` untouched | `level` plus an age-pass opt-out flag |
| "Lists differ only by `failsafe_exempt`" | Holds | Holds | Broken; a third kind of target |
| Rows belonging to one target | DEBUG rows match both log targets. Harmless: the exempt one only matters to the failsafe, and both age out at the same cutoff | Exactly one | Exactly one per list |
| Age pass work for log records | One extra delete per cycle, on the partial index (D2). Ordering the DEBUG target first means the existing target finds no old DEBUG rows, unless the DEBUG target hits `retention_max_batches_per_target`; then the existing target deletes the rest at the same cutoff, and the capped target marks the cycle incomplete as any capped target does | Two deletes, same rows in total | Unchanged |
| Churn in existing targets and tests | No target changes; tests that pin the registry (target count, failsafe label order) and the failsafe's size-read call counts shift by the new target and its priority group | Same, plus a second log target | Same as A |
| Needed by later pickups | Near-miss and API write targets (parent D12) have no row filter | Same, so the negated field has no second user | Same |
| What peers do | Loki: `retention_stream` by selector, overlapping a global retention period | Seq: separate per-level retention policies | unknown |

**Recommendation:** A. It adds one field and keeps the registry's one stated invariant. The overlap does no harm because the two log targets share a cutoff and only the DEBUG one is subject to the failsafe. The registry docstring and the existing target's `failsafe_exempt` docstring say the exempt log target covers INFO and above for the failsafe because DEBUG has its own target.
**Pick B instead if** you want every row owned by exactly one target, so `failsafe_exempt` keeps its plain meaning, at the cost of a second filter field with no other user. **Pick C instead if** you'd rather skip one extra cheap delete per age cycle at the cost of a third kind of target.
**Reversibility:** easy (registry entries and one dataclass field)
**Ratified:** Chose an overlapping DEBUG target with a `level` filter in both lists over partitioning targets (`level` plus a negated-level field) or a failsafe-only target, to add one field and keep the registry's "lists differ only by `failsafe_exempt`" rule, accepting that DEBUG rows match both log targets and the age pass makes one extra indexed delete per cycle.

### D2: Does the DEBUG tier get an index?

**Situation:** the existing log indexes are `idx_lr_time (timestamp)`, `idx_lr_exec (execution_id)`, `idx_lr_app_time (app_key, timestamp)` (`001.sql`) and `idx_lr_default_view (timestamp, seq)` (`016.sql`). None covers `level`. Without an index, the DEBUG delete (`... WHERE level = 'DEBUG' ORDER BY timestamp LIMIT n`) scans `idx_lr_time` from the oldest row and skips non-DEBUG rows. Measured on SQLite with 1M older INFO rows and 100k DEBUG rows interleaved after them: 160 ms per 1,000-row batch, 100 ms per stale-row probe, and 174 ms for the empty-tier delete that every over-limit run makes even with no DEBUG rows. With `CREATE INDEX ... ON log_records(timestamp) WHERE level = 'DEBUG'`, the planner uses the partial index: 3 ms per batch, 0.1 ms per probe, and 0 ms for an empty tier. The index only grows when DEBUG rows are written.

**Deciding factor:** the DEBUG tier's batches and empty checks hold the single writer for as little time as possible, at the lowest write cost.

| | A: partial index on `timestamp WHERE level = 'DEBUG'` | B: composite `(level, timestamp)` index | C: no index |
|---|---|---|---|
| Batch delete, 1M older INFO rows | 3 ms (~30 ms for a full 10-batch run under D3) | Similar to A (the planner seeks `level = 'DEBUG'`) | 160 ms (~1.6 s per full run) |
| Empty-tier cost on every over-limit run | ~0 | ~0 | 174 ms and growing with the table |
| Write cost | Only on DEBUG inserts: measured +4-7% per 50-row all-DEBUG batch (1.24-1.28 ms to 1.33 ms) | Every log insert | None |
| Migration | `022.sql` | `022.sql` | None |

**Recommendation:** A. It gives B's delete speed and only costs a write on DEBUG rows, which are the rows it serves.
**Pick B instead if** a later query needs to filter other levels by time. **Pick C instead if** you'd rather not add a migration, accepting a scan proportional to the table on every over-limit run. A bound `level = ?` parameter still selects the partial index on the project's SQLite (3.53.1) and driver, so the filter needn't be a literal.
**Reversibility:** easy (drop the index in a later migration)
**Ratified:** Chose a partial index on DEBUG rows' timestamps in `022.sql` over a composite `(level, timestamp)` index or no index, to keep the DEBUG tier's batches and empty checks near zero, accepting one migration and an index write on each DEBUG insert.

### D3: Is the DEBUG tier bounded by the failsafe's shared budget? (supersedes parent D9's budget exemption)

**Situation:** parent D9 put the DEBUG tier outside the shared budget (`size_failsafe_max_iterations` batches of `size_failsafe_delete_batch` rows per run, 10 × 1,000 by default; `config/models.py`), so each run deletes until live data is under the limit. That needs a new `RetentionTarget` flag and a second loop branch in `_check_size_failsafe`, and it runs as one job on the single write queue (`run_size_failsafe` → `enqueue_if_ready`). During a large one-time backlog, such as the first run after upgrading an install that already persists DEBUG lines (they were exempt, so they can sit far past the limit) or a lowered `max_size_mb`, the job holds the writer. Awaited writes that haven't started within `write_submit_timeout_seconds` (60 s) are withdrawn: execution batches, listener and job registration, session create and finalize. Once `write_queue_max` (2,000) items are queued, log batches of every level are dropped (`database_write_queue.py`, `logging_.py`). The measured delete rate on the real schema is about 108k rows/s on a desktop disk, so the 60 s mark comes at roughly 1.8 GB of overshoot there and at much less on SD-card or NAS storage. Startup is affected too: the catch-up (`catch_up_cleanup_at_startup`) runs the failsafe before age retention under one 15 s budget.

**Deciding factor:** the least new machinery, without costing other writers their evidence.

| | A: no exemption; shared budget | B: exemption plus a per-run time box, then capped | C: exemption, uncapped (parent D9 as written) | D: chunked continuation jobs |
|---|---|---|---|---|
| New failsafe machinery | None: a registry entry only | Flag, second loop branch, deadline check | Flag, second loop branch | Flag, branch, state carried across jobs |
| Other writes during a big backlog | Unaffected (10 batches, well under a second) | Wait at most one box | Withdrawn past 60 s; log batches dropped once the queue fills | Interleave between chunks |
| Overshoot while capture runs faster than the budget (~2.8 rows/s) | Grows by the difference until capture stops; the tier caps, so executions stay protected | At most about one interval of capture | At most one interval of capture | At most one interval of capture |
| Startup catch-up | Bounded like today | Box uses most of the 15 s budget | Can take the whole budget; retention skipped | Chunks inside the budget |
| What peers do | unknown; in-repo, age retention and the failsafe both cap batches to bound queue occupancy | unknown | unknown | unknown |

**Recommendation:** A. It removes the flag and the second branch outright, and with them every way a long run can starve other writers. The overshoot it allows needs a DEBUG capture that is both fast and sustained, which per-app capture (#3679) is designed to end. The existing over-limit WARNINGs report a capped tier, and users can raise `size_failsafe_max_iterations` or `size_failsafe_delete_batch`.
**Pick B instead if** D9's "overshoot is at most one interval of capture" must hold even during heavy capture. **Pick C instead if** multi-hundred-MB DEBUG backlogs are unrealistic for this audience. **Pick D instead if** the limit must be restored within one run while writes keep flowing.
**Reversibility:** easy (adding an exemption later is the drafted flag and branch)
**Ratified:** Chose putting the DEBUG tier on the failsafe's existing shared budget over a budget exemption (time-boxed, uncapped, or chunked), to add no failsafe machinery and never starve other writers, accepting that a capture faster than the budget's ~2.8 rows/s keeps the database over `max_size_mb` until capture stops, and that a stored DEBUG backlog larger than one run's budget (such as the first over-limit run after upgrading an install that already persisted DEBUG lines) keeps it over the limit until the backlog drains at one budget per failsafe interval, with executions untrimmed in both cases because a capped DEBUG tier stops the run. Supersedes parent D9's "outside the shared budget; each run deletes until under the limit".

## Assumed

- DEBUG lines are deleted by the failsafe before any other target and age out on `logging.log_retention_days`. Carried from parent D9; its budget exemption is superseded by D3.
- INFO, WARNING, ERROR and CRITICAL lines stay exempt from the failsafe and expire only by age. Carried from parent D9.
- The docs currently call `log_records` failsafe-exempt and "a rounding error next to executions", which parent D9 requires this change to correct. Evidence: `docs/pages/core-concepts/database-telemetry.md` ("How Retention Works"); parent D9's recommendation.
- The failsafe order places DEBUG lines first. The near-miss rollups and API write targets that D12 places later in the order arrive with their own pickups. Carried from parent D12 (its order list).
- Stored log levels are limited to the five standard names, so `level = 'DEBUG'` matches every persisted DEBUG line. Evidence: `019.sql` rewrites any other level to `INFO`.
- The latest migration is `021.sql`. Evidence: `src/hassette/migrations_sql/`.
- No other ledger names the parent, so no sibling pickup touches D9; this ledger's D3 supersedes only D9's budget exemption. Evidence: no other `**Parent:**` line naming `142-diagnostic-evidence` under `design/specs/`.

## Build

- [x] Implementation and tests committed
- [x] Docs
- [x] Ship-time challenge

**Calls made during the build:**
- `build_tier_where` renamed to `build_filter_where`, with a shared `row_filter_terms` helper both WHERE builders use: it now filters by level as well as tier, and the shared helper keeps the failsafe and age filters from drifting apart.
- `RetentionTarget.level` is typed `Literal["DEBUG"] | None`: only DEBUG has the partial index, so another level would silently scan `idx_lr_time`.
- `docs/pages/operating/log-levels.md` gets a one-sentence pointer next to `log_retention_days`: it is where users turn DEBUG persistence on, so they learn there that the size limit deletes those lines first.
- The age pass walks `_RETENTION_TABLES` sorted by `priority` (chosen at the ship-time challenge), so `priority` alone owns the DEBUG-first order for both passes instead of list position plus a comment.
- The partial-index test captures the statements the failsafe actually runs and explains each one, rather than restating the SQL, so a change to the production query shape can't pass unnoticed.
