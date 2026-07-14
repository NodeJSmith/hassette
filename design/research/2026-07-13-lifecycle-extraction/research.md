---
proposal: "Extract framework-internal lifecycle methods from App's inherited API surface into module-level functions, sweeping all names app authors should never call."
date: 2026-07-13
status: Draft
flexibility: Leaning
motivation: "API freeze prep — cleaning the public surface before locking it down for 1.0 stability guarantees"
constraints: "Must not break polymorphic dispatch for overridden methods (initialize, shutdown, cleanup). Must not silently break spy-by-reassignment test patterns."
non-goals: "Restructuring Resource itself, unifying Service's duplicated initialize/shutdown, changing property-based names"
depth: normal
---

# Research Brief: Extract Framework-Internal Names from App's Public Surface

**Initiated by**: Issue to extract sequence-unsafe lifecycle machinery out of App's inherited API surface, expanded to a full sweep of all inherited names that don't belong on the app-author surface.

## Context

### What prompted this

API freeze prep for 1.0. App currently inherits ~45 public names from Resource and LifecycleMixin. Of those, only ~15 are genuinely part of the app-author API. The remaining ~30 are framework plumbing — lifecycle state machines, child-resource wiring, readiness signaling, task bucket registration — that app authors should never call. Exposing them pollutes IDE autocomplete, creates a false impression of a stable API surface, and risks app authors calling sequence-unsafe methods that corrupt lifecycle state.

### Current state

**Inheritance chain:**
```
App → Resource → LifecycleMixin → object
         ↑
    FinalMeta (metaclass, enforces @final)
```

`resources/__init__.py` is empty. No module-level function pattern exists anywhere in the `resources/` package today. The codebase does use module-level utility functions elsewhere (e.g., `wait_for_ready` in `utils/service_utils.py`).

`FinalMeta` enforces `@final` at class-creation time. `Service` and `Hassette` are the only two classes whitelisted to override `initialize`/`shutdown`. No `__dir__` or `__all__` override exists anywhere in the chain — the framework relies entirely on underscore-prefix convention plus `@final` to signal intent.

**Complete name inventory:**

The table below lists every public name App inherits, its source, and its category. "App-author API" means an app author legitimately uses it in `on_initialize`/`on_shutdown`/handler code. "Framework-internal" means only framework machinery (AppLifecycleService, Resource.initialize, Service._serve_wrapper, etc.) calls it. "Ambiguous" means the name has legitimate advanced uses but is primarily framework plumbing.

| Name | Kind | Source | Category |
|------|------|--------|----------|
| `logger` | attr | Resource | App-author API |
| `api` | attr | App | App-author API |
| `scheduler` | attr | App | App-author API |
| `bus` | attr | App | App-author API |
| `states` | attr | App | App-author API |
| `app_config` | attr | App | App-author API |
| `instance_name` | property | App (overrides Resource) | App-author API |
| `now()` | method | App | App-author API |
| `on_initialize()` | hook | Resource | App-author API |
| `on_shutdown()` | hook | Resource | App-author API |
| `before_initialize()` | hook | Resource | App-author API |
| `after_initialize()` | hook | Resource | App-author API |
| `before_shutdown()` | hook | Resource | App-author API |
| `after_shutdown()` | hook | Resource | App-author API |
| `task_bucket` | attr | Resource | App-author API (used by AppSync dispatch) |
| `cache` | cached_property | Resource | App-author API (disk cache for app data) |
| `unique_name` | property | App (overrides Resource) | App-author API |
| `index` | attr | App | App-author API |
| `handle_failed()` | method | LifecycleMixin | **Framework-internal** |
| `handle_crash()` | method | LifecycleMixin | **Framework-internal** |
| `handle_stop()` | method | LifecycleMixin | **Framework-internal** |
| `handle_starting()` | method | LifecycleMixin | **Framework-internal** |
| `handle_running()` | method | LifecycleMixin | **Framework-internal** |
| `create_service_status_event()` | method | LifecycleMixin | **Framework-internal** |
| `mark_ready()` | method | LifecycleMixin | **Framework-internal** |
| `mark_not_ready()` | method | LifecycleMixin | **Framework-internal** |
| `request_shutdown()` | method | LifecycleMixin | **Framework-internal** |
| `start()` | method | LifecycleMixin | **Framework-internal** |
| `cancel()` | method | LifecycleMixin | **Framework-internal** |
| `register_task_bucket_factory()` | classmethod | Resource | **Framework-internal** |
| `add_child()` | method | Resource | **Framework-internal** |
| `start_children_and_wait()` | method | Resource | **Framework-internal** |
| `initialize()` | @final method | Resource | **Framework-internal** (polymorphic) |
| `shutdown()` | @final method | Resource | **Framework-internal** (polymorphic) |
| `cleanup()` | @final method | App (overrides Resource) | **Framework-internal** (polymorphic) |
| `restart()` | method | Resource | **Framework-internal** |
| `status` | property+setter | LifecycleMixin | Ambiguous (read by advanced apps, set only by framework) |
| `hassette` | attr | Resource | Ambiguous (direct access to framework singleton) |
| `parent` | attr | Resource | Ambiguous |
| `children` | attr | Resource | Ambiguous |
| `ready_event` | attr | LifecycleMixin | Ambiguous |
| `shutdown_event` | attr | LifecycleMixin | Ambiguous |
| `is_ready()` | method | LifecycleMixin | Ambiguous |
| `wait_ready()` | method | LifecycleMixin | Ambiguous |
| `role` | ClassVar | App (overrides Resource) | Framework-internal |
| `source_tier` | ClassVar | App (overrides Resource) | Framework-internal |
| `depends_on` | ClassVar | Resource | Framework-internal (raises on App) |
| `class_name` | ClassVar | Resource | Framework-internal |
| `unique_id` | attr | Resource | Framework-internal |
| `owner_id` | property | Resource | Framework-internal |
| `config_log_level` | property | App (overrides Resource) | Framework-internal |
| `app_key` | property | App (overrides Resource) | Framework-internal |
| `app_manifest` | attr | App | Framework-internal |
| `app_config_cls` | ClassVar | App | Framework-internal |
| `shutting_down` | class attr | Resource | Framework-internal |
| `initializing` | class attr | Resource | Framework-internal |
| `shutdown_completed` | class attr | LifecycleMixin | Framework-internal |
| `is_task_bucket` | ClassVar | Resource | Framework-internal |
| `task` | property | LifecycleMixin | Framework-internal |

