# Nitpick Audit: Backend Scheduler & Resources

**Scope:** `app/`, `resources/`, `scheduler/`, `state_manager/`, `task_bucket/`
**Date:** 2026-05-21

---

## 1. Magic Numbers and Strings

**`classes.py:81`** — `max_iterations = 10_000` is a local variable, not a module-level named constant. Inline assignment inside a method body for a value that controls iteration budget and appears in a log message at line 111 qualifies as a scattered config value.

**`resources/base.py:86`** — The two fully-qualified class name strings `"hassette.resources.base.Service"` and `"hassette.core.core.Hassette"` are hardcoded as literals in a tuple comparison. If either class is ever renamed or moved, these silently stop matching. They should be named constants.

**`resources/base.py:213–217`** — The string `"Hassette"` appears as a class-name sentinel at line 213, the string `"hassette"` as the literal logger root name at line 214, and `"Hassette."` as a prefix to strip at line 217. Three related but distinct literals for the same concept, none of them named.

**`resources/mixins.py:202`** — Task name string `"resource:resource_initialize"` is an inline literal with no named constant. The matching pattern `"service:serve:{self.class_name}"` in `base.py:757` uses a different format prefix (`resource:` vs `service:`), which is consistent by intent but has nothing tying them together as a naming scheme.

**`task_bucket.py:338`** — `"Task-"` is a magic prefix string for detecting auto-named asyncio tasks. If CPython ever changes its default naming convention this silently breaks.

**`scheduler/scheduler.py:381`** — `assert source_tier in ("app", "framework")` hard-codes the two valid `SourceTier` values inline. These values are also present in the `SourceTier` type definition; the assertion should reference that type's members, not re-spell them.

---

## 2. Scattered Constants

**`classes.py:27`** — `seq = itertools.count(1)` is a module-level mutable object with a generic name. The `1` start value is meaningful (IDs start at 1, not 0, so 0 is a sentinel) but there is no comment or constant for this; `SENTINEL_JOB_ID = 0` is implied but not declared anywhere in scope.

**`resources/base.py:86`** — (See also Magic Numbers.) The allowlist of special-cased class names in `FinalMeta.__init__` is inline in a method. As the framework grows, this list may need updating; it belongs at module level as a named constant set.

**`app/app_config.py:22`** — `instance_name: str = ""` and `app_key: str = ""` both default to empty string. The empty-string sentinel is used for "not configured" logic elsewhere but is not extracted as a named constant (`UNSET_INSTANCE_NAME = ""`).

---

## 3. Ternary Abuse

**(3. Ternary Abuse): clean** — No nested ternaries, statement ternaries, or long-condition ternaries found in the reviewed files.

---

## 4. CSS and Styling Sins

**(4. CSS and Styling Sins): skipped** — Python backend code.

---

## 5. Dead Code

**`app/app_config.py:15`** — Docstring typo: `"overriden"` should be `"overridden"`. Minor but the docstring is user-facing documentation.

**`resources/mixins.py:340`** — `from hassette.events import HassetteServiceEvent` is a lazy import inside `_create_service_status_event()`. The project rules prohibit lazy imports except under `TYPE_CHECKING`. The method is on a hot path (called after every lifecycle transition). The module-level `TYPE_CHECKING` guard at line 13–14 already imports `HassetteServiceEvent` for type purposes; the runtime import belongs at module level.

**`resources/base.py:193`** — `from hassette.task_bucket import TaskBucket` is a lazy import inside `Resource.__init__`. This is a circular-import workaround, but it is undocumented. The global rules only exempt `TYPE_CHECKING` guards for this pattern.

**`app/utils.py:31`** — `from hassette.app import App` is a lazy import inside `_get_app_config_class()`, justified by a `# avoid circular import` comment but not under `TYPE_CHECKING`. Second occurrence at `utils.py:96` inside `_validate_init_method()` is identical.

**`resources/mixins.py:153,192,213,270`** — Four section divider comments (`# --------- props`, `# --------- lifecycle ops`, `# --------- readiness`, `# --------- transitions`). The project style rules prohibit decorated comment blocks between methods.

**`resources/base.py:520–521`** and **`base.py:521`**, **`base.py:566`**, **`base.py:729`**, **`base.py:737`**, **`base.py:767`** — Six `NOTE:` comments inside docstrings without a ticket reference. `NOTE:` is a form of inline documentation debt — these cross-reference synchronization requirements between `Resource.initialize()` and `Service.initialize()` but there is no issue tracking that the duplication exists or should be eliminated.

---

## 6. Naming Inconsistencies

**`resources/base.py:78`** — `FinalMeta.__init__` parameters are named `name`, `bases`, `ns`, `kw` — the abbreviations `ns` (for namespace dict) and `kw` match the CPython metaclass convention, but `ns` and `kw` are opaque to anyone unfamiliar with that convention. `namespace` and `kwargs` would be self-documenting.

