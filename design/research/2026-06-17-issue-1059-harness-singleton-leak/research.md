# Research Brief: Fix 3.11 test-isolation cascade from harness teardown leaking the global Hassette singleton

---
proposal: "Find the true root cause and minimal fix for a Python-3.11-only test-isolation cascade where harness teardown leaks the global Hassette singleton when a service is driven STOPPED→FAILED during shutdown."
date: 2026-06-17
status: Draft
flexibility: Exploring
motivation: "A flaky/cascading test-isolation failure that only manifests on Python 3.11 produces 86-97 'Hassette instance is already set' errors per run, blocking confidence in the suite."
constraints: "Test infrastructure (src/hassette/test_utils/) plus core lifecycle (src/hassette/resources/, src/hassette/core/). Core changes warrant system + e2e suites before shipping. Fix minimal and low-risk."
non-goals: "Not redesigning the lifecycle state machine; not changing production shutdown ordering unless it is the proven cause."
depth: deep
---

**Initiated by**: GitHub issue #1059 — investigate why harness teardown leaks the global singleton on Python 3.11, and decide between (1) a defensive `try...finally` singleton clear and (2) a transition-guard / ordering fix, or a cleaner root-cause alternative.

## Context

### What prompted this

On Python 3.11 only, the test suite produces 86-97 cascading `RuntimeError("Hassette instance is already set")` failures per run on a single xdist worker. The reported mechanism: a service is driven `STOPPED → FAILED` during harness teardown; because the harness forces `strict_lifecycle=True`, that transition raises `InvalidLifecycleTransitionError`; the exception escapes `HassetteHarness.stop()` *before* the singleton context var is reset, leaving the global `HASSETTE_INSTANCE` set. Every subsequent test that constructs a harness then trips `set_global_hassette`'s "already set" guard.

### Current state

**Singleton management** (`src/hassette/context.py:40-59`). `HASSETTE_INSTANCE` is a bare `ContextVar` (no default). `set_global_hassette()` returns a `Token` on first set, returns `None` if the same instance is re-set, and raises `RuntimeError("Hassette instance is already set. ...")` if a *different* instance is set while one is live (context.py:42-43). The harness stores the token and resets it in `stop()`.

**Harness teardown** (`src/hassette/test_utils/harness.py:607-660`). The sequence:
1. `shutdown_event.set()` (608)
2. stop loop watchdog — `try/except`, errors collected (614-619)
3. shut down children in `reversed(self.hassette.children)` — `try/except` per child, errors collected (621-626)
4. close event streams — `try/except`, collected (632-637)
5. close exit stack — `try/except`, collected (639-642)
6. restore task factory + null out loop refs — **no `try/except`** (644-647)
7. **singleton reset** — **no `try/except`** (649-650)
8. `api_mock.assert_clean()` — `try/except`, collected (653-657)
9. if any collected errors: `raise ExceptionGroup(...)` (659-660)

The singleton reset at line 650 runs only if nothing between line 624's collected loop and line 650 raises *uncaught*. Steps 6 and 7 are the only unguarded statements before the reset.

**Lifecycle state machine** (`src/hassette/resources/mixins.py:18-74, 155-183`). `VALID_TRANSITIONS` makes `STOPPED` near-terminal: `STOPPED → {STARTING}` only (mixins.py:48). `STOPPED → FAILED` is **not** legal. The `status` setter validates transitions only when `self.hassette.config.strict_lifecycle is True` — then it raises `InvalidLifecycleTransitionError` (mixins.py:165-170); otherwise it logs a warning and proceeds (mixins.py:171-178). **The harness forces strict mode** (`harness.py:316-317`: `if not config.strict_lifecycle: config.strict_lifecycle = True`). Production defaults to `strict_lifecycle=False` (`config/config.py:160`), so in production the same transition only logs a warning — this is why the bug is test-only.

**The "bus is down" RuntimeError.** The literal string does not exist in `src/`; it is the issue author's paraphrase. The matching real error is `RuntimeError("cannot schedule new futures after shutdown")`, raised by the stdlib `ThreadPoolExecutor` when `loop.run_in_executor(self.hassette.sync_executor, _call)` (`task_bucket/task_bucket.py:230`) submits to an already-shut-down `SyncExecutorService.executor`. `SyncExecutorService.on_shutdown` calls `executor.shutdown(...)` (`sync_executor_service.py:205`); the interruptible executor's `shutdown` calls `super().shutdown(wait=False, cancel_futures=True)` (`interruptible_executor.py:161`), after which any further submit raises.

