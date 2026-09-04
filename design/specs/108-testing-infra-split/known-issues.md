# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: Traceback-limit sign flip loses app-frame focus in startup-failure logs

Status: resolved — fixed during known issues walkthrough (commit 37704535)
Run: 128
Source: impl-review
Reason not fixed now: out-of-scope
Observed in: pre-existing at base_commit fda049fb (predates T01; not introduced by this run)
Affected files:
- src/hassette/core/app_lifecycle_service.py:207, :215 (call sites), :49-51 (deleted rationale comment)

Issue:
`get_short_traceback(INIT_FAILURE_TRACEBACK_LIMIT)` is called with a positive limit at both
app-init-failure log sites, instead of the negative limit (`-INIT_FAILURE_TRACEBACK_LIMIT`) that
was originally used deliberately. `traceback.format_exc()`'s `limit` counts frames from the
outermost (call site) end when positive and from the innermost (raise site) end when negative —
the innermost end is where the app's own file:line actually appears. With the positive limit,
startup-failure tracebacks now surface framework-internal frames instead of the app author's own
code, making these logs less useful for app authors debugging their own init failures. The
comment explaining why the negative sign was intentional was also deleted alongside the sign
flip.

Why deferred:
Confirmed via `git diff origin/main fda049fb -- src/hassette/core/app_lifecycle_service.py` that
this change already exists at this run's base_commit, before T01 ever started — it predates the
108-testing-infra-split design entirely and is unrelated branch history on `1333`, not something
any task in this run touched (T05's own single-line touch to this file was an unrelated comment
path-reference fix, verified via `git diff 626c70a3 HEAD` showing only that one line changed).
The design doc's Non-Goals explicitly excludes behavior changes from this migration's scope, so
fixing an unrelated pre-existing regression here would itself be scope creep relative to the
approved design.

Recommended follow-up:
Revert the two `get_short_traceback()` call sites to use `-INIT_FAILURE_TRACEBACK_LIMIT` and
restore the deleted rationale comment above `INIT_FAILURE_TRACEBACK_LIMIT = 5`, in a follow-up
fix unrelated to this feature.

Acceptance criteria:
- Both `get_short_traceback()` call sites in `app_lifecycle_service.py` pass a negative limit.
- The rationale comment explaining the negative-limit convention is restored.
