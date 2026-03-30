---
depends_on:
- WP09
lane: done
plan_section: 2. Best-Effort Cleanup and STOPPED Event in Timeout Handler + 6. Reset
  _initializing in _finalize_shutdown()
title: Refactor _finalize_shutdown() with timeout, hook, and _initializing warning
work_package_id: WP09b
---

## Objectives & Success Criteria

Refactor `Resource._finalize_shutdown()` to use the `_force_terminal()` method from WP09, add `_on_children_stopped()` hook, wrap `cleanup()` in `asyncio.timeout`, and add `_initializing` defense-in-depth warning.

After this WP:
- `cleanup()` is wrapped in `asyncio.timeout(resource_shutdown_timeout_seconds)` in the base `_finalize_shutdown()`
- The timeout handler calls `child._force_terminal()` instead of inline flag patching
- `_on_children_stopped()` is a no-op hook called after clean child shutdown, skipped on timeout
- `_initializing` warning fires with DEBUG/WARNING gating based on `shutdown_event.is_set()`

## Subtasks

1. Add `_on_children_stopped()` no-op hook to `Resource` in `src/hassette/resources/base.py` with docstring specifying success-path-only semantics and `super()` requirement
2. Refactor `Resource._finalize_shutdown()` in `src/hassette/resources/base.py`:
   - Wrap `cleanup()` in `asyncio.timeout(timeout)` with TimeoutError + Exception handling
   - Add `children_timed_out = False` flag
   - Replace inline force-patch block in `except TimeoutError` with `child._force_terminal()` calls and set `children_timed_out = True`
   - After child propagation: set `_shutdown_completed = True`, add `_initializing` warning with `shutdown_event.is_set()` gating (DEBUG if requested, WARNING otherwise)
   - Call `_on_children_stopped()` only when `not children_timed_out`
   - Keep existing `handle_stop()` / `event_streams_closed` guard
3. Add unit tests in `tests/unit/resources/test_lifecycle_propagation.py`:
   - `test_on_children_stopped_called_on_clean_shutdown`: verify hook fires when children shut down cleanly
   - `test_on_children_stopped_skipped_on_timeout`: mock a child that hangs, verify hook is NOT called when timeout fires
   - `test_cleanup_timeout_fires_on_hung_cleanup`: mock `cleanup()` to hang, verify TimeoutError is caught and logged
   - `test_initializing_warning_on_shutdown_during_init`: set `_initializing = True` + `shutdown_event.set()`, verify DEBUG log; set `_initializing = True` without `shutdown_event`, verify WARNING log

## Test Strategy

Tests in `tests/unit/resources/test_lifecycle_propagation.py`. Use existing `conftest.py` fixtures. Tests verify:
- Hook call/skip semantics based on `children_timed_out` flag
- `asyncio.timeout` wrapping `cleanup()` catches hung cleanup
- `_initializing` log level depends on `shutdown_event` state

## Review Guidance

- `_on_children_stopped()` MUST only run when `children_timed_out is False`
- `_on_children_stopped()` docstring MUST state "Overrides MUST call `await super()._on_children_stopped()`"
- The `asyncio.timeout` wrapping `cleanup()` replaces the bare `try/except Exception` — verify both TimeoutError and Exception are handled separately
- `_initializing` warning: verify `shutdown_event.is_set()` gates between DEBUG and WARNING log levels
- The timeout handler MUST call `child._force_terminal()` (from WP09), NOT inline flag patching

## Activity Log

- 2026-03-30T00:00:00Z — system — lane=planned — WP created (split from original WP09)
- 2026-03-30T13:16:36Z — system — lane=doing — moved from planned
- 2026-03-30T13:32:14Z — system — lane=done — moved from doing
