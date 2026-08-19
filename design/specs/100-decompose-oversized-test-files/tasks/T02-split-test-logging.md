---
task_id: "T02"
title: "Split tests/unit/test_logging.py by subsystem"
status: "planned"
depends_on: []
implements: ["FR#2", "AC#2"]
---

## Target Files

- delete: `tests/unit/test_logging.py` (all 24 classes move out; delete once empty — see Prompt)
- create: `tests/unit/test_logging_setup.py`
- create: `tests/unit/test_logging_correlation.py`
- create: `tests/unit/test_logging_capture_handler.py`
- create: `tests/unit/test_logging_persistence.py`

## Prompt

`tests/unit/test_logging.py` is 1060 lines with 24 test classes, exceeding the repo's 800-line
file threshold (closes issue #1579). Split it by subsystem cluster into sibling files. This
directory (`tests/unit/`) is flat (no subpackage), so use flat sibling files, not a subpackage.

Read the full current file first, then move classes into these four new files:

- `tests/unit/test_logging_setup.py` — `TestEnableBasicLoggingAutoFormat`,
  `TestLoggingPipelineConsoleRenderer`, `TestLoggingPipelineJSONRenderer`,
  `TestEnableBasicLogging`, `TestNoisyLibrarySuppression`, `TestColoredlogsRemoved`,
  `TestNoModuleGlobals`
- `tests/unit/test_logging_correlation.py` — `TestCorrelationFilterSeqIncrements`,
  `TestCorrelationFilter`, `TestSeqMovedToFilter`, `TestExecutionIdInheritedByChildTask`,
  `TestCorrelationFilterAppliesToChildLoggers`, `TestAddExecutionIdProcessor`,
  `TestLogEntryCorrelationFields`, `TestLogEntryToDictIncludesSeq`
- `tests/unit/test_logging_capture_handler.py` — `TestLogCaptureHandlerStillCaptures`,
  `TestLogCaptureHandlerPopulatesCorrelationFields`, `TestQueueHandlerPipeline`,
  `TestHassetteQueueHandlerDrops`, `TestLogCaptureHandlerShutdownGuard`,
  `TestLogCaptureHandlerBroadcastEnvelope`
- `tests/unit/test_logging_persistence.py` — `TestLogPersistenceHandlerBatching`,
  `TestLogPersistenceDropCountWithDB`, `TestDequeueTimeoutFlush`

After moving all 24 classes out, delete the original `tests/unit/test_logging.py`. It should have
no residual content: the shared `LoggingPipelineFixture` already lives in `tests/unit/conftest.py`
(not in this file), so all four new files import it from there rather than duplicating it — there
is nothing module-local left behind to preserve.

Preserve every import each moved class needs. This is a pure move — no logic, assertion, or
fixture behavior changes. Give each new file a short module docstring (3-5 lines) naming the
sibling files it complements.

## Verify

- [ ] FR#2: All 24 test classes from the original file are distributed across the four new subsystem files described above; no class is missing, duplicated, or altered.
- [ ] AC#2: `uv run pytest tests/unit/test_logging*.py -v` passes. Test count matches what the original single file reported before the split. Every resulting file is under 800 lines (`wc -l tests/unit/test_logging*.py`).
