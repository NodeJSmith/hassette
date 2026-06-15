---
proposal: "Add always-on guards that detect blocking I/O in user apps before/when it stalls Hassette's shared asyncio event loop, modeled on but adapted from Home Assistant's block_async_io."
date: 2026-06-15
status: Draft
flexibility: Exploring
motivation: "A single user app calling blocking I/O (file reads, sync HTTP, time.sleep, blocking DB drivers) stalls the shared event loop and degrades every other app on the instance."
constraints: "Always-on (production), not opt-in dev-only. Per-call overhead matters because always-on means the hot path. Must not flag framework-sanctioned executor offload (asyncio.to_thread / run_in_thread)."
non-goals: "Sandboxing apps; preventing blocking outright; catching blocking inside sync handlers that already run in the executor thread."
depth: deep
---

# Research Brief: Blocking-I/O Detection for Hassette's Shared Event Loop

**Initiated by**: Issue #162 — guard against blocking I/O in async apps, modeled on Home Assistant's `async_check_blocking` / blocking-call detection.

## Context

### What prompted this

Hassette runs every user app on one shared asyncio event loop. The loop is a single point of failure for responsiveness: if any app's handler or scheduled job calls a blocking primitive directly in a coroutine — `open()`, `requests.get()`, `time.sleep()`, a blocking DB driver — the loop cannot run any other callback until that call returns. Every other app's handlers, the bus, the scheduler, and the WebSocket reconnect logic all stall together. The framework wants to detect this, attribute it to the offending app, and warn (or optionally raise).

### Current state

Hassette already has the scaffolding this feature needs:

- **Loop setup** lives in `Hassette.run_forever()` at `src/hassette/core/core.py:444-453`. The loop is obtained via `asyncio.get_running_loop()` (created by the caller), then `self.loop.set_debug(self.config.asyncio_debug_mode)` (line 450) and `set_task_factory(...)` (line 453) run. The loop thread id is captured at line 449 (`self._loop_thread_id = threading.get_ident()`). No exception handler and no `slow_callback_duration` are set today. This is the natural hook point for any loop-level instrumentation.

- **A runtime-warning precedent exists**: `src/hassette/core/await_guard.py` detects forgotten `await`s. It is the closest existing pattern and the new feature should mirror its shape (Direct — read the file):
  - A three-state behavior enum `ForgottenAwaitBehavior` (`IGNORE` / `WARN` / `ERROR`) in `src/hassette/types/enums.py`.
  - Resolution order: per-app `AppConfig.forgotten_await_behavior` overrides global `HassetteConfig.forgotten_await_behavior`, which defaults to `WARN` (`await_guard.py:165-178`).
  - Emission via `warnings.warn(msg, HassetteForgottenAwaitWarning, stacklevel=1)` (`await_guard.py:113-120`). `ERROR` is realized by the user's `filterwarnings("error")`, not by raising directly — the warning class subclasses `RuntimeWarning`.
  - **Source attribution captured eagerly at call time, not at report time.** `capture_source_location()` (`src/hassette/utils/source_capture.py`) walks `inspect.stack()` and returns the first frame whose `__name__` does not start with `hassette.` — i.e. the first *user* frame. The behavior and owner identity are resolved eagerly too, so the `__del__` reporting path never touches config during teardown.

- **Config** is Pydantic v2 settings (`src/hassette/config/config.py`). Cross-cutting flags (`dev_mode`, `asyncio_debug_mode` at ~line 167, `forgotten_await_behavior` at ~line 193) live flat at the root; subsystems (`database`, `websocket`, `logging`, `scheduler`) are nested models via `Field(default_factory=...)` defined in `src/hassette/config/models.py`.

