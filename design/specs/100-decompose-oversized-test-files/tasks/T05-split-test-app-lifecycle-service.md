---
task_id: "T05"
title: "Extract instance-lifecycle test classes from tests/unit/core/test_app_lifecycle_service.py"
status: "planned"
depends_on: []
implements: ["FR#5", "AC#5"]
---

## Target Files

- modify: `tests/unit/core/test_app_lifecycle_service.py`
- create: `tests/unit/core/test_app_lifecycle_service_instances.py`

## Prompt

`tests/unit/core/test_app_lifecycle_service.py` is 900 lines with 15 test classes, exceeding the
repo's 800-line file threshold (closes issue #1582). This directory already has an established
split pattern for this same service: `test_app_lifecycle_service_coverage.py` and
`test_app_lifecycle_service_operations.py` already exist as siblings. Follow that exact pattern.

Before starting, read `tests/unit/core/CLAUDE.md` for this directory's shared fixtures/helpers
(`mock_hassette`, `mock_registry`, `mock_factory`, `lifecycle_service`, `set_registry_apps`, all
from this directory's `conftest.py`), and read
`tests/unit/core/test_app_lifecycle_service_coverage.py`'s opening docstring/imports as the
reference style for the new file (relative `from .conftest import set_registry_apps` import,
short module docstring naming sibling files it complements).

Read the full current `test_app_lifecycle_service.py`, then move these instance-lifecycle classes
into a new `tests/unit/core/test_app_lifecycle_service_instances.py`:
- `TestInitializeInstances`
- `TestCleanupFailedInstance`
- `TestShutdownInstance`
- `TestShutdownInstances`
- `TestShutdownAll`

Reuse the directory's shared fixtures and `set_registry_apps` helper via
`from .conftest import ...` — do not duplicate them locally. This is a pure move — no logic,
assertion, or fixture behavior changes. Give the new file a short module docstring (3-5 lines)
naming the sibling files it complements, matching the style in
`test_app_lifecycle_service_coverage.py`.

## Verify

- [ ] FR#5: The five instance-lifecycle test classes listed above live in `test_app_lifecycle_service_instances.py`; the remaining 10 classes stay in `test_app_lifecycle_service.py`. No test dropped or duplicated.
- [ ] AC#5: `uv run pytest tests/unit/core/ -k app_lifecycle_service -v` passes. Test count matches what the original file (plus its two existing siblings, unchanged) reported before the split. `test_app_lifecycle_service.py` and `test_app_lifecycle_service_instances.py` are both under 800 lines.
