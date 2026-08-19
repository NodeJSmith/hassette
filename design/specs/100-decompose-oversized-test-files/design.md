# Design: Decompose Six Oversized Test Files

**Date:** 2026-08-19
**Status:** archived
**Mode:** sketch

## Problem

Six test files exceed the repo's 800-line threshold enforced by the `file-sizes` CI job
(`.github/workflows/lint.yml`, non-blocking per CLAUDE.md's Known-failing lint checks section,
but tracked as real pre-existing debt via issues #1578-#1583). Each file has grown past the point
where a reader can hold its scope in their head, and each was filed as its own `size:small`
issue. All six are pure test-file splits — no production code changes, no behavior changes.

## Goals

- Bring all six files under 800 lines.
- Every split follows the directory's own existing convention (sibling `test_*_<topic>.py`
  files, or a subpackage where no sibling convention exists yet).
- Zero behavior change: identical test count, identical pass/fail results, before and after.
- Close issues #1578, #1579, #1580, #1581, #1582, #1583 in one PR. GitHub's `Closes #A, #B`
  shorthand only auto-closes the first issue in the list — the PR body must repeat the `closes`
  keyword before each issue number (`closes #1578, closes #1579, ...`) for all six to close.

## Functional Requirements

- **FR#1** `tests/integration/test_websocket_service.py` (1200 lines) is split into a new
  `tests/integration/websocket/` package, grouped by: connection/auth, send/dispatch,
  disconnect/reconnect-retry (incl. `FailingConnection`), and `TestSubscribeEventsRetry`.
- **FR#2** `tests/unit/test_logging.py` (1060 lines, 24 test classes) is split by subsystem into
  sibling files: setup/renderers, correlation/seq, capture/queue handler, persistence handler.
- **FR#3** `tests/unit/test_autodetect_apps.py` (924 lines) is split along its four existing class
  boundaries (`TestAutoDetectAppsCurrDir`, `TestAutoDetectApps`, `TestValidateApps`,
  `TestAutoDetectIntegration`) into sibling files.
