# Context: Deterministic DB Seeding Script

## Problem & Motivation

There is no way to see the hassette monitoring dashboard in edge-case states (empty install, degraded health, high error rates, large data volumes) without manually orchestrating a real Home Assistant instance and waiting 60-90 seconds for demo apps to organically produce telemetry. This blocks frontend QA, CLI doc generation, visual regression screenshots, and demos. A standalone script that generates deterministic SQLite databases for named scenarios provides instant, controllable, reproducible data for all these consumers.

## Visual Artifacts

None.

## Key Decisions

1. **Param builders + sync insert helper** — import existing param builder functions from `hassette.core.telemetry.repository` (with `_` prefix dropped) for column-shape fidelity. Write a thin sync `insert_row` helper in the seed script for writes. Do NOT reuse `TelemetryRepository` methods directly (they are async and `insert_blocking_event` silently swallows errors).
2. **Raw sqlite3 + migration runner** — no async runtime needed. `run_migrations(db_path)` creates the schema; the seed script's insert helper uses plain stdlib `sqlite3`.
3. **SeedContext as ID-graph builder** — a class that owns cross-table ID bookkeeping and insert ordering (session→listener/job→execution→log/blocking). Scenario generators interact exclusively through SeedContext methods.
4. **Fictional app keys** — invented names not tied to `examples/` apps. Decoupled from demo stack.
5. **Over-seed past health thresholds** — error rates well past warning/critical boundaries so minor threshold adjustments don't change displayed health status.
6. **Always fresh file** — each run deletes/replaces the output file. No in-place upsert. Atomic swap via `os.replace()` after integrity checks pass.
7. **Plain dict registry** — scenario names map to callables via a dict literal. No enum, plugin discovery, or directory-per-scenario.

## Constraints & Anti-Patterns

- Do NOT use `INSERT OR REPLACE` or `ON CONFLICT DO NOTHING` — these silently corrupt auto-increment IDs or skip rows.
- Do NOT introduce Faker, Mimesis, or RNG-based libraries. All data is hand-authored and deterministic.
- Do NOT reuse `TelemetryRepository` methods directly (async, error-swallowing).
- `scheduled_jobs.repeat` must be hardcoded to `0` in the extracted `job_insert_params`.
- `execution_id` values must be deterministic strings, not real UUIDs.
- All timestamps must be fixed offsets from a deterministic reference point, never wall-clock.
- `log_records`/`blocking_events` `execution_id` is a bare string with no FK constraint (intentional — write-ordering in production). The seeder must validate consistency with a post-seed LEFT JOIN assertion.

## Design Doc References

- ## Architecture — SeedContext shape, write path, param builder extraction, integrity checks, lifecycle field contract, scenario definitions
- ## Functional Requirements — FR#1-FR#11 covering script CLI, table coverage, integrity, determinism
- ## Edge Cases — empty scenario, large-volume pagination, adversarial strings, cancelled/retired combinations, nullable execution_id
- ## Test Strategy — param builder unit tests, scenario smoke tests, determinism tests, FK/consistency violation tests
- ## Convention Examples — standalone script structure, param builder pattern, test factory pattern, migration runner usage

## Convention Examples

### Standalone script structure

**Source:** `scripts/export_schemas.py`

```python
#!/usr/bin/env python3
"""Export JSON Schemas for frontend type generation and config validation.

Usage::
    python scripts/export_schemas.py
"""

import argparse
import json
from pathlib import Path

def main() -> None:
    parser = argparse.ArgumentParser(description="Export schemas.")
    parser.add_argument("--types", action="store_true")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    # ...

if __name__ == "__main__":
    main()
```

### Param builder function

**Source:** `src/hassette/core/telemetry/repository.py`

```python
def _execution_insert_params(record: ExecutionRecord) -> dict[str, Any]:
    return {
        "kind": record.kind,
        "listener_id": record.listener_id,
        "job_id": record.job_id,
        "session_id": record.session_id,
        "execution_id": record.execution_id,
        "status": record.status,
        # ... all fields, booleans coerced to int
    }
```

### Test factory with keyword-only defaults

**Source:** `src/hassette/test_utils/factories.py`

```python
def make_listener_registration(
    *,
    app_key: str = DEFAULT_TEST_APP_KEY,
    instance_index: int = 0,
    handler_method: str = "test_app.on_event",
    topic: str = "hass.event.state_changed",
    debounce: float | None = None,
    # ... all fields with sensible defaults
) -> ListenerRegistration:
    return ListenerRegistration(app_key=app_key, instance_index=instance_index, ...)
```

### Migration runner (standalone, synchronous)

**Source:** `src/hassette/core/migration_runner.py`

```python
def run_migrations(db_path: Path, *, target: int | None = None) -> None:
    """Apply pending migrations to the database at db_path (synchronous)."""
    # Opens stdlib sqlite3 connection, reads .sql files, applies via executescript()
```