- **Per-execution attribution already exists** and is the single most important finding for actionability. `src/hassette/core/command_executor.py:bind_execution_context()` (~line 422) runs around every handler and job (`execute_handler` ~line 445, `execute_job` ~line 488). It sets `CURRENT_EXECUTION_ID` (`src/hassette/context.py:17`, a UUIDv7 ContextVar) and binds `structlog.contextvars` keys `app_key`, `instance_name`, `instance_index`. **These ContextVars are live for the entire duration a handler/job runs on the loop** — which is exactly the window during which a blocking call would fire. Detection can read them directly; no stack-to-app mapping is required to name the app.

- **Framework-sanctioned blocking** flows through `asyncio.to_thread`. Sync user handlers are normalized to async via `TaskBucket.make_async_adapter()` → `run_in_thread()` (`src/hassette/task_bucket/task_bucket.py:153-213`), which wraps `asyncio.to_thread`. The logging service offloads `QueueListener.stop()` the same way (`src/hassette/core/logging_service.py`). This blocking runs **on a worker thread, not the loop thread** — so any thread-id-gated detection (HA's exact mechanism) is automatically correct here: it only fires when `threading.get_ident() == loop_thread_id`, and executor work never satisfies that. This is the key reason the false-positive constraint is cheaply satisfiable.

### Key constraints

- **Always-on in production.** This is the hard constraint that eliminates the obvious answer. It rules out `loop.set_debug(True)` as the primary mechanism (see below) and forces a careful overhead budget on anything in the hot path.
- **Must not flag executor offload.** Satisfied automatically by thread-id gating.
- **Must name the offending app.** Satisfied by reusing the existing ContextVars.
- **Crash risk.** Always-on + raise could take down production apps for a blocking call that was merely slow, not fatal.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| Config surface (nested `BlockingIODetectionConfig` + per-app field) | `config/models.py`, `config/config.py`, `app/app_config.py` | Low | Low — mirrors `forgotten_await_behavior` exactly |
| Loop instrumentation install | `core/core.py` (`run_forever`, ~line 450) | Low | Med — loop-level hooks are global; must be idempotent and removable |
| Monkeypatch guards (`protect_loop` analog) | new module e.g. `core/block_io_guard.py` | Med | Med — choosing the primitive set, thread-id gating, install/teardown |
| App attribution helper | reuse `context.py` + `command_executor.py` (read-only) | Low | Low — ContextVars already populated |
| Behavior enum + warning class | `types/enums.py`, new `BlockingIOWarning` | Low | Low |
| Tests (gate-blocking, sentinel, executor-not-flagged) | `tests/` | Med | Low |
| Docs (concept page + config reference) | `docs/pages/...` | Low | Low — required by `design-completeness.md` |

### What already supports this

- **Thread-id gating is already half-built**: `self._loop_thread_id` is captured at `core.py:449`. HA's entire "is this call in the loop" decision is `threading.get_ident() == loop_thread_id`. Hassette already has the value.
- **App attribution is free** via `CURRENT_EXECUTION_ID` + structlog contextvars (no stack walking needed to name the app).
- **The `await_guard` template** gives a vetted, in-house answer to every cross-cutting question: behavior tiers, config resolution, warning class, eager source capture, teardown safety. The new feature is largely "the same shape, different trigger."
- **Frame filtering already exists**: `source_capture.py`'s "first non-`hassette.` frame" logic is exactly what's needed to point a stack at user code instead of framework internals.
- **Executor offload is structurally separated** onto worker threads, so the dominant false-positive source is excluded by construction.

### What works against this

- **`loop.set_debug(True)` is not viable always-on.** Confirmed against CPython `base_events.BaseEventLoop._run_once`: slow-callback timing is gated entirely behind `if self._debug:` — two `time()` calls per callback plus extra repr/lifecycle work, ~2–5µs per callback, on every callback the loop runs. `slow_callback_duration` does **nothing** unless debug mode is on; it only tunes the threshold once timing is active. So the cheapest-sounding option carries the heaviest always-on tax, and its signal is a useless callback repr (the handle is a framework wrapper, not the app's blocking line).
- **Monkeypatch completeness is fundamentally partial.** Wrapping Python-level primitives cannot catch blocking inside C extensions (numpy/pandas), C-based DB drivers (`psycopg2`, `mysqlclient`) that don't route through the Python `socket` module, or `libcurl`-backed clients. This is an inherent ceiling, not a Hassette-specific gap.
- **Loop-level hooks are global mutable state.** Monkeypatching builtins/stdlib affects the whole process, including the framework's own and third-party library code. Install/teardown must be careful, and tests must restore state (HA explicitly tears its patches down after tests).

## Options Evaluated

The strongest single source of truth on overhead is CPython's `_run_once` and the `blockbuster`/HA implementations; claims below are Supported by those plus the four exploration passes. Where a number is an order-of-magnitude estimate it is marked Inferred.

### Option A: Tiered — cheap always-on watchdog/slow-callback signal + opt-in deep monkeypatch (recommended)

**How it works**: Split the problem into a cheap always-on *symptom* detector and an opt-in *cause* detector.

- **Tier 1 (always-on, cheap): loop-lag watchdog.** A lightweight monitor measures how late the loop runs a periodic heartbeat. Concretely: schedule a `loop.call_later(interval, beat)` (e.g. interval 250ms) that records expected-vs-actual time; lag beyond a threshold means the loop was blocked. Reading `CURRENT_EXECUTION_ID` + structlog contextvars *at the moment lag is detected* names the app/handler/job that was on the loop. This is reactive (fires after the stall) but has near-zero per-callback cost — it adds one timer per interval, not work per callback — and unlike `set_debug` it can name the app via the live ContextVars. Optionally, when lag is severe, capture `sys._current_frames()[loop_thread_id]` for a stack snapshot pointing into the blocking line. This avoids `set_debug(True)` entirely.
  - Note: a watchdog implemented as a loop callback cannot fire *while* the loop is fully blocked; it fires on the next iteration after the block clears, and the lag measurement reveals the stall retroactively. A truly concurrent reading (stack dump *during* the block) requires a separate OS thread; that is a Tier-1.5 enhancement, not required for the MVP.

- **Tier 2 (opt-in, precise): `protect_loop`-style monkeypatch.** When enabled (dev, CI, or a deliberately-opted-in production instance debugging a known problem), patch a curated primitive set (`builtins.open`, `time.sleep`, `socket.socket.connect/recv/send`, `os.listdir`/`scandir`/`walk`, `glob`) with a guard that checks `threading.get_ident() == loop_thread_id`. On a hit, capture the first non-`hassette.` frame (reuse `source_capture.py`), read the ContextVars, and warn/raise per behavior. This is proactive and gives the exact offending line, at ~1–2µs per *guarded* call — but only on the patched primitives, and only when opted in, so the always-on budget is untouched.

This split directly answers the user's always-on-viability question: the always-on layer is the watchdog (symptom, cheap, names the app), and the precise layer (cause, exact line) is opt-in because its completeness/overhead/process-global tradeoffs don't justify forcing it on every instance.

**Pros**:
- Always-on layer has negligible per-callback overhead (one timer, not per-callback timing) — unlike `set_debug`.
- Names the offending app/handler/job out of the box by reusing `CURRENT_EXECUTION_ID` + structlog contextvars; no new attribution machinery.
- Executor offload is never flagged: thread-id gating in Tier 2, and Tier 1 measures loop lag which executor work doesn't cause.
- Tier 2 reuses the existing frame-filter (`source_capture.py`) and behavior-enum/warning patterns from `await_guard.py` — low conceptual surface area.
- Degrades honestly: Tier 1 admits "something blocked the loop for N ms, it was app X" even for numpy/C-driver blocking that monkeypatching can never catch.

**Cons**:
- Two mechanisms to build and document instead of one.
- Tier 1 is reactive — the warning arrives after the stall, and a loop-callback watchdog reads the *next* execution's context unless the stack/context is captured carefully at the lag-detection boundary. Getting "which app blocked" exactly right needs the heartbeat to compare against the handle that just ran (capture context in the task factory or command executor, surface it when lag is observed), or a separate watchdog thread that snapshots during the block.
- Tier 2's primitive list is a maintenance item and is inherently incomplete.

**Effort estimate**: Medium. Tier 1 watchdog + ContextVar read + config + warning class is small. Tier 2 monkeypatch module with install/teardown and a curated primitive set is the bulk. Tests for both, plus docs.

**Dependencies**: None required. Optionally vendor-inspired by `blockbuster` (cbornet/blockbuster) for the Tier 2 primitive list and `aiodebug` for the Tier 1 slow-callback/hang-inspection patterns — but reimplementing in-house is cleaner than adding a dependency given how small each piece is and the need to integrate with Hassette's ContextVars and config.

### Option B: Monkeypatch-only, always-on (HA's exact model)

**How it works**: Skip the watchdog. Always-on `protect_loop`-style guards on a curated primitive set, thread-id gated, attributing via ContextVars and the `source_capture.py` frame filter. Default `WARN`. This is the most literal reading of issue #162 ("modeled on HA's block_async_io").

**Pros**:
- Single mechanism; proactive; exact offending line.
- ~1–2µs per guarded call is acceptable for the realistic frequency of `open`/`sleep`/`socket` in app code.
- Closest to the issue's stated reference; HA runs essentially this.

**Cons**:
- Process-global monkeypatching of builtins/stdlib affects the framework and all third-party libraries always, in production. HA accepts this; it's a heavier always-on footprint than a watchdog.
- Inherently incomplete: silent on numpy/pandas/C-driver/libcurl blocking. The user is told "we guard blocking I/O" but the most dangerous real-world offenders (a blocking DB driver) can slip through. A watchdog would still catch those as loop lag.
- Patch set is a standing maintenance and false-positive surface (e.g. legitimate sync work paths that aren't via the executor).
- **Important nuance vs HA**: HA's blocking detection is *not* truly always-on in production in the sense the user wants — it's enabled via `block_async_io.enable()` and is primarily a dev/CI correctness gate, torn down after tests. Adopting it as a hard always-on production guard goes somewhat beyond HA's own posture.

**Effort estimate**: Medium (slightly less than A — one mechanism).

**Dependencies**: None.

### Option C: Slow-callback logging only (do-less)

**How it works**: The minimal change. In `run_forever`, after line 450, install a custom loop exception handler and rely on asyncio's slow-callback warning. To get the signal you must enable debug mode (or replicate its timing), set `loop.slow_callback_duration`, and route the resulting warning through Hassette's logger, enriched with the live ContextVars.

**Pros**:
- Smallest diff; no monkeypatching, no new module.
- Catches *any* slow callback regardless of cause (numpy included), because it times the callback, not specific primitives.

**Cons**:
- **Requires `set_debug(True)` to get the timing at all** — the ~2–5µs/callback always-on tax the user specifically asked us to weigh, applied to every callback. This is the worst overhead profile of the three for an always-on requirement.
- asyncio's native message is a callback repr (a framework wrapper handle), not the app's blocking line — low actionability without extra context plumbing.
- Conflates "slow async work" (a legitimately expensive coroutine) with "blocking I/O" — more false positives than the watchdog, which can be tuned on lag magnitude.

**Effort estimate**: Small.

**Dependencies**: None.

Option C is strictly dominated by Tier 1 of Option A: the watchdog gets the same "something stalled the loop" signal *without* paying `set_debug`'s per-callback tax, and names the app the same way. Recommend C only as a throwaway spike to validate the ContextVar-enrichment plumbing, not as the shipped design.

## Concerns

### Technical risks

- **Reactive attribution accuracy (Tier 1).** A loop-callback watchdog observes lag *after* the blocking handle finished; the obvious `CURRENT_EXECUTION_ID.get()` at that point may read the *next* execution. Mitigation: capture the execution context of each handle as it runs (the task factory at `core.py:453` and `command_executor.bind_execution_context` are the natural capture points) and attribute the lag to the handle that *just ran long*, not the one currently on the loop. This is the single most important correctness detail to prototype.
- **Monkeypatch install/teardown (Tier 2).** Patching builtins is process-global. Install must be idempotent, restore originals on shutdown, and be test-isolated (HA's "undo after tests" lesson). A leaked patch corrupts unrelated test runs — directly relevant given the project's `pytest -n auto` sensitivity noted in repo memory.
- **uvloop / alternate loops.** If Hassette ever runs on uvloop, `slow_callback_duration`/`set_debug` semantics differ; the watchdog (pure `call_later` lag) is loop-agnostic and more portable. Confirm which loop policy Hassette uses today before leaning on debug-mode behavior.

### Complexity risks

- Two tiers mean two config switches, two code paths, two docs sections, two failure modes to reason about. The laziness/reader-load instinct says start with one. The counter-argument is that always-on viability genuinely forces the split: no single mechanism is simultaneously cheap, always-on, complete, and actionable.
- The behavior enum (`warn`/`raise`/`ignore`) multiplied by per-app overrides multiplied by two tiers is a combinatorial surface. Keep the resolution logic in one place, mirroring `await_guard.py`'s single resolver.

### Maintenance risks

- The Tier 2 primitive list is a living artifact: new stdlib surfaces, new common blocking libraries. Treat it as data, not scattered patches, so it's auditable in one place.
- Committing to "Hassette guards blocking I/O" sets a user expectation the monkeypatch tier cannot fully meet (C-extension blocking). The watchdog tier is what honors the promise for the uncatchable cases; messaging should be honest that Tier 2 is "known-primitive" detection, not total.

## Open Questions

- [x] **RESOLVED — Default behavior: `warn` or `raise`?** Both, on different tiers. Tier 1 watchdog ships default-on as warn-after; Tier 2 monkeypatch is intercept + raise, dev-mode default and prod-opt-in. See "Decisions Resolved" below.
- [ ] **Which event loop policy does Hassette use in production (stdlib vs uvloop)?** Determines whether any debug-mode timing is even portable. (Searched `core.py` run_forever; loop is taken from `get_running_loop()`, so the policy is set by the entry point/caller — not confirmed in this pass.)
- [ ] **Should scheduled jobs and bus handlers share one detection path or be configured separately?** Both already set the same ContextVars via the command executor, so a unified path is feasible; confirm desired granularity.
- [ ] **Tier 2 primitive set scope** — start with HA's list (`open`, `time.sleep`, `socket`, `os` dir ops, `glob`, `importlib`, SSL cert loads) or a leaner Hassette-specific subset? (Searched HA `block_async_io.py` via web; full list captured in research.)
- [ ] **Watchdog implementation: loop callback vs dedicated thread?** A loop callback is simpler but reactive; a dedicated daemon thread can snapshot the loop thread's stack *during* a block via `sys._current_frames()`. Decide for MVP. (Not resolved by code reading — needs a prototype.)
- [x] **RESOLVED — Tier 2 gated behind `dev_mode` by default with an explicit prod opt-in flag?** Yes — modeled on the existing `watch_files` hot-reload flag (a normally-dev behavior with a deliberate production override).
- [→] **Event-loop isolation (framework vs. app loops)** — split into a separate effort, tracked in **#1038**. It would resolve the watchdog reactive-attribution question by letting a core-loop watchdog monitor the app loop, but it is not a blocker for the detection feature. See "Related: Event-Loop Isolation" below.

## Decisions Resolved (post-research discussion)

A clarifying discussion after the brief settled the framing and the warn-vs-raise question.

**Detect-after and intercept-before are two different mechanisms, and both are wanted.** A `time.sleep(30)` in a handler can be met three ways: *ignore* (stall silently), *warn-after* (stall the full 30s, then log), or *intercept + raise* (the sleep never runs; the handler fails immediately). Warn-after is the watchdog; intercept + raise is the monkeypatch. The watchdog **reports** the stall after the fact; only the monkeypatch **prevents** it. The original issue intent — "a warning, and the action wouldn't happen" — is the intercept + raise behavior.

**Agreed direction:**

- **Tier 1 (watchdog) ships default-on as warn-after** — the always-on safety net. It also catches what monkeypatching cannot (numpy, C DB drivers, libcurl) as raw loop lag.
- **Tier 2 (monkeypatch) is intercept + raise**, defaulting on in `dev_mode` and force-enableable in production via an explicit flag, modeled on the existing `watch_files` hot-reload flag.
- Priority between the two tiers is now explicit: watchdog = default safety net; monkeypatch = the foot-gun stopper that is dev-default / prod-opt-in.

This supersedes the brief's earlier hedging on warn-vs-raise: the answer is **both, on different tiers, with different defaults.**

## Related: Event-Loop Isolation (separate effort — tracked in #1038)

A separate architectural question surfaced: should Hassette internals (WebSocket, bus dispatch, scheduler, web UI) run on a different event loop and thread than user apps, so a blocking app cannot freeze the framework's lifeline?

- **Feasible.** One loop per thread; core ↔ app communication via `run_coroutine_threadsafe` / `call_soon_threadsafe`. Blocking I/O releases the GIL, so the core thread keeps running while an app thread is parked in `time.sleep`.
- **Solves** app-blocks-framework (internals stay observable and recoverable). **Does not solve** app-blocks-other-apps — all apps share the app loop unless taken further to a loop/thread per app.
- **Cost.** Every framework↔app boundary becomes cross-thread: every `self.api.*` call, ContextVar propagation across loops, loop-aware shared primitives. Foundational, not a bolt-on.
- **Synergy with detection.** A watchdog on the *core* loop monitoring the *app* loop is never the blocked one — it can detect stalls in real time and snapshot the blocked app thread via `sys._current_frames()[app_thread_id]`, resolving the reactive-attribution flaw flagged above. Isolation makes warn-after both safer to default and more reliable to build.
- **Decision.** Kept separate from #162. The detection feature ships against today's single-loop architecture; loop isolation gets its own research/ADR (#1038). It is the change that would *justify* warn-after as the comfortable default, but it is a major investment whose main beneficiary — multiple careless app authors — does not exist yet.

## Recommendation

**Build Option A (tiered), defaulting Tier 1 (loop-lag watchdog) to always-on `warn` and Tier 2 (monkeypatch) to opt-in.** Confidence: Supported for the mechanism choice (grounded in CPython `_run_once`, HA's implementation, and the existing Hassette scaffolding); Inferred on the exact overhead deltas.

The reasoning the user asked us to resolve:

- **Is always-on viable per approach?** Only the watchdog is genuinely viable always-on. `set_debug`-based slow-callback detection (Option C) pays a per-callback tax on the hot path and is dominated by the watchdog. Always-on monkeypatching (Option B) is viable on overhead but pays a process-global footprint and is incomplete; better as the opt-in deep tier. So the realistic always-on recommendation *is* the tiered design — the watchdog is the cheap always-on signal, monkeypatch is the opt-in deep detector. This matches the hypothesis embedded in the prompt.

- **Warn vs raise default.** Default to `warn`. Always-on + `raise` can crash a production app over a blocking call that merely stalled the loop briefly — a worse outcome than the stall it's reporting. Mirror `await_guard.py`: a three-state `IGNORE`/`WARN`/`ERROR` enum, global default `WARN`, per-app override, and realize `ERROR`/raise via a `BlockingIOWarning` + the user's `filterwarnings("error")` (or an explicit strict flag) rather than an unconditional raise. This gives strict-mode users (CI, a hardened instance) the hard failure without imposing it on everyone.

- **App attribution.** Reuse `CURRENT_EXECUTION_ID` + the `app_key`/`instance_name`/`instance_index` structlog contextvars set in `command_executor.bind_execution_context`. No stack-to-app mapping needed for naming; the `source_capture.py` frame filter supplies the offending *line* for Tier 2.

- **False positives on framework offload.** Thread-id gating (`threading.get_ident() == self._loop_thread_id`, value already captured at `core.py:449`) makes executor work structurally invisible to Tier 2, and the watchdog measures loop lag that executor work doesn't cause. The constraint is satisfied by construction.

### Config surface to add

Nested model in `config/models.py`, wired into `config/config.py` next to `asyncio_debug_mode`, plus a per-app override in `app/app_config.py` (mirroring `forgotten_await_behavior`):

```python
class BlockingIODetectionConfig(ExcludeExtrasMixin, BaseModel):
    behavior: BlockingIOBehavior = BlockingIOBehavior.WARN   # IGNORE | WARN | ERROR
    lag_threshold_seconds: float = Field(default=0.1, ge=0.001)  # Tier 1 watchdog
    watchdog_interval_seconds: float = Field(default=0.25, ge=0.01)
    deep_detection_enabled: bool = False                     # Tier 2 monkeypatch opt-in
    capture_stack_on_block: bool = True                      # Tier 1 stack snapshot on severe lag
```

Per-app: `blocking_io_behavior: BlockingIOBehavior | None = None` resolving global → `WARN`, exactly as `forgotten_await_behavior` does.

### Suggested next steps

1. **Prototype the Tier 1 watchdog attribution in a branch** — the one genuinely uncertain piece. Validate that a `call_later` heartbeat plus per-handle context capture (at the task factory / command executor boundary) correctly names *the handler that just blocked*, not the next one. This is the make-or-break detail; resolve it before committing to the full design. (`/mine.define` after the spike.)
2. **Confirm the event-loop policy** (stdlib vs uvloop) at the entry point so the design doesn't lean on non-portable debug-mode timing.
3. **Draft a design doc** (`/mine.define`) capturing: the two tiers, the `BlockingIOBehavior` enum + resolver mirroring `await_guard.py`, the config surface above, the Tier 2 primitive list (seeded from HA's `block_async_io.py`), and the docs/frontend obligations from `design-completeness.md`.
4. **Run `/mine.challenge`** on the design before implementation — the tiered split, the reactive-attribution risk, and the always-on-`warn` default are exactly the kind of decisions worth poking holes in.

## Sources

- Home Assistant `block_async_io.py` / `util/loop.py`: https://github.com/home-assistant/core/blob/dev/homeassistant/block_async_io.py
- HA blocking-operations developer docs: https://developers.home-assistant.io/docs/asyncio_blocking_operations/
- HA 2024.7 changelog (blocking-check rollout, test teardown): https://www.home-assistant.io/changelogs/core-2024.7/
- CPython `asyncio/base_events.py` (`_run_once`, debug-gated slow-callback timing): https://github.com/python/cpython/blob/main/Lib/asyncio/base_events.py
- Python asyncio dev/debug docs (`slow_callback_duration`, `set_debug`): https://docs.python.org/3/library/asyncio-dev.html
- `blockbuster` (monkeypatch primitive set, test-oriented): https://github.com/cbornet/blockbuster — intro: https://dev.to/cbornet/introducing-blockbuster-is-my-asyncio-event-loop-blocked-3487
- `aiodebug` (`log_slow_callbacks`, `hang_inspection` watchdog + stack dumps): https://gitlab.com/quantlane/libs/aiodebug , https://pypi.org/project/aiodebug/
- `aiomonitor` (out-of-loop monitoring thread, live stack introspection): https://github.com/aio-libs/aiomonitor
