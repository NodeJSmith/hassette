# Design: Blocking-I/O Detection for the Shared Event Loop

**Date:** 2026-06-15
**Status:** approved
**Scope-mode:** hold
**Research:** design/research/2026-06-15-blocking-io-detection/research.md

## Problem

Hassette runs every user app on one shared asyncio event loop. A single app that calls a blocking primitive directly inside a coroutine — `time.sleep(30)`, `requests.get(...)`, `open(...).read()`, a blocking DB driver — stalls that loop. While the call runs, no other app's handlers fire, the bus stops dispatching, the scheduler stops ticking, and the WebSocket reconnect logic stalls. One careless line in one app degrades every app on the instance, and today nothing detects it or names the culprit.

App authors get no signal. The loop just goes quiet for N seconds, and the only symptom is "everything felt frozen for a moment." There is no warning, no attribution to the offending app, and no way to make the mistake fail loudly during development.

Issue #162 asks for a guard modeled on Home Assistant's `block_async_io`. The research (see Research link) settled the shape: detection cannot be both cheap, always-on, complete, and precise in a single mechanism, so the feature is tiered.

## Goals

- Detect when the shared event loop is stalled by blocking work originating in app code, always-on, in production, with negligible per-callback overhead.
- Name the offending app, handler/job, and (where possible) the source line — attribution must be actionable, not "something blocked the loop."
- Give app authors a development-time guard that **prevents** the blocking call (raises) rather than only reporting it after the stall.
- Reuse the existing `await_guard` machinery (behavior enum, config resolution, warning class, source capture) so the feature is "the same shape, different trigger" rather than a new subsystem.
- Persist detected blocking events to the telemetry DB for later querying.

## Non-Goals

- **Event-loop isolation** (running framework internals on a separate loop/thread from user apps). Tracked separately in #1038. This design targets today's single-loop architecture.
- **Monitoring-UI surfacing** of blocking events. Events are persisted to the telemetry DB this round; the UI view is a deliberate follow-up (no frontend work in this effort).
- **Sandboxing or preventing blocking outright** in production. Production protection is detect-and-report (Tier 1); prevention (Tier 2 raise) is a dev-default / prod-opt-in tool, not a forced production guard.
- **Catching blocking inside sync handlers that already run in the executor thread** — that work is intentionally off-loop and is not a stall.

## User Scenarios

### App author: writes and debugs an automation

- **Goal:** catch a blocking mistake before it degrades the running instance.
- **Context:** local development with `dev_mode` on, plus the same app later running in production.

#### Dev-time: a blocking call is caught at the call site

1. **Author writes `time.sleep(30)` inside an async handler and runs the app in dev_mode.**
   - Sees: an immediate `HassetteBlockingIOWarning` (escalated to an exception under the default dev filter) naming the primitive (`time.sleep`), the app, and the source line — raised *before* the sleep runs.
   - Decides: replace it with `await asyncio.sleep(30)` or offload to the executor.
   - Then: the handler no longer trips the guard.

#### Production: a blocking call is detected after the fact

1. **The same app, running in production, hits a blocking call that wasn't caught in dev (e.g. a blocking DB driver inside a C extension).**
   - Sees: a structured warning log naming the app/handler and the measured stall duration, plus a stack snapshot of the loop thread when the stall was severe. The blocking call still ran — the loop was stalled — but the event is attributed and recorded.
   - Decides: investigate the named app; optionally enable Tier 2 in production via the explicit opt-in flag to get the exact line.
   - Then: a `blocking_events` row exists in the telemetry DB for the stall.

### Framework operator: configures detection

- **Goal:** tune or silence detection without code changes.
- **Context:** `hassette.toml` / env config.

#### Configure behavior

1. **Operator sets `blocking_io.behavior = "ignore"` globally, or per-app via `AppConfig.blocking_io_behavior`.**
   - Sees: detection suppressed at the chosen scope; per-app override wins over global, mirroring `forgotten_await_behavior`.
   - Then: no warnings, no DB rows for the silenced scope.

