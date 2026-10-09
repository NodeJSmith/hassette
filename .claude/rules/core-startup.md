---
paths:
  - "src/hassette/core/**"
  - "src/hassette/app/**"
  - "tests/unit/core/**"
  - "tests/integration/test_dashboard_without_ha.py"
  - "tests/integration/test_state_proxy.py"
  - "tests/system/test_startup*.py"
  - "tests/system/test_state_proxy.py"
---

# Core — Startup, Readiness, and Services

Resource lifecycle mechanics (teardown reports, `_init_task`/`_shutdown_task`, module-level lifecycle functions) live in `.claude/rules/resource-lifecycle.md`.

## Service dependencies

`BusService` and `SchedulerService` both declare `depends_on: [DatabaseService, SyncExecutorService]` — the database is guaranteed ready before any listener or job registration can occur. `AppBootstrapCoordinator` also declares `SyncExecutorService` in its `depends_on`, which transitively keeps it available to app instances by the time `AppHandler` bootstraps them. The dedicated sync-handler executor outlives every component that submits sync work (Bus, Scheduler, and the App lifecycle hooks), so it is torn down only after them at shutdown.

`SyncExecutorService` (`sync_executor_service.py`) is a thin lifecycle wrapper around `SyncExecutor` (`sync_executor.py`), a plain capability class — no `Resource`/`Service` base — that owns the thread pool and is constructed in `Hassette.__init__()` before the Resource lifecycle starts, so every `TaskBucket` holds a `SyncExecutor` reference from birth. The reference is not a working pool: the pool exists only after `SyncExecutorService.on_initialize()` (see `SyncExecutor.submit()`), so don't assume sync execution works before that service has initialized.

**LoggingService** (`logging_service.py`) — a Resource with `depends_on=[DatabaseService]` that upgrades logging from synchronous (console-only) to asynchronous (console + capture + persistence) during `on_initialize()`. Owns the QueueListener, LogCaptureHandler, and LogPersistenceHandler. The async pipeline starts unconditionally; persistence degrades gracefully on failure.

## WebSocket readiness vs. lifecycle readiness

`WebsocketService` marks itself lifecycle-ready unconditionally in `on_initialize()`, before `serve()` ever attempts a connection — lifecycle readiness ("the service is running") is intentionally decoupled from HA connection status.

`ConnectionState.CONNECTED` (exposed via `is_connected`) has exactly one meaning — "external readiness": authentication succeeded, the receive loop is running, and Home Assistant confirmed the HA event subscription. `WebsocketService`'s own send gate (`_send_ready_event`, behind `send_json()`/`send_and_wait()`) is auth-level: it opens after auth with the receive loop running, before the subscription confirms, so setup traffic like `subscribe_events` can flow. That gate does not imply external readiness, and the service does not enforce it on sends — callers that must not send before CONNECTED check `is_connected` themselves, as `Api.ws_send_json()`/`Api.ws_send_and_wait()` do.

Each transition into external readiness gets a monotonically increasing connection generation (`get_connected_generation()` / `wait_connected_generation()`); a disconnect invalidates that generation without decrementing or reusing it, so `StateProxy` can reject synchronization work that belongs to a superseded connection.

Because `WebsocketService`'s lifecycle readiness never implies HA connectivity, `ApiResource.depends_on` is empty and `StateProxy.depends_on` is `[ApiResource, BusService, SchedulerService]` — neither lists `WebsocketService`.

`RuntimeQueryService.get_system_status()` reads `ws.is_connected` (current), `has_ever_connected` (latch, never reverts), and `AppBootstrapCoordinator.is_released()` (`bootstrap_released`) to report "starting" (never connected), "ok" (currently connected AND bootstrap released), or "degraded" for every other case that has connected at least once — including a live connection where bootstrap hasn't released yet.

## App bootstrap gate

`AppBootstrapCoordinator` (`app_bootstrap_coordinator.py`) is the single authoritative decision point for "may apps start?" It is a `Resource`, not a `Service` — no serve loop, no restart policy, no continuous enforcement. Its `depends_on` is the complete app-facing prerequisite set: `[ApiResource, BusService, SchedulerService, StateProxy, SyncExecutorService]`.

Once that dependency wait completes it marks its own Resource readiness — so the finite startup wave finishes even without Home Assistant — then waits in background work for `StateProxy.wait_initial_state_capability()`. Only when that capability resolves does it open a separate, process-latched release (`wait_released()` / `is_released()`). That latch, not Resource readiness, means "apps may initialize code": it opens once, never re-closes on a later disconnect, and framework shutdown cancels any outstanding wait so teardown is never delayed by a Home Assistant that never connects.

`AppHandler.depends_on` is `[AppBootstrapCoordinator]` only. Every app-creation path funnels through `AppLifecycleService.start_app()`'s admission check:

- The initial bulk bootstrap uses `AppAdmissionMode.WAIT_FOR_RELEASE` (the one path allowed to await the latch).
- Manual HTTP start/reload use `AppAdmissionMode.REJECT_IF_UNRELEASED`, which raises `AppBootstrapNotReleasedError` (mapped to HTTP 409) instead of waiting.
- Config-change and file-watcher reconciliation that arrives before release does not retain a waiting task — `AppLifecycleService` coalesces repeated pre-release changes into one latest desired-state record and replays it once after release opens.

## StateProxy initial-state capability

`StateProxy`'s Resource readiness means only "the synchronization coordinator is wired," not that Home Assistant data is usable. A separate `has_initial_state_capability()` / `wait_initial_state_capability()` pair resolves only after the current externally-ready generation's initial snapshot has loaded, its Resource-lifetime state-change listener has journaled any events observed concurrently, and one generation-fenced commit has applied both.

A failed or never-attempted initial snapshot never opens this capability, so app bootstrap stays blocked indefinitely while `StateProxy` keeps retrying (through the next scheduled poll, or one coalesced generation-scoped retry timer when polling is disabled or hasn't started). This is deliberate: the framework does not permit degraded app bootstrap against an unavailable state cache.

Once initial capability has been reached, a later disconnect marks the cache `STALE` rather than `UNAVAILABLE` (see `StateCacheFreshness`), preserving stale reads for running apps without re-blocking the coordinator — a lost connection after bootstrap never stops or suspends running apps.

## Dashboard without Home Assistant

The dashboard and app bootstrap do not share one readiness signal. When Home Assistant is unreachable at startup, `WebApiService` still reaches ready and serves — `RuntimeQueryService.depends_on` excludes `AppHandler`, so registry metadata (manifests, the `--app` filter) stays queryable and `get_system_status()` reports `app_count=0` — while every app instance remains unbootstrapped until HA reaches external readiness and an initial snapshot commits. Health stays `starting` the whole time HA has never connected; there is no dedicated "apps pending" status.

## Process model

Exactly one live `Hassette()` instance per process at a time. Constructing a new instance after an earlier one finished is routine (the test suite does it constantly via `HassetteHarness`); two instances initializing or running concurrently is unsupported. Process-global state relies on this — `enable_basic_logging()`'s extra-logger snapshot/restore (`src/hassette/logging_.py`) and `block_io_guard.py`'s patch-tracking globals both assume single-writer access. Don't add concurrency guards (locks, owner-id checks) to such state without a specific driving need; the assumption is a deliberate non-goal.