### Key constraints

- Test infra + core lifecycle. Per CLAUDE.md, core changes require `nox -s system` and `nox -s e2e` before shipping.
- Minimal, low-risk diff (laziness-protocol, subtract-first).
- Never run `pytest -n auto` locally (auto-memory: froze the machine); push and let CI run heavy suites.
- e2e/system suites do **not** run on 3.11 (`noxfile.py:67,93` gate them to 3.13/3.14); only `tests` and `coverage` sessions hit 3.11 (`noxfile.py:44,153`). The bug therefore surfaces in the unit/integration suite under xdist `--dist loadscope`.

## Feasibility Analysis

### The trigger sequence (root cause)

The bug is a **teardown ordering race**, not a defect in the singleton clear itself. The chain:

1. A service (the `SyncExecutorService`, or any service whose serve task / shutdown hook still submits sync work) reaches `STOPPED` during teardown — via `Service.shutdown()` cancelling the serve task, whose `except CancelledError` path calls `handle_stop()` → `STOPPED` (`service.py:163-167`), then `_finalize_shutdown()` calls `handle_stop()` again (idempotent, `base.py:444-446`).
2. *After* the executor is stopped, something still routed to the sync executor submits work: `loop.run_in_executor(...)` (`task_bucket.py:230`) raises `RuntimeError("cannot schedule new futures after shutdown")`.
3. That `RuntimeError` is surfaced on a code path that calls `handle_failed(exc)` on an *already-STOPPED* resource. `handle_failed` sets `self.status = ResourceStatus.FAILED` (`mixins.py:284`).
4. With `strict_lifecycle=True`, the `STOPPED → FAILED` assignment raises `InvalidLifecycleTransitionError` from inside the status setter (`mixins.py:166`).

