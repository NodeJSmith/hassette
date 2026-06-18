# Design: Mock at boundaries in core service tests (issue #1036)

**Date:** 2026-06-17
**Status:** approved
**Scope-mode:** hold
**Research:** design/research/2026-06-17-mock-at-boundaries-audit/research.md

## Problem

Several core tests patch Hassette's own internal methods instead of mocking only true system boundaries (the HA API, the aiohttp websocket, time, the DB). When a test overwrites the very method whose behavior it claims to verify — e.g. a reconnect-cache test that patches `StateProxy.load_cache`, or a cleanup test that patches `WebsocketService.partial_cleanup` — it stops exercising that logic, so the test passes whether or not the logic is correct. This gives false regression confidence in exactly the subsystems (websocket reconnection, state cache, app lifecycle) where "it seemed to work" is least trustworthy.

The precise anti-pattern is narrower than "any patch on a real object." Stubbing a *collaborator* of the method under test is legitimate and often correct (it is how you isolate a unit). The violation is **patching the method (or the path) the test is asserting about** — the "method under test" (MUT). Issue #1036 named five spots; the pre-work audit (see Research) found similar patches across 7 files. The adversarial review then showed that a meaningful fraction of those are collaborator stubs in `serve()`-loop tests, not MUT patches — so the real conversion set is smaller than the raw count, and part of the work is *annotating* deliberate collaborator stubs rather than rewriting them.

## Goals

- Each in-scope test mocks only (a) true external boundaries (aiohttp `ClientSession`/`ws_connect`, the HA REST API via `RecordingApi`/harness mock server, time) and (b) the direct collaborators of its method-under-test — and never patches the MUT itself.
- A regression in the real logic a test claims to cover now causes that test to fail, where today (when the MUT is patched away) it would not.
- The full existing test suite stays green throughout (the suite is the behavioral pin).
- The lesson is enforced structurally by a CI guard, not only by prose — re-introducing a MUT patch in these files fails the build.
- The five spots named in #1036 are all resolved, including the `test_history.py:78` vacuous assertion.

## Non-Goals

These are deliberately deferred and routed elsewhere — out of scope for this refactor:

