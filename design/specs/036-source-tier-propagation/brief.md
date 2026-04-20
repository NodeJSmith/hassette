# Source Tier Propagation — Design Brief

**Date:** 2026-04-19
**Issues:** #547, #548

## Problem

Framework components (StateProxy, RuntimeQueryService) have telemetry misclassified as app-tier. Two root causes:

1. `Bus.on()` and `Scheduler.schedule()` default `source_tier` to `"app"` with no way to inherit from the owning Resource
2. `BusService.add_listener()` gates DB registration on `if listener.app_key` — framework components with empty `app_key` bypass DB tracking entirely, making their errors invisible to telemetry

## Decided Design

### 1. Always persist listener/job registrations to the DB

Remove the `if listener.app_key:` gate in `BusService.add_listener()`. All listeners go through `_register_then_add_route()` regardless of `app_key`. If a component doesn't set `app_key`, the row has an empty `app_key` — but it still exists and its executions are tracked. Same for `SchedulerService`.

This is the core fix. The gate was coupling identity (labeling) with tracking (persistence). Those are separate concerns.

### 2. Propagate `source_tier` through Resource hierarchy

- Add `source_tier: ClassVar[SourceTier] = "framework"` to `Resource` — framework is the default because most Resources in `core.*` are framework components
- `App` and `AppSync` override to `source_tier = "app"`
- `Bus.on()` reads `self.parent.source_tier` and passes it to `Listener.create()`
- `Scheduler.schedule()` reads `self.parent.source_tier` and passes it to `ScheduledJob()`
- Child resources inherit their parent's tier automatically

### 3. Additional changes completed in this scope

- Removed `register_framework_listener()` — framework components (ServiceWatcher, SessionManager, AppHandler) now own Bus children and register via `Bus.on()` directly (originally scoped as #548, completed here)
- Added `app_key` property to `Resource` base class for framework identity
- Added runtime assertions: Bus/Scheduler require parent, `source_tier` must be valid
- Do NOT introduce `FrameworkResource`, `telemetry_key`, or any new base classes
- Do NOT rename `app_key` (cosmetic, follow-up)
- Do NOT add a DB migration for key format changes (not needed for the fix)

## Verification

- Framework errors appear under "Framework" filter in dashboard
- App errors continue to appear under "Apps" filter
- StateProxy's listeners and poll job get `source_tier='framework'` in the DB
- RuntimeQueryService's listeners get `source_tier='framework'` in the DB
- Unit tests verify propagation: Resource → Bus → Listener, Resource → Scheduler → ScheduledJob

## Key Decisions Made During Discovery

1. **Default to framework, not app** — almost everything that runs is framework; App/AppSync are the exceptions that override
2. **Remove the registration gate, don't work around it** — the `app_key` gate was the real root cause of invisible framework errors
3. **Scope expanded** — source_tier propagation, gate removal, and register_framework_listener removal completed together; app_key rename remains follow-up
4. **No new abstractions** — FrameworkResource was over-engineering; just put source_tier on Resource directly

## Context From Prior Challenges (informational)

Two rounds of challenge on a more complex design revealed:
- SessionManager registration timing must stay post-ready in core.py (DB not initialized during on_initialize)
- AppHandler's file-watcher registration is conditional on dev_mode — preserve the guard if moving it
- The `owner_id` format change between `register_framework_listener` and `Bus.on()` is a non-issue for cold start (Router is in-memory, rebuilt on restart)
- `drain_framework_registrations()` works regardless of registration entry point — it queries by key pattern
- `handler_invocations` and `job_executions` have no `app_key` column (verified against 001_initial_schema.py) — they reference listeners/scheduled_jobs via FK

These findings informed the register_framework_listener removal completed in this PR.