**Where the exception escapes the collected-error net.** Most `handle_failed` calls during shutdown are wrapped in `with suppress(Exception)` (`base.py:298, 304, 307`; `service.py:171, 174`), so the transition error is swallowed *there* and would never escape `stop()`. The **unguarded** call is the serve-wrapper's terminal handler: `service.py:181-184` runs `await self.handle_failed(e)` with no suppression. If a late submission's `RuntimeError` surfaces inside a still-live serve task (or any task spawned in the harness's task bucket) and routes through that path, the `InvalidLifecycleTransitionError` propagates out of the task. Whether it then escapes `stop()` *before* line 650 depends on **when that task's exception is finalized relative to the synchronous body of `stop()`** — which is exactly the asyncio-version-sensitive part (see "Why 3.11 only").

Confidence: **Supported** for the STOPPED→FAILED-under-strict mechanism (directly readable in mixins.py:48,165-170 + harness.py:316-317). **Inferred** for which specific task surfaces the `RuntimeError` and which `handle_failed` site is unsuppressed — the suppress-wrapping at base.py:298/304/307 means the escape must come through an unsuppressed path (service.py:184 is the only one found), but I could not capture a live traceback pinning the exact submitter. An implementer should capture the real traceback first (see Open Questions).

### Why the harness differs from production (the structural gap)

Production shuts down via **wave-based** ordering: `Hassette._shutdown_children()` iterates `reversed(self._init_waves)`, gathering each dependency wave and draining it fully before the next (`core.py:643-674`). Because `BusService`, `SchedulerService`, and `AppHandler` all declare `depends_on=[..., SyncExecutorService]` (`sync_executor_service.py:62-65`), the executor is in the *last* wave — every submitter is fully stopped and drained before the executor closes. The `SyncExecutorService` module docstring (lines 8-12) asserts this guarantee.

The **harness** does not use waves. It tears down with a flat `for resource in reversed(self.hassette.children)` (`harness.py:622`). Children are added in `STARTUP_ORDER`, a topological sort of the harness `DEPENDENCIES` graph (`harness.py:262-277`), so at the *component* level `sync_executor` is added first and torn down last — matching production intent. But the flat reverse loop drains each resource sequentially with no wave barrier: it `await`s `resource.shutdown()` one at a time and does not gather-drain a whole dependency level before proceeding. Pending tasks spawned by an earlier-torn-down resource can still be in flight (and still submit to the executor) when the executor is torn down. The harness reproduces a race that production's wave barrier closes.

Confidence: **Supported.** The two code paths are directly comparable (core.py:643-674 vs harness.py:622) and the `depends_on` wave guarantee is documented and readable.

### Why 3.11 only

The transition error and the singleton reset are version-independent; the *timing* of when a background-task exception finalizes relative to the `stop()` coroutine body is not. Two version-sensitive factors plausibly explain 3.11-only reproduction:

- **Task scheduling/finalization order changed in 3.12.** 3.12 introduced eager-task infrastructure and changed when the exception handler runs relative to the originating task's context. The net effect is that the *interleaving* of a doomed background task's exception with the teardown coroutine's synchronous statements differs between 3.11 and 3.12+. On 3.11, the `InvalidLifecycleTransitionError` from the late `handle_failed` is finalized in a window that lets it propagate out of `stop()` before line 650; on 3.12+ the same error is finalized later (or in a different context) so the reset at 650 runs first. ([Python 3.12 What's New — asyncio](https://docs.python.org/3.12/whatsnew/3.12.html), [Python 3.11 vs 3.12 asyncio differences](https://medium.com/h7w/python-3-11-and-3-12-differ-on-asyncio-and-may-break-your-code-ce4d3007f08c))
- **`run_in_executor` cancellation-after-shutdown timing.** There is a known 3.11 behavior where `run_in_executor` futures and their threads interact differently with cancellation/shutdown ([cpython#107505](https://github.com/python/cpython/issues/107505)). This can change whether a late submission raises synchronously at `run_in_executor` call time or is deferred.

The repo already documents one 3.11-vs-3.12 asyncio-adjacent divergence (coverage `settrace` vs PEP 669 `sys.monitoring`, `tests/unit/task_bucket/test_interruptible_executor.py`), confirming the team accepts version-gated behavior in this subsystem.

Confidence: **Inferred, leaning Speculative.** The general direction (3.12 changed task/exception finalization timing) is **Supported** by the docs and the linked article. The claim that *this specific* error escapes on 3.11 but not 3.12 *because of* that change is **Inferred** — I did not reproduce the divergence or capture both tracebacks. An implementer should confirm by reproducing on 3.11 and 3.12 (Open Questions). Do not ship a fix whose correctness *depends* on a precise 3.11 finalization theory; ship one that holds regardless of timing.

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| Defensive: wrap singleton reset in `finally` | `src/hassette/test_utils/harness.py` (stop) | Low | Low — test-infra only |
| Ordering: drain/wave the harness teardown like production | `src/hassette/test_utils/harness.py` (stop, ~622) | Medium | Medium — could mask other races, changes teardown semantics |
| Routing: don't drive an already-STOPPED resource to FAILED during shutdown | `src/hassette/resources/mixins.py` (handle_failed) or `service.py:184` | Medium | Medium-High — touches core failure routing; behavior shared with production |
| Regression test | `tests/unit/test_framework_injection_points.py` (new class) | Low | Low |
| Verification | system + e2e nox sessions | — | gated to 3.13/3.14, won't cover the 3.11 path |

### What already supports a clean fix

- The singleton reset is already a single, idempotent-by-token statement (`harness.py:649-650`). Wrapping it in `finally` is a 3-line, semantically obvious change.
- The harness already *collects* errors into `shutdown_errors` and raises an `ExceptionGroup` at the end — the design intent is "tear everything down, then report." The unguarded reset is an inconsistency with that intent, not a deliberate ordering choice.
- `handle_stop`/`handle_failed` are already guarded with early-return idempotence (`mixins.py:266-268, 279-281`), so a STOPPED→FAILED guard fits the existing style.
- An isolation-test pattern already exists: `clean_hassette_context` fixture and `TestSetGlobalHassetteReturnsToken` in `tests/unit/test_framework_injection_points.py` test exactly the token set/reset contract.

### What works against a fix

- The serve-wrapper's terminal `handle_failed` (`service.py:181-184`) is **shared with production**. Changing it risks altering production failure routing. A routing fix must be scoped to "don't fail a resource that is already STOPPED," not "swallow serve errors."
- The harness intentionally diverges from production teardown in several places (`_HarnessEventStreamService`, mock executors). Making harness teardown wave-based to match production is a larger change that could surface or hide unrelated races.

## Options Evaluated

### Option A: Defensive `try...finally` singleton clear in harness `stop()` (candidate 1)

**How it works.** Move the singleton reset (and the loop-ref nulling) into a `finally` block wrapping the whole teardown body so the contextvar is always reset before `stop()` returns or re-raises, regardless of what escaped. Concretely: wrap the steps from line 608 onward in `try`, and in `finally` run the loop-restore + `HASSETTE_INSTANCE.reset(token)`. Collected errors still raise as the `ExceptionGroup` after the finally clears state.

**Pros**:
- Smallest, lowest-risk diff — test-infra only, zero production impact.
- Holds **regardless of timing** — fixes the symptom on 3.11, 3.12, 3.13, and any future version, and regardless of which exact exception escapes. This is the property the bug most needs: the cascade is caused by *any* uncaught escape before the reset, not specifically by `InvalidLifecycleTransitionError`.
- Matches the existing "tear down fully, then report" design intent already encoded in `shutdown_errors`/`ExceptionGroup`.

**Cons**:
- Defensive: treats the symptom (leak on escape), not the cause (why STOPPED→FAILED happens). The underlying ordering race still fires and still logs a strict-mode error; the cascade just stops.
- A test relying on `stop()` raising cleanly will now see the singleton already cleared — desirable here, but worth a note.

**Effort estimate**: Small.
**Dependencies**: none.

### Option B: Don't drive an already-STOPPED resource to FAILED during shutdown (candidate 2, root-cause)

**How it works.** Add an early return / guard so `handle_failed` is a no-op when the resource is already in a terminal state (`STOPPED`, `CRASHED`, `EXHAUSTED_DEAD`) **and** shutdown has been requested. The cleanest insertion is in `handle_failed` (`mixins.py:278`): if `self.status in TERMINAL_STATUSES` (or `== STOPPED`) and `self.shutdown_event.is_set()`, log-and-return instead of setting FAILED. This makes the late "cannot schedule new futures after shutdown" `RuntimeError` benign during teardown — which it genuinely is, since the executor is *supposed* to be closed by then.

Alternatively, scope the guard to the serve-wrapper terminal handler (`service.py:181-184`): if `self.shutdown_event.is_set()`, route to `handle_stop()` instead of `handle_failed()` (mirroring the `ClosedResourceError` branch at service.py:168-175, which already treats shutdown-time errors as benign stops).

**Pros**:
- Addresses the cause: a shutdown-time submit-after-close is benign and should not be a failure. The `ClosedResourceError` branch already encodes exactly this "during shutdown it's a stop, not a failure" judgment (service.py:169-175) — this extends the same principle to the `RuntimeError`/terminal-state case.
- Fixes the noisy strict-mode warning/error in **production** too (production currently logs an invalid-transition warning on this path).
- Removes a real invalid transition rather than papering over its consequence.

**Cons**:
- Touches core failure routing shared with production — higher blast radius; needs system + e2e coverage, which do **not** run on 3.11.
- Risk of over-broadening: a guard that swallows *all* failures once `shutdown_event` is set could mask a genuine failure that occurs during shutdown. Must be scoped to terminal-state-or-benign-error, not "ignore everything during shutdown."
- Does not, by itself, protect the singleton clear against *other* future escapes (a different unguarded exception before line 650 would re-leak).

**Effort estimate**: Medium.
**Dependencies**: none.

### Option C: Make harness teardown wave-aware (do-more, address the ordering divergence)

**How it works.** Replace the flat `for resource in reversed(self.hassette.children)` loop (harness.py:622) with the same wave-based drain production uses (`core.py:643-674`), or delegate harness teardown to the production `_shutdown_children()` path. This closes the race at its structural source — the executor would never be torn down while a submitter still has in-flight tasks.

**Pros**:
- Eliminates the divergence between harness and production teardown, so the harness exercises the real shutdown path. Highest fidelity.
- Closes the race at the root: no late submission can reach a closed executor.

**Cons**:
- Largest, riskiest change. The harness diverges from production deliberately in several spots; unifying teardown could surface or hide unrelated races and break other module-scoped fixtures.
- Over-engineered for a test-isolation bug per laziness-protocol / subtract-first. The cascade is fixable with 3 lines (Option A); rewriting teardown to fix it is disproportionate.
- Still does not defend the singleton clear against unrelated future escapes.

**Effort estimate**: Large.
**Dependencies**: none.

## Concerns

### Technical risks
- **The exact escaping traceback is unconfirmed.** The suppress-wrapping at base.py:298/304/307 means the escape must traverse an unsuppressed path (service.py:184 is the only one found in the trace). If the real escape is elsewhere (e.g., an `ExceptionGroup` re-raise interaction, or a task surfaced during loop teardown at harness.py:644-647), a routing-only fix (Option B) could miss it while Option A would still catch it. Capture the real traceback before committing to B alone.
- **Option B blast radius.** `handle_failed` and the serve-wrapper are production code. A mis-scoped guard could swallow genuine shutdown-time failures. Scope strictly to terminal-status or shutdown-benign errors.
- **3.11 verification gap.** system/e2e nox sessions skip 3.11 (noxfile.py:67,93). The fix's 3.11 behavior is only exercised by the unit/integration suite. The regression test must run on 3.11 (it does — `tests`/`coverage` sessions include 3.11).

### Complexity risks
- Option C adds a new failure mode (harness teardown semantics drift from the simple reverse-order model that other fixtures may implicitly rely on).

### Maintenance risks
- Option A leaves the underlying ordering race live (it still logs a strict-mode invalid-transition warning during teardown). If that warning trips `filterwarnings`-as-error config in some session, it could become a separate flake. Check whether the strict-mode warning is currently surfacing in CI logs.

## Open Questions

- [ ] **Capture the real escaping traceback on 3.11.** Run the failing suite under 3.11 with `-p no:randomly` disabled / faulthandler and log the full `InvalidLifecycleTransitionError` stack. Confirm which resource (SyncExecutorService? a Bus/Scheduler child?) and which `handle_failed` call site (service.py:184 vs another) is the source. This decides whether Option B's guard location is correct.
- [ ] **Reproduce the 3.11-vs-3.12 divergence.** Add a temporary test that forces a late submit-after-shutdown and assert it escapes `stop()` on 3.11 but not 3.12, to confirm the timing theory. (Searched: Python 3.12 What's New asyncio, cpython#107505, 3.11/3.12 asyncio difference articles — found general task-finalization-timing changes but no statement pinning *this* exact case.)
- [ ] **Is the strict-mode invalid-transition warning already polluting CI logs?** If so, Option B (or a routing fix) is warranted on its own merits beyond the singleton cascade.
- [ ] **Does any test rely on `stop()` raising with the singleton still set?** Grep for tests that assert on `stop()` raising; confirm none depend on the leaked-singleton ordering.

## Recommendation

**Ship Option A (defensive `try...finally`) as the primary fix, and add a scoped version of Option B (Option B via the serve-wrapper / `handle_failed` terminal-state guard) as a paired root-cause fix — but only after capturing the real traceback.** These are complementary, not redundant, and the defense-in-depth is justified here:

- **Option A is the correct primary fix** because the cascade's proximate cause is *an uncaught exception escaping before the singleton reset* — and that can happen for reasons beyond this one transition. A `finally` clear makes the harness robust to *any* teardown escape, on any Python version. It is 3 lines, test-infra-only, zero production risk, and consistent with the harness's existing "collect errors, report at the end" design. This alone stops the 86-97-error cascade.

- **Option B is worth adding** because the STOPPED→FAILED transition is a genuine bug: a submit-after-shutdown `RuntimeError` during teardown is benign (the executor is *meant* to be closed), and the codebase already treats the analogous `ClosedResourceError`-during-shutdown as a stop, not a failure (service.py:168-175). Extending that judgment removes a real invalid transition and silences a production warning. But it touches shared core code, so scope it tightly (terminal-status-or-shutdown-benign only) and verify it against the captured traceback first.

- **Do not pursue Option C now.** Rewriting harness teardown to be wave-aware is disproportionate to a test-isolation bug per subtract-first/laziness. Note it as a possible future hardening if the harness/production teardown divergence causes further flakes.

Rationale against "Option B alone": a routing fix is correctness-correct but timing-fragile — if the real escape ever comes from a different path, the leak returns. Rationale against "Option A alone": it leaves a real invalid transition (and its production warning) live. A is the safety net; B removes the cause. Both are cheap; ship both.

### Suggested next steps
1. **Capture the 3.11 traceback** (Open Question 1) — this is the gate. Confirm the source resource and `handle_failed` site before writing the B guard.
2. **Implement Option A**: wrap `stop()`'s body in `try`, move loop-restore + `HASSETTE_INSTANCE.reset(token)` into `finally` (harness.py:644-650). Keep the `ExceptionGroup` raise after the finally.
3. **Implement scoped Option B**: in `handle_failed` (mixins.py:278) or the serve-wrapper terminal handler (service.py:181-184), short-circuit to `handle_stop()`/no-op when the resource is already terminal and `shutdown_event.is_set()`. Match the existing `ClosedResourceError`-during-shutdown precedent.
4. **Add the regression test** (see below).
5. **Verify**: run the affected unit test file on 3.11 specifically (`uv run nox -s "tests-3.11"` or `uv run pytest tests/unit/test_framework_injection_points.py` under 3.11). Run `nox -s system` and `nox -s e2e` for the core (Option B) change per CLAUDE.md — noting these run on 3.13/3.14, so they verify Option B does not regress production teardown, not the 3.11 path. Do **not** run `pytest -n auto` locally.
6. Suggest running `/mine-challenge` on the chosen fix before committing, given it touches core failure routing.

## Regression Test Design

**Goal**: pin the invariant "harness teardown raises during shutdown ⇒ the global singleton is still reset, so a subsequent harness can construct cleanly." This must capture Option A's guarantee independent of the 3.11 timing quirk (which is not reliably reproducible on 3.12+).

**Location**: `tests/unit/test_framework_injection_points.py`, new class `TestHarnessTeardownClearsSingletonOnError`. This file already owns the `set_global_hassette` token contract and the `clean_hassette_context` fixture, and runs on all Python versions including 3.11 (`tests`/`coverage` nox sessions).

**Design** (uses the repo's documented error-isolation pattern, CLAUDE.md "Error isolation" + tests/TESTING.md):

1. Build a `HassetteHarness` with at least `with_bus()` (so a real token is set; `skip_global_set=False`).
2. `await harness.start()`.
3. **Inject a teardown failure** that escapes the collected-error net into an *unguarded* statement before the singleton reset. Two approaches, prefer the first:
   - **Direct (timing-independent, recommended)**: patch one of the unguarded teardown steps (e.g., `self.hassette._loop.set_task_factory`, harness.py:645) to raise, OR monkeypatch `shutdown_resource` to raise *outside* the per-child `try/except` is not possible (it's inside the loop) — so instead patch the loop-restore call to raise. This directly exercises "an exception escapes before line 650."
   - **Mechanism-faithful (optional, may only fail pre-fix on 3.11)**: drive a child to `STOPPED` then submit to the closed sync executor to provoke the real `STOPPED→FAILED` `InvalidLifecycleTransitionError`. Mark this `xfail`/skip on 3.12+ if it does not reproduce there.
4. `with pytest.raises(ExceptionGroup)` (or the specific error) around `await harness.stop()` — assert teardown *did* raise.
5. **Assert the singleton was still cleared**: `assert context.HASSETTE_INSTANCE.get(None) is None` — this is the core regression assertion. Pre-fix (without `finally`) this fails because the reset was skipped; post-fix it passes.
6. (Optional, stronger) Construct a *second* harness and assert `set_global_hassette` does **not** raise "already set" — proving the cascade is broken end-to-end.

For Option B specifically, add a focused unit test in `tests/unit/resources/test_lifecycle_transitions.py` (which already tests strict-mode transitions): assert that calling `handle_failed` on a resource already in `STOPPED` with `shutdown_event` set does **not** raise under `strict_lifecycle=True` and does **not** move the status to FAILED (post-fix), using `make_mock_hassette(strict_lifecycle=True, sealed=False)` per the existing pattern at test_lifecycle_transitions.py:73.

**Commit sequencing** (git-workflow.md bug-fix rule): land the failing regression test first (RED), then the fix (GREEN).

## Sources

- [Python 3.12 What's New — asyncio / eager tasks](https://docs.python.org/3.12/whatsnew/3.12.html)
- [Python 3.11 and 3.12 differ on asyncio (and may break your code)](https://medium.com/h7w/python-3-11-and-3-12-differ-on-asyncio-and-may-break-your-code-ce4d3007f08c)
- [cpython#107505 — run_in_executor not stopping thread after task cancellation in asyncio (Python 3.11)](https://github.com/python/cpython/issues/107505)
- [asyncio — Developing with asyncio (exception handler context)](https://docs.python.org/3/library/asyncio-dev.html)