- **FR#4** `tests/unit/cli/test_client.py` (851 lines, 18 test classes plus an unrelated
  `SimpleModel` Pydantic helper class) has its credential/auth
  test classes extracted into a new `test_client_credentials.py`. `tests/unit/cli/CLAUDE.md`
  doesn't document a prior precedent for splitting an oversized file within this directory by
  sub-concern (its "File layout" table lists already-distinct concern files, not a split
  history), but its two-layer testing convention and credential-test guidance ("prefer the
  hermetic factory") still govern how the moved tests must be written.
- **FR#5** `tests/unit/core/test_app_lifecycle_service.py` (900 lines, 15 test classes) has its
  instance-lifecycle test classes extracted into a new `test_app_lifecycle_service_instances.py`,
  following the same sibling-split pattern already used by
  `test_app_lifecycle_service_coverage.py` / `test_app_lifecycle_service_operations.py`.
- **FR#6** `tests/unit/core/test_command_executor_pipeline.py` (827 lines, flat function-based)
  is split by theme (queue/capacity/retry-batch, persist/flush, serve-loop/blocking/completion)
  into sibling files, following the topic-split convention already used by
  `test_command_executor.py` / `test_command_executor_error_handler.py` /
  `test_command_executor_execution_id.py`.

## Acceptance Criteria

- **AC#1** (FR#1) `uv run pytest tests/integration/websocket/ -v` passes with the same test count
  as `git show HEAD:tests/integration/test_websocket_service.py` had before the split (collect
  count comparison). Every resulting file is under 800 lines (`wc -l`).
- **AC#2** (FR#2) `uv run pytest tests/unit/test_logging*.py -v` passes with the same test count
  as before. Every resulting file is under 800 lines.
- **AC#3** (FR#3) `uv run pytest tests/unit/test_autodetect_apps*.py tests/unit/test_validate_apps.py -v`
  passes with the same test count as before. Every resulting file is under 800 lines.
- **AC#4** (FR#4) `uv run pytest tests/unit/cli/test_client*.py -v` passes with the same test
  count as before. Every resulting file is under 800 lines.
- **AC#5** (FR#5) `uv run pytest tests/unit/core/ -k app_lifecycle_service -v` passes with the
  same test count as before. Every resulting file is under 800 lines.
- **AC#6** (FR#6) `uv run pytest tests/unit/core/ -k command_executor -v` passes with the same
  test count as before. Every resulting file is under 800 lines.
- **AC#7** After all six splits, `prek -a && prek pyright -a --stage pre-push` passes clean
  (`prek -a` alone does not run pyright — it's pre-push staged per
  `.claude/rules/git-workflow.md`/CLAUDE.md's "Correct hassette lint command" convention) and no
  production code under `src/` is touched (`git diff --stat main -- src/` is empty).

## Approach

Each split is a mechanical move of existing test classes/functions into new files, verified by
running the affected tests before and after and diffing collected test IDs (or at minimum test
counts) to confirm nothing was dropped or duplicated.

**General rules for every split:**
- Preserve all existing imports needed by the moved tests; do not introduce new production
  imports.
- Preserve shared module-level fixtures/helpers used by moved tests — if a helper is used by
  classes that end up in different files, either duplicate the (trivial) helper only if it's a
  one-liner used identically in both places, or promote it to the directory's `conftest.py` per
  `.claude/rules/test-conventions.md` (checking `src/hassette/test_utils/factories.py` and
  `helpers.py` first for anything that looks like a reusable factory).
- Relative imports for local helpers follow the existing convention seen in
  `test_command_executor_error_handler.py` (`from .conftest import ...`).
- Where a directory already splits a class family with a `# dup-ignore-start`/`# dup-ignore-end`
  comment pattern (seen in `test_command_executor_error_handler.py`) for tests that intentionally
  mirror another file's shape, preserve that annotation across the move rather than dropping it.
- New files get a short module docstring naming the sibling files they complement, matching the
  pattern in `test_app_lifecycle_service_coverage.py`.

**Per-file specifics:**

1. **`tests/integration/test_websocket_service.py` → `tests/integration/websocket/` package.**
   This is the one file with no existing sibling-split convention in its directory (compare
   `tests/integration/bus/`, `tests/integration/web_api/`, `tests/integration/telemetry/`, which
   are already subpackages). Create `tests/integration/websocket/__init__.py`,
   `conftest.py` (hosting the shared `websocket_service` fixture), and topic files for
   connection/auth, send/dispatch, disconnect/reconnect-retry (including the `FailingConnection`
   helper class), and `test_subscribe_events_retry.py` for `TestSubscribeEventsRetry`. Delete the
   original flat file once the package covers it.

2. **`tests/unit/test_logging.py` → sibling files.** Split into
   `test_logging_setup.py` (renderers/basic-logging/noisy-library-suppression classes),
   `test_logging_correlation.py` (correlation/seq classes),
   `test_logging_capture_handler.py` (capture/queue handler classes), and
   `test_logging_persistence.py` (persistence handler classes). Preserve `LoggingPipelineFixture`
   usage from `tests/unit/conftest.py` — it's shared, not moved.

3. **`tests/unit/test_autodetect_apps.py` → sibling files.** Keep
   `TestAutoDetectAppsCurrDir` + `TestAutoDetectApps` in `test_autodetect_apps.py`; move
   `TestValidateApps` to `test_validate_apps.py`; move `TestAutoDetectIntegration` to
   `test_autodetect_apps_integration.py`. Preserve shared imports and the autouse config fixture
   in each new file.

4. **`tests/unit/cli/test_client.py` → `test_client_credentials.py`.** Move
   `TestCredentialAttachment`, `TestNoLiteralWebApiTokenArgument`, `TestVerifySslPassthrough`,
   `TestVerifySslWarning`, `TestNonLoopback401Message`, `TestRequestIssuedDespiteNoCredential`
   into the new file. Per `tests/unit/cli/CLAUDE.md`, these tests should already prefer
   `make_cli_config`/`make_test_config` over constructing `HassetteConfig` directly — preserve
   that pattern in the move, including the deliberate real-env exception noted for
   `test_env_var_populates_config_and_attaches_bearer_header` if it's among the moved tests.

5. **`tests/unit/core/test_app_lifecycle_service.py` → `test_app_lifecycle_service_instances.py`.**
   Move `TestInitializeInstances`, `TestCleanupFailedInstance`, `TestShutdownInstance`,
   `TestShutdownInstances`, `TestShutdownAll`. Reuse the directory's shared fixtures
   (`mock_hassette`, `mock_registry`, `mock_factory`, `lifecycle_service`) and helper
   (`set_registry_apps`) from `tests/unit/core/conftest.py` via `from .conftest import ...` — do
   not duplicate them.

6. **`tests/unit/core/test_command_executor_pipeline.py` → sibling files.** Split by theme:
   queue/capacity + retry-backoff-batching tests into
   `test_command_executor_pipeline_queue.py`; flush/persist/DB-closed-handling tests into
   `test_command_executor_pipeline_persist.py`; serve-loop/blocking-event/completion-event tests
   into `test_command_executor_pipeline_serve.py`. Shared factory helpers (`make_invocation`,
   `make_job_record`, `make_real_invoke_handler_cmd`, `init_executor`, `raising_persist`,
   `wire_raising_persist`, `make_executor_with_send_event`) move to whichever new file(s) need
   them — check `src/hassette/test_utils/factories.py` first per
   `.claude/rules/test-conventions.md` before keeping them as local `make_*` definitions (a local
   `make_*` that shadows a shared factory name is flagged by
   `tools/check_test_factories.py`'s pre-commit hook).

## Dependencies and Assumptions

None — self-contained test reorganization within the current worktree.

## Changed Files

- delete: `tests/integration/test_websocket_service.py`
- create: `tests/integration/websocket/__init__.py`
- create: `tests/integration/websocket/conftest.py`
- create: `tests/integration/websocket/test_connection.py` (or equivalent topic name)
- create: `tests/integration/websocket/test_dispatch.py`
- create: `tests/integration/websocket/test_reconnect.py`
- create: `tests/integration/websocket/test_subscribe_events_retry.py`
- delete: `tests/unit/test_logging.py` (all 24 classes move out)
- create: `tests/unit/test_logging_setup.py`
- create: `tests/unit/test_logging_correlation.py`
- create: `tests/unit/test_logging_capture_handler.py`
- create: `tests/unit/test_logging_persistence.py`
- modify: `tests/unit/test_autodetect_apps.py`
- create: `tests/unit/test_validate_apps.py`
- create: `tests/unit/test_autodetect_apps_integration.py`
- modify: `tests/unit/cli/test_client.py`
- create: `tests/unit/cli/test_client_credentials.py`
- modify: `tests/unit/core/test_app_lifecycle_service.py`
- create: `tests/unit/core/test_app_lifecycle_service_instances.py`
- delete: `tests/unit/core/test_command_executor_pipeline.py` (all helpers and tests move out)
- create: `tests/unit/core/test_command_executor_pipeline_queue.py`
- create: `tests/unit/core/test_command_executor_pipeline_persist.py`
- create: `tests/unit/core/test_command_executor_pipeline_serve.py`
