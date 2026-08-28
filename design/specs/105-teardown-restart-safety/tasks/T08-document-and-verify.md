---
task_id: "T08"
title: "Document and verify restart safety"
status: "done"
depends_on: ["T06", "T07"]
implements: ["AC#8", "AC#9", "AC#10"]
---

## Summary

Document the teardown report, restart admission rules, lifecycle task ownership, TaskBucket sealing, and host-owned
recovery boundary. Then run the complete local backend and static-analysis gates to prove the assembled lifecycle and
watcher behavior preserves clean shutdown and restart policy outside refusal cases.

## Target Files

- read: `design/specs/105-teardown-restart-safety/design.md`
- modify: `docs/pages/core-concepts/internals/lifecycle.md`
- modify: `docs/pages/core-concepts/apps/task-bucket.md`
- modify: `CLAUDE.md`
- read: `tests/system/test_shutdown.py`
- read: `noxfile.py`
- read: `prek.toml`

## Prompt

Implement `Documentation Updates` and perform final verification. Update the lifecycle internals page to explain that
STOPPED is phase bookkeeping, describe SAFE/UNSAFE reports and their Python inspection surface, show how concurrent
attempts join, explain lifecycle re-entry and restart refusal, and state that process replacement is host-owned after
refusal. Update the TaskBucket page because its public `cancel_all()` description is now stale: document bounded
cancellation results and lifecycle sealing without implying a universal hard-stop guarantee. Update CLAUDE.md's Resource
hierarchy description with paired lifecycle-attempt ownership, TaskBucket-independent coordinator tasks, retained body
observation, and report-controlled restart admission. Do not document excluded app replacement, frontend state, sync
thread proof, or process death. Run the required persona and accuracy reviews on both changed docs pages, then run the
full local dev and prek gates.

## Focus

- Gap: `docs/pages/core-concepts/apps/task-bucket.md` currently says `cancel_all()` awaits every task to completion; the
  new bounded return contract and sealed owner shutdown make that statement inaccurate.
- Keep operator guidance factual: Hassette refuses unsafe same-instance restart but cannot kill cancellation-resistant
  Python work; systemd/Docker/embedding code owns process replacement.
- Explain the immutable returned report and current unconsumed `teardown_report` property without adding frontend or
  generated API claims.
- Run `doc-persona-review` and `doc-accuracy-review` for the lifecycle and TaskBucket pages before final verification.
- Do not edit `CHANGELOG.md`; release-please owns it.

## Verify

- [ ] AC#8: `uv run pytest tests/unit/resources tests/unit/core/test_service_watcher_coverage.py tests/unit/core/test_service_watcher_exhausted.py tests/unit/core/test_fatal_shutdown.py tests/integration/test_lifecycle_propagation.py tests/integration/test_service_watcher.py tests/integration/test_task_bucket.py -q` passes clean restart, policy, lifecycle propagation, and orderly shutdown regressions.
- [ ] AC#9: `uv run nox -s dev` completes with zero test failures.
- [ ] AC#10: `prek -a` completes with no errors.
