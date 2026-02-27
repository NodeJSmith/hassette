# Research Brief: Refactor Hassette Core to Reduce God Object Pattern

**Date**: 2026-02-26
**Status**: Ready for Decision
**Proposal**: Reduce complexity and improve testability of the Hassette coordinator class by extracting cohesive responsibilities into focused services
**Initiated by**: Codebase audit identified Hassette as a god object (7 responsibilities, 439 lines, 26 instance attributes)

---

## Context

### What Prompted This

The Hassette class has evolved into a god object that complicates testing and slows future development:

**Pain Points** (from user):
- **Testing complexity**: Tests are brittle because Hassette has 13+ dependencies to mock
- **Future-proofing**: Framework is pre-1.0 and growing — now is the time to establish good patterns

**Evidence** (from audit):
- **439 lines** of code with 7 distinct responsibilities
- **34 commits in 6 months** (3.8x higher churn than average)
- **Recent growth**: +243 lines added in 3 days for session lifecycle migration (Feb 24-26)
- **High coupling**: 64 files directly import/reference Hassette, 20+ access `.config` property

### Current State

Hassette is the central coordinator with these responsibilities:

1. **Lifecycle Coordination** — orchestrates startup/shutdown of 13+ child services
2. **Service Container** — owns and exposes services via properties (`.api`, `.states`, `.bus`, etc.)
3. **Session Tracking** — creates database sessions, records crashes, finalizes on shutdown (235 lines, newly added)
4. **Event Stream Management** — owns anyio memory channels, provides `send_event()` to 5 services
5. **Configuration Access** — stores and exposes `HassetteConfig` to all services
6. **Context Management** — sets global context variables for framework-wide access
7. **Registry Holder** — stores state/type registries as class attributes

