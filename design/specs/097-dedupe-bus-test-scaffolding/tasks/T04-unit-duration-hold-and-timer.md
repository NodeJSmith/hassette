---
task_id: "T04"
title: "Extract file-local helpers in test_duration_hold.py and test_duration_timer.py"
status: "planned"
depends_on: []
implements: ["FR#7", "FR#8", "AC#1", "AC#3"]
---

## Target Files

- modify: `tests/unit/bus/test_duration_hold.py`
- modify: `tests/unit/bus/test_duration_timer.py`

## Prompt

Read both files in full first. **Do not merge factories between these two files** — `design.md`
confirms `test_duration_hold.py` builds `DurationHoldManager` and `test_duration_timer.py` builds
`DurationTimer`, two different production classes with non-overlapping constructors. This task is
about collapsing *intra-file* repetition, not cross-file consolidation. Also do not touch
`test_duration_config.py` — the duplicate-code checker reports no clusters there.

**`test_duration_hold.py`** (`TestStartDurationTimer` and `TestCreateCancelListener` classes,
e.g. lines 185-303 and 422-497): tests repeatedly build a listener with `duration_config` set, then
attach a `MagicMock` as its timer:

```python
task_bucket = make_task_bucket()
listener = create_listener(
    topic="hass.event.state_changed.light.kitchen",
    entity_id="light.kitchen",
    duration=60.0,
    task_bucket=task_bucket,
)
assert listener.duration_config is not None
mock_timer = MagicMock()
listener.duration_config._timer = mock_timer

invoke_fn = AsyncMock()
```

Add one file-local helper — e.g. `def make_listener_with_mock_timer(entity_id="light.kitchen", duration=60.0, task_bucket=None) -> tuple[Listener, MagicMock]` — that returns
`(listener, mock_timer)` with `task_bucket` created internally if not passed. Some tests also need
the `task_bucket` itself back (for `assert manager.duration_timers_active == ...` style checks tied
to a specific bucket) — check each call site and expose whatever the helper's callers actually
consume; extend the return tuple or accept a passed-in bucket if some tests need to reuse the same
one across multiple listeners.

**`test_duration_timer.py`**: after T01-T03 land (independent of this task, but re-run the checker
after your own changes to see current state), check whether any of the 3 clusters the checker
reports for this file remain. If they do, they're intra-file repeats of a setup/extraction shape
around `make_timer(...)` + `on_fire` callback capture (e.g.
`timer.start(on_fire=on_fire); task = timer._task; assert task is not None`) — read the actual
flagged line ranges from `uv run python tools/check_duplicate_code.py` output and extract a
file-local helper matching whatever pattern is actually flagged, rather than guessing from this
prompt alone.

Both helpers are **file-local** — do not add them to `tests/unit/bus/conftest.py` or
`src/hassette/test_utils/`. Preserve every test's actual assertions exactly.

## Verify

- [ ] FR#7: `test_duration_hold.py` has one file-local helper collapsing the
      listener+duration_config+mock-timer setup pattern.
- [ ] FR#8: `test_duration_timer.py`'s remaining checker-flagged clusters (if any survive after
      T01-T03) are collapsed into file-local helper(s).
- [ ] AC#1 (partial): run `uv run python tools/check_duplicate_code.py 2>&1 | grep -B1 -A5 "test_duration_hold.py\|test_duration_timer.py"` and confirm intra-file clusters in these two files are gone (any cross-file cluster naming `test_duration_config.py` alongside them was pre-existing and out of scope — verify it wasn't newly introduced).
- [ ] AC#3: `uv run pytest tests/unit/bus/test_duration_hold.py tests/unit/bus/test_duration_timer.py tests/unit/bus/test_duration_config.py -n 4` passes with zero failures, and no test function or
      parametrize case was accidentally dropped or added — spot-check via
      `uv run pytest tests/unit/bus/test_duration_hold.py tests/unit/bus/test_duration_timer.py tests/unit/bus/test_duration_config.py --collect-only -q | tail -1` compared against the pre-edit
      count for these three files (record it before editing if not already known).