## Functional Requirements

- **FR#1** The system measures event-loop responsiveness continuously while running, with no dependency on `loop.set_debug(True)`.
- **FR#2** When loop responsiveness degrades beyond a configurable threshold, the system emits a blocking-detected signal naming the app, handler/job, and measured stall duration.
- **FR#3** Tier 1 detection (responsiveness watchdog) is enabled by default and its default response is to warn (report after the stall), never to raise.
- **FR#4** Tier 1 attribution names the execution that was running on the loop **during** the stall, not the execution that ran next.
- **FR#5** Tier 2 detection (call-site interception) wraps a curated set of blocking primitives and, when one is called on the loop thread, responds per the configured behavior at the call site — before the blocking call proceeds.
- **FR#6** Tier 2 is enabled by default only in `dev_mode`; enabling it in production requires an explicit opt-in flag.
- **FR#7** Detection behavior is resolved per-app first, then global, then a hardcoded default, using a three-state enum (`ignore` / `warn` / `error`); `error` escalates via the standard `warnings` filter, not an unconditional raise.
- **FR#8** Work the framework legitimately offloads to the executor (sync handlers, logging-pipeline shutdown) never triggers detection.
- **FR#9** Legitimate slow asynchronous work (e.g. `await asyncio.sleep(30)`) never triggers Tier 1 detection.
- **FR#10** Each detected blocking event is persisted to the telemetry database with app attribution, primitive/source where available, stall duration, and timestamp.
- **FR#11** A blocking event whose app attribution resolves to a sentinel/unknown owner is still recorded, attributed to the framework tier rather than dropped.
- **FR#12** Detection install and teardown are idempotent and fully reversible, leaving no monkeypatch or watchdog active after shutdown.

## Edge Cases

