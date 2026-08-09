---
task_id: "T04"
title: "File separate issue for coverage/watchdog false-positive"
status: "planned"
depends_on: []
implements: ["FR#5", "AC#5"]
---

## Target Files

(no code changes — issue tracker only)

## Prompt

File a new GitHub issue for the coverage/loop-watchdog false-positive using `/mine-create-issue`.

Context for the issue:

- **Test**: `test_tier1_ignore_suppresses_warning_and_row` in `tests/integration/telemetry/test_blocking_io_executor_offload.py`
- **Root cause**: Coverage.py's sysmon bytecode tracing (Python 3.12+) and settrace tracing (3.11) add genuine event-loop overhead that triggers the `LoopWatchdog`'s `lag_threshold_seconds` (0.05s in the test). The watchdog correctly detects a real stall, but the stall is caused by coverage instrumentation, not user code. The test asserts zero warnings, which fails.
- **Not a timing-margin issue**: unlike the other tests in #1571, this is a different mechanism entirely — coverage instrumentation causes real stalls, not a race between wall-clock sleeps and async dispatch.
- **Suggested fix**: Either increase `lag_threshold_seconds` in the test from 0.05 to 0.2-0.3s (and proportionally increase the intentional `time.sleep` stall), or suppress watchdog warnings when `COVERAGE_PROCESS_START` is set.
- **Related**: The codebase already has a pattern for coverage interference — see `skip_c_blocked_under_coverage_py311` in `tests/unit/test_sync_executor_service_saturation.py`.

Labels: `type:bug`, `area:testing`, `area:core`, `size:small`
Milestone: Code Quality

Reference parent issue #1571 in the description.

## Verify

- [ ] FR#5: A new issue exists on the tracker for the coverage/watchdog false-positive
- [ ] AC#5: The issue has appropriate labels and references #1571
