# System Internals — Resource Lifecycle & Supervision

**Status:** New page (content from current `internals.md` section 10)
**Voice mode:** Concept — system-as-subject, no "you", contributor/deep-dive audience

## Outline

### H2: Resource State Machine
State transitions diagram: `NOT_STARTED` → `STARTING` → `RUNNING` → `STOPPING` → `STOPPED`. Error/terminal states: `FAILED`, `CRASHED`, `EXHAUSTED_COOLING`, `EXHAUSTED_DEAD`.

### H2: Readiness vs Running
`mark_ready()` signals readiness; RUNNING is the status. Why these are separate — a service can be running but not yet ready to serve dependents.

### H2: Wave Startup and Shutdown
How the dependency graph drives startup waves (level 0 first, then level 1, etc.) and shutdown in reverse.

### H2: Service Supervision
#### H3: RestartSpec
Class attribute on services: restart type, sliding-window budget, backoff parameters, error routing.
#### H3: RestartType
`PERMANENT` (always restart), `TRANSIENT` (restart on unexpected failure), `TEMPORARY` (never restart).
#### H3: Sliding-Window Budget
Intensity (max restarts) and period (window size). Budget resets on recovery.
#### H3: Error Routing
Fatal vs non-retryable error names. Three-layer routing: handler-level, service-level, framework-level.
#### H3: Exhaustion States
`EXHAUSTED_COOLING` (cooldown period after budget runs out) → either budget resets or transitions to `EXHAUSTED_DEAD` after `max_cooldown_cycles` (0 = infinite).
#### H3: Backoff Parameters
`backoff_base_seconds`, `backoff_multiplier`, `backoff_max_seconds`, `startup_timeout_seconds`.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `internals_restart_spec.py` | Keep or move from `core-concepts/snippets/` | RestartSpec example |

## Cross-Links

- **Links to:** Architecture & Data Flow, Per-Service Internals, Operating/overview (runtime behavior references these mechanics)
- **Linked from:** Architecture & Data Flow, Operating overview