**Count:** ~18 app-author API, ~30 framework-internal, ~6 ambiguous.

### Key constraints

1. **Polymorphic methods cannot be extracted.** `initialize`, `shutdown`, and `cleanup` are overridden by Service, Hassette, WebsocketService, DatabaseService, and App itself. They must remain as methods on Resource for `super()` dispatch to work.
2. **Properties are a different construct.** `unique_name`, `app_key`, `instance_name`, `config_log_level` are overridden as properties by App and/or Hassette. Converting properties to module-level functions changes call-site syntax (`resource.unique_name` to `unique_name(resource)`) pervasively and breaks subclass override semantics. These are best handled separately from method extraction.
3. **Spy-by-reassignment test pattern.** ~8 test files intercept framework-internal methods by overwriting instance attributes (`instance.mark_ready = Mock()`). If internal framework call sites switch from `self.mark_ready()` to a free-function call `mark_ready(self)`, these monkeypatches silently stop intercepting. This is the single biggest structural risk in the change.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| New module (`resources/lifecycle.py` or similar) | 1 new file | Low | Low — new code, no conflicts |
| LifecycleMixin method bodies → module functions | 1 file (mixins.py) | Medium | Low — move + signature change |
| Resource method bodies → module functions | 1 file (base.py) | Medium | Low — move + signature change |
| Framework call sites (`self.method()` → `method(self)`) | ~15 files in src/ | Medium | Medium — must not miss any |
| Test call sites (direct calls) | ~35 files | Medium | Low — mechanical rename |
| Test spy-by-reassignment patterns | ~8 files | Medium | **High** — structural redesign needed |
| `test_forgotten_await_completeness.py` exclusion set | 1 file | Low | Low — update string set |
| `test_service_lifecycle.py` FinalMeta guard tests | 1 file | Low | Low — remove or adapt |
| `__dir__` override on App | 1 file (app.py) | Low | Low |

### What already supports this

