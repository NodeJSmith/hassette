---
task_id: "T02"
title: "Add App __dir__ override and allowlist test"
status: "done"
depends_on: []
implements: ["FR#8", "FR#3", "FR#6", "AC#1"]
---

## Summary

Add a `__dir__` override to App that returns only the app-author API names. Add a `_APP_PUBLIC_API` frozenset constant. Create a test file that asserts `dir(app_instance)` matches the allowlist and verifies extracted methods are not accessible via `hasattr`. This is independently landable — `__dir__` hides names from autocomplete regardless of whether extraction has happened yet.

## Target Files

- modify: `src/hassette/app/app.py`
- create: `tests/unit/app/test_app_dir.py`
- read: `src/hassette/resources/mixins.py`
- read: `src/hassette/resources/base.py`

## Prompt

In `src/hassette/app/app.py`, add a module-level constant and a `__dir__` method to the `App` class:

```python
_APP_PUBLIC_API: frozenset[str] = frozenset({
    "logger", "api", "scheduler", "bus", "states", "app_config",
    "instance_name", "unique_name", "index", "now",
    "on_initialize", "on_shutdown",
    "before_initialize", "after_initialize",
    "before_shutdown", "after_shutdown",
    "task_bucket", "cache",
    "is_ready", "wait_ready",
})
```

Add to the `App` class body:

```python
def __dir__(self) -> list[str]:
    return sorted(_APP_PUBLIC_API)
```

`AppSync` (also in `app.py`, subclasses `App`) must override `__dir__` to include its 6 sync hooks:

```python
_APPSYNC_HOOKS: frozenset[str] = frozenset({
    "before_initialize_sync", "on_initialize_sync", "after_initialize_sync",
    "before_shutdown_sync", "on_shutdown_sync", "after_shutdown_sync",
})
```

Add to the `AppSync` class body:

```python
def __dir__(self) -> list[str]:
    return sorted(_APP_PUBLIC_API | _APPSYNC_HOOKS)
```

Create `tests/unit/app/test_app_dir.py` with tests:

1. **App allowlist test** — construct an App instance and assert `set(dir(app_instance)) == _APP_PUBLIC_API`. Import `_APP_PUBLIC_API` from `hassette.app.app`.

2. **AppSync allowlist test** — construct an AppSync instance and assert `set(dir(appsync_instance)) == _APP_PUBLIC_API | _APPSYNC_HOOKS`.

3. **Regression guard** — assert the App allowlist has exactly 20 names and AppSync has exactly 26.

The `hasattr` test for extracted methods (AC#4) belongs in T06 after methods are deleted — `hasattr` still returns True while methods exist on the class.

## Focus

- `App.__init__` is at `app.py:94-115`. The `__dir__` method should be placed after `__init__`.
- `_APP_PUBLIC_API` should be a module-level constant, placed above the `App` class definition (follows coding-style.md "Constants at the Top" rule).
- The `tests/unit/app/` directory may need to be created. Check if it exists; create `__init__.py` if needed.
- Use `make_mock_hassette()` from `hassette.test_utils` to construct the App for testing — see test-conventions.md for the import path.

## Verify

- [ ] FR#8: `add_child` remains a method on Resource but is excluded from `dir(app_instance)`. Verify: `pytest tests/unit/app/test_app_dir.py -k add_child` (the allowlist test confirms `add_child` is absent from `dir()`).
- [ ] FR#3: `dir()` on an App instance returns exactly the 20 app-author API names. Verify: run `pytest tests/unit/app/test_app_dir.py`.
- [ ] FR#6: The allowlist test exists and passes. Verify: `pytest tests/unit/app/test_app_dir.py -v` shows passing assertions.
- [ ] AC#1: `dir(App(...))` returns exactly the app-author API allowlist. Verify: `pytest tests/unit/app/test_app_dir.py -v` passes, including the set-equality assertion.
