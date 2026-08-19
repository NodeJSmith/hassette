---
task_id: "T06"
title: "Split tests/unit/core/test_command_executor_pipeline.py by theme"
status: "planned"
depends_on: []
implements: ["FR#6", "AC#6"]
---

## Target Files

- delete: `tests/unit/core/test_command_executor_pipeline.py` (all helpers and tests move out; delete once empty — see Prompt)
- create: `tests/unit/core/test_command_executor_pipeline_queue.py`
- create: `tests/unit/core/test_command_executor_pipeline_persist.py`
- create: `tests/unit/core/test_command_executor_pipeline_serve.py`

## Prompt

`tests/unit/core/test_command_executor_pipeline.py` is 827 lines, exceeding the repo's 800-line
file threshold (closes issue #1583). Unlike the other files in this batch, it's flat
function-based (no test classes) — a set of shared factory helpers followed by ~26 standalone
test functions. This directory already has an established topic-split pattern for the
`CommandExecutor` class: `test_command_executor.py`, `test_command_executor_error_handler.py`,
`test_command_executor_execution_id.py` already exist as siblings. Follow that exact pattern
(including any `# dup-ignore-start`/`# dup-ignore-end` comment blocks you find in
`test_command_executor_error_handler.py` if similar intentionally-mirrored test shapes exist here
— preserve such annotations across the move, don't drop them).

Before starting, read `tests/unit/core/CLAUDE.md` for this directory's shared fixtures/helpers,
and check `src/hassette/test_utils/factories.py` and `src/hassette/test_utils/helpers.py` per
`.claude/rules/test-conventions.md` before keeping any of this file's local `make_*` factories —
if a matching shared factory already exists there, import it instead of moving the local copy.

Read the full current file, then split by theme into:

- `tests/unit/core/test_command_executor_pipeline_queue.py` — bounded queue/capacity warning
  tests and retry/backoff batching tests (~lines 173-365 and 514-612 in the original file)
- `tests/unit/core/test_command_executor_pipeline_persist.py` — `_build_record` field-read tests
  and flush/persist/DB-closed-handling tests (~lines 366-513)
- `tests/unit/core/test_command_executor_pipeline_serve.py` — serve-loop draining tests,
  blocking-event DB-uninitialized-handling tests, and completion-event warning tests
  (~lines 613-827)

Move the shared helper factories (`make_invocation`, `make_job_record`,
`make_real_invoke_handler_cmd`, `init_executor`, `raising_persist`, `wire_raising_persist`,
`make_executor_with_send_event`, originally at lines 39-166) into whichever new file(s) actually
need them — if more than one file needs the same helper, either put it in the directory's
`conftest.py` (checking it's not already covered by a `test_utils` factory first) or duplicate
only if it's genuinely file-local and trivial. Adjust the exact line-range boundaries as needed
once you've read the file — the goal is thematic coherence and each file under 800 lines, not an
exact match to these line numbers.

This is a pure move — no logic, assertion, or fixture behavior changes. Give each new file a
short module docstring (3-5 lines) naming the sibling files it complements.

## Verify

- [ ] FR#6: All ~26 test functions from the original file are distributed across the three thematic files described above; no test dropped or duplicated. Shared factory helpers are either imported from `src/hassette/test_utils/factories.py`/`helpers.py` (if a match exists) or co-located with their consumers without unexplained duplication.
- [ ] AC#6: `uv run pytest tests/unit/core/ -k command_executor -v` passes (covers this split plus the three existing `test_command_executor*.py` siblings, unchanged). Test count for the pipeline tests specifically matches what the original single file reported before the split. Every resulting file is under 800 lines.
