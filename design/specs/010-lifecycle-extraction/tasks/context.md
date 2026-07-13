# Context: Extract Framework-Internal Names from App's Public Surface

## Problem & Motivation

App inherits ~54 public names from Resource and LifecycleMixin, but only ~20 are app-author API. The remaining ~34 are framework plumbing — lifecycle state machines, child-resource wiring, readiness signaling, task bucket registration. These names appear in IDE autocomplete, create a false impression of stable API surface, and risk app authors calling sequence-unsafe methods that corrupt lifecycle state. Before the 1.0 API freeze, the public surface must reflect only what app authors should use. This extraction removes 16 non-polymorphic methods entirely and hides the rest via `__dir__`.

## Visual Artifacts

None.

## Key Decisions

1. **Two new modules** — `resources/lifecycle.py` for 11 lifecycle state-transition functions, `resources/operations.py` for 5 structural-operation functions. Separation follows the conceptual divide between state management and resource structure.
2. **`add_child` stays as a method** on Resource (hidden via `__dir__`) because `App.__init__` calls `self.add_child()` 4 times and extracting it makes the constructor read oddly.
3. **`is_ready` and `wait_ready` are app-author visible** — legitimate advanced use cases for checking readiness.
4. **`hassette`, `status`, `parent`, `children`, `ready_event`, `shutdown_event` are hidden** — framework plumbing, not app-author API.
5. **No compatibility shims** — methods deleted entirely from classes, all call sites migrated in one wave. No thin delegating stubs.
6. **`_LifecycleHostP` Protocol updated** — `create_service_status_event` removed from Protocol requirements since the free function accesses resource attributes directly.
7. **Underscore-prefixed methods drop the prefix** when becoming module-level functions — `_run_hooks` → `run_hooks`, `_ordered_children_for_shutdown` → `ordered_children_for_shutdown`.

## Constraints & Anti-Patterns

- Do NOT leave thin delegating stubs on the classes. Methods are deleted entirely; all call sites migrate.
- Do NOT modify `_LifecycleHostP` Protocol beyond removing `create_service_status_event`.
- Do NOT extract polymorphic methods (`initialize`, `shutdown`, `cleanup`, `_force_terminal`, `_shutdown_children`, `_on_children_stopped`, `_finalize_shutdown`).
- Do NOT extract properties (`unique_name`, `app_key`, `instance_name`, `config_log_level`, `status`, `owner_id`, `task`).
- Do NOT change the `FinalMeta` metaclass or `@final` enforcement.
- Spy-by-reassignment test patterns (`instance.method = Mock()`) silently break when methods become module-level functions. Each spy test must be redesigned to `patch("hassette.resources.lifecycle.func")`.
- `mark_ready`, `mark_not_ready`, and `request_shutdown` signatures use `reason: str | None = None`, not `str = ""`.
- `handle_crash` takes `Exception`, not `BaseException`.

## Execution Risks

### `start`/`cancel` name collision (T03, T04)

`start` and `cancel` are generic names. `LifecycleMixin.start()` manages `_init_task`, but `start` and `cancel` also exist on `asyncio.Task`, `Subscription`, and other types. Grepping for `self.start(` or `self.cancel(` matches all of them. The executor MUST disambiguate — only migrate calls on `Resource`/`Service` instances, not `task.cancel()` or `subscription.cancel()`. The AC#7 grep (`\.start\s*=.*Mock`) has the same false-positive risk for `Subscription.cancel` and `task.cancel` — filter those explicitly.

### Spy test count may be incomplete (T04)

The spy-by-reassignment file list drifted three times during planning (8 → 9 → 14). The current 14-file list may still miss files. Before committing T04, run the AC#7 grep early and triage EVERY hit — don't assume the target file list is exhaustive.

### Dead-code window hides migration misses (T05 → T06)

After T03 migrates `src/` call sites but before T06 deletes old methods, both paths work — a test calling `resource.handle_failed(exc)` still passes because the old method exists. If T05 misses a file, nobody notices until T06 deletes the methods and the test fails. The T06 executor MUST run the full test suite after deletion. If context compacts between T05 and T06, the T06 executor should re-run the AC#7 grep to verify no old-style calls survive in `tests/`.

## Design Doc References

- `## Architecture` — module structure, `__dir__` on App, Protocol update, call-site migration patterns, test spy migration patterns
- `## Functional Requirements` — FR#1-FR#8 covering extraction, `__dir__`, call-site migration, Protocol update, allowlist test, spy test redesign
- `## Acceptance Criteria` — AC#1-AC#7 covering dir() output, imports, hasattr, test suite, linter, grep verification
- `## Impact → Changed Files` — 35 src/ files, 14 spy test files, ~41 mechanical test files
- `## Test Strategy` — 14 spy-by-reassignment files (table with file:pattern:fix), ~35 mechanical rename files, 3 new test areas
- `## Replacement Targets` — 5 replacement categories with actions
- `## Key Constraints` — extract leaves first ordering, no compatibility shims

## Convention Examples

### Module-level utility operating on Resource instances

**Source:** `src/hassette/utils/service_utils.py`

```python
async def wait_for_ready(
    resources: "list[Resource] | Resource",
    timeout: float = 20,
    shutdown_event: asyncio.Event | None = None,
) -> bool:
    """Block until all dependent resources are ready or shutdown is requested."""
    resources = resources if isinstance(resources, list) else [resources]
    if not resources:
        return True
    # ...
```

### Protocol-typed self for lifecycle hosts

**Source:** `src/hassette/resources/mixins.py`

```python
class _LifecycleHostP(typing.Protocol):
    logger: logging.Logger
    hassette: "Hassette"
    role: ResourceRole
    class_name: str
    unique_name: str
    task_bucket: "TaskBucket"
    async def initialize(self, *args: Any, **kwargs: Any) -> None: ...
```

### Framework lifecycle orchestration call pattern

**Source:** `src/hassette/core/app_lifecycle_service.py`

```python
with anyio.fail_after(self.startup_timeout):
    await inst.initialize()
    inst.mark_ready(reason="initialized")
await self.emit_app_state_change(inst, status=RUNNING, previous_status=STARTING)
```

### Explicit public API via `__all__`

**Source:** `src/hassette/app/__init__.py`

```python
__all__ = [
    "App",
    "AppConfig",
    "AppSync",
    "BlockingIOBehavior",
    "ForgottenAwaitBehavior",
    "only_app",
]
```