1. **`_LifecycleHostP` Protocol.** LifecycleMixin already uses a `TYPE_CHECKING`-only Protocol that types `self` as "any object with `logger`, `hassette`, `role`, `class_name`, `unique_name`, `task_bucket`, `create_service_status_event`, `initialize`." This means the codebase already treats the mixin's `self` as "an object satisfying an interface" — a `def handle_failed(resource: _LifecycleHostP, exc)` function fits that existing convention naturally.
2. **Existing module-level utility pattern.** `wait_for_ready()` in `utils/service_utils.py` is already a module-level function that operates on Resource instances. The extraction follows an established pattern.
3. **`INHERITED_LIFECYCLE_EXCLUSIONS` in test_forgotten_await_completeness.py.** This set already enumerates the exact methods that are inherited-but-not-app-author-API: `handle_crash`, `handle_failed`, `handle_running`, `handle_starting`, `handle_stop`, `initialize`, `shutdown`, `cleanup`, `restart`, `start_children_and_wait`, `wait_ready`, plus the lifecycle hooks. This is a ready-made source of truth for which names to sweep.
4. **No override of any `handle_*` method.** All five `handle_*` methods and `create_service_status_event` are defined exactly once (in `LifecycleMixin`) and never overridden anywhere in the codebase. Same for `mark_ready`, `mark_not_ready`, `request_shutdown`, `is_ready`, `wait_ready`, `add_child`, `start_children_and_wait`, `start`, `cancel`, `restart`. These are all clean, single-implementation extractions with no polymorphic complications.
5. **All external calls on App instances come from exactly two places.** `AppLifecycleService` (production lifecycle driver) and `AppTestHarness`/test-utils. No example app, doc snippet, or user-facing module ever calls these methods on an App instance.

### What works against this

1. **Spy-by-reassignment test pattern.** ~8 test files monkeypatch instance methods (`inst.mark_ready = Mock()`) to intercept internal framework calls. These silently break if the framework switches to free-function calls, because the monkeypatch overwrites the instance attribute but the free function doesn't read the instance attribute — it calls the function directly. Each of these tests needs to be redesigned to mock the module-level function instead (`patch("hassette.resources.lifecycle.mark_ready")`).
2. **`resources/__init__.py` is empty.** No existing module-level function pattern in this package. The extraction introduces a new convention.
3. **Cross-call ordering.** Several candidates call other candidates internally. `handle_failed` calls `mark_not_ready` and `create_service_status_event`. `request_shutdown` calls `mark_not_ready`. Extraction must proceed leaves-first: extract `mark_not_ready` and `create_service_status_event` before `handle_failed`, etc.
4. **`_run_hooks` calls `self.handle_failed()`.** This private method in Resource calls `handle_failed` via `self.` dispatch. If `handle_failed` is extracted, `_run_hooks` must call the free function instead — but `_run_hooks` is itself not overridden, so this is safe.

## Options Evaluated

### Option A: Extract to module-level functions + `__dir__` on App (recommended)

**How it works:**

Create a new module `src/hassette/resources/lifecycle.py` containing module-level functions for all non-polymorphic framework-internal methods. Each function takes the resource as its first parameter, typed against `_LifecycleHostP` (or a refined Protocol). The original methods on LifecycleMixin and Resource are deleted entirely — no thin delegating stubs.

All framework call sites in `src/` that currently call `self.handle_failed(exc)` change to `handle_failed(self, exc)`. All external call sites (AppLifecycleService calling `inst.mark_ready()`) change to `mark_ready(inst)`.

Add `__dir__` to App that returns only app-author API names. This cleans IDE autocomplete for the remaining inherited names that can't be extracted (polymorphic methods, properties, attributes).

For polymorphic methods (`initialize`, `shutdown`, `cleanup`) and properties (`status`, `unique_name`, etc.): leave on the class but exclude from App's `__dir__`. They remain callable but invisible in autocomplete.

**Extraction inventory (17 methods):**

*From LifecycleMixin (11):*
- `handle_failed(resource, exception)`
- `handle_crash(resource, exception)`
- `handle_stop(resource)`
- `handle_starting(resource)`
- `handle_running(resource)`
- `create_service_status_event(resource, status, exception, ready, ready_phase)`
- `mark_ready(resource, reason)`
- `mark_not_ready(resource, reason)`
- `request_shutdown(resource, reason)`
- `start(resource)`
- `cancel(resource)`

*From Resource (6):*
- `add_child(resource, child_class, **kwargs)`
- `start_children_and_wait(resource, timeout)`
- `restart(resource)`
- `register_task_bucket_factory(factory)` (classmethod → module function)
- `_run_hooks(resource, hooks, continue_on_error)` (private, but moves with its caller chain)
- `_ordered_children_for_shutdown(resource)`

**Methods that stay on the class (not extracted):**

