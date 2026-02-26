# ADR-0002: Extract SessionManager, EventStreamService, and Refactor AppHandler from Hassette

## Status
Accepted

## Context

The `Hassette` class has evolved into a god object with 7 distinct responsibilities, 439 lines of code, and 26 instance attributes. Recent audit (2026-02-26) and comprehensive research identified testing complexity and future-proofing concerns as primary pain points.

### Current Responsibilities

1. **Lifecycle Coordination** — orchestrates startup/shutdown of 13+ child services
2. **Service Container** — owns and exposes services via properties (`.api`, `.states`, `.bus`, etc.)
3. **Session Tracking** — database session CRUD, crash recording, orphaned session cleanup (235 lines, added Feb 24-26)
4. **Event Stream Management** — owns anyio memory channels, provides `send_event()` to 5 services
5. **Configuration Access** — stores and exposes `HassetteConfig` to all services
6. **Context Management** — sets global context variables for framework-wide access
7. **Registry Holder** — stores state/type registries as class attributes

### Evidence of Impact

**Code metrics**:
- 439 lines of code
- 34 commits in 6 months (3.8x higher churn than average)
- Recent growth: +243 lines in 3 days for session lifecycle migration
- 64 files directly import/reference Hassette
- 86 test files (40+ integration tests use real Hassette instances)

**Testing pain**:
- Integration tests require mocking 13+ dependencies
- **HassetteHarness is complex** — tracks startup order, manages dependency resolution, requires understanding all 13+ services to use
- Session tracking logic can't be tested independently
- Event stream behavior tangled with Hassette lifecycle
- AppHandler composition (Registry, Factory, Lifecycle, ChangeDetector) is complex and hard to test in isolation
- Writing new tests requires understanding the entire Hassette object graph

