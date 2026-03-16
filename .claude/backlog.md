## Codebase Audit (feature wave 8b9390d..3c40430) — 2026-03-16

### 1. Scheduler API ignores `instance_index` filter — CRITICAL
`web/routes/scheduler.py:42-44` — `/scheduler/jobs` accepts `instance_index` param but never uses it in filtering. Multi-instance apps return jobs from all instances. Bus equivalent handles this correctly.

### 2. Hardcoded `instance_index=0` in app detail partials — CRITICAL
`web/ui/partials.py:136,147` — `app_detail_listeners_partial` and `app_detail_jobs_partial` hardcode `instance_index=0`. Referenced in `app_instance_detail.html` for initial page load. Live HTMX updates use correct instance-aware endpoints.

### 3. Polling-based `wait_for_ready` race window — HIGH
`utils/service_utils.py:8-39` (bug #314) — 100ms polling loop instead of event-based waits. Creates timing-dependent race windows. 5 call sites across CommandExecutor, StateProxy, WebApiService.

### 4. ServiceWatcher doesn't validate readiness after restart — HIGH
`service_watcher.py:177-189` (bug #315) — Listens for RUNNING status but never checks `mark_ready()`. Service that crashes between RUNNING and ready appears recovered but is stuck.

### 5. No coordination for cascading service failures during shutdown — HIGH
Bug #318 — CommandExecutor correctly flushes in normal path, but abnormal shutdown sequences can trigger RuntimeError from submit() if DatabaseService shuts down first.

### 6. No migration downgrade test — MEDIUM
`migrations/versions/001_initial_schema.py` — Upgrade path tested; downgrade never exercised.

### 7. Sentinel ID filtering untested — MEDIUM
`command_executor.py:503-518` — Records with listener_id=0 or session_id=0 silently dropped (correct), but no test verifies this under startup race conditions.

### 8. Inconsistent `mark_ready` timing across services — MEDIUM
Some services mark ready in `on_initialize()` (early), others in `serve()` (late). No documented pattern for when to use which.
