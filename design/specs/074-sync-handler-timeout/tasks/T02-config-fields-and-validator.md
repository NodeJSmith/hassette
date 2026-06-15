---
task_id: "T02"
title: "Add sync-executor config fields and budget validator"
status: "planned"
depends_on: []
implements: ["FR#8"]
---

## Summary
Add two configuration fields to `LifecycleConfig` controlling the dedicated sync-handler executor's pool size and shutdown interruption budget, plus a cross-field validator ensuring the interruption budget stays under the total shutdown budget. Without the validator, an operator can set a budget larger than the total shutdown window, causing the outer shutdown timeout to fire mid-interrupt and leave threads partially interrupted.

## Prompt
Edit `src/hassette/config/models.py`, `LifecycleConfig` class (`:218-259`). Add two fields near `total_shutdown_timeout_seconds` (`:236`):

- `sync_executor_max_workers: int = Field(default_factory=lambda: min(32, (os.cpu_count() or 1) + 4))` — the dedicated pool ceiling. Match the prior implicit default-pool sizing. Add a docstring noting this is a reasonable starting ceiling, NOT a literal behavior-equivalence (the old shared pool also served logging/DB, so a same-size dedicated pool gives sync handlers more effective headroom).
- `sync_executor_shutdown_timeout_seconds: float = Field(default=10.0)` — the shutdown interruption budget (HA's value). Docstring: the join-or-interrupt budget for sync-handler worker threads at shutdown; must be under `total_shutdown_timeout_seconds`.

Add a `@model_validator(mode="after")` mirroring the existing one at `:208-215` (note: that example, `fill_event_defaults`, is on `LoggingConfig`, not `LifecycleConfig` — it is a shape reference for the validator pattern, not the same class):

```python
@model_validator(mode="after")
def validate_sync_executor_shutdown_budget(self) -> "LifecycleConfig":
    if self.sync_executor_shutdown_timeout_seconds >= self.total_shutdown_timeout_seconds:
        raise ValueError(
            f"sync_executor_shutdown_timeout_seconds "
            f"({self.sync_executor_shutdown_timeout_seconds}) must be less than "
            f"total_shutdown_timeout_seconds ({self.total_shutdown_timeout_seconds})"
        )
    return self
```

Ensure `os` and `model_validator` are imported at the top of the file (check existing imports — `model_validator` is already used at `:208`). Do NOT use a lazy import.

Add a unit test to the appropriate config test file (locate it: `tests/unit/**/test*config*.py` or `tests/unit/test_config*.py` — search first; create `tests/unit/test_lifecycle_config.py` only if no suitable file exists). Run with `uv run pytest <file> -v` (never `-n auto`).

## Focus
- `total_shutdown_timeout_seconds` is typed `int` (`:236`); the new budget is `float`. A `float < int` comparison is valid Python — no coercion needed, but keep the new field `float` for sub-second budgets.
- The validator runs at config load, so an invalid config fails fast at startup with a clear message — this is the intended behavior (the design's Finding 8 fix).
- Defaults must keep existing behavior working: with no config override, `sync_executor_max_workers` matches the old `min(32, cpu+4)` sizing and the budget (10.0) is safely under the default total (30).
- This task adds config only; the fields are consumed by `SyncExecutorService` in T03/T05.

## Verify
- [ ] FR#8: `LifecycleConfig` exposes `sync_executor_max_workers` (default `min(32, cpu+4)`) and `sync_executor_shutdown_timeout_seconds` (default `10.0`); constructing a config with `sync_executor_shutdown_timeout_seconds >= total_shutdown_timeout_seconds` raises a `ValueError` naming both fields, and a valid combination loads cleanly.