**Design patterns already in place**:
- Strong Resource/Service foundation with lifecycle hooks
- TaskBucket pattern for async task management
- Service restart logic (ServiceWatcher with exponential backoff)
- Recent precedent: session tracking was just moved from DatabaseService → Hassette (commit #312, Feb 26) to establish correct ownership

### Constraints

- Pre-1.0 framework (breaking internal changes acceptable)
- User is open to comprehensive redesign, not just incremental tweaks
- Good test coverage (72% of Hassette methods) provides safety net
- Session tracking just landed (Feb 24-26) — still fresh, good extraction candidate
- AppHandler is already complex after recent refactor — needs continued improvement

## Decision

Extract three cohesive responsibilities from Hassette into focused services, reducing Hassette to a pure lifecycle coordinator. All three phases are immediate work (not deferred).

**Dual goals**:
1. Reduce Hassette complexity (439 lines → ~150-200 lines)
2. **Simplify test harness** — create focused test fixtures for each service, making tests easier to write and maintain

### Phase 1: Extract SessionManager Service

Create `SessionManager` service to own all database session lifecycle logic:

**Extracted methods**:
- `_create_session()` → `SessionManager.create_session()`
- `_finalize_session()` → `SessionManager.finalize_session()`
- `_on_service_crashed()` → `SessionManager.on_service_crashed()`
- `_mark_orphaned_sessions()` → `SessionManager.mark_orphaned_sessions()`

**Ownership**:
- `SessionManager` becomes a child of Hassette (like other services)
- Depends on `DatabaseService` for database access
- Session ID exposed via `Hassette.session_id` property (delegates to SessionManager)

**Implementation location**: `src/hassette/core/session_manager.py`

**Benefits**:
- Removes 235 lines of session logic from Hassette
- Session tracking becomes testable in isolation
- Reduces Hassette complexity immediately
- Follows recent pattern (correct ownership principle from Feb 26 migration)

### Phase 2: Extract EventStreamService

Create `EventStreamService` to own anyio memory channels and event stream lifecycle:

**Extracted responsibilities**:
- Memory stream creation and ownership (`_send_stream`, `_receive_stream`)
- `send_event()` method abstracted behind clean interface
- Stream closing logic in shutdown
- `event_streams_closed` property

**Producer coordination**:
- 5 services currently call `hassette.send_event()`:
  - WebsocketService, AppHandler, FileWatcherService, ServiceWatcher, AppLifecycle
- These will be updated to use `EventStreamService` interface

**BusService integration**:
- BusService currently clones receive stream
- Will receive stream directly via constructor dependency

**Implementation location**: `src/hassette/core/event_stream_service.py`

**Benefits**:
- Event stream behavior testable independently
- Clear ownership boundary (EventStreamService owns streams, BusService owns routing)
- Makes buffer configuration explicit (relates to issue #321)
- Removes stream management complexity from Hassette

### Phase 3: Refactor AppHandler Composition

Extract app lifecycle management into focused services:

**Current AppHandler composition** (complex):
- `_registry`: AppRegistry (tracks loaded apps)
- `_factory`: AppFactory (creates app instances)
- `_lifecycle`: AppLifecycle (start/stop apps, emit events)
- `_change_detector`: AppChangeDetector (detects file changes)

**Refactoring approach**:
AppHandler becomes a facade that coordinates three focused services:

1. **AppRegistry** — app instance tracking, lookup by name/key/index
2. **AppLifecycle** — app initialization, startup, shutdown, event emission
3. **AppChangeDetector** — file monitoring, change detection, reload triggers

**Benefits**:
- Each service testable in isolation
- Clear separation of concerns (registry vs. lifecycle vs. change detection)
- Easier to add features (e.g., app health checks, restart policies)
- Reduces AppHandler from orchestrator+implementation to pure facade

**Implementation location**:
- `src/hassette/core/app_registry.py`
- `src/hassette/core/app_lifecycle_service.py` (rename from `app_lifecycle.py`)
- `src/hassette/core/app_change_detector.py`
- `src/hassette/core/app_handler.py` (becomes facade)

### Post-Refactor Hassette Responsibilities

After all three phases, Hassette will be reduced to:

1. **Lifecycle Coordination** — orchestrate startup/shutdown sequence of child services
2. **Service Container** — expose services via properties (delegates to children)
3. **Configuration Holder** — store and provide access to `HassetteConfig`
4. **Context Management** — set global context variables

**Target size**: ~150-200 lines (down from 439)

**Preserved public API**:
- `.api`, `.states`, `.bus`, `.scheduler` properties (unchanged)
- `.config` property (unchanged)
- `get_instance()` class method (unchanged)
- `get_app()` method (unchanged, delegates to AppHandler)
- `send_event()` method (delegates to EventStreamService)

## Consequences

### Positive

**Immediate testing wins**:
- SessionManager testable without full Hassette instance
- Event stream behavior verifiable in isolation
- AppRegistry, AppLifecycle, AppChangeDetector each independently testable
- **Test harness simplification**: Each extracted service gets simple test fixtures, reducing HassetteHarness complexity
- **Easier test authoring**: New tests don't need full Hassette wiring for isolated components

**Reduced complexity**:
- Hassette drops from 439 lines → ~150-200 lines
- Each service has single, focused responsibility
- Easier onboarding (new developers can understand individual services)

**Better maintainability**:
- Changes to session tracking don't touch Hassette core
- Changes to app lifecycle isolated to AppLifecycle service
- Event stream tuning isolated to EventStreamService

**Architectural clarity**:
- Clear ownership boundaries (session vs. lifecycle vs. event routing)
- Services can be reused in other contexts (CLI tools, scripts)
- Follows Resource/Service patterns already established in codebase

**Future flexibility**:
- AppRegistry could support plugin apps
- EventStreamService could support multiple streams
- SessionManager could add audit trail features

### Negative

**More files to maintain**:
- Adds SessionManager, EventStreamService, AppRegistry, AppLifecycle, AppChangeDetector
- More test files (one per service)
- More documentation to write

**Indirection**:
- `Hassette.session_id` delegates to SessionManager
- `Hassette.send_event()` delegates to EventStreamService
- Property access adds one extra hop

**Migration effort**:
- 5 services need updates for `send_event()` interface change
- Integration tests need updates (40+ tests use real Hassette)
- Test harness requires updates each phase (but gets simpler overall)

**Learning curve**:
- Developers must learn where each responsibility lives
- More services to understand during debugging
- Session tracking no longer in obvious location (Hassette)

### Risks

**Phase 3 complexity**:
- AppHandler refactor is the highest risk (complex interdependencies)
- Registry, Lifecycle, ChangeDetector are tightly coupled today
- **Mitigation**: Incremental extraction, comprehensive tests, careful dependency mapping

**Integration surface**:
- 64 files import Hassette, 20+ access `.config` property
- Public API changes would break many files
- **Mitigation**: Preserve all public APIs (properties, methods) — only internal structure changes

**Test churn**:
- 40+ integration tests expect specific Hassette structure
- Tests accessing private attributes will break
- **Mitigation**: Update tests incrementally per phase, use HassetteHarness pattern

**Event stream coordination**:
- BusService, 5 producers, and EventStreamService must coordinate correctly
- Stream cloning behavior must be preserved
- **Mitigation**: Comprehensive event flow testing before and after Phase 2

**Timing**:
- Three phases is significant work (2-3 weeks estimated)
- Could delay other feature work
- **Mitigation**: Each phase delivers immediate value — can pause between phases if needed

## Alternatives Considered

### Alternative 1: Incremental Extraction (Stop After Phase 2)

Extract SessionManager and EventStreamService, but defer AppHandler refactor until pain justifies effort.

**Rejected because**:
- User explicitly wants AppHandler improved now ("AppHandler is still messy, even after the recent refactor")
- AppHandler complexity is a known pain point (complex composition, hard to test)
- Pre-1.0 is the ideal time for breaking internal changes
- Doing all three phases together maintains momentum and architectural consistency

### Alternative 2: Service Registry Pattern

Replace manual service registration with declarative `ServiceRegistry` that owns child service lifecycle, property access, and configuration.

**Rejected because**:
- Over-engineered for 13 services (registry pays off at 50+ services)
- Adds indirection layer without proportional testing benefit
- High upfront cost (2-3 weeks) for modest long-term gain
- Doesn't address specific pain points (session tracking, event streams, AppHandler)
- Research brief rated this as "over-engineering for current needs"

### Alternative 3: Configuration Dependency Injection

Create service-specific config objects passed via constructor (instead of `self.hassette.config` access).

**Rejected because**:
- Boilerplate heavy (13+ config classes to create)
- Doesn't reduce Hassette's responsibilities (still owns config)
- Services still need `hassette` reference for other reasons (send_event, wait_for_ready)
- Partial solution that doesn't address core god object problem
- Can be done later if config coupling becomes a bottleneck

### Alternative 4: Do Nothing

Code works, tests pass, no bugs reported. Leave Hassette as-is.

**Rejected because**:
- Testing complexity is already painful (user-reported pain point)
- 34 commits in 6 months shows ongoing churn
- 243 lines added in 3 days (session tracking) shows accelerating growth
- Pre-1.0 is the best time to establish good patterns
- Future features will only worsen the god object problem

## Implementation Plan

### Phase 1: Extract SessionManager (Week 1)

**Day 1-2: Create SessionManager**
1. Create `src/hassette/core/session_manager.py`
2. Define `SessionManager(Service)` class
3. Move 4 methods from Hassette → SessionManager
4. Add `DatabaseService` as child dependency
5. Expose `session_id` property

**Day 3: Update Hassette**
1. Register SessionManager as child in `Hassette.__init__()`
2. Delegate `session_id` property to `_session_manager.session_id`
3. Replace session method calls with `_session_manager.method()` calls
4. Remove 235 lines of session logic from Hassette

**Day 4-5: Tests and Test Fixtures**
1. Create `tests/integration/test_session_manager.py`
2. Move session lifecycle tests from `test_core.py`
3. Add new tests for session isolation
4. **Create test fixture: `create_session_manager(db_service)` helper in `conftest.py`**
5. **Update HassetteHarness to optionally include SessionManager**
6. Update Hassette tests to mock SessionManager
7. Verify all 86 tests still pass (`uv run pytest -n auto`)

**Deliverables**:
- SessionManager service (~235 lines removed from Hassette)
- Simple test fixture for SessionManager (no full Hassette needed)
- Tests demonstrate simpler testing pattern

---

### Phase 2: Extract EventStreamService (Week 2)

**Day 1-2: Create EventStreamService**
1. Create `src/hassette/core/event_stream_service.py`
2. Define `EventStreamService(Service)` class
3. Move stream creation, `send_event()`, closing logic from Hassette
4. Abstract `send_event()` behind clean interface
5. Add `event_streams_closed` property

**Day 3: Update BusService and Producers**
1. BusService receives stream via constructor (not clone)
2. Update 5 producer services to use EventStreamService interface:
   - WebsocketService, AppHandler, FileWatcherService, ServiceWatcher, AppLifecycle
3. Update Hassette to delegate `send_event()` to EventStreamService

**Day 4-5: Tests and Test Fixtures**
1. Create `tests/integration/test_event_stream_service.py`
2. Test stream lifecycle, send_event(), closing behavior
3. Test producer integration (5 services)
4. Test BusService integration (stream handoff)
5. **Create test fixture: `create_event_stream_service(buffer_size=1000)` helper**
6. **Update HassetteHarness to reflect simpler event stream wiring**
7. End-to-end event flow verification
8. Verify all 86 tests still pass

**Deliverables**:
- EventStreamService with clean event stream abstraction
- Simple test fixture for event stream testing
- Updated HassetteHarness with reduced event stream complexity

---

### Phase 3: Refactor AppHandler (Week 3)

**Day 1-2: Extract AppRegistry**
1. Create `src/hassette/core/app_registry.py`
2. Move app instance tracking from AppHandler._registry
3. Methods: `register()`, `unregister()`, `get_all()`, `get_by_key()`, `get_by_name()`
4. Tests: `tests/unit/test_app_registry.py`

**Day 3: Extract AppLifecycle**
1. Rename `app_lifecycle.py` → `app_lifecycle_service.py`
2. Move lifecycle logic from AppHandler._lifecycle
3. Depends on AppRegistry for instance lookup
4. Methods: `start_app()`, `stop_app()`, `reload_app()`, emit events
5. Tests: `tests/integration/test_app_lifecycle_service.py`

**Day 4: Extract AppChangeDetector**
1. Create `src/hassette/core/app_change_detector.py`
2. Move change detection from AppHandler._change_detector
3. Depends on AppRegistry for app file lookup
4. Methods: `detect_changes()`, `get_changed_apps()`
5. Tests: `tests/unit/test_app_change_detector.py`

**Day 5: Refactor AppHandler to Facade and Update Test Harness**
1. AppHandler becomes coordinator of 3 services
2. Public API preserved (`get_app()`, `apps` property, lifecycle methods)
3. **Create test fixtures: `create_app_registry()`, `create_app_lifecycle()`, `create_app_change_detector()` helpers**
4. **Significantly simplify HassetteHarness** (AppHandler is simpler, fewer dependencies to track)
5. Update integration tests to use simpler test patterns
6. Verify all 86 tests still pass
7. Verify web routes still work (7 routes use `get_app()`)

**Deliverables**:
- Focused services for app management (AppRegistry, AppLifecycle, AppChangeDetector)
- AppHandler as clean facade
- Test fixtures for each service (testable without AppHandler or Hassette)
- **Significantly simplified HassetteHarness** (clearer builder, fewer dependencies)

---

### Verification After Each Phase

After completing each phase:
1. Run full test suite: `uv run pytest -n auto`
2. Run type checking: `uv run pyright`
3. Run linting: `uv run ruff check`
4. Manual smoke test: Start Hassette, load an app, verify events flow
5. Check test coverage: `uv run pytest --cov=src/hassette/core --cov-report=term-missing`

### Success Criteria

**Phase 1 Success**:
- [ ] SessionManager service exists and is tested independently
- [ ] Hassette reduced by ~235 lines
- [ ] All 86 tests pass
- [ ] Session tracking works identically to before
- [ ] **Test fixture `create_session_manager()` exists and is used in tests**
- [ ] **Tests demonstrate session logic testable without full Hassette**

**Phase 2 Success**:
- [ ] EventStreamService exists and is tested independently
- [ ] 5 producer services use new interface
- [ ] BusService receives stream via constructor
- [ ] All 86 tests pass
- [ ] Event flow works end-to-end
- [ ] **Test fixture `create_event_stream_service()` exists**
- [ ] **HassetteHarness updated to reflect simpler event stream wiring**

**Phase 3 Success**:
- [ ] AppRegistry, AppLifecycle, AppChangeDetector exist and are tested independently
- [ ] AppHandler is a facade (delegates to 3 services)
- [ ] Public API unchanged (`.get_app()`, `.apps` work identically)
- [ ] All 86 tests pass
- [ ] Web routes still work (7 routes inject Hassette, call `get_app()`)
- [ ] **Test fixtures for AppRegistry, AppLifecycle, AppChangeDetector exist**
- [ ] **HassetteHarness significantly simplified** (fewer dependencies, clearer builder)

**Overall Success**:
- [ ] Hassette reduced from 439 lines → ~150-200 lines
- [ ] 4+ new services with focused responsibilities
- [ ] All public APIs preserved (no breaking changes for users)
- [ ] Integration tests updated to work with new structure
- [ ] **Test harness significantly simpler** — each service has focused test fixtures
- [ ] **New tests demonstrate easier testing patterns** (no full Hassette needed for isolated components)
- [ ] Documentation updated (docstrings, architecture docs, testing patterns)

## References

- **Audit findings**: Codebase audit (2026-02-26) identified god object pattern
- **Research brief**: `design/research/2026-02-26-hassette-refactoring/research.md` — comprehensive analysis of 4 refactoring options
- **Blast radius analysis**: 64 files depend on Hassette, 86 test files
- **Recent session migration**: Commit #312 (Feb 26) — precedent for correct ownership principle
- **Resource/Service pattern**: `src/hassette/resources/base.py` — foundation for new services
- **AppHandler complexity**: Recent refactor acknowledged complexity, user wants continued improvement
