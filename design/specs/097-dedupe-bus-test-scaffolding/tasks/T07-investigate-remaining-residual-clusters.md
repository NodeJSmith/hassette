---
task_id: "T07"
title: "Investigate and resolve remaining duplicate-code clusters entirely inside this design's files"
status: "done"
depends_on: ["T01", "T02", "T03", "T04", "T06"]
implements: ["FR#12"]
---

## Target Files

- modify (investigate): `tests/integration/bus/test_bus_duration.py`
- modify (investigate): `tests/integration/bus/test_bus_immediate.py`
- modify (investigate): `tests/integration/bus/test_bus_error_handler_combos.py`
- modify (investigate): `tests/unit/bus/test_duration_hold.py`
- modify (investigate): `tests/integration/bus/helpers.py` (only if a new shared extraction is warranted)
- modify: `tests/integration/bus/CLAUDE.md` / `tests/unit/bus/CLAUDE.md` (document any new helper)

## Prompt

Run `uv run python tools/check_duplicate_code.py` and filter the output to clusters whose every
fragment lives inside the four files above (do not touch clusters that also reach into files this
design never targeted — e.g. `test_accessors.py`, `test_predicates.py`, `tests/unit/core/test_bus_service_*.py` —
those are explicitly out of scope; leave them alone). As of this task's creation there are 22 such
clusters: ~16 in `test_bus_duration.py`/`test_bus_immediate.py`/`test_bus_error_handler_combos.py`
(mostly a short `handler, received, fired = make_collector(hassette)` + `bus.on_state_change(...)`
registration "arrange" block, or similar short setup blocks), and 6 in `test_duration_hold.py`
(design.md's Goals section notes these exist post-T04, but T04's own task only targeted the
listener+duration_config+mock-timer setup block specifically — these 6 were never individually
investigated for further extraction, so do not assume they're already confirmed-irreducible; verify
for real).

**For each cluster, do real work, not a rubber stamp:**

1. Read every fragment in the cluster and the full surrounding test function(s).
2. If the fragment can be cleanly extracted into a helper (file-local, or added to
   `tests/integration/bus/helpers.py` if the pattern is shared across integration-bus files —
   follow the same file-local-vs-shared placement rule T01/T03/T04/T06 used, and
   `.claude/rules/test-conventions.md`) without reducing test clarity or coupling unrelated
   registration kwargs together, extract it. Preserve every test's actual assertions, timeout
   values, and registration arguments exactly — pure structural refactor only.
2. If extraction would force together things that are legitimately different per test (e.g. each
   test's `bus.on_state_change(...)` call has genuinely different kwargs — entity, `changed_to`,
   `duration`, `on_error`, `name` — such that a shared helper would need as many parameters as the
   call itself, or would obscure which registration variant a specific test exercises), do not
   force it. Instead wrap every fragment in the cluster with `# dup-ignore-start: <reason>` /
   `# dup-ignore-end` (see `tools/check_duplicate_code.py`'s module docstring for the exact
   convention). The reason must be specific to that cluster — what's actually the same, what's
   actually different, and why forcing extraction would hurt readability. Do not use a generic
   "arrange boilerplate" reason for every cluster; each one gets its own honest justification.
3. It is fine — expected, even — for some clusters to end in extraction and others to end in a
   documented dup-ignore. Do not pick one approach for all 22 clusters; judge each on its own
   merits the way T01 and T06 did.

After resolving all 22 clusters, re-run `uv run python tools/check_duplicate_code.py` and confirm
none of the originally-flagged 22 clusters still appear un-ignored and un-extracted.

Update `design/specs/097-dedupe-bus-test-scaffolding/design.md`: add FR#12 describing this task's
outcome (how many clusters were extracted vs. marked, with a one-line summary each), and update the
Goals section's integration/unit cluster-count bullets with the final post-T07 counts. Update
`tests/integration/bus/CLAUDE.md` and/or `tests/unit/bus/CLAUDE.md` if any new shared or file-local
helper was added.

## Verify

- [x] FR#12: every one of the 22 originally-flagged clusters (fully inside this task's four target
      files) is resolved — either its shared fragment no longer exists as duplicated code, or every
      occurrence in the cluster is wrapped in a `dup-ignore-start`/`dup-ignore-end` pair with a
      cluster-specific reason (not a generic one reused verbatim across clusters).
- [x] `uv run python tools/check_duplicate_code.py` confirms zero remaining un-resolved clusters
      whose fragments are entirely inside `test_bus_duration.py`, `test_bus_immediate.py`,
      `test_bus_error_handler_combos.py`, or `test_duration_hold.py`. (Clusters reaching into files
      outside this design's scope are unaffected and expected to remain — not a failure.)
- [x] design.md's FR#12 and Goals section accurately reflect the final extraction/mark counts.
- [x] `uv run pytest tests/unit/bus/ tests/integration/bus/ -n 4` passes with zero failures.
- [x] `prek -a` passes clean on every modified file.

## Resolution

Resolved: 9 of the 22 clusters via 6 new helper extractions (`send_live_event_and_wait_drain`,
`make_error_collector_pair` in `tests/integration/bus/helpers.py`/`test_bus_error_handler_combos.py`;
`arm_duration_timer`, `arm_remaining_duration_timer`, `fire_mock_timer`, `compute_elapsed_for`,
`hold_matches_with_predicate` file-local in `test_duration_hold.py`); the remaining 13 via
cluster-specific `dup-ignore-start`/`dup-ignore-end` markers with individual reasons. Final counts:
`tests/unit/bus/` 27→21, `tests/integration/bus/` 37→20 — matches design.md's FR#12.

Code review re-run: PASS (0 findings). Integration review re-run: PASS (0 findings) — independently
re-verified the earlier HIGH finding (a `dup-ignore` marker that suppressed real duplication instead
of the intended fragment) is fixed, not just claimed.