**`app/app_config.py:33`** — Pydantic validator parameter is named `v: str`. Single-letter names outside loop indices violate the naming rule. `value` is the idiomatic name.

**`scheduler/classes.py:27`** — Module-level counter named `seq`. Too generic — `_job_id_counter` or `_job_id_sequence` would convey intent at a glance without needing to read the comment above it.

**`task_bucket.py:141`** — Variable named `result: Future[asyncio.Task[T]] = Future()` inside `spawn()`. This is the generic name `result` used for a `Future` that holds a `Task`. `task_future` would be unambiguous.

**`state_manager.py:152`** — `DomainStates.__iter__` is annotated `-> typing.Generator[...]` while every other iterable method in the same class (`items`, `iterkeys`, `itervalues`, `StateManager.__iter__`, etc.) uses `-> Iterator[...]`. Inconsistent return-type vocabulary for the same concept; `Generator` is a subtype of `Iterator` and there is no reason to distinguish them here.

**`resources/base.py:331`** — `_run_hooks` parameter typed as `list[typing.Callable[[], typing.Awaitable[None]]]` uses the `typing.` prefix namespace for both `Callable` and `Awaitable`, while the same file imports both from `typing` at the top (`from typing import Any, ClassVar, TypeVar, final`). Should use `Callable` and `Awaitable` directly rather than the `typing.X` form.

**`task_bucket.py:251`** — `run_on_loop_thread(self, fn: typing.Callable[..., R], *args, **kwargs)` uses `typing.Callable` while the top of the same file already imports `Callable` from `collections.abc`. Mixed namespace for the same type.

**`resources/mixins.py` vs `scheduler/triggers.py` vs `app/app.py`** — Module-level logger defined three different ways across reviewed files:
- `LOGGER = logging.getLogger(__name__)` (mixins.py:11, triggers.py:16) — uses `import logging` at top
- `LOGGER = getLogger(__name__)` (classes.py:22, utils.py:11, app.py:25) — uses `from logging import getLogger`

These are functionally identical but stylistically inconsistent across the module set.

**`app/app.py:1,3`** — Both `import logging` and `from logging import getLogger` are present. `import logging` is used only for the `logging.Logger` type annotation on line 67. The `logging` module import is redundant; `Logger` could be imported directly alongside `getLogger`.

**`resources/base.py` — `_shutting_down` / `_initializing` vs `_shutdown_completed`** — Two boolean class attributes use the present-participle pattern (`_shutting_down`, `_initializing`) while a third uses the past-participle pattern (`_shutdown_completed`). The naming is not wrong individually, but within the same class the inconsistency makes the state machine harder to scan.

---

## 7. Structural Messiness

**`resources/base.py`** — 828 lines. Exceeds the 800-line hard limit. Contains two large classes (`Resource` and `Service`) plus `FinalMeta`, `RestartSpec`, and `_ResourceContextFilter`. These could be split (e.g., `service.py` for the `Service` class).

**`scheduler/scheduler.py`** — 774 lines. Approaching the hard limit. The file is almost entirely a `Scheduler` class with eight near-identical convenience method bodies (`run_in`, `run_once`, `run_every`, `run_minutely`, `run_hourly`, `run_daily`, `run_cron`), each 51–88 lines, each forwarding to `schedule()` with minimal variation.

**`scheduler/scheduler.py:320`** — `schedule()` is 88 lines. Does trigger validation, source capture, `ScheduledJob` construction, and job registration — four distinct responsibilities in one method.

**`scheduler/scheduler.py:458`** — `run_once()` is 54 lines (mostly docstring, but the signature alone spans 14 lines). Same pattern for `run_every` (52 lines), `run_daily` (51 lines), `run_cron` (55 lines). The seven convenience methods are near-identical: each validates one parameter, constructs one trigger, and delegates to `schedule()`. The repeated full parameter lists with identical names, types, and docstring fragments are copy-paste structure.

**`resources/base.py:330`** — `_run_hooks()` has nesting depth 5: `for` → `try` → `except` → `if` → `with`. The `continue_on_error` branching inside a try/except block is hard to follow at a glance.

**`resources/base.py:363`** — `_auto_wait_dependencies()` is 54 lines with a role-based early return (`if self.role == ResourceRole.APP: raise`), dependency deduplication, a wait, and two distinct failure paths. Does more than one thing.

**`state_manager.py:241`** — `StateManager.__getattr__()` is 54 lines. Contains a registry call, two different `AttributeError` raises with different messages, a cache check, and a cache write. The guard at line 272 (`if domain.startswith("_") or domain in ("hassette", "parent", "name")`) introduces a third hard-coded string set inside the method — `"hassette"`, `"parent"`, `"name"` — with no explanation for why these three specifically.