| Method | Reason |
|--------|--------|
| `initialize()` | @final, overridden by Service and Hassette (FinalMeta-whitelisted). Polymorphic dispatch required. |
| `shutdown()` | @final, overridden by Service and Hassette. Polymorphic dispatch required. |
| `cleanup()` | Overridden by App, WebsocketService, DatabaseService. `super()` chain. |
| `_force_terminal()` | Overridden by Service. `super()` chain. |
| `_shutdown_children()` | Overridden by Hassette (full replacement, not additive). |
| `_on_children_stopped()` | Overridden by Hassette (additive `super()` + custom logic). |
| `_finalize_shutdown()` | Calls `_shutdown_children` and `_on_children_stopped` via `self.` — must preserve polymorphic dispatch. |
| `_auto_wait_dependencies()` | Branches on `self.role == ResourceRole.APP` — App-specific special case in Resource. Could extract but ties to dependency checking; lower value. |
| All properties | Different construct; override semantics differ from methods. Separate effort. |
| All lifecycle hooks | `on_initialize`, `on_shutdown`, `before_*`, `after_*` are the app-author API. Stay. |

**Names hidden by `__dir__` (not extracted, but removed from autocomplete):**

`initialize`, `shutdown`, `cleanup`, `restart`, `status` (setter), `hassette`, `parent`, `children`, `ready_event`, `shutdown_event`, `role`, `source_tier`, `depends_on`, `class_name`, `unique_id`, `owner_id`, `config_log_level`, `app_key`, `app_manifest`, `app_config_cls`, `shutting_down`, `initializing`, `shutdown_completed`, `is_task_bucket`, `task`, `is_ready`, `wait_ready`.

**Pros:**
- Truly removes 17 methods from the class. They no longer exist on `Resource`/`LifecycleMixin` and thus cannot be called on an App instance at all (not just hidden — gone).
- `__dir__` handles the remaining ~25 names that can't be extracted (polymorphic, properties, attributes), cleaning IDE autocomplete completely.
- Follows functions-over-methods convention from coding-style.md.
- The `_LifecycleHostP` Protocol already provides the type signature for the first parameter.
- Module-level functions are easier to test in isolation (no need to construct a full Resource to test `create_service_status_event`).

**Cons:**
- ~8 spy-by-reassignment tests need structural redesign (switch to `patch("hassette.resources.lifecycle.mark_ready")`). This is the biggest cost.
- ~35 test files need mechanical call-site updates (`resource.handle_failed(exc)` to `handle_failed(resource, exc)`).
- Introduces a new convention in `resources/` (module-level functions where there were none).
- Cross-call ordering requires careful sequencing during implementation: extract leaves first, then callers.

**Effort estimate:** Medium. The extraction itself is mechanical for each method. The test updates are high-volume but mostly find-and-replace. The ~8 spy tests need thought. Estimated 2-3 focused sessions.

**Dependencies:** None. Pure refactor of existing code.

### Option B: `__dir__` override only (do less)

**How it works:**

Add a `__dir__` override to App that returns only app-author API names. No methods are moved, extracted, or renamed. Optionally add a `__getattr__` that emits a `DeprecationWarning` when framework-internal names are accessed on an App instance (to catch app authors who discover them via other means).

**Pros:**
- Near-zero risk. No method signatures change. No call sites change. No tests change.
- Immediate effect on IDE autocomplete — app authors stop seeing `handle_failed` and friends.
- Can ship in a single commit, trivially reviewable.
- Does not preclude Option A later — this is a valid first step.

**Cons:**
- Names still technically exist on the class and are callable. `app.handle_failed(exc)` still works at runtime.
- `hasattr(app, "handle_failed")` still returns True.
- Does not follow functions-over-methods convention.
- Does not reduce the actual API surface for stability guarantees — any code calling these methods today continues to work after a `__dir__`-only change, so the 1.0 API freeze would need to explicitly document "these methods exist but are not part of the stable API" rather than removing them outright.
- A `DeprecationWarning` on `__getattr__` is tricky to implement correctly because `__getattr__` only fires on attribute lookup failure (after `__getattribute__`), and inherited methods resolve via `__getattribute__`, not `__getattr__`. Achieving runtime access warnings requires `__getattribute__` override, which has performance implications on every attribute access.

**Effort estimate:** Small. One file changed (app.py), no test changes.

**Dependencies:** None.

## Concerns

### Technical risks

- **Silent spy breakage (Option A).** The ~8 tests that do `instance.mark_ready = Mock()` will silently stop intercepting if the production code switches to `mark_ready(instance)`. The mock gets installed but never called — assertions pass vacuously if they're `assert_called` (they won't be called, so `assert_called` fails, which is *detectable*). The real risk is tests that stub to *prevent* a side effect (`svc.mark_ready = MagicMock()` to avoid setting `ready_event`) — those stop preventing the side effect, and the test may still pass by coincidence but is no longer testing what it claims. Each of the 8 tests needs manual inspection to determine the failure mode.

