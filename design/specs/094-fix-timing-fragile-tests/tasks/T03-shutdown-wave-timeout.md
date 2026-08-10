---
task_id: "T03"
title: "Widen shutdown-wave test timeout"
status: "done"
depends_on: []
implements: ["FR#4", "AC#4"]
---

## Target Files

- modify: `tests/unit/core/test_core_coverage.py`

## Prompt

In `tests/unit/core/test_core_coverage.py`, find `TestShutdownChildren::test_force_terminates_wave_on_timeout_and_returns_false` (line 301).

Change the timeout from 0.05 to 0.5:

```python
h.config.lifecycle.resource_shutdown_timeout_seconds = 0.5
```

The hanging child sleeps 1000s, so 0.5s still triggers force-termination with 10x+ margin over any CI scheduling jitter. The test's logic ("does a hanging child trigger force-termination?") is unchanged.

## Verify

- [ ] FR#4: `resource_shutdown_timeout_seconds` is 0.5 in the test
- [ ] AC#4: `uv run pytest --count=20 -x tests/unit/core/test_core_coverage.py::TestShutdownChildren::test_force_terminates_wave_on_timeout_and_returns_false -v` passes all 20 iterations