**`scheduler/scheduler.py:196–208`** — `add_job()` has an `elif if_exists == "skip" and existing.matches(job): return existing` followed by `elif if_exists == "skip":` (lines 196–203). The second `elif` is an `else` branch of the first with extra condition — the two `elif if_exists == "skip"` arms are easy to misread as equivalent cases. The first arm should be a nested `if`/`else` inside a single `if if_exists == "skip":` block.

**`task_bucket.py:130`** — `else:` after `return asyncio.create_task(coro, name=name)` (the fast path). The `else` is redundant — remove it and unindent the slow path.

**`task_bucket.py:173`** — `else: return fn(*args, **kwargs)` after `return fn(*args, **kwargs)` inside `_call()` in `run_in_thread`. Same pattern — `else` after `return`.

**`app/utils.py:76`** — `_validate_init_method()` is 52 lines. The MRO traversal logic is non-trivial but the method does three things: skips internal classes, finds the App index in the MRO, iterates pre-App bases to find an offending `__init__`.

**`scheduler/scheduler.py:192–208`** — `add_job()` has `elif if_exists == "replace":` followed by `elif if_exists == "skip" and ...` followed by `elif if_exists == "skip":` followed by `else:`. The `Literal["error", "skip", "replace"]` type has three values but the chain has four branches (one value gets two `elif` arms). Structurally asymmetric.

---

## 8. Import Hygiene

**`resources/mixins.py:340`** — (Also flagged in Dead Code.) `from hassette.events import HassetteServiceEvent` is a runtime lazy import inside `_create_service_status_event()`. The import belongs at module level or at minimum under `TYPE_CHECKING` if used only for type purposes; here it is used to instantiate an object so it must be at module level.

**`resources/base.py:193`** — Lazy runtime import of `TaskBucket` inside `Resource.__init__`. Not under `TYPE_CHECKING`, no comment explaining it as a circular-import workaround.

**`app/utils.py:31,96`** — Two separate lazy runtime imports of `App` inside two separate functions. The `# avoid circular import` comment at least explains intent, but both should be consolidated at module level under `TYPE_CHECKING` since both usages are type-checking calls (`issubclass`, `isinstance`).

**`app/app.py:1`** — `import logging` is redundant given `from logging import getLogger` at line 3. The only additional use is `logging.Logger` at line 67, which should instead be `Logger` (already importable from `from logging import getLogger, Logger`).

---

## 9. Hard-Coded Environment Values

**(9. Hard-Coded Environment Values): clean** — No URLs, hostnames, credentials, or machine-specific paths found in the reviewed files.

---

## 10. Formatting Inconsistencies

**`state_manager.py:272`** — `if domain.startswith("_") or domain in ("hassette", "parent", "name"):` — the string tuple `("hassette", "parent", "name")` is an inline set of reserved attribute names with no comment explaining why these three. Not a formatting issue per se, but the lack of a named constant or comment makes it read as a magic string set.

**`resources/base.py:107`** — `origin_name = f"{origin.__qualname__}"` — f-string wrapping a single variable with no formatting operations. Should be `origin_name = origin.__qualname__` (plain assignment, no f-string).

**`task_bucket.py:179`** — `post_to_loop(self, fn, *args, **kwargs) -> None` has no type annotations on `fn`, `*args`, or `**kwargs`. Every other method in the class has full annotations. This is the only untyped public method in the file.

**`task_bucket.py:267`** — `create_task_on_loop(self, coro, *, name=None)` — both `coro` and `name` lack type annotations. The analogous `spawn()` method at line 120 fully annotates the same parameters.

**`task_bucket.py:258`** — Inner `_call()` inside `run_on_loop_thread` has no return type annotation, while the identical inner `_call()` at line 170 inside `run_in_thread` is annotated `-> R`.

**`scheduler/classes.py:391`** — `status: str  # "success", "error", "cancelled", "timed_out"` — the field comment enumerates valid values inline rather than using a `Literal` type or an enum, which is inconsistent with how `trigger_db_type()` across all trigger classes returns a `Literal["after"]`, `Literal["once"]`, etc.

---

## Summary

| Category | Findings |
|---|---|
| Magic Numbers and Strings | 6 |
| Scattered Constants | 3 |
| Ternary Abuse | 0 |
| CSS and Styling Sins | skipped |
| Dead Code | 8 |
| Naming Inconsistencies | 9 |
| Structural Messiness | 12 |
| Import Hygiene | 4 |
| Hard-Coded Environment Values | 0 |
| Formatting Inconsistencies | 6 |
| **Total** | **48** |

Highest-impact cleanup: the seven near-identical convenience methods in `scheduler.py` (run_in/run_once/run_every/run_minutely/run_hourly/run_daily/run_cron) are ~350 lines of copy-paste structure that could collapse to a single internal delegation helper, plus `resources/base.py` is over the 800-line hard limit and `Service` belongs in its own file.
