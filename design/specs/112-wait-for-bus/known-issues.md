# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: entity_topic() helper not backfilled into two pre-existing test files

Status: resolved — fixed during known issues walkthrough
Run: 139
Source: final-review
Reason not fixed now: out-of-scope
Observed in: integration review, final scope
Affected files:
- tests/integration/bus/test_bus_duration.py (lines 40, 389, 416)
- tests/integration/test_scheduler_entity_time.py (line 68)

Issue:
This branch adds a new `entity_topic()` helper to `tests/support/helpers.py` and correctly
adopts it in its own two new test files. Two pre-existing test files inline the equivalent
topic-string construction instead of using the new helper, so the codebase now has two ways
to build the same string.

Resolution:
Both files were backfilled to use `entity_topic()` in place of the inlined topic-string
construction during the known issues walkthrough for run 139. No behavior change; existing
tests continue to pass.