- **`_run_hooks` internal dispatch.** `Resource._run_hooks` catches exceptions from lifecycle hooks and calls `self.handle_failed(exc)`. If `handle_failed` is extracted, `_run_hooks` must call the free function. Since `_run_hooks` is itself a candidate for extraction and is not overridden, this is safe — but the two must be extracted together or `_run_hooks` first, then `handle_failed`.

- **`App.__init__` calls `self.add_child()`.** App's constructor uses `add_child` to wire `api`, `scheduler`, `bus`, `states`. If `add_child` becomes a module function, this changes to `add_child(self, Api)` inside `__init__`. This is mechanical but unusual-looking — a constructor calling a module function on itself. The alternative is leaving `add_child` on the class and hiding it via `__dir__`, since App's `__init__` is the one legitimate use of `add_child` "by" an App instance (even though it's framework construction code, not app-author code).

### Complexity risks

- **New module convention.** `resources/lifecycle.py` introduces module-level functions into a package that currently has none. Future contributors need to understand that lifecycle operations are functions, not methods, which is a departure from the method-on-self pattern used everywhere else in `resources/`.

- **Two calling conventions.** After extraction, some operations on a Resource are methods (`resource.initialize()`) and some are functions (`handle_failed(resource, exc)`). The split follows the rule "polymorphic = method, non-polymorphic = function" but this rule must be discoverable by contributors.

### Maintenance risks

- **Keeping `__dir__` in sync.** The `__dir__` override on App needs to be updated when new app-author API is added. Forgetting to add a new method to `__dir__` means it's invisible to app authors. A test can enforce this (assert `dir(App(...))` matches an allowlist).

## Open Questions

- [ ] **Should `add_child` stay on Resource?** App's `__init__` calls `self.add_child()` for legitimate construction-time wiring. Extracting it makes the constructor read oddly. Alternatively, leave it as a method and hide via `__dir__` since no app author should ever call it post-construction.
- [ ] **Where do the functions live?** `resources/lifecycle.py` groups the lifecycle state-machine functions. But `add_child`, `start_children_and_wait`, and `restart` are structural, not lifecycle. Should there be two modules (`lifecycle.py` for state transitions, `operations.py` for structural operations), or one catch-all?
- [ ] **Should `is_ready` and `wait_ready` be extracted or kept as ambiguous-but-hidden?** An app author *might* legitimately want to check if a sibling resource is ready. If so, these belong in the app-author API. If not, they should be extracted.
- [ ] **Should `status` (read-only) be in App's `__dir__`?** App authors can legitimately read `self.status` to check their own lifecycle state. The *setter* is framework-internal, but the getter is arguably useful. The `__dir__` could include `status` while the docs mark the setter as internal.

## Recommendation

**Option A (extract + `__dir__`)** is the right approach for an API freeze. A `__dir__`-only change (Option B) hides names from autocomplete but doesn't actually remove them — any app author who discovers `app.handle_failed()` through documentation, source reading, or `hasattr` can still call it, and the 1.0 stability guarantee would need to carve out these "hidden but present" methods. Extraction makes the guarantee structural: the methods don't exist on the class, so there's nothing to stabilize.

The spy-by-reassignment test breakage (the main risk) is detectable and contained — the 8 affected tests are identifiable from this brief, and the fix pattern is consistent (`patch` the module-level function instead of monkeypatching the instance attribute). The effort is proportional to the value: a clean API surface is worth 2-3 sessions of mechanical updates plus 8 test redesigns.

**Confidence:** Direct for the name inventory and call-site mapping (read from source). Direct for extraction feasibility of non-overridden methods (verified by grep). Inferred for test breakage patterns — the failure modes (silent spy bypass) are consistent with how Python attribute resolution works, but each of the 8 tests needs individual inspection to confirm the specific failure mode.

### Suggested next steps

1. **Write a design doc via /mine-define** covering the extraction inventory, module structure, `__dir__` allowlist, and the 8 spy tests that need redesign. Resolve the open questions (especially `add_child` placement and `is_ready`/`wait_ready` categorization).
2. **Implement in two phases:** First commit: `__dir__` override on App (immediate surface cleanup, zero risk, independently landable). Second series: extract methods to module-level functions, update call sites, redesign spy tests.
3. **Add a `__dir__` allowlist test** that asserts `set(dir(app_instance))` matches the declared app-author API. This catches future regressions where a new method on Resource leaks into App's surface without being explicitly categorized.