**Data Flow** (Hassette's role):
- **HA Events → Apps**: Pass-through coordinator (manages streams, doesn't process events)
- **State Changes**: Orchestrator (ensures StateProxy dependencies are ready)
- **App Actions → HA**: Service gateway (owns ApiResource and WebsocketService)
- **Event Publishing**: Event hub (5 services call `hassette.send_event()`)

**Current Architecture** (simplified):
```
Hassette (Resource)
├── DatabaseService (SQLite connection, migrations)
├── BusService (event routing, listener dispatch)
├── ServiceWatcher (monitors service health, restarts failed services)
├── WebsocketService (HA WebSocket connection)
├── FileWatcherService (monitors app file changes)
├── AppHandler (manages app lifecycle, Registry, Factory, Lifecycle)
│   └── [complex composition: Registry, Factory, LifecycleManager, ChangeDetector]
├── SchedulerService (background task scheduler)
├── ApiResource (HA REST API session)
├── StateProxy (caches HA state, owns Bus + Scheduler)
├── DataSyncService (aggregates state for web UI)
├── WebApiService (FastAPI server)
└── Public instances: Api, Bus, Scheduler, StateManager
```

### Key Constraints

- **Pre-1.0 framework**: Breaking changes acceptable, no external users yet
- **Comprehensive redesign**: User is open to aggressive refactoring, not just incremental tweaks
- **Test coverage is good**: 72% of Hassette methods tested — safety net exists
- **Recent session migration**: 243 lines of session tracking just landed (Feb 24-26) — still fresh, good extraction candidate
- **Known design debt**: 67 broad exception catches, race conditions in `wait_for_ready()`, config is a hotspot (30 changes in 6 months)

---

## Feasibility Analysis

### What Would Need to Change

| Component | Files Affected | Effort | Risk | Notes |
|-----------|---------------|--------|------|-------|
| **Session Tracking** | 5 core services | Low | Low | Already isolated in Hassette, clear boundaries |
| **Event Stream** | 6 (BusService + 5 producers) | Medium | Medium | Requires coordinating send_event() calls |
| **Service Properties** | 15+ (all property accessors) | Low | Low | Mechanical refactor, safe |
| **AppHandler Composition** | 7 (AppHandler + internals) | High | High | Complex interdependencies |
| **Configuration DI** | 20+ (all services) | High | Medium | Touches every service constructor |
| **Context Management** | 3 (context, app_utils, helpers) | Low | Low | Minimal usage, easy to update |

### What Already Supports This

**Strong Resource/Service Foundation**:
- Every component extends `Resource` or `Service` with lifecycle hooks
- Parent/child relationships already established
- TaskBucket pattern for async task management
- Consistent error handling and restart logic (ServiceWatcher)

**Clear Separation Already Exists**:
- WebsocketService and ApiResource are already separate (not tangled)
- DatabaseService is self-contained
- FileWatcherService, SchedulerService are standalone

**Recent Pattern: Correct Ownership**:
- Session tracking was just moved from DatabaseService → Hassette (Feb 26, commit #312)
- Demonstrates principle: "Move logic to the correct owner"
- Shows team is actively improving architecture

**Test Harness Infrastructure**:
- `HassetteHarness` provides mock Resource for unit tests
- Builder pattern with auto-dependency resolution
- Tests already handle component isolation

### What Works Against This

**High Coupling to `.config`**:
- 20+ access points across all services
- Every service reads `self.hassette.config` in `on_initialize()` and throughout lifecycle
- Changing this requires updating every service constructor (high effort)

**5 Services Depend on `send_event()`**:
- WebsocketService, AppHandler, FileWatcherService, ServiceWatcher, AppLifecycle all emit events via Hassette
- Can't remove `send_event()` without providing alternative
- Event stream is central to the architecture

**Web Route Dependency Injection**:
- 7 web routes inject Hassette via FastAPI DI: `async def route(hassette: HassetteDep)`
- Changing how Hassette is stored in `request.app.state` breaks all routes
- Low effort to fix but high blast radius

**86 Test Files**:
- 40+ integration tests use real Hassette instances
- 5 E2E tests with full web stack
- Any public API change requires test updates

**AppHandler Complexity**:
- Owns Registry, Factory, LifecycleManager, ChangeDetector
- These are tightly integrated, hard to test independently
- Refactoring this is high effort, high risk

---

## Options Evaluated

### Option A: Incremental Extraction (3 Phases)

**How it works**:
Extract responsibilities one at a time, starting with the cleanest seam (session tracking), then event streams, then AppHandler composition. Preserve all public APIs. Focus on improving testability without breaking existing code.

**Phase 1: Extract SessionManager** (Low Risk, Immediate Value)
- Move session tracking from Hassette to new `SessionManager` service
- Methods: `create_session()`, `mark_orphaned_sessions()`, `finalize_session()`, `record_crash()`
- Hassette keeps `session_id` property (delegates to SessionManager)
- Test surface: Move session tests to `test_session_manager.py`

**Phase 2: Extract EventStreamService** (Medium Risk, Medium Value)
- Create `EventStreamService` to own anyio memory channels
- Abstract `send_event()` behind a clean interface
- BusService receives stream via constructor, not via clone
- Test surface: 5 services call `send_event()` need updates

**Phase 3: Refactor AppHandler Composition** (High Risk, High Value)
- Extract `AppSessionService` to own Registry + Lifecycle + ChangeDetector
- AppHandler becomes facade/coordinator
- Easier to test app loading/reloading independently
- Test surface: AppHandler tests need updates

**Pros**:
- Low risk per phase — each extraction is isolated
- Immediate testing wins (SessionManager is testable day 1)
- Preserves public API (`.api`, `.states`, `.config` unchanged)
- Follows recent pattern (session tracking just moved to correct owner)
- Aligns with existing Resource/Service architecture

**Cons**:
- Three separate refactoring efforts (extended timeline)
- Hassette still has 4 responsibilities after Phase 3 (not fully decomposed)
- Doesn't address `.config` coupling (20+ access points remain)
- AppHandler refactor (Phase 3) is complex, may stall

**Effort estimate**: Medium — 3 phases × ~2-3 days each = 1-2 weeks total

**Dependencies**: None beyond pytest and existing test infrastructure

---

### Option B: Comprehensive Service Registry Pattern

**How it works**:
Replace manual service registration with a declarative `ServiceRegistry` that owns child service lifecycle, property access, and configuration. Hassette becomes a pure coordinator that delegates to the registry.

**Design**:
```python
class ServiceRegistry(Resource):
    """Owns all service creation, lifecycle, and access."""

    def register(self, name: str, service_type: Type[Service], config: dict) -> None:
        """Register a service with its config."""

    def get(self, name: str) -> Service:
        """Access a service by name."""

    async def start_all(self) -> None:
        """Initialize all services in dependency order."""

    async def stop_all(self) -> None:
        """Shutdown all services in reverse order."""

class Hassette:
    def __init__(self, config: HassetteConfig):
        self._services = ServiceRegistry()
        self._services.register("database", DatabaseService, {...})
        self._services.register("websocket", WebsocketService, {...})
        # ...

    @property
    def api(self) -> Api:
        return self._services.get("api")
```

**Benefits**:
- Service registration becomes data-driven (could be YAML/TOML configured)
- Removes 15+ boilerplate property definitions from Hassette
- Easier to add/remove services (no Hassette modifications)
- Registry pattern is familiar to developers
- Could extract session tracking, event streams as registry-managed services

**Drawbacks**:
- High upfront effort — requires rewriting all service registration
- Adds indirection layer (registry between Hassette and services)
- Property access becomes delegated (`self._services.get("api")` vs. `self._api`)
- 86 test files would need updates (integration tests expect direct properties)
- Doesn't solve `.config` coupling (services still need config access)

**Pros**:
- Scalable — adding new services becomes trivial
- Clean separation — Hassette is pure coordinator, registry owns composition
- Future-proof — registry could support plugins, dynamic service loading
- Aligns with DI patterns from FastAPI

**Cons**:
- Over-engineering for current needs (13 services, not 100)
- High risk — large refactor increases bug surface area
- Breaking change for all property access (`.api`, `.states`, etc.)
- Blocks other work during extended refactor period

**Effort estimate**: Large — 2-3 weeks of focused work, high complexity

**Dependencies**: None, but could adopt `dependency-injector` library for registry implementation (adds external dependency)

---

### Option C: Configuration Dependency Injection

**How it works**:
Instead of services accessing `self.hassette.config`, create service-specific config objects that are passed via constructor. Reduces coupling to Hassette instance.

**Design**:
```python
@dataclass(frozen=True)
class WebsocketServiceConfig:
    url: str
    timeout_seconds: int
    heartbeat_interval_seconds: int
    token: str
    log_level: str

    @classmethod
    def from_hassette(cls, h: Hassette) -> "WebsocketServiceConfig":
        return cls(
            url=h.config.ws_url,
            timeout_seconds=h.config.websocket_timeout_seconds,
            heartbeat_interval_seconds=h.config.websocket_heartbeat_interval_seconds,
            token=h.config.token,
            log_level=h.config.websocket_service_log_level,
        )

class WebsocketService(Service):
    def __init__(self, config: WebsocketServiceConfig, *, parent: Resource | None = None):
        # No need for hassette reference just for config
        super().__init__(parent=parent)
        self.config = config
```

**Benefits**:
- Services are testable without full Hassette instance
- Clear dependency declaration (explicit config fields)
- Config changes are visible (type hints document what each service needs)
- Aligns with Pydantic philosophy (explicit is better than implicit)

**Drawbacks**:
- High effort — 13+ services need config objects
- Services still need `hassette` reference for other reasons (send_event, wait_for_ready)
- Verbose — each service needs a config class
- Doesn't reduce responsibilities in Hassette (still owns config)

**Pros**:
- Improves testability significantly
- Makes service dependencies explicit
- Follows FastAPI DI patterns
- Can be done incrementally (one service at a time)

**Cons**:
- Boilerplate heavy (13+ config classes)
- Partial solution (doesn't address event streams, session tracking)
- Services still coupled to Hassette for non-config reasons

**Effort estimate**: Medium-Large — ~1-2 days per service × 13 services = 2-3 weeks

**Dependencies**: None

---

### Option D: Minimal Extraction (Session + Event Streams Only)

**How it works**:
Extract only the two cleanest seams (session tracking and event stream management) into focused services. Leave everything else as-is. Fastest path to testing wins.

**Phase 1: SessionManager** (same as Option A Phase 1)
**Phase 2: EventStreamService** (same as Option A Phase 2)
**Stop here** — don't refactor AppHandler, don't add config DI, don't build a registry.

**Pros**:
- Fastest time-to-value (1 week)
- Low risk (only 2 extractions)
- Immediate testability improvement
- Follows recent architectural pattern (correct ownership)
- Hassette drops from 439 lines → ~200 lines

**Cons**:
- Incomplete — Hassette still has 5 responsibilities
- Doesn't address `.config` coupling
- Doesn't fix AppHandler complexity
- Future growth will add responsibilities back to Hassette

**Effort estimate**: Small — ~1 week total

**Dependencies**: None

---

## Concerns

### Technical Risks

**Race Conditions in Service Lifecycle**:
- Known issue (Feb 26 audit): `wait_for_ready()` uses polling, not event-driven readiness
- Extracting services could worsen this if dependencies aren't explicit
- **Mitigation**: Fix readiness pattern before refactoring, or document dependencies clearly

**Breaking Test Isolation**:
- 86 test files, 40+ integration tests use real Hassette
- Any public API change (properties, methods) breaks tests
- **Mitigation**: Preserve public API in Options A and D; accept test churn in Options B and C

**Event Stream Coupling**:
- 5 services call `send_event()` — extracting EventStreamService requires coordinating all 5
- BusService clones the receive stream — fragile if stream lifecycle changes
- **Mitigation**: Phase 2 of Option A handles this carefully; Options B/C ignore it

### Complexity Risks

**AppHandler is Tangled**:
- Registry, Factory, Lifecycle, ChangeDetector are tightly interdependent
- Extracting these (Option A Phase 3) is high risk
- **Mitigation**: Skip AppHandler refactor (Option D) or defer to future work

**Over-Engineering**:
- ServiceRegistry (Option B) adds significant abstraction for 13 services
- Config DI (Option C) creates boilerplate for modest gain
- **Mitigation**: Choose minimal approach (Option D) or incremental (Option A)

**Configuration Hotspot**:
- Config is the #1 most-changed file (30 commits in 6 months)
- Refactoring config access (Option C) may conflict with ongoing config changes
- **Mitigation**: Accept config coupling as unavoidable; focus on other seams

### Maintenance Risks

**Long-Term Ownership**:
- Extracting services creates more files to maintain
- Each new service needs tests, docs, error handling
- **Mitigation**: Only extract cohesive responsibilities (SessionManager, EventStreamService)

**Backward Compatibility**:
- Framework is pre-1.0 — breaking changes are acceptable now
- Post-1.0, refactoring becomes much harder
- **Mitigation**: Do it now while breaking changes are cheap

---

## Open Questions

- [ ] Should session tracking include future audit trail features, or stay focused on lifecycle?
- [ ] Could EventStreamService support multiple streams (not just the main bus stream)?
- [ ] Is the `wait_for_ready()` race condition critical enough to fix before refactoring?
- [ ] Should AppHandler be split even if it's high risk, given testing complexity?
- [ ] Would a ServiceRegistry benefit from plugin support, or is that over-engineering?

---

## Recommendation

**Choose Option A: Incremental Extraction (3 Phases)** — but **stop after Phase 2** unless AppHandler pain becomes acute.

### Rationale

1. **Aligns with recent patterns**: Session tracking was just moved to Hassette (Feb 26). Extracting SessionManager continues that "correct ownership" principle.

2. **Immediate testability wins**: SessionManager and EventStreamService are independently testable from day 1. No need to mock all of Hassette.

3. **Low risk per phase**: Each extraction is isolated. If Phase 1 works well, proceed to Phase 2. If not, stop.

4. **Preserves public API**: Apps and web routes see no changes (`.api`, `.states`, `.config` unchanged). Only internal structure improves.

5. **Avoids over-engineering**: ServiceRegistry (Option B) and Config DI (Option C) add complexity without proportional value. The codebase has 13 services, not 100.

6. **Defers high-risk work**: AppHandler refactor (Phase 3) is complex and can wait until testing pain justifies the effort.

### Why Not the Other Options?

- **Option B (Service Registry)**: Over-engineered. Adds indirection layer for modest benefit. High upfront cost.
- **Option C (Config DI)**: Doesn't address the main god object problem (Hassette still owns 7 responsibilities). Creates boilerplate.
- **Option D (Minimal Extraction)**: Good for speed, but leaves AppHandler complexity unaddressed. If testing remains painful after Phase 2, Phase 3 is still needed.

### Suggested Next Steps

1. **Create ADR** (`/mine.adrs`) to record the decision: "Extract SessionManager and EventStreamService from Hassette"
   - Document the god object problem
   - Explain the incremental approach
   - Capture Phase 3 as future work

2. **Fix `wait_for_ready()` race condition first** (from Feb 26 audit):
   - Switch from polling to event-driven readiness
   - This ensures new services (SessionManager, EventStreamService) don't inherit broken patterns

3. **Implement Phase 1**: Extract SessionManager
   - Create `src/hassette/core/session_manager.py`
   - Move 235 lines of session logic from Hassette
   - Add `test_session_manager.py` with comprehensive coverage
   - Verify all 86 tests still pass

4. **Implement Phase 2**: Extract EventStreamService
   - Create `src/hassette/core/event_stream_service.py`
   - Abstract `send_event()` behind clean interface
   - Update 5 producer services to use new interface
   - Verify event flow works end-to-end

5. **Reassess**: After Phase 2, measure testing complexity
   - If AppHandler testing is still painful → proceed to Phase 3
   - If testing is manageable → stop and move on to other priorities

---

## Sources

- **Audit findings**: `/mine.audit` analysis (2026-02-26) identified god object pattern
- **Blast radius analysis**: Integration surface mapping (64 files, 86 tests)
- **Architecture mapping**: Resource hierarchy, data flow, service dependencies
- **Git history**: 6 months of evolution, recent session tracking migration (commit #312)
- **Design decisions**: ADR-0001 (Command Executor pattern), Feb 26 health audit (race conditions)
- **Codebase patterns**: Resource/Service hierarchy, event-driven bus, async-first
