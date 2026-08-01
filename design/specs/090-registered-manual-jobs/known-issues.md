# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: Trailing-period inconsistency between design doc and shipped status text

Status: open
Source: impl-review
Reason not fixed now: needs-decision
Observed in: T06 (CLI), T07 (frontend), commit 87db5785 (final state)
Affected files:
- design/specs/090-registered-manual-jobs/design.md (Operator Surfaces section)
- src/hassette/cli/commands/job.py
- frontend/src/components/app-detail/job-detail.tsx (or equivalent status-text source)

Issue:
The design doc specifies trailing periods on status text ("Timing unavailable.", "Waiting for entity time.", "Schedule completed.", "Manual only."). The shipped CLI and frontend implementation (matching the task files' own unpunctuated wording) omits the period on 4 of 6 strings. The two planning documents (design.md vs. task files) disagree with each other, not just with the code — the code correctly followed the task files.

Why deferred:
Purely cosmetic, no functional impact. Resolving it requires a product decision (which punctuation convention is correct) rather than a mechanical fix, and touches both docs and shipped user-facing text.

Recommended follow-up:
Pick one convention (with vs. without trailing periods) and align design.md, the task files, and the shipped CLI/frontend text to match.

Acceptance criteria:
- design.md's Operator Surfaces section and the actual CLI/frontend status strings use the same punctuation convention.

## KI-002: Stale "heap" terminology in test naming

Status: open
Source: impl-review
Reason not fixed now: out-of-scope
Observed in: T03 (registry and registration)
Affected files:
- tests/unit/core/test_scheduler_service_trigger.py

Issue:
The module docstring and the test `test_returns_job_found_on_heap` still say "heap," though this feature moved live job lookup from heap membership to the `_jobs_by_id` registry (`SchedulerService._jobs_by_id`) — the test itself correctly exercises the registry, only its name/docstring are stale.

Why deferred:
Purely a naming/documentation nit inside a test file with no behavioral consequence; out of scope for any of T01-T08's stated Target Files.

Recommended follow-up:
Rename `test_returns_job_found_on_heap` to something like `test_returns_job_found_in_registry` and update the module docstring's "heap" references to "registry" where they describe live-lookup behavior (retain "heap" only where the test genuinely describes `_ScheduledJobQueue`/due-time heap behavior).

Acceptance criteria:
- Test and docstring naming in test_scheduler_service_trigger.py accurately reflects registry- vs. heap-based behavior for each test.
