# Design Audit: Bus, Scheduler, Execution, Web, API, State, App Lifecycle, Telemetry

**Date:** 2026-06-19
**Scope (8 areas):** `bus/`, `scheduler/`, the execution layer (`core/command_executor.py`, `task_bucket/`, `core/sync_executor_service.py`, `resources/`), `web/` (Part 1); `api/`, `state_manager/`+`core/state_proxy.py`, the app-lifecycle services (`core/app_*.py`, `app/`), and `telemetry` (`core/telemetry*`, `core/telemetry/`, `core/session_manager.py`, `core/runtime_query_service.py`) (Part 2).
**Method:** Three independent advisory reviewers per area (structural-simplification, over-engineering/training-bias, integration/coupling), run area-by-area so later areas could cross-validate earlier findings. Six high-stakes claims were then verified directly against source, and the whole doc was put through a fine-toothed-comb accuracy pass and a 3-critic adversarial challenge (see Review gates at the end). Findings revised in response are marked inline.

## Overall read

The subsystems are **well-built, not rotten**. The reviewers consistently praised load-bearing design: the trigger protocol, `ExecutionModeGuard` as a pure state machine, codegen-generated `sync.py` shims, the `RetryableBatch` write-queue distinction, `DB_ERRORS` centralization, and typed FastAPI dependency aliases. Almost none of the findings are correctness bugs.

The findings are mostly **boundary gaps the build never ratcheted shut**, not random entropy. One framing correction from the challenge: when the *same* smell (private-attr reach-through, twin-drift, constants-synced-by-test, hand-copy) recurs across all 8 subsystems independently, the root cause is "nothing in the build stops it," not "the code aged." A list of point-fixes against a recurring pattern re-accretes the moment it lands. Crucially, **the repo already ships the enforcement mechanism**: `tools/check_module_boundaries.py` is an AST lint whose docstring states the intent verbatim ("Nothing in the type checker or test suite stops a lower layer from importing a higher one… This guard fails such imports") and explicitly notes the `core↔bus` cycle "must be refactored before those rules can pass (tracked in #1079)." So the most durable single recommendation is **extend that ratchet** — add a rule forbidding `hassette._*` access outside `core/`, and re-enable the `core↔bus` rule after the cycle break — which fences every T2/N1 point-fix from re-accreting. Beyond the boundary gaps, the remaining findings are genuine accretion: dead code from past migrations, defensive guards inside the trust perimeter, and hand-written translation where a library feature would do.

## Verified claims (checked against source, not taken on a reviewer's word)

1. **`bus → core → bus` runtime import cycle — CONFIRMED REAL.** `core/commands.py:7` imports `Listener` at runtime (its `TYPE_CHECKING` block holds only error-handler types); `bus/invocation.py:10` imports `InvokeHandler` at runtime. One reviewer claimed this was `TYPE_CHECKING`-guarded — that was wrong. The cycle resolves today only because neither module uses the other's names at import time; one module-level expression away from `ImportError`.
2. **`config_log_all_events` hot-reload bug — CONFIRMED REAL.** `bus_service.py:134` is `@cached_property` reading `config.logging.all_events`; its sibling `config_log_level` (`:130`) is a live `@property`. Once first read during dispatch, the all-events flag freezes and ignores config hot-reload.

## Cross-cutting themes (ranked — these are the real findings)

### T1. Bus and scheduler are drifted twins with fully duplicated dispatch machinery — HIGH
The non-parallel dispatch pipeline exists as two independent implementations:

| Bus (`bus/listeners.py`, `HandlerInvoker`) | Scheduler (`core/scheduler_service.py` + `scheduler/classes.py`) |
|---|---|
| `pending_done: set[Future]` (203) | `ScheduledJob.pending_done` (classes.py:245) |
| `run_with_mode()` (297) | `run_job_with_guard()` (384) |
| `invocation_with_stall_watch()` (339) | `invocation_with_stall_watch()` (433) |
| `release_guard()` drains pending (361) | `drain_pending_done()` (595) |
| `STALL_THRESHOLD_SECONDS = 60.0` (27) | `STALL_THRESHOLD_SECONDS = 60.0` (32) |

