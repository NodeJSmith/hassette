---
task_id: "T03"
title: "Deduplicate scheduler_service test files flagged by tools/check_duplicate_code.py"
status: "done"
depends_on: []
implements: ["FR#1", "FR#3", "AC#1", "AC#2", "AC#3", "AC#4"]
---

## Target Files

- modify: `tests/unit/core/test_scheduler_service_error_handler.py`
- modify: `tests/unit/core/test_scheduler_service_reschedule.py`
- modify: `tests/unit/core/test_scheduler_service_timeout.py`
- modify: `tests/unit/core/test_scheduler_service_trigger.py`

Note: `tests/unit/core/test_scheduler_service_dequeue.py` is in the issue's named scope but currently has **zero** flagged clusters — confirm that during verification but no changes are expected there.

## Prompt

Read `design/specs/098-dedup-core-service-tests/design.md` (Approach section) and `design/specs/098-dedup-core-service-tests/tasks/context.md` first — they explain the two-track (extract vs. annotate) decision framework and the existing `tests/unit/core/conftest.py` factory catalog.

`tools/check_duplicate_code.py` (PMD CPD clone detector) currently flags 5 duplicate clusters across these 4 files (ground truth as of 2026-08-16 — re-run for current line numbers). Unlike the other three groups, none of these clusters cross outside the 16-file scope — this group is fully self-contained:

```bash
uv run python tools/check_duplicate_code.py 2>&1 | grep -A5 "test_scheduler_service"
```

Snapshot of the 5 clusters (file:start-end):

1. `test_scheduler_service_reschedule.py:638-644,648-654,658-664,668-674`
2. `test_scheduler_service_timeout.py:15-21,26-32,37-43,54-59`
3. `test_scheduler_service_error_handler.py:44-48,56-60,68-72` + `test_scheduler_service_timeout.py:17-21,28-32,39-43,55-59`
4. `test_scheduler_service_timeout.py:15-20,54-58` + `test_scheduler_service_trigger.py:62-67`
5. `test_scheduler_service_reschedule.py:79-83,97-101,119-124,496-500`

Note clusters 2 and 3 both touch `test_scheduler_service_timeout.py` with overlapping-but-distinct line ranges (PMD found two different minimum-length matches within the same broader repeated block) — resolving cluster 2's occurrence may also resolve cluster 3's, or you may need one fix that covers both. Re-run the grep after your first pass through this file to confirm.

Apply the extract-or-annotate decision from design.md's Approach section based on what you find in the flagged ranges. Check `tests/unit/core/conftest.py` first before adding any new shared helper — but **do not add a new fixture/helper to `conftest.py` itself**; it's a shared write target across all four parallel tasks, and none of these clusters require a `conftest.py`-level helper. If a helper turns out to be useful across `test_scheduler_service_error_handler.py`, `_reschedule.py`, and `_timeout.py`, keep it local to one of those files (or a small local import between them) rather than promoting it to `conftest.py`.

## Verify

- [ ] FR#1, FR#3, AC#1 (this task's slice): `uv run python tools/check_duplicate_code.py 2>&1 | grep -E "tests/unit/core/test_(bus_service|command_executor|scheduler_service|service_watcher)"` — must include no lines from `test_scheduler_service_error_handler.py`, `_reschedule.py`, `_timeout.py`, or `_trigger.py`.
- [ ] Confirm `test_scheduler_service_dequeue.py` still produces zero findings (no action needed, just verify the assumption holds).
- [ ] AC#2: `uv run pytest tests/unit/core/test_scheduler_service_*.py -v` passes with the same test count as before your changes.
- [ ] AC#3: `prek -a` clean on every file you touched.
- [ ] AC#4: every `dup-ignore-start`/`dup-ignore-file` marker you added has a specific reason.
