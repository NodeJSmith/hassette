# Comprehensive Codebase Audit — 2026-03-25

8 parallel audit agents (all Opus 4.6) examined the hassette codebase from different angles.

## Reports

| Report | Agent | Findings |
|---|---|---|
| [general-health.md](general-health.md) | General audit | 1C, 5H, 9M, 6L |
| [scheduler-events.md](scheduler-events.md) | Design audit (scheduler/bus/events) | 0C, 4H, 7M, 6L |
| [scheduler-events-code.md](scheduler-events-code.md) | Code reviewer (scheduler/bus/events) | 2C, 6H, 8M, 6L |
| [db-layer.md](db-layer.md) | DB auditor | 0C, 1H, 3M, 3L |
| [web-frontend.md](web-frontend.md) | Frontend developer | 0C, 2H, 5M, 7L |
| [web-a11y.md](web-a11y.md) | UI/UX auditor | 1C, 4H, 11M, 2L |
| [convention-drift.md](convention-drift.md) | Integration reviewer | 0C, 2H, 8M, 3L |
| [coupling.md](coupling.md) | Architect | 0C, 2H, 5M, 2L |

## Cross-Cutting Synthesis

### Critical (4 unique findings)

1. **No focus indicators anywhere** — app unusable for keyboard users (a11y)
2. **Coverage threshold commented out** — no CI enforcement (general health)
3. **Non-thread-safe ID generators** — `itertools.count` shared across threads (scheduler code)
4. **Mutable trigger state** — `IntervalTrigger.next_run_time()` mutates `self.start` (scheduler code)

### High — Recurring Themes

**Duplicated execution logic** (flagged by 3 agents)
- `CommandExecutor._execute_handler` / `_execute_job` share ~170 lines of near-identical code
- `utils/execution.py` already provides `track_execution()` for exactly this pattern

**Hassette god object** (coupling)
- ~15 private attributes form a de facto public API
- User resources all reach into `hassette._private` to bind to backing services

**Core imports web layer** (coupling)
- `RuntimeQueryService` imports Pydantic response models from `web.models`
- Reverse dependency from infrastructure into presentation

**Missing test coverage for core services** (general health)
- `bus_service.py` (504 lines) and `scheduler_service.py` (527 lines) have no dedicated test files

**Accessibility blockers** (a11y) — 1 critical + 4 high
- No skip nav, non-interactive elements with click handlers, mobile users stranded

**Rate limiting design** (scheduler code + design)
- Throttle holds lock during handler execution
- Debounced handlers silently swallow exceptions
- `once=True` + debounce race condition

### Notable Medium Findings

- Logger naming 3 ways across 31+ files
- 17 production `assert` statements that vanish under `-O`
- `api.py` at 880 lines / 39 methods exceeds 800-line limit
- Frontend TS types manually maintained, no CI validation against OpenAPI spec
- Stub endpoint `/api/bus/metrics` returns hardcoded zeros
- SPA catch-all path check uses `Path.parents` instead of `is_relative_to()`
- `ApiResource.on_shutdown` signature breaks lifecycle hook contract
- Bus dispatch creates unbounded concurrent handler tasks (no backpressure)
- Stale CLAUDE.md still documents htmx/Alpine.js architecture

### Clean Areas

- **DB layer** — well-architected, parameterized queries, proper indexing, WAL mode, graceful shutdown
- **Event handling module** — zero reverse dependencies, pure functions, cleanest code in the repo
- **Migration strategy** — working up/down migrations, batched writes
- **Resource/Service lifecycle** — strong pattern, well-enforced
- **Frontend signal-based state** — clean hooks, good test coverage (14 test files)
- **WebSocket handling** — robust reconnection with exponential backoff
- **CSS token discipline** — no raw hex values, full dark/light theming