- **Cluster D — `bus_service.add_listener` helper (~30 sites).** The `mock_add_listener` conftest helper patches a real internal method. Exclusion here is a **pragmatic ROI call, not a principled one**: the patched method sits above the DB boundary and the helper is documented and restored, but the same "near a boundary / deliberate" description also applies to patches we *are* converting. We exclude it only because unwinding it touches a 70+-test conftest for low correctness gain. Say so plainly so the next auditor does not re-open the debate expecting a principled distinction. Capture a follow-up note.
- **Scheduler `__new__` doubles (~15 sites in `test_scheduler_service_reschedule.py`).** Patch `run_job_with_guard` on a hand-built scaffold whose `task_bucket` is already mocked. **File a separate tracking issue** to review and potentially migrate these — not part of this PR.
- **`get_states_raw` monkeypatching (~5 sites).** Not a violation — `get_states_raw` (`src/hassette/api/api.py:367`) is the HA REST boundary, and #1036 names it as the injection point. Leave as-is; do not migrate to `RecordingApi` for consistency.
- **Cluster E/F remainder** — `test_scheduler_mode.py` (`warn_stalled_job`), `test_service_watcher.py` (`shutdown_safe_sleep`), `test_duration_hold.py` (`_timer`), `test_bus_contract.py` (`register_listener`), `test_database_service.py` (`logger`, `get_db_size_mb`). Capture in the same follow-up note as Cluster D. The one exception folded into scope is `test_history.py:78` (a named #1036 spot).
- **No production-code behavior changes.** Test-only refactor. Allowed non-test edits: moving/extending test helpers under `src/hassette/test_utils/`, and adding the CI guard script. Never a change to `src/hassette/` runtime behavior.

## User Scenarios

### Maintainer: a contributor changing core service code
- **Goal:** know whether a change to websocket/state/lifecycle logic broke something.
- **Context:** edits `src/hassette/core/websocket_service.py` (or state proxy / lifecycle) and runs the test suite before pushing.

#### A real regression is caught
1. **Contributor breaks `partial_cleanup` or the recv-task wiring inside `connect_ws`.**
   - Sees: the WebsocketService tests fail, because they run the real method against a fake aiohttp websocket instead of a mock that returns canned values.
   - Decides: fix the regression before pushing.
   - Then: with the old MUT patches, those tests would have stayed green and the regression would have reached main.

### Maintainer: a contributor who accidentally re-introduces the anti-pattern
- **Goal:** not silently regress the suite back to MUT-patching.
- **Context:** adds a new test and reaches for `service.make_connection = AsyncMock()` out of habit.

#### The CI guard catches it
1. **Contributor pushes a test that patches a prohibited MUT symbol in an in-scope file.**
   - Sees: the `check_internal_patches.py` CI step fails with the file:line and the prohibited symbol.
   - Then: they either drive the MUT through its boundary, or add the required `# boundary-exempt:` annotation if it is a legitimate collaborator stub.

## Functional Requirements

- **FR#1** Each in-scope test mocks only true external boundaries (aiohttp `ws_connect`, HA REST via `RecordingApi`/mock server, time) and the direct collaborators of its method-under-test. No test reassigns or `patch.object`-patches the method (or path) whose behavior it asserts — the MUT runs for real.
- **FR#2** WebsocketService tests whose MUT is a connection-level method (`connect_ws`, `dispatch`, `respond_if_necessary`, `partial_cleanup`, `authenticate`) run that real method against a fake aiohttp websocket (`ws_connect` returns `build_fake_ws()`), stubbing only its collaborators — and assert readiness/connection-established outcomes via emitted bus events rather than by patching `_emit_readiness_event` / `mark_ready` on the service.
- **FR#3** WebsocketService tests whose MUT is the `serve()` reconnect loop or `start_recv_and_subscribe()` keep their collaborator stubs (`make_connection`, `subscribe_events`, `send_connection_established_event`, `task_bucket.spawn`, and dual-role `partial_cleanup`/`mark_ready`/`_emit_readiness_event` when stubbed here as collaborators) — these are NOT MUT patches and are NOT converted to the `fake_ws` path. Each such stub carries the `# boundary-exempt: collaborator of <MUT>` annotation, and the test observes its outcome through the bus where it asserts side effects. Driving these through a fake-ws recv sequence is explicitly rejected (see Architecture / Edge Cases).
- **FR#4** StateProxy tests drive cache load and reconnect through the public surface (`on_reconnect()`, `is_ready()`) with the HA boundary supplied via `RecordingApi`/mock server, and assert readiness transitions via emitted bus events — `load_cache`, `subscribe_to_events`, and `_emit_readiness_event` are not patched as the path under test. Assertions that today verify call-count/idempotency semantics on `mark_not_ready` (the `if not is_ready(): return` guard) are preserved by counting emitted not-ready events, not weakened to a bare `is_ready()` presence check.
- **FR#5** AppLifecycleService/AppHandler tests mock the collaborators (`AppFactory`, `AppRegistry`, `AppChangeDetector`, or the app-dir/config boundary) and drive through the public entry points (`apply_changes()`, `handle_change_event()`) — `start_app`, `stop_app`, `reload_app`, `resolve_only_app`, `handle_crash`, `detect_changes`, and `refresh_config` are not patched when they are the MUT.
- **FR#6** `test_history.py:78` uses `side_effect=lambda x: x` (not `return_value = lambda x: x`) for the `normalize_history` stub, so the patched call returns the data unchanged rather than a lambda object. Single one-line swap inside the existing `patch(...)` block; the test's structure (only the minimal-flag call is patched; the non-minimal call runs real code outside the patch) is unchanged. Today's `return_value` form makes the inequality assertion pass vacuously.
- **FR#7** A CI guard (`tools/check_internal_patches.py`) scans the in-scope files for reassignment/`patch.object` of the prohibited symbols (the canonical list is enumerated in Architecture → "Guard scope and the dual-role principle") and fails unless the line carries a `# boundary-exempt: collaborator of <MUT>` annotation. The annotation is the per-site human classification the guard cannot make structurally. Wired into `.github/workflows/lint.yml` alongside the existing `tools/frontend/check_*.py` guards.
- **FR#8** Every test changed by FR#1–FR#6 asserts on an observable outcome (returned value, emitted event, recorded API call, or public state) — no test is left configuring a mock that is never asserted on.

## Edge Cases

- **`serve()` / `start_recv_and_subscribe()` would hang if driven through a fake ws.** `subscribe_events` registers a Future resolved only by a real recv frame (`respond_if_necessary` → `dispatch` → `raw_recv` → `ws.receive`), and `task_bucket.spawn` must yield a real schedulable task. A fake ws with `receive = AsyncMock()` and no scripted frames hangs on the subscribe timeout. This is exactly why these tests stub `make_connection`/`subscribe_events`/`task_bucket` as collaborators (FR#3) — keep that, do not try to feed a scripted recv sequence.
- **Auth handshake.** Do NOT enrich `build_fake_ws()` to script the `auth_required`→`auth_ok` exchange — that would make the fake a second implementation of HA's WS protocol, so a protocol change forces synchronized edits to both `websocket_service.py` and the fake (change amplification). Instead, in serve()/connect-driven tests where `authenticate` is a collaborator (not the MUT), stub `authenticate` — exactly as the existing `test_connect_ws_sets_ws_and_authenticates` already does. `build_fake_ws()` stays a thin aiohttp stub with no protocol knowledge. The only test where the real `authenticate` runs is one whose MUT *is* `authenticate`, which scripts just the frames that one method consumes.
- **Early-drop retry tests are `serve()`-loop tests (FR#3), not MUT patches.** They count `make_connection` calls to verify the outer `while True:` loop (`websocket_service.py:240`) that retries after a post-connection recv-task failure — distinct from `make_connection`'s inner `@retry` on `ws_connect` failure (~380–395). `make_connection` here is a collaborator of `serve()`; stubbing it is correct. Annotate and keep; do not attempt recv-failure-via-fake_ws.
- **Concurrency-gated reconnect.** StateProxy tests (around lines 604–636) gate `load_cache`/`subscribe_to_events` to assert ordering. Re-express by gating the `RecordingApi`/boundary response with an `asyncio.Event` and asserting observable ordering (startup-race pattern in CLAUDE.md). Watch the scheduling: a single `await asyncio.sleep(0)` may not be enough to let the gated task reach its await point — assert `not task.done()` after the yield to confirm the gate actually blocks before setting it.
- **`mark_not_ready` idempotency-guard sites.** `mark_not_ready` is public; some patches are call-verification spies confirming the `if not is_ready(): return` guard fired. An `is_ready()` check cannot distinguish "called once, guarded" from "called twice, unguarded." Preserve the semantics by asserting the count of emitted not-ready `service_status` events, not by dropping to a presence check.
- **A test that genuinely cannot be redriven through a boundary.** If a behavior is only reachable by patching the MUT, that signals a missing seam. Prefer a narrow injection seam in the test helper; if infeasible, keep the patch with a `# boundary-exempt:` annotation and flag it in the PR rather than forcing a worse test.

## Acceptance Criteria

- **AC#1** No in-scope test reassigns or `patch.object`-patches its method-under-test among the prohibited symbols (FR#2/FR#4/FR#5). Verified by `tools/check_internal_patches.py` passing. Permitted and `# boundary-exempt:`-annotated: serve()/`start_recv_and_subscribe` collaborator stubs (FR#3) and `authenticate` collaborator stubs.
- **AC#2** `test_history.py:78` uses `side_effect=lambda x: x` (no `return_value = lambda` remains for `normalize_history`); patch-block structure unchanged. Verified by reading the test and confirming the inequality assertion now exercises real un-normalized data.
- **AC#3** The full unit + integration suite passes: `uv run pytest tests/unit tests/integration` is green.
- **AC#4** The system and e2e suites are green **on the PR branch before merge** (hard gate, not a general-CI assumption): the `system` and `e2e` CI jobs must report success on this PR. Local runs are optional (heavy suites may be unsafe locally per project memory), but a green CI run on the branch is required — these exercise the real aiohttp/HA boundaries the unit tests mock.
- **AC#5** Sanity spot-check (not a coverage proof): breaking one representative method per cluster (`partial_cleanup`, `StateProxy.load_cache`, `stop_app`) causes at least one in-scope test to fail. This demonstrates the converted tests run the real method; it does not prove exhaustive coverage.
- **AC#6** `tools/check_internal_patches.py` exists and is wired into `.github/workflows/lint.yml`; running it locally passes.
- **AC#7** A follow-up issue exists for the scheduler `__new__` doubles, and a follow-up note records the deferred Cluster D / E / F items.

## Key Constraints

- **Do not change production behavior.** If a test cannot be redriven without a source change, that is a PR-review discussion, not a silent `src/` edit.
- **Keep the pin green at every step.** Each file's tests pass after that file is converted, before moving on. Do not leave multiple files broken at once.
- **Do not "fix" by deleting coverage** or by weakening an assertion (e.g. call-count → presence) to make a boundary version pass.
- **`build_fake_ws()` stays a thin aiohttp stub.** No HA protocol knowledge in the fake — stub `authenticate`/`subscribe_events` as collaborators instead.
- **`get_states_raw` is the boundary, not a target.** Do not flag or migrate it.
- **The MUT is never patched.** Mock external boundaries and the MUT's collaborators only (invariants.md: Mock at Boundaries Only).

## Dependencies and Assumptions

- Existing test infrastructure suffices: `HassetteHarness`, `RecordingApi` (`src/hassette/test_utils/recording_api.py`), the harness mock API server, and the existing `build_fake_ws()` / `fake_session` pattern. No new framework — only relocation and reuse.
- `build_fake_ws()` is moved to `src/hassette/test_utils/` (it currently lives in `tests/integration/test_websocket_service.py`, but the unit tests in `tests/unit/core/` also need it). This move is **step 0** of the websocket work, landed before any file conversion, so no file sits broken waiting on a cross-file helper. The helper is NOT enriched with protocol/handshake scripting (see Edge Cases).
- CI runs the `system` and `e2e` jobs on PRs (required for AC#4). Confirmed by `.github/workflows/` — if a job is not auto-triggered on PRs, AC#4 includes wiring it or triggering it manually on the branch.

## Architecture

The refactor distinguishes, per test, the **method under test (MUT)** from its **collaborators**. Mock external boundaries and collaborators; never the MUT. The boundary-mock pattern already exists in `test_websocket_service.py` (`test_connect_ws_sets_ws_and_authenticates`: a `fake_session.ws_connect` returning `build_fake_ws()`, real `connect_ws` running, `authenticate` stubbed as a collaborator). The work extends that idiom to MUT-patch tests and annotates the legitimate collaborator stubs.

**Cluster A — WebsocketService**, three files, split by MUT:

- *A1 — connection-method MUTs* (`connect_ws`, `dispatch`, `respond_if_necessary`, `partial_cleanup`, `authenticate`). The seam is `aiohttp.ClientSession`/`ws_connect` (`make_connection` → `connect_ws` → `session.ws_connect`, `websocket_service.py:303`). Run the real MUT against `build_fake_ws()`; stub its collaborators (e.g. `authenticate` when testing `connect_ws`); assert readiness via bus events, not by patching emit methods. These are the genuine conversions.
- *A2 — orchestration MUTs* (`serve()` reconnect/early-drop loop, `start_recv_and_subscribe()`). Here `make_connection`, `subscribe_events`, `send_connection_established_event`, and `task_bucket.spawn` are collaborators. Stubbing them is correct and required (driving them through a real fake-ws recv sequence hangs — Edge Cases). The work is to **annotate** each stub `# boundary-exempt: collaborator of <MUT>` and ensure side-effect assertions go through the bus. The rule, stated once: *if `serve()`/`start_recv_and_subscribe` is the method under test, `make_connection`/`subscribe_events`/etc. are its collaborators and may be stubbed.* This reclassifies the early-drop and reconnect tests as already-correct-with-annotation, which is why the real conversion set is smaller than the raw site count.

**Cluster B — StateProxy** (`test_state_proxy.py`). The boundary is the HA REST API via `RecordingApi`/mock server (and the `get_states_raw` seam, left as-is). Where the path under test is reconnect/cache behavior, drive `on_reconnect()` and assert via `is_ready()` + bus events instead of patching `load_cache`/`subscribe_to_events`. Categorize the `mark_not_ready` sites: pure spies asserting only "called" → assert the resulting readiness transition; idempotency-guard spies asserting call-count → assert the count of emitted not-ready events (FR#4); concurrency-gating sites → gate the boundary response with an `asyncio.Event` (Edge Cases).

**Cluster C — AppLifecycleService/AppHandler** (`test_app_lifecycle_service.py`, `test_app_lifecycle_service_operations.py`, `test_apps.py`). Collaborators are `AppFactory`, `AppRegistry`, `AppChangeDetector`, and the app-dir/config boundary. Mock those and drive through `apply_changes()`/`handle_change_event()` instead of patching the lifecycle methods when they are the MUT.

**Guard scope and the dual-role principle.** Classification is **per-test, by MUT** — and several symbols are dual-role: a MUT in a dedicated test, a collaborator in a `serve()`/`start_recv_and_subscribe` test. `partial_cleanup` is the MUT in `test_partial_cleanup_*` (convert to fake-ws) but a collaborator in early-drop/reconnect tests (annotate). `mark_ready` and `_emit_readiness_event` are short-circuited (patched so the real method does not run) in some A1 tests (convert to bus-event assertions) but are call-count collaborator stubs in `start_recv_and_subscribe` isolation tests (annotate). The guard cannot tell these apart structurally, so it flags **every** reassignment/`patch.object` of a prohibited symbol on a real service/proxy/lifecycle object and requires a `# boundary-exempt: collaborator of <MUT>` annotation to pass — the annotation is the human's per-site classification.

The prohibited-symbol set the guard matches (the canonical input for `tools/check_internal_patches.py`):

```
WebsocketService: make_connection, connect_ws, dispatch, respond_if_necessary,
                  partial_cleanup, authenticate, mark_ready,
                  _emit_readiness_event, subscribe_events,
                  send_connection_established_event
StateProxy:       load_cache, subscribe_to_events, mark_not_ready,
                  _emit_readiness_event
Lifecycle:        start_app, stop_app, reload_app, resolve_only_app,
                  handle_crash, detect_changes, refresh_config
```

`task_bucket.spawn` is deliberately **excluded** from this set — it is a method on a different object (the task bucket), not on the service/proxy/lifecycle under guard, so the guard does not match it even though A2 tests stub it as a collaborator.

"Short-circuit readiness" means patching `mark_ready`/`_emit_readiness_event` so the real method does not run (letting the test reach a "ready" state without the real machinery) — distinct from a call-count spy on a method that still runs. The former converts to a bus-event assertion; the latter, in an isolation test, annotates.

**Sequencing.**
0. Move `build_fake_ws()` from `tests/integration/test_websocket_service.py` to `src/hassette/test_utils/`; update the definition site to re-import from there (it is the only current user). Subsequent steps add imports in the unit-test files as they are converted. Suite stays green.
1. `test_history.py:78` one-line fix (lands the #1036 named spot early).
2. Cluster A — annotate A2 collaborator stubs, convert A1 MUT patches. Three files.
3. Cluster B (StateProxy).
4. Cluster C (lifecycle).
5. **Capstone:** add `tools/check_internal_patches.py` + wire into the lint workflow, and document the convention in `tests/TESTING.md`. The guard lands **last**, not mid-conversion: a guard introduced before the clusters are converted would fail CI on every not-yet-converted MUT patch. By the capstone, all in-scope files are converted or annotated, so the guard passes on a clean tree. The `# boundary-exempt:` annotations are written during steps 2–4 as each collaborator stub is classified; the guard simply codifies them at the end.
Keep the suite green after each file.

## Replacement Targets

Replaced, not preserved alongside new code:

- **(A1)** MUT patches on `WebsocketService` — `connect_ws`/`dispatch`/`respond_if_necessary` (always MUTs in their tests), `partial_cleanup` **when it is the MUT** (dedicated `test_partial_cleanup_*` tests), `authenticate` when it is the MUT, plus `mark_ready`/`_emit_readiness_event` **when used to short-circuit readiness** (patched so the real method does not run) — → `fake_session`/`fake_ws` boundary mocks + bus-event observation.
- **(A2, NOT replaced — annotated instead)** In `serve()`/`start_recv_and_subscribe` tests (e.g. `test_early_drop_*`, `test_service_status_stays_running_during_early_drop`, `test_mark_ready_after_connect_emits_event`, `test_start_recv_and_subscribe_marks_ready`), the MUT is the orchestration method and these are its collaborators: `make_connection`, `partial_cleanup`, `subscribe_events`, `send_connection_established_event`, `task_bucket.spawn`, and call-count stubs of `mark_ready`/`_emit_readiness_event`. Keep them; add `# boundary-exempt: collaborator of <MUT>` annotations; route side-effect assertions through the bus where a test asserts them. The same symbol (`partial_cleanup`, `mark_ready`, `_emit_readiness_event`) is therefore A1-convert in one test and A2-annotate in another — classify per-test by MUT, per the dual-role principle in Architecture.
- **(B)** MUT patches on `StateProxy` — `load_cache`, `subscribe_to_events`, `_emit_readiness_event`, and logic-skipping `mark_not_ready` patches — → `RecordingApi`/boundary-gated drives through `on_reconnect()`/`is_ready()` + bus events. Spy-style `mark_not_ready` call-count assertions → emitted not-ready event counts (not a bare presence check).
- **(C)** MUT patches on lifecycle objects (`start_app`/`stop_app`/`reload_app`/`resolve_only_app`/`handle_crash`/`detect_changes`/`refresh_config`) → collaborator mocks + `apply_changes()`/`handle_change_event()` drives.
- **(history)** `test_history.py:78` `return_value = lambda x: x` → `side_effect=lambda x: x` (one-line, structure unchanged).

No production code is replaced.

## Convention Examples

### Boundary-mock pattern for connection-method MUTs (A1 — the model to copy)

**Target form for** `tests/integration/test_websocket_service.py` (`test_connect_ws_sets_ws_and_authenticates`) — the current test has the same shape but the `authenticate` stub is not yet annotated; the annotation is part of this work:

```python
async def test_connect_ws_sets_ws_and_authenticates(websocket_service: WebsocketService) -> None:
    """connect_ws sets self._ws and calls authenticate."""
    fake_ws = build_fake_ws()
    fake_session = MagicMock()
    fake_session.ws_connect = AsyncMock(return_value=fake_ws)

    websocket_service.authenticate = AsyncMock()  # boundary-exempt: collaborator of connect_ws

    await websocket_service.connect_ws(fake_session)   # REAL connect_ws (the MUT) runs

    assert websocket_service._ws is fake_ws
    websocket_service.authenticate.assert_awaited_once()
```

DO mock `fake_session.ws_connect` (the aiohttp boundary) and run the real MUT. DON'T patch `connect_ws` itself when it is the MUT.

### Legitimate collaborator stub in an orchestration-MUT test (A2 — keep + annotate, do NOT convert)

**Source:** `tests/integration/test_websocket_service.py` — `test_early_drop_retries_and_succeeds` (~lines 558–618)

```python
# serve() is the MUT; make_connection is its collaborator.
async def fake_make_connection(_session):
    ...
websocket_service.make_connection = fake_make_connection  # boundary-exempt: collaborator of serve()
```

This is correct, not the anti-pattern. The test verifies `serve()`'s outer retry loop by counting `make_connection` calls. Do NOT try to drive it via a fake-ws recv sequence (it would hang on the subscribe Future / task spawn — Edge Cases). Add the annotation; the CI guard then accepts it.

### Startup-race / gating pattern for StateProxy ordering assertions

**Source:** CLAUDE.md "Regression test patterns for this project"

```python
gate = asyncio.Event()
mock_boundary.side_effect = lambda *_: gate.wait()   # gate the HA boundary, not load_cache
task = asyncio.create_task(state_proxy.on_reconnect())
await asyncio.sleep(0)
assert not task.done()          # confirm the gate actually blocks before setting it
gate.set()
await task
```

## Alternatives Considered

- **Fix only the 5 cited lines (do-minimum).** Rejected: leaves sibling violations in the same files, re-opening the issue.
- **Blanket "never patch a real object's method" rule.** Rejected: it misclassifies legitimate collaborator stubs in `serve()`/`start_recv_and_subscribe` tests as violations, sends implementers down a hang-prone fake-ws-recv path, and would weaken those tests. The MUT-vs-collaborator distinction is the correct framing.
- **Enrich `build_fake_ws()` to script the HA handshake/recv protocol.** Rejected: makes the fake a second protocol implementation (change amplification at the protocol boundary). Stub `authenticate`/`subscribe_events` as collaborators instead.
- **Include everything (Clusters D/E/F).** Rejected for scope: D is a pragmatic exclusion, the scheduler doubles are a gray-zone scaffold; routed to follow-ups.
- **Prose-only guidance in TESTING.md, no CI guard.** Rejected: prose regresses silently. The repo already enforces analogous conventions via `tools/frontend/check_*.py`; a parallel guard is ~50 lines (encode-lessons-in-structure.md).

## Test Strategy

### Existing Tests to Adapt
The seven in-scope files are the artifact:
- `tests/integration/test_websocket_service.py` — A1 conversions + A2 annotations.
- `tests/unit/core/test_ws_connection_state.py` — `make_connection`/`partial_cleanup` sites (classify A1 vs A2 per MUT).
- `tests/unit/core/test_websocket_readiness_events.py` — connection/emit/subscribe + `task_bucket` (mostly A2 isolation tests — annotate; convert only true MUT patches).
- `tests/integration/test_state_proxy.py` — `load_cache`/`subscribe_to_events`/`_emit_readiness_event`/`mark_not_ready` (categorize per Cluster B); leave `get_states_raw`.
- `tests/unit/core/test_app_lifecycle_service.py`, `tests/unit/core/test_app_lifecycle_service_operations.py`, `tests/integration/test_apps.py` — lifecycle MUT patches.
- `tests/integration/test_history.py` — line 78 one-line swap.

### New Test Coverage
No net-new behaviors. The refactor adds *coverage strength* (real methods now run). Strength is sanity-checked by AC#5 (spot-check, not proof). New non-test code: `tools/check_internal_patches.py` (the CI guard) and the relocated `build_fake_ws()` helper.

### Tests to Remove
None. Every converted test keeps its intent; assertions are re-expressed or annotated, not deleted.

## Documentation Updates

- `tests/TESTING.md` — add a subsection: the MUT-vs-collaborator rule, the `fake_session`/`build_fake_ws` boundary pattern, the `# boundary-exempt: collaborator of <MUT>` annotation convention, and a pointer to `tools/check_internal_patches.py`.
- `tools/check_internal_patches.py` — self-documenting `--help` / module docstring describing the prohibited symbols and the exemption annotation (mirrors the existing `tools/frontend/check_*.py` scripts).
- No user-facing docs-site/README/CLI changes — internal test infrastructure (`chore:` per changelog-quality.md).

## Impact

### Changed Files
- create `tools/check_internal_patches.py` — CI guard: fail on un-annotated MUT patches in the in-scope files.
- modify `.github/workflows/lint.yml` — wire in the new guard.
- modify `src/hassette/test_utils/` (new or existing helper module) — relocate `build_fake_ws()` here (step 0).
- modify `tests/integration/test_websocket_service.py` — A1 conversions + A2 annotations; remove the local `build_fake_ws` definition / re-import from test_utils.
- modify `tests/unit/core/test_ws_connection_state.py` — classify + convert/annotate.
- modify `tests/unit/core/test_websocket_readiness_events.py` — classify + convert/annotate.
- modify `tests/integration/test_state_proxy.py` — convert StateProxy MUT patches; retain `get_states_raw`.
- modify `tests/unit/core/test_app_lifecycle_service.py`, `tests/unit/core/test_app_lifecycle_service_operations.py`, `tests/integration/test_apps.py` — lifecycle conversions.
- modify `tests/integration/test_history.py` — `return_value`→`side_effect` at line 78.
- modify `tests/TESTING.md` — document the rule + annotation convention.

### Behavioral Invariants
- Production behavior in `src/hassette/` must not change — verified by the system + e2e suites (AC#4) and a zero `src/` runtime diff (the only `src/` edit is the additive `test_utils` helper relocation).
- All currently-passing tests remain passing (AC#3); the suite is the pin.
- `get_states_raw` boundary mocking continues unchanged.

### Blast Radius
- Test-only at runtime; risk confined to test correctness and the CI guard's accuracy (a too-strict guard could block legitimate stubs — hence the `# boundary-exempt:` escape annotation).
- The relocated `build_fake_ws()` is shared across Cluster A; change it additively in step 0 and re-run all three websocket files.
- The system/e2e CI jobs are the real-boundary safety net for the WebsocketService/StateProxy changes and gate merge (AC#4).

## Open Questions

None blocking. (Per-site A1-vs-A2 classification and the "add a seam vs. annotate the stub" call are delegated to PR review; the CI guard makes any missed MUT patch visible rather than silent.)

## Follow-Up / Deferred Work

These items were identified during orchestration of #1036 and are recorded here as a durable committed note. GitHub follow-up issues filed: #1072 (scheduler doubles), #1073 (deflake).

### Scheduler `__new__` doubles (test_scheduler_service_reschedule.py)

`tests/unit/core/test_scheduler_service_reschedule.py` uses `__new__`-bypassing doubles for `Scheduler` construction in several tests. This pattern pre-dates the mock-at-boundaries work and was not in scope for #1036 (the file does not appear in the seven in-scope files). A follow-up migration review is warranted to apply the same boundary discipline.

Filed as #1072. Labels: `type:enhancement`, `area:testing`, `area:scheduler`, `size:small`.

### Cluster D — `bus_service.add_listener` / `mock_add_listener` conftest helper (~30 sites)

The `mock_add_listener` conftest helper and direct `bus_service.add_listener` stubs across the bus test suite were assessed and deferred. The ROI is lower than Clusters A–C (the bus method is closer to a boundary than a MUT in most of these tests) and the refactor volume (~30 sites) does not justify the risk at this time. Deferred with pragmatic ROI exclusion.

### Cluster E/F remainder

The following files contain stubs or patches that were out of scope for #1036 or assessed as lower-priority:

- `tests/unit/core/test_scheduler_mode.py` — `warn_stalled_job` stub
- `tests/unit/core/test_service_watcher.py` — `shutdown_safe_sleep` stub
- `tests/unit/test_duration_hold.py` — `_timer` stub
- `tests/unit/bus/test_bus_contract.py` — `register_listener` stub
- `tests/unit/core/test_database_service.py` — `logger` and `get_db_size_mb` stubs

Each of these may benefit from the same boundary treatment in a future pass. No blocking issues identified.

### Pre-existing flaky test (unrelated to #1036)

`tests/integration/test_lifecycle_propagation.py::TestCloseStreamsAfterChildrenStopped::test_children_stopped_before_on_children_stopped_hook` fails occasionally under `-n` parallel load but passes in isolation. This is unrelated to the mock-at-boundaries work.

Filed as #1073. Labels: `type:bug`, `area:testing`, `topic:concurrency`, `size:small`.