Scheduler docstrings literally say "mirrors the bus version." Eight method pairs do the same thing under different names (`run_with_mode`/`run_job_with_guard`, `warn_stalled`/`warn_stalled_job`, `fire_removal_callback`/`fire_removal_callbacks`, `config_matches`/`matches`, `is_cancelled` property vs direct `_dequeued` reads, and divergent `mark_registered` idempotency where the scheduler **silently swallows** a double-registration the bus warns about). The duplicated thing is *behavior* (the orchestration glue around the already-shared `ExecutionModeGuard`), not *state*.

*(Comb correction: the `scheduler_service.py:598` drain/release caveat is **not** a missing-comment divergence — the bus's `release_guard` drains `pending_done` directly and has no analogous ordering constraint, so do not "match" the comment onto the bus.)*

**Fix (re-scoped by the challenge):** Extract a **stateless bridge helper** — e.g. `run_with_mode_bridge(guard, task_bucket, stall_name, invoke_fn)` in `execution_mode.py` (already imported by the bus) — that both `HandlerInvoker` and `SchedulerService` *call*. Do **not** extract a stateful `DispatchModeRunner` object that both compose: the bus/scheduler decoupling is deliberate and documented (`listeners.py:34-36`: the scheduler keeps its own `STALL_THRESHOLD_SECONDS` "so it does not import from the bus layer"), and a shared stateful owner of `pending_done` re-introduces exactly that coupling — a scheduler-only change (batched drains, queue-depth telemetry) would then force edits to a component the bus also depends on, with the bus's tests as collateral, and would pressure legitimately-divergent behavior (`mark_registered`) toward false unification. The two real bugs the duplication *causes* (stall-threshold drift, `mark_registered` swallow) are cheap one-line fixes — do those independently; treat the bridge extraction as an optional, separately-pinned refactor. The executor itself does *not* duplicate this machinery, so `execution_mode.py` is the correct home.

### T2. Private-attribute reach-through into `hassette._*` — HIGH (correctness time-bomb)
Subsystem code bypasses existing public properties and reads private attributes by name, with **divergent null-handling**:

- `bus_service.py:471` — `hassette._state_proxy`, then `if None: return None` (silent skip)
- `state_manager.py:238` — `hassette._state_proxy`, then `assert ... is not None` (crash)
- `runtime_query_service.py:272` — uses the public `state_proxy` property (correct)
- `scheduler/scheduler.py:116` — `hassette._scheduler_service` (assert-then-assign)
- `api/api.py:280` — `hassette._api_service` (assert-then-assign)
- `task_bucket.py:142` — `hassette._loop_thread_id` (arguably justified framework fast-path)

Three different strategies for the same `_state_proxy` attribute is the time-bomb. Public properties already exist and raise `RuntimeError` on `None`.

**Fix:** Migrate all production reads to the public properties; add a `try_state_proxy() -> StateProxy | None` for the legitimately-optional case so null-handling lives in one place. Expose `loop_thread_id` as a public property.

### T3. Constants duplicated, synced only by tests — MEDIUM
The "keep these two equal, a test enforces it" pattern recurs in two genuine cases; a third claimed instance was a false positive (corrected below):

- `STALL_THRESHOLD_SECONDS` — bus + scheduler, identical, kept equal only by `test_stall_threshold_sync.py`. **Genuine** (subsumed by T1). → hoist to a shared module.
- `MAX_RETRY_ATTEMPTS=5` — duplicated in `api_resource.py` and `websocket_service.py` with **naming drift** (`NOT_RETRYABLE` vs `NON_RETRYABLE`), untested. → hoist the count; leave the (legitimately different) exception tuples local.
- ~~Saturation `0.75`/`30.0s` "three copies"~~ — **FALSE POSITIVE (comb + challenge).** Verified: `bus_service.py:40` has only `_DISPATCH_SATURATION_WARN_RATE_LIMIT_SECS = 30.0` and **no `0.75`**; `0.75` exists only in `command_executor.py:44` (`_CAPACITY_WARN_THRESHOLD`, per-entity) and `sync_executor_service.py:32` (`_SATURATION_WARN_THRESHOLD`, global pool) — three *semantically distinct* tuning knobs that merely share the literal `30.0`. Consolidating them would *falsely couple* three subsystems; nothing breaks if they diverge. → rename for clarity so the three knobs read as distinct; do **not** consolidate or test-pin them.
- ~~Log levels "already disagree"~~ — **FALSE POSITIVE (comb).** Verified: `ws.py._LOG_LEVELS` and `logs.py._VALID_LEVELS` hold the identical five levels; neither has `"all"`. The only difference is `dict[str,int]` vs `frozenset`. Minor: `logs.py` could derive its set from `ws.py`'s dict to avoid future drift, but there is no current disagreement.

### T4. Hand-written model-copy code in web where Pydantic would collapse it — HIGH (volume)
The web layer translates core→response models with explicit field-by-field copies:

- `ListenerWithSummary` (39 fields) duplicates `ListenerSummary` (34 fields) + 5; `to_listener_with_summary` copies all 34 by hand (~45 lines → ~7). `models.py:296`, `mappers.py:174`.
- `ConfigResponse` + 6 sub-models re-declare the entire config hierarchy; `config.py` hand-copies ~40 fields. `model_validate(from_attributes=True)` collapses it.
- `system_status_response_from` / `readiness_response_from` / `connected_payload_from` — three single-caller field-copy mappers.

**Fix (comb correction):** `from_attributes=True` will *not* auto-populate the 5 web-only computed fields (`listener_kind`, `handler_summary`, and the three live counts) — they need explicit computation. The real collapse is `ListenerWithSummary(**ls.model_dump(), listener_kind=…, handler_summary=…, suppressed_count=…, …)` — replacing the 34 hand-copied fields with `**ls.model_dump()` plus the 5 explicit ones. Keep `ListenerWithSummary` as a separate model (the boundary is correct); only the mapper *body* shrinks. The `ConfigResponse` hierarchy and the three single-caller status mappers are the larger `model_validate(from_attributes=True)` wins. ~150 deletable lines. Move the inline config mapping into `mappers.py` for consistency.

### T5. Health/error-rate math computed in 3+ places — MEDIUM
`AppHealthSummary` has `.success_rate`/`.error_rate` properties (`telemetry_models.py:45`) that are **dead** (zero callers), while `telemetry.py` re-derives the formula in `health_status_from_summary`/`error_rate_from_summary` (`:91`,`:105`) and again inline in the `app_health` route (`:147`). Diverges silently when the failure definition changes. (Latent: the property lacks the `min(...,100)` clip that `compute_error_rate` has.)

**Fix (comb correction):** The dashboard path uses `AppHealthSummary` and *can* use the properties — make them canonical there. But the `app_health` route operates on `AppHealthAggregates`, a **different** dataclass without those properties — so "use the model properties" cannot work for it. The viable single-source fix is a **shared helper over raw counts** that both `AppHealthSummary.error_rate` and the `AppHealthAggregates` path call, or add a matching `error_rate` to `AppHealthAggregates`. Pick one home; delete the duplicates.

### T6. Dead code from prior migrations — MEDIUM (clean wins)
- `bus/metrics.py` `ListenerMetrics` — 108-line class, zero production callers; `LiveCounts` replaced it. Delete file + test.
- `web/telemetry_helpers.py:84` `alert_context()` — Preact-migration leftover, no callers.
- `scheduler` `run_minutely`/`run_hourly` — convenience wrappers, only docstrings/tests call them (~140 lines across `scheduler.py`+`sync.py`).
- `task_bucket` `run_on_loop_thread`/`create_task_on_loop` — no production callers.
- `telemetry_helpers.py` `_ListenerLike` Protocol — one concrete type, never used as a protocol.

### T7. Defensive guards inside the trust perimeter — MEDIUM
**Partition first (challenge):** before deleting any guard, classify it. A *type-system-fact* guard (the annotation already guarantees it on every reachable path) is safe to delete; a *boundary/wiring-fact* guard (enforces an invariant on a path the type system doesn't cover — direct construction, untyped HA JSON, unwired services) must be kept or strengthened. Several items below are the latter.
- **Enum coercion for `mode`/`backpressure` is NOT redundant double-coercion (corrected).** `bus.py:577` coerces at the *registration boundary* (ergonomics — clear `ValueError` with the listener name in scope); `listeners.py:123` (`ListenerOptions.__post_init__`) is the **dataclass invariant**, guaranteeing every construction path (including direct construction at `listeners.py:667` and test harnesses) holds an `ExecutionMode` enum. Deleting the `__post_init__` copy lets a string `mode` reach dispatch where `mode is ExecutionMode.SINGLE` identity checks silently fail — wrong dispatch, no error. → **Keep `__post_init__`; drop only the redundant bus-level pre-coercion.**
- `isinstance(timeout, bool)` / `isinstance(job, ScheduledJob)` (`classes.py:268`, `scheduler.py:207`) — check whether these sit on a public-API-reachable path before deleting; `timeout` flows from user config (untyped) so the `bool` guard may be load-bearing.
- `resources/base.py` — `unique_name` LBYL double-guard (`:208`); dead `_cache is not None` guard inside a `@cached_property` (`:196`).
- `apps.py:157` `get_app_source` — `.exists()` then `read_text()` with `FileNotFoundError` caught anyway (TOCTOU LBYL).
- `telemetry.py:73` — try/except for a startup-ordering case the architecture already prevents.
- `HeapQueue.remove_item` — `in` scan then `.remove()` scan (LBYL, double O(n)) on every cancel.

### T8. Over-abstraction with one concrete case — LOW/MEDIUM
- `CommandExecutor.execute()` — 6-line `match` dispatch; both callers know the concrete type. Call `execute_handler`/`execute_job` directly, delete it.
- `resources/mixins.py` Protocol shims (`_TaskBucketP`/`_HassetteP`/`_HassetteConfigP`) for one concrete host — replace with `TYPE_CHECKING` imports.
- `task_bucket.make_async_adapter` — wraps already-async fns in a no-op closure; return `fn` directly.
- `bus._build_preds` — 4-callable strategy for 10 lines shared by 2 co-located callers; inline.
- `Daily` is `Cron` in a trench coat — 3-class stack (`Daily`→`CronTrigger`←`Cron`) differing only by label; fold into a `label=` param.
- `_ScheduledJobQueue` (a `Resource` whose only lifecycle is `mark_ready`) + `HeapQueue` live inside the 800-line `scheduler_service.py`; the bus keeps `Router` in its own file. Extract to `scheduler/`.

### T9. Hot-path coupling: executor traverses the app registry per execution — MEDIUM (coupling + perf)
`CommandExecutor.bind_execution_context` (`:497`) calls `hassette.app_handler.get(...)` on **every** handler/job execution just to resolve `instance_name` for logging. The command objects already carry `app_key`/`instance_index`.

**Fix:** Populate `instance_name` on `ListenerIdentity`/`ScheduledJob` at registration time; the executor reads it from the command. Removes the cross-layer call from the hot path.

## Confirmed bugs (verified against source)
1. `config_log_all_events` cached_property freezes hot-reload. Fix: live `@property`. **Caveat (challenge):** it's read in `should_log_event` *per dispatched event* (`bus_service.py:359`) — the hottest path — so the live read isn't strictly free; if profiling later flags it, invalidate-on-reload instead of reading raw each time.
2. `ScheduledJob.mark_registered` silently no-ops a double-registration the bus logs as WARNING (T1) — observability loss. Cheap fix; add the matching WARNING.
3. **Inert `@retry` on `StateProxy.yield_domain_states`** (generator defeats the decorator). Reachable from app code during cold start (`for _, x in self.states.light:` racing `load_cache`) — a startup-race failure, the hardest window to reproduce. **Pair the fix with a structural guard (challenge):** `@retry`-on-a-generator is a *class* of bug; add a check to the existing `tools/check_*.py` linters so the next one is caught, and verify on the cold-start surface, not just a unit test.
4. ~~Conversion-path divergence~~ — **reclassified (challenge): NOT a quick bug.** `[]` raising vs `.get()` returning `None` mirrors `d[k]` vs `d.get(k)` and is arguably correct. Only the *exception type* is worth normalizing (`[]` should raise a domain `UnableToConvertStateError`, not leak a raw Pydantic `ValidationError`); the raise-vs-return behavior must stay. This is a public API-contract change needing docs/deprecation — see N3, **moved to the backlog tier.**

## Fix sequence — two tiers (re-scoped by the challenge)
The stated goal is *basic bug fixes + minor cleanup + the doc*. The original 7-phase plan bundled two high-blast-radius refactors (T1, N2) into the same sequence, reading as "do all of it." Split into a ship-now slice (near-zero behavior risk) and a backlog filed as issues.

**Ship-now (this PR — near-zero behavior risk):**
1. **Confirmed bugs 1–3** (not #4). Bug 3 paired with a linter guard.
2. **Dead-code deletes (T6)** — `ListenerMetrics`, `alert_context`, `run_minutely/hourly`, `run_on_loop_thread`/`create_task_on_loop`, `_ListenerLike`, `get_domain_states`, dead `DomainStates`/`StateManager` iteration surface, `get_recent_invocations_1h` single-app variant. Pure subtraction.
3. **N1: `assert`→public-property + add the missing `api_service` property.** Wiring-fact guards (strengthen, never delete — see N1/T7); the `RuntimeError` must name the missing service + a startup-ordering hint.
4. **Boundary-lint ratchet** — extend `tools/check_module_boundaries.py` to forbid `hassette._*` access outside `core/` (the structural fix that stops T2 re-accreting). Re-enable the `core↔bus` rule as a follow-up to the cycle break.
5. **Safe trust-perimeter guard removals (T7)** — only the type-system-fact ones, after partitioning. *Keep* the enum `__post_init__` invariant.

**Backlog (file as issues, link to #1079):**
- **Break the `bus→core→bus` import cycle** (Verified #1) — move `InvokeHandler`/`ExecuteJob` to a neutral module, or relocate `bus/invocation.py` into `core/`. **Must precede any T1 bridge work (corrected ordering — was inverted).**
- **T1 stateless bridge** + the `only_app` stateless-detector fix (N2) — each separately pinned (characterization tests on *startup ordering* for anything touching app lifecycle).
- **T4/T5** web mapper + health-math unification; **T9** executor hot-path decoupling; **N3** conversion exception-type normalization (with docs); **N4/N5** telemetry SQL collapse + package move; remaining **T8** over-abstraction.
- **Verify-then-fix:** `Api._set_state` round-trips (test HA's `POST /api/states/{id}` merge against a live instance first).

# Part 2 — api, state_manager, app lifecycle, telemetry

Second wave, same recipe, carrying the seven established patterns as cross-validation hooks. Two more high-stakes claims verified against source (below). The first four areas were the load-bearing runtime; these four are the access/lifecycle/persistence surface.

## Verified claims (Part 2)
3. **`@retry` on `StateProxy.yield_domain_states` is INERT — CONFIRMED BUG.** The method has the full `@retry(... ResourceNotReadyError ...)` stack but is a generator (`yield` in the body) that raises `ResourceNotReadyError` inside the body. `@retry` wraps the call, which returns a generator object; the readiness check/raise only run on first `next()`, after tenacity has returned. Retries never fire on this path (they *do* work on the non-generator `get_state`/`__contains__`). `state_proxy.py:178`.
4. **`api_service` is the only service slot with no public property — CONFIRMED.** `core.py` exposes guarded `RuntimeError`-raising properties for every service (`websocket_service`, `state_proxy`, …) except `_api_service`, which `Api.__init__` and `ApiResource.ws_conn` reach via the private attr.

## New / escalated cross-cutting themes

### N1. `assert` used as a runtime service-wiring guard — HIGH (production correctness) — *the audit's strongest finding; all 3 critics endorsed*
`api.py:280` (`_api_service`), `api_resource.py:110` (`_websocket_service`), `api.py:801` (`get_history` response shape), `state_manager.py:238` (`_state_proxy`) all guard with `assert ... is not None` instead of the established public-property `RuntimeError`. **`python -O` strips asserts** (Docker images often set `PYTHONOPTIMIZE`) — the guards vanish and the code dereferences `None`. This sharpens T2: the reach-throughs aren't stylistic, their guards are inert under `-O`. **These are wiring-fact guards — strengthen, never delete (contrast T7's delete list).** **Fix:** add the missing `api_service` public property; route all four through public properties (and a `try_state_proxy()` for the optional case). The replacement `RuntimeError` **must name the missing service and a startup-ordering hint** — under `-O` today the failure is a bare `AttributeError` at the dereference site, so the 2am traceback points at the wrong place.

### N2. App-lifecycle: one real data-model finding + over-decomposition — HIGH for `only_app`, lower for the rest
*(Demoted and corrected by the challenge — the original "pure facade, collapse it" framing was wrong.)*
- **`only_app` is one fact stored in two mutable places (the real finding).** `AppRegistry._only_app` and `AppChangeDetector.only_app_filter` are synced by `update_only_app_filter` (`app_lifecycle_service.py:486-489`). Correction: there is a **single writer today**, so "split-brain" is overstated — the actual gap is **no test pin + both setters public** (`app_registry.py:182`, `app_change_detector.py:108`) = future drift risk. Fix (a "derive, don't sync" win, worth doing on its own): pass `only_app` as a parameter to `detect_changes()`; make `AppChangeDetector` stateless; add a test asserting the registry filter and the next `detect_changes` agree.
- **`AppLifecycleService` owns a `Bus` child it never uses** (`app_lifecycle_service.py:86`) — real dead Resource child; the live subscription is on `AppHandler.bus`. Safe delete.
- **`AppHandler` is NOT a "pure pass-through facade" (corrected).** Verified: `on_initialize` (`app_handler.py:88-105`) has `dev_mode`/`allow_reload_in_prod` gating + the production-reload warning + the conditional file-watcher subscription; `after_initialize` (`:107-116`) orchestrates `bootstrap_apps()` then `mark_ready` with a documented deferred-readiness invariant the wave-based startup depends on. Only `start/stop/reload/apply` are true one-line delegates. Collapsing it is a **core lifecycle merge** across ~10 references (incl. the hot path), not dead-code deletion — and it contradicts the "well-built, not rotten" thesis. → **Do not collapse as a "clean win."** If pursued at all, it's a separately-pinned refactor with characterization tests on *startup ordering*. Backlog.
- Minor: `AppSync`'s 6 identical `@final` hook wrappers, `AppFactory` taking the whole `Hassette` to extract one arg, a half-finished facade (`get_full_snapshot` leaks through `.registry`).

### N3. state_manager: a contract-normalization + a perf trap (beyond the inert @retry)
- **Conversion-path divergence (re-scoped by the challenge — NOT a quick bug):** `self.states.light["x"]` (raw `model_validate`) raises `ValidationError`/`KeyError`; `self.states.get("light.x")` (→ `try_convert_state`) returns a `BaseState` fallback. The raise-vs-return split mirrors `d[k]` vs `d.get(k)` and is **intentional** — keep it. Only normalize the *exception type*: `[]` should raise a domain `UnableToConvertStateError`, not leak a raw Pydantic `ValidationError`. This is a public API-contract touch → needs docs/deprecation, backlog tier.
- **Iteration defeats the cache:** `StateManager.__iter__`/`values()`/`items()` use `__getitem__`, building a fresh `DomainStates` (empty validation cache) per call. **Fix is subtler than "route through `_domain_states_cache`" (comb):** the cache is keyed by `type[BaseState]` and is populated only on `__getattr__` (attribute-style) access; the documented contract for `__getitem__` is no-cache direct access. Route iteration through the *attribute* path's cache lookup without changing `__getitem__`'s caching semantics. Verify against the collision-guard test.
- **`StateRegistry`/`TypeRegistry` are `ClassVar` singletons dressed as instances** — `hassette.state_registry → _state_registry → instance → ClassVar` is 4 layers to reach a class dict. Commit to one shape (all-classmethod or one real instance); deletes 3 `Hassette` slots + 2 properties.

### N4. telemetry SQL quadruplication — HIGH (volume)
`get_listener_summary`/`get_all_listeners_summary` and `get_job_summary`/`get_all_jobs_summary` are **four copies of ~70-line queries** (CTE + aggregates + mapping) differing only by a `WHERE app_key=... AND instance_index=...` vs `WHERE 1=1`. A new aggregate column must be added in four places. → one method each with optional `app_key`/`instance_index` params; ~140–200 lines gone.

### N5. telemetry package boundary is incoherent — MEDIUM
Read-side queries moved to `core/telemetry/` but write-side (`telemetry_repository.py` 662, `telemetry_models.py` 428) stayed in `core/`. `SessionManager` also inlines write SQL that belongs in a repository (every other table goes through `TelemetryRepository`). The split is module-vs-package, not a real read/write or domain boundary. → move the telemetry write-side + models into `core/telemetry/`; route session writes through a repository.

## Theme confirmations from Part 2
- **T2 (private-attr reach-through):** strongly confirmed and escalated via N1. The canonical fix (`try_state_proxy()` + the missing `api_service` property + migrate all callers) resolves bus, state_manager, api, and api_resource at once. Also: `bus_service.read_entity_state` reads `state_proxy.states` dict directly, bypassing `get_state`'s retry contract.
- **T3 (constants synced by tests):** more instances — `MAX_RETRY_ATTEMPTS=5` duplicated in `api_resource.py`/`websocket_service.py` with **naming drift** (`NOT_RETRYABLE` vs `NON_RETRYABLE`, untested); session-status strings are bare untyped literals shared with the DB schema.
- **T4/T5 (hand-copy + health math):** confirmed hard. The `AppHealthSummary.error_rate`/`success_rate` properties are **dead** (zero callers) while three other implementations of the same formula exist in the web layer — pick the property as canonical, delete the rest. Resolution on the `ListenerWithSummary` debate: reviewers split on whether the mapper is waste or the right boundary — **the separate model is correct** (5 fields are genuinely web-only/computed), but the 34-field hand-copy *body* should still become `model_validate(from_attributes=True) + model_copy`.
- **T6/T7/T8:** abundant — dead code (`get_domain_states`, `DomainStates.iterkeys/itervalues/to_dict`, `StateManager` container protocol, `get_recent_invocations_1h` single-app variant); trust-perimeter guards (`issubclass(BaseEntity)`, `BaseState.is_group` dead guards, `AppFactory` LBYL double-lookup) — **partition before deleting (T7)**; over-abstraction (the `Api`→`ApiResource` relay layers). **Correction (challenge): the `_do_*` wrapper split in `session_manager`/`database_service` is NOT over-abstraction** — it's the write-queue concurrency boundary (`public method enqueues → _do_* runs the SQL on the DB thread`), the same `submit`-through-one-writer pattern the audit *praises* as `RetryableBatch` in the Overall read. Removing it would break the concurrency boundary. Likewise the per-area `config_log_level` properties are the codebase's standard Resource pattern, not duplication to collapse.

## Additional items worth flagging
- **`Api._set_state` round-trips (verify-then-fix, promoted from a footnote):** it makes 2 extra HTTP calls for a client-side attribute merge a reviewer claims HA's `POST /api/states/{id}` does natively, with a TOCTOU window on every attribute write. If confirmed, that's a latent data race more serious than most structural findings. **Concrete check: test HA's `POST /api/states/{id}` merge behavior against a live instance**, then fix if confirmed.
- **Twin-drift does NOT extend to api/state/app/telemetry** — none hold a third copy of the dispatch/retry machinery. The T1 bridge remains the contained fix.

## Review gates (what this doc was put through)
- **6 source-verified claims** (true): `bus→core→bus` runtime cycle; `config_log_all_events` freeze; inert `@retry`; missing `api_service` property; saturation constants (disproved the "3 copies" claim); identical log-level sets (disproved the "already disagree" claim).
- **Fine-toothed-comb accuracy pass** — caught 6 factual errors (saturation miscount, log-levels, T4/T5 fix mechanisms, the T1 drain-caveat false divergence, the N3 cache-fix imprecision); all corrected inline above.
- **3-critic adversarial challenge** (systems-architect, senior-engineer, adversarial-reviewer), 0 CRITICAL / 6 HIGH. Key reversals folded in: AppHandler is not a pure facade (N2 demoted); T1 → stateless bridge, not shared object; import-cycle break must precede it (ordering fixed); verdict reframed to a missing-ratchet diagnosis citing `check_module_boundaries.py`/#1079; `_do_*` and the per-area `config_log_level` un-flagged as false positives; enum `__post_init__` kept; conversion-path moved out of the quick-bug bucket.

## Notes on method
Cross-validation paid off repeatedly: the scheduler pass confirmed 3 bus findings; the execution pass confirmed the dispatch duplication is contained to bus/scheduler; Part 2 sharpened T2 (the `-O`-stripped asserts). But the audit's structural hit-rate is lower than its tone implied: the comb caught 6 factual slips and the challenge caught ~4 more over-statements among unverified structural claims (AppHandler-as-facade, T3 saturation, `_do_*`, "split-brain"). **Lesson encoded above:** verified claims are reliable; unverified structural `file:line` claims are leads to confirm, not facts — so the highest-blast-radius items (T1, N2) were demoted to a separately-pinned backlog, and the ship-now slice is restricted to confirmed bugs, pure deletions, the `-O`-assert fix, and the boundary-lint ratchet. The method itself is duplication-primed (three reviewers each tasked to find smells will find them), which is why every structural recommendation now carries a "verify before refactoring" gate.