- **Legitimate slow async** — a handler that `await`s something slow keeps the loop responsive; the watchdog must not flag it (FR#9). This is the core reason Tier 1 measures loop responsiveness, not handler wall-clock duration.
- **Executor offload** — sync handlers and `logging_service` shutdown run on worker threads; thread-id gating excludes them from Tier 2, and they don't stall the loop so Tier 1 ignores them (FR#8).
- **C-extension blocking** — a blocking C DB driver or `numpy` call can't be caught by Tier 2 monkeypatching; Tier 1 still catches it as loop lag. Messaging must be honest that Tier 2 is "known-primitive" detection, not total.
- **Spawned sub-tasks** — handlers spawn tasks that inherit a snapshot of `CURRENT_EXECUTION_ID` that is not cleared when the parent ends (see `context.py`). Attribution must blame the app whose work actually held the loop, not a stale inherited ID.
- **Startup / shutdown windows** — `_loop_thread_id` is captured at `core.py:449`; detection must be inert before that point and after teardown (FR#12).
- **Severe stall with no readable frame** — `sys._current_frames()` may return nothing useful; the event is still recorded with duration + app attribution, stack omitted.
- **Monkeypatch leakage under parallel tests** — Tier 2 patches process-global primitives; install/teardown must be test-isolated so a leaked patch can't corrupt unrelated test runs (the repo's `pytest` runs are sensitive to cross-test state).
- **Alternate event loop (uvloop)** — the watchdog must rely on loop-agnostic mechanisms (`call_later` lag or a wall-clock thread), not debug-mode timing semantics. (See Open Questions — confirm the production loop policy.)

## Acceptance Criteria

- **AC#1** With Tier 1 enabled and default config, a handler that calls `time.sleep(T)` for T past the threshold produces exactly one blocking-detected warning naming that handler's app and a stall duration ≈ T. (FR#1, FR#2, FR#3)
- **AC#2** Under the same conditions, the warning attributes the stall to the app that called `time.sleep`, even when another execution is scheduled to run immediately after. (FR#4)
- **AC#3** A handler that runs `await asyncio.sleep(T)` for the same T produces **no** blocking-detected warning. (FR#9)
- **AC#4** A sync handler (which the framework runs via the executor) doing blocking I/O produces no blocking-detected warning and no `blocking_events` row. (FR#8)
- **AC#5** In `dev_mode` with default config, `time.sleep` called on the loop thread raises `HassetteBlockingIOWarning` (under the default error filter) before sleeping; the same call in production (without the opt-in flag) does not raise. (FR#5, FR#6)
- **AC#6** Setting `blocking_io_behavior` on an app overrides the global `blocking_io.behavior` for that app only; `ignore` suppresses both the warning and the DB row for that app. (FR#7)
- **AC#7** Each detected event writes one `blocking_events` row with app key, stall duration, timestamp, tier, and (Tier 2) primitive + source location. (FR#10)
- **AC#8** An event with an unresolved owner is recorded with framework-tier attribution, not dropped. (FR#11)
- **AC#9** After `Hassette` shuts down, no blocking primitive remains patched and no watchdog task/thread remains running; a second start re-installs cleanly. (FR#12)
- **AC#10** Enabling Tier 2 in production requires the explicit opt-in flag; with the flag unset, no primitives are patched in production. (FR#6)

## Key Constraints

- **Do not use `loop.set_debug(True)` as the detection mechanism.** It taxes every callback (~2–5µs) and yields a useless framework-wrapper repr instead of the app's blocking line. Confirmed against CPython `_run_once` in the research.
- **Do not attribute via a bare `CURRENT_EXECUTION_ID.get()` read from the watchdog.** The ContextVar is unbound the instant a handler returns (`command_executor.py:484` `finally`), and a separate OS thread cannot read another thread's ContextVar at all. Attribution requires a plain thread-visible marker.
- **Do not flag executor offload.** Thread-id gating (`threading.get_ident() == self._loop_thread_id`) is the mechanism; never relax it.
- **Do not let Tier 2 patches leak across tests.** Install/teardown must restore originals deterministically.
- **Do not raise by default in production.** Always-on + raise can crash a live app over a brief stall.

## Dependencies and Assumptions

- Assumes the loop thread id captured at `core.py:449` identifies the single loop thread for the instance's lifetime (true under the current single-loop architecture; #1038 would change this).
- Assumes `command_executor.bind_execution_context` (line 422) remains the single choke point where every handler/job execution is wrapped — it is the natural place to set the thread-visible "currently executing" marker.
- Assumes the telemetry DB migration framework (`migrations_sql/NNN.sql`, currently through `003.sql`) is the path for the new table.
- No new third-party dependencies. The Tier 2 primitive list is inspired by `blockbuster` (cbornet/blockbuster) and HA's `block_async_io.py` but reimplemented in-house to integrate with Hassette's config and attribution.

## Architecture

The feature is two tiers plus a shared config/behavior/warning spine modeled on `await_guard`.

### Shared spine (mirrors `await_guard.py`)

- **`BlockingIOBehavior(StrEnum)`** in `src/hassette/types/enums.py` — `IGNORE` / `WARN` / `ERROR`, a direct sibling of `ForgottenAwaitBehavior`. `ERROR` escalates only through the user's `filterwarnings("error")`, exactly as the forgotten-await path does.
- **`HassetteBlockingIOWarning(RuntimeWarning)`** in `src/hassette/exceptions.py`, sibling to `HassetteForgottenAwaitWarning`.
- **Behavior resolution** — a helper mirroring `guard_await`'s eager resolution: per-app `AppConfig.blocking_io_behavior` → global `HassetteConfig.blocking_io` → hardcoded `WARN`. Resolved eagerly while the owning context is live.
- **Source attribution** — reuse `utils/source_capture.py`. Tier 2 uses `find_caller_frame()` (first non-`hassette.` frame) via `capture_source_location()` for the `"<file>:<lineno>"`; if the offending source *snippet* is also wanted in the DB row, `capture_registration_source()` returns both location and snippet. Tier 1's severe-stall stack uses `sys._current_frames()[loop_thread_id]` filtered through the same `is_internal_frame` logic.

### Tier 1 — always-on loop-responsiveness watchdog

Detects *that* the loop stalled and *which app* held it, cheaply, always-on. Default behavior `WARN`.

The make-or-break detail (flagged in the research) is attribution. Two candidate mechanisms were considered, and **the T02 spike resolved the choice in favor of Candidate B** before the design committed:

- **Candidate A — in-loop `call_later` heartbeat.** Schedule a recurring heartbeat (e.g. 250ms); lag beyond threshold means the loop was blocked. Simple and loop-agnostic, but the heartbeat only runs *after* the block clears, by which point the execution context is unbound — so it would need a record of "the handle that just ran and how long it held the loop." **Rejected:** it cannot name the blocker. By the time it fires, the marker is already cleared (or rebound to the next execution), so it never observes the execution that froze the loop.
- **Candidate B — dedicated daemon watchdog thread (CHOSEN).** A thread observes a thread-visible "last loop tick" timestamp and the thread-visible "currently executing" marker. Because it runs off-loop, it reads the marker *during* the block (the handler's `finally` hasn't run yet) and can snapshot `sys._current_frames()[loop_thread_id]` live. Correct attribution by construction; cost is one daemon thread.

**Spike outcome (T02):** the realistic spike (`tests/unit/core/test_blocking_io_marker_spike.py`) ran a real `time.sleep` that froze the loop thread with another execution scheduled immediately after. The daemon thread (B) read the live marker mid-freeze and named the blocking app (`blocking_app`); the in-loop heartbeat (A) was starved during the freeze and never observed the blocker's marker — it only ever saw `None` or the next execution. This is the AC#2 condition, and only B satisfies it. T03 builds the daemon watchdog: an off-loop thread that detects a stale in-loop tick (loop frozen beyond `lag_threshold_seconds`) and reads `_current_execution` to attribute. The spike confirmed the T01 config defaults (`lag_threshold_seconds=0.1`, `watchdog_interval_seconds=0.25`) are a sane starting point — a sub-threshold daemon poll detected a 0.45s freeze well within the window.

Both depend on a new **thread-visible execution marker** (a plain attribute, not a ContextVar — a separate OS thread cannot read another thread's ContextVar, which is why the marker cannot be `CURRENT_EXECUTION_ID` itself). It is stored as an instance attribute on the command executor (`self._current_execution`), set in `bind_execution_context` (line 422) on entry and cleared in the paired `unbind_execution_context` teardown (line 439), carrying `(app_key, instance_name, instance_index, execution_id, started_at)`. `unbind_execution_context` was a `@staticmethod`; T02 converted it to an instance method so it can clear `self._current_execution` — its callers already invoke it as `self.unbind_execution_context(token)` (the `finally` blocks of `execute_handler` and `execute_job`), so the call sites are unchanged. The marker is published as an immutable `ExecutionMarker` (a `@dataclass(frozen=True)`, matching the codebase convention) via a single atomic attribute assignment (single-slot, never mutated in place); a class-level `None` default makes it safe to read before the first execution and on `__new__`-built test instances. `instance_index` was added in T03 so Tier 1 attribution can populate the `blocking_events.instance_index` column at source rather than re-resolving it post-hoc. T02's spike validated that the chosen candidate (B) attributes a `time.sleep` stall to the correct app under the "next execution scheduled immediately after" condition (AC#2), and the outcome is recorded above.

Tier 1 distinguishes blocking from slow-async because it measures loop *responsiveness*: an `await` yields control and the heartbeat/tick keeps advancing, so slow async work produces no lag (FR#9, AC#3).

### Tier 2 — call-site interception (`protect_loop`-style monkeypatch)

A new module (`src/hassette/core/block_io_guard.py`) patches a curated primitive set — `builtins.open`, `time.sleep`, `socket.socket.connect/recv/send`, `os.listdir`/`scandir`/`walk`, `glob.glob`, seeded from HA's `block_async_io.py`. Each wrapper checks `threading.get_ident() == loop_thread_id`; on a hit it resolves behavior, captures the offending line via `source_capture`, reads the thread-visible marker for app attribution, and warns/raises. Install/teardown live alongside the loop setup in `core.py` (install after line 449, teardown in shutdown), and must be idempotent and reversible (FR#12, AC#9).

Two refinements landed during T04 implementation, both faithful to the design intent rather than departures from it:

- **Non-blocking socket gate.** asyncio's own transports call `socket.socket.recv/send/connect` on the loop thread, but on *non-blocking* sockets (`setblocking(False)`), which do not stall the loop. The socket wrapper passes through when `self.getblocking()` is False, so only genuinely blocking socket calls are flagged — this is HA's approach and avoids a per-HA-event false-positive storm. The thread-id gate alone is insufficient here because asyncio's non-blocking I/O *is* on the loop thread.
- **Per-thread re-entrancy guard.** Emitting a warning can read source via `linecache`, which calls the patched `builtins.open` on the loop thread — an unguarded wrapper would recurse to a `RecursionError`. A `threading.local` flag makes any patched call that fires *while a wrapper is mid-detection on this thread* pass straight through. The guard also suppresses inner patched calls a primitive makes synchronously (e.g. one `os.walk` no longer multiplies into a warning per internal `os.scandir`).
- **The dev-mode error filter is opt-in, not auto-installed (refines AC#5).** AC#5's "raises before sleeping" is delivered *under* an active `filterwarnings("error", category=HassetteBlockingIOWarning)` — which the T04 test sets explicitly and verifies. Hassette deliberately does NOT install that filter automatically in `dev_mode`: a process-global error filter on the shared warning category would also escalate Tier 1's daemon-thread warning, which the daemon then swallows for survival, making Tier 1 silent in dev. So the warn-vs-raise split is preserved by leaving escalation to the user's filter config (pytest `filterwarnings`, `-W error`, or a startup call). The docs frame this as the recommended dev/CI setup. The capability is implemented and tested; only the auto-install was rejected.

Tier 2 defaults on in `dev_mode` and off in production; an explicit `allow_blocking_detection_in_prod`-style flag enables it in production, mirroring `allow_reload_in_prod` (`config.py:182`) exactly.

### Persistence

A new telemetry table `blocking_events` (migration `004.sql`) records each event: `session_id` FK, `app_key`, `instance_name`, `instance_index`, `execution_id`, `tier` (`watchdog`/`monkeypatch`), `primitive` (Tier 2, nullable), `source_location` (nullable), `stall_duration_ms` (Tier 1, nullable), `detected_ts`, `source_tier` (`app`/`framework`). A `BlockingEvent` model is added to `core/telemetry_models.py` (sibling to `SlowHandlerRecord`) and a write path to the telemetry repository, following the established record→repository pattern. Sentinel/unknown owners are recorded with `source_tier = 'framework'` (FR#11, AC#8). No query API or UI view this round.

### Config surface

- **`BlockingIODetectionConfig`** nested model in `src/hassette/config/models.py`:
  - `behavior: BlockingIOBehavior | None` (global default; `None` → `WARN`)
  - `watchdog_enabled: bool = True`
  - `lag_threshold_seconds: float` (Tier 1)
  - `watchdog_interval_seconds: float` (Tier 1)
  - `capture_stack_on_block: bool = True`
  - `deep_detection_enabled: bool | None` (Tier 2; `None` → follows `dev_mode`)
  - `allow_deep_detection_in_prod: bool = False` (the `watch_files`-style prod override)
- Wired into `HassetteConfig` as `blocking_io: BlockingIODetectionConfig = Field(default_factory=...)`, alongside the other nested-config fields (`database`, `websocket`, `logging`, ...) near the top of the class at `config.py:84-105` — not next to the scalar `asyncio_debug_mode` at line 167.
- **`AppConfig.blocking_io_behavior: BlockingIOBehavior | None = None`** (`app/app_config.py:32` sibling) for per-app override.

## Replacement Targets

No existing code is being replaced. The feature is additive: a new guard module, a new config model, a new enum, a new warning class, a new telemetry table, and a thread-visible marker added to the existing `command_executor` choke point. `await_guard.py` and `source_capture.py` are reused, not modified (beyond possibly widening `source_capture` exports if needed).

## Migration

A new forward-only SQL migration `src/hassette/migrations_sql/004.sql` creates the `blocking_events` table and its indexes (by `detected_ts`, by `app_key`+`detected_ts`, by `session_id`), following the `executions` table conventions in `001.sql` (INTEGER PK autoincrement, `session_id` FK — note `log_records` has no `session_id` column at all, so `executions` is the precedent — and the `source_tier` CHECK constraint). Note: `executions` also carries a second CHECK tying `source_tier='framework'` to a sentinel `app_key`; `blocking_events` does NOT copy that — it uses a nullable `app_key` for unresolved owners, so its only `source_tier` constraint is the `IN ('app','framework')` check. No existing data is transformed; existing rows in other tables are untouched. The migration is additive and does not need a down-migration beyond the framework's existing handling.

## Convention Examples

### Eager behavior resolution + warning emission (the pattern Tier 2 and the watchdog mirror)

**Source:** `src/hassette/core/await_guard.py`. Note these are **two separate methods**: resolution is eager (in `guard_await`, while the owning context is live); emission is deferred (in `RegistrationHandle.__del__`). The blocking guard mirrors the split — resolve when the marker is set, emit when a block is detected.

```python
# --- in guard_await(): eager resolution, per-app -> global -> default ---
behavior: ForgottenAwaitBehavior = DEFAULT_FORGOTTEN_AWAIT_BEHAVIOR
with contextlib.suppress(AttributeError, ValueError, TypeError):
    per_app = getattr(getattr(owner, "app_config", None), "forgotten_await_behavior", None)
    if per_app is not None:
        behavior = ForgottenAwaitBehavior(per_app)
    else:
        hassette_cfg = getattr(getattr(owner, "hassette", None), "config", None)
        global_val = getattr(hassette_cfg, "forgotten_await_behavior", None)
        if global_val is not None:
            behavior = ForgottenAwaitBehavior(global_val)

# --- in RegistrationHandle.__del__(): deferred emission ---
# WARN and ERROR both emit here; ERROR escalates only via the user's filterwarnings("error").
if self._behavior is not ForgottenAwaitBehavior.IGNORE:
    warnings.warn(msg, HassetteForgottenAwaitWarning, stacklevel=1)
```

### First non-`hassette` frame attribution (reused verbatim for Tier 2 source line)

**Source:** `src/hassette/utils/source_capture.py`

```python
def is_internal_frame(frame: Any) -> bool:
    name: str = frame.f_globals.get("__name__", "") if hasattr(frame, "f_globals") else ""
    return name == "hassette" or name.startswith("hassette.")
# capture_source_location(...) returns "<file>:<lineno>" of the first non-internal frame.
```

### Per-execution context binding (the choke point that gains the thread-visible marker)

**Source:** `src/hassette/core/command_executor.py`

```python
def bind_execution_context(self, app_key: str | None, instance_index: int) -> tuple[str, Token[str | None]]:
    execution_id = str(uuid_utils.uuid7())
    token = CURRENT_EXECUTION_ID.set(execution_id)
    # ... structlog.contextvars.bind_contextvars(app_key=..., instance_name=..., instance_index=...)
    return execution_id, token
# unbind in the finally of execute_handler / execute_job
```

### Prod-override flag precedent (the model for `allow_deep_detection_in_prod`)

**Source:** `src/hassette/config/config.py`

```python
allow_reload_in_prod: bool = Field(default=False)
"""Whether to enable the file watcher for automatic app reloads in production mode.
When True, file changes trigger automatic app reloads (same as dev_mode). ... Defaults to False."""
```

## Alternatives Considered

- **`loop.set_debug(True)` + `slow_callback_duration` + a custom exception handler (do-less).** Smallest diff, catches any slow callback. Rejected as the primary mechanism: it pays the ~2–5µs/callback always-on tax the requirement specifically weighs against, and its signal is a framework-wrapper repr, not the app's blocking line. Strictly dominated by the Tier 1 watchdog. Could still serve as a throwaway spike to validate context enrichment, not as the shipped design.
- **Monkeypatch-only, always-on in production (HA's literal model).** Single mechanism, exact offending line. Rejected as the always-on default: process-global patching of builtins in production is a heavier footprint, is incomplete (silent on C-extension/C-driver blocking — the most dangerous real offenders), and HA itself runs this as a dev/CI gate, not a production always-on guard. Kept as the opt-in Tier 2.
- **Per-execution wall-clock timing in the command executor (no watchdog).** Dead-simple and perfectly attributed. Rejected because it cannot distinguish a 30s `await` (fine) from a 30s block (bad) — both show the same wall-clock — producing false positives on legitimately slow async work (FR#9).
- **Do nothing / rely on app authors.** Viable given the single-user reality, but the feature is cheap insurance and the issue is filed; the watchdog tier's cost is low enough to justify shipping.

## Test Strategy

### Existing Tests to Adapt
No existing tests are expected to break — the feature is additive. Tests that construct `HassetteConfig` or `AppConfig` with full field enumeration may need the new fields added; search `tests/` for direct construction of those configs and extend fixtures if they assert on exact field sets. The `HassetteHarness` (`src/hassette/test_utils/harness.py`) sets the task factory at line 534 and is the natural place to exercise watchdog install in integration tests.

### New Test Coverage
- **Spike validation (WP1)** — a focused test proving the chosen watchdog mechanism attributes a `time.sleep` stall to the correct app under the "next execution scheduled immediately" condition. (AC#2, FR#4)
- **Tier 1 unit/integration** — blocking handler trips exactly one warning with duration ≈ T (AC#1); `await asyncio.sleep` trips nothing (AC#3); executor offload trips nothing (AC#4); severe-stall stack snapshot present/absent paths.
- **Tier 2 unit/integration** — `time.sleep` on the loop thread raises in dev_mode before sleeping (AC#5); does not raise in prod without the flag (AC#5, AC#10); patches installed only when enabled; idempotent install/teardown leaves no residue (AC#9). Use the gate/sentinel patterns in `CLAUDE.md` (Regression test patterns).
- **Behavior resolution** — per-app override beats global, `ignore` suppresses warning + DB row (AC#6); mirror the `forgotten_await_behavior` resolution tests.
- **Persistence** — one row per event with correct attribution (AC#7); sentinel owner recorded as framework tier (AC#8); follow the sentinel-filtering test pattern in `CLAUDE.md`.

### Tests to Remove
No tests to remove.

## Documentation Updates

- **New concept page** under `docs/pages/core-concepts/` (e.g. `blocking-io-detection.md`) — what loop blocking is, the two tiers, the warn-vs-raise model, and the dev-default/prod-opt-in posture. Follow `voice-guide.md` (system-as-subject for concept pages) and use tested snippets per `doc-rules.md`. Run `doc-persona-review` and `doc-accuracy-review` on the new page before shipping (required by `.claude/rules/doc-rules.md`).
- **Config reference** — document `blocking_io.*` and `AppConfig.blocking_io_behavior`, alongside the existing `forgotten_await_behavior` and `asyncio_debug_mode` entries.
- **Docstrings** — on the new config model fields, the `BlockingIOBehavior` enum, the guard module's public functions, and `HassetteBlockingIOWarning`.
- **CHANGELOG** — none (release-please generates it from the `feat:` commit).
- **No frontend/docs-UI work** — UI surfacing is a Non-Goal this round.

## Impact

### Changed Files
- `src/hassette/core/command_executor.py` — **cross-cutting.** Adds a thread-visible execution marker, set in `bind_execution_context` (line 422) and cleared in `unbind_execution_context` (line 439, the paired teardown called from both `finally` blocks). Highest-risk change: it sits on every handler/job path. Must add no measurable overhead and must not alter existing attribution.
- `src/hassette/core/core.py` — install/teardown of the watchdog and (conditionally) the Tier 2 patches in `run_forever` (after line 449) and shutdown.
- `src/hassette/config/models.py` — new `BlockingIODetectionConfig`.
- `src/hassette/config/config.py` — wire `blocking_io` field next to `asyncio_debug_mode`.
- `src/hassette/app/app_config.py` — new `blocking_io_behavior` field.
- `src/hassette/types/enums.py` — new `BlockingIOBehavior`.
- `src/hassette/exceptions.py` — new `HassetteBlockingIOWarning`.
- `src/hassette/core/block_io_guard.py` — **new** Tier 2 module.
- `src/hassette/core/<watchdog>.py` — **new** Tier 1 module (name finalized after the spike).
- `src/hassette/migrations_sql/004.sql` — **new** `blocking_events` table.
- `src/hassette/core/telemetry_models.py` — new `BlockingEvent` model.
- telemetry repository — new write path for blocking events.
- `tests/...` — new coverage per Test Strategy.
- `docs/pages/core-concepts/blocking-io-detection.md` — **new** concept page.

<!-- Gap check 2026-06-15: clean — no unlisted dependencies. bind_execution_context has no external callers (marker change contained to command_executor); migration runner auto-discovers numeric *.sql stems (004.sql needs no wiring); all new identifiers (BlockingIOBehavior, HassetteBlockingIOWarning, BlockingEvent, blocking_io config, blocking_events table) have no existing consumers. Config-construction tests that enumerate fields → addressed in T01 Focus. -->

### Behavioral Invariants
- Existing per-execution attribution (`CURRENT_EXECUTION_ID`, structlog contextvars) must continue to behave identically — the new marker is additive and must not change the ContextVar lifecycle.
- Executor offload semantics (`run_in_thread`, `make_async_adapter`) must be unchanged.
- `forgotten_await_behavior` detection must be unaffected — the two guards share patterns but not state.
- Loop setup ordering in `run_forever` (task factory at line 453, service start sequence) must be preserved.

### Blast Radius
- The command-executor marker touches every handler and job invocation — the broadest surface. Everything else is opt-in-at-config or new modules with no existing consumers.
- Tier 2 monkeypatching is process-global while installed; it affects framework and third-party code in the process, gated to fire only on the loop thread. This is why it is dev-default / prod-opt-in.

## Open Questions

- [x] **RESOLVED — Watchdog mechanism (Candidate A vs B): Candidate B (off-loop daemon thread).** The T02 spike (`tests/unit/core/test_blocking_io_marker_spike.py`) proved that only an off-loop reader names the blocker: it reads the thread-visible marker *during* the freeze, while an in-loop heartbeat is starved until the freeze clears and can only ever see `None` or the next execution. See `## Architecture` → "Tier 1" for the recorded outcome. T03 builds the daemon watchdog on this mechanism.
- [x] **RESOLVED — Production event-loop policy (stdlib vs uvloop):** stdlib asyncio. The entry point is `asyncio.run(run_server(config))` (`src/hassette/cli/commands/run.py:45`) — no uvloop, no custom `EventLoopPolicy`. Tier 1 still uses loop-agnostic timing as good practice, but there is no uvloop debug-timing concern today.
- [x] **RESOLVED — Tier 1 default threshold values:** `lag_threshold_seconds=0.1`, `watchdog_interval_seconds=0.25` (set in T01's `BlockingIODetectionConfig`). The T02 spike confirmed these are sane against real timing — a sub-threshold daemon poll cleanly detected a 0.45s freeze. T03 may refine if integration testing surfaces false positives, but these are the committed defaults.
