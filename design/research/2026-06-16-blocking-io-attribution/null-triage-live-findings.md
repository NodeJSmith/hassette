# Issue 1048 — Live NULL-triage findings (2026-06-16)

Ran the brief's #1 next step (the NULL-triage query) against the **live** `blocking_events`
table on the running labrat instance (`docker exec hassette`, 133 rows). This sizes the
prize and settles the Option C vs Option B decision with data.

## Headline numbers

- **133 total events**, **35 NULL app_key (26%)** — *not* the 66% in the issue. The NULL
  *count* is stable at 35 while attributed events grew to 98, so the rate fell as the
  instance accumulated correct attributions. "66% unusable" is stale.

## Tier split (the key structural finding)

| tier | attributed | NULL | notes |
|------|-----------:|-----:|-------|
| Tier 2 `monkeypatch` | 73 | **35** | every NULL is here |
| Tier 1 `watchdog` | 25 | 0 | never NULL |

## The 35 NULLs are overwhelmingly *correct*

All 35 are Tier 2 `builtins.open` (31) / `os.listdir` (4) with `source_tier=framework`:

- **~30 are genuine framework/library reads** outside any app execution — `importlib.metadata`,
  `dotenv/main.py`, hassette `session_manager.py:52`, `scheduler.py:474`. No execution is bound
  → correctly NULL.
- **~5 point at app setup code** (`meeting_app.py:34`, `air_purifier.py:76`,
  `garage_proximity/app.py:64`, `new_remote_app.py:80`, `bus_overlap.py:47`) — `open()` in
  `on_initialize`/module load, which legitimately runs without a bound execution marker. Minor;
  recoverable only by binding a marker around lifecycle hooks, which is out of scope.

**No `time.sleep`/socket NULLs, no Tier 1 NULLs.** The "66% lost attribution" framing doesn't hold.

## The wrong-app bug is real but small — and lives in Tier 1

Tier 1 watchdog attributions (25):

| app_key | n | verdict |
|---------|--:|---------|
| `blocking_io_lab` | 18 | ✅ correct — busy-loop blocks in the same span as its bind (the brief's "easy case") |
| `__hassette__.StateProxy` | 3 | ~ok — JSON decode / weakref, framework state parsing attributed to the framework resource |
| `scheduler_overlap_lab` | 2 | ❌ **displaced** — stacks are `uvicorn/protocols/http` (web server serving a request) and `selectors.py:452 select` (loop idle-wait). Neither is scheduler_overlap_lab's code. |
| `bus_overlap_lab` | 1 | ❌ likely displaced — stack is `asyncio/events.py:89 _run` (generic loop callback dispatcher) |
| `andys` | 1 | ? — `hassette __main__:10` (startup) |

So **~3–4 of 25 Tier 1 events blame an innocent app**: when the loop stalls in framework/loop/
uvicorn code while some app's marker is the most-recently-bound, that app gets blamed.

**Tier 2 attribution looks correct** — e.g. `monarch_updater` → `monarchmoney.py:2971` is the app's
own call chain into a blocking library `open()`. Tier 2 reads the marker inline on the same task as
the blocker, so it's high-confidence (matches the brief's prediction).

## Decision: ship Option C, skip Option B

- **Tier 2 is already accurate** — no change needed beyond the (free) `asyncio.current_task()`
  same-task confirmation if we want to harden it.
- **Tier 1 is the wrong-app culprit**, and the displaced slice is ~3–4 events. Option C (stamp
  `ExecutionMarker` with `task_id`; when the watchdog can't confirm the marker's task froze the
  loop, record NULL instead of blaming the last-bound app) fixes exactly these.
- **Option B (per-task registry to *recover* attribution) is not worth it.** The recoverable prize
  is tiny (~5 app-setup NULLs + a handful of displaced Tier 1 events), and B's cost is the unproven
  cross-thread frozen-task identification. The data says don't pay for it.

## Implementation scope (Option C)

1. `ExecutionMarker` (+ `bind_execution_context`): add `task_id: int = id(asyncio.current_task())`.
2. Tier 1 `loop_watchdog.py`: when the captured loop stack is framework/loop code (or otherwise
   can't be confirmed as the marker's task), emit NULL + a `reason` tag ("displaced/unconfirmed")
   instead of the last-bound app.
3. Tier 2 `block_io_guard.py`: compare `id(asyncio.current_task())` at the call site to the
   marker's `task_id` — match = high confidence (already effectively the case).
4. **Add the missing displacement regression test** (handler A binds, yields; B binds+blocks →
   attribute B; displaced-A block → NULL-not-wrong). The current spike tests only cover the
   same-span case.

The `selectors.py select` attribution also hints Tier 1 may be flagging loop *idle-wait* as a
stall — worth checking the lag threshold / whether `select()` frames should be excluded from
attribution entirely.
