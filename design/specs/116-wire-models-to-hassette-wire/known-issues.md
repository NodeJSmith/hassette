# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: Files exceeding the 800-line hard cap

Status: filed (already tracked — see #1686, #1759, #1286, #1300, #1033, #1292, #1576, #1575, #2357, #815, #1574, #2344, #814, #1721, #2279, #2354, #2348, #2366; #2442 filed in error as a duplicate and closed)
Run: 146
Source: clean-code
Reason not fixed now: out-of-scope
Observed in: clean-code run at HEAD be1ffeca
Affected files:
- src/hassette/scheduler/scheduler.py (1349 lines)
- src/hassette/core/app_lifecycle_service.py (1587 lines)
- src/hassette/core/database_service.py (1306 lines)
- src/hassette/core/scheduler_service.py (1157 lines)
- src/hassette/core/core.py (929 lines)
- src/hassette/core/state_proxy.py (889 lines)
- src/hassette/core/websocket_service.py (890 lines)
- src/hassette/testing/_harness.py (858 lines)
- src/hassette/core/telemetry/repository.py (826 lines)
- src/hassette/resources/lifecycle.py (965 lines)
- src/hassette/core/service_watcher.py (804-805 lines)
- tests/unit/resources/lifecycle/test_shutdown.py (1123 lines)
- tests/integration/test_service_watcher.py (1145 lines)
- tests/integration/test_scheduler_mode.py (1026 lines)
- tests/unit/core/test_runtime_query_service.py (808 lines)

Issue:
`coding-style.md` caps files at 800 lines (200-400 typical). All listed files pre-date this
branch and exceed that cap; this diff only touched import lines in each (moving enum/type
imports to `hassette_wire`), so none of the size growth is attributable to this PR.

Why deferred:
Splitting any of these files is a structural refactor unrelated to the wire-models migration
this branch implements — out of scope for this run, and risky to bundle into a migration PR
since it would obscure the actual diff under review.

Recommended follow-up:
File a decomposition pass (see `/mine-decompose`) for the core-service files in a dedicated
follow-up PR, split along each file's already-documented sub-concerns (e.g.
`database_service.py`'s retention/size-failsafe logic, `scheduler_service.py`'s heap-queue vs.
dispatch logic). Test files with heavily duplicated arrange/act/assert blocks (see KI-005) should
shrink materially once parametrized, which may resolve some of these without an explicit split.

Acceptance criteria:
- Each listed file is at or under 800 lines, or a documented exception is recorded.

## KI-002: Oversized functions and deep nesting in core services

Status: open (already tracked — see #2279/#2354 database_service.py, #2357 scheduler_service.py, #2348 core.py, #1574/#2344 app_lifecycle_service.py, #1686/#2376 telemetry/repository.py; resources/lifecycle.py, resources/base.py, and testing/app_harness.py have no existing issue)
Run: 146
Source: clean-code
Reason not fixed now: out-of-scope
Observed in: clean-code run at HEAD be1ffeca
Affected files:
- src/hassette/core/database_service.py (`_check_size_failsafe`, ~260 lines, 5 levels of nesting)
- src/hassette/core/scheduler_service.py (`dispatch_and_log`, ~150 lines)
- src/hassette/core/core.py (`run_forever`, ~140 lines)
- src/hassette/core/app_lifecycle_service.py (`handle_change_event`, several long nested branches)
- src/hassette/core/telemetry/repository.py (`reconcile_registrations`, ~120 lines)
- src/hassette/resources/lifecycle.py (`_run_shutdown_coordinator`, ~130 lines)
- src/hassette/resources/base.py (`_force_terminal` ~70 lines, `_run_post_hook_shutdown_stage` ~55 lines)
- src/hassette/testing/app_harness.py (`_setup`, ~90 lines, 9+ inline steps)

Issue:
`coding-style.md` guides functions under ~50 lines and nesting under 4 levels. None of these
functions were touched by this diff beyond unrelated import-line changes.

Why deferred:
Pre-existing structure, not introduced or modified by the wire-models migration this branch
implements. Refactoring core lifecycle/scheduling logic is a separate, higher-risk effort that
deserves its own reviewed PR with dedicated test coverage of the refactor.

Recommended follow-up:
Decompose each function along its already-commented sub-steps in a dedicated cleanup PR (see
`/mine-decompose`).

Acceptance criteria:
- Each listed function is under ~50 lines and nesting is under 4 levels, or a documented
  exception is recorded.

## KI-003: Near-duplicate query methods and repeated property-accessor blocks

Status: filed (#2443 for registration_queries.py; core.py accessors already tracked at #1292/#2348)
Run: 146
Source: clean-code
Reason not fixed now: out-of-scope
Observed in: clean-code run at HEAD be1ffeca
Affected files:
- src/hassette/core/telemetry/registration_queries.py (`get_listener_summary` / `get_job_summary`,
  ~90-line near-duplicate functions sharing the same CTE/aggregate shape)
- src/hassette/core/core.py (~20 near-identical `@property` accessors of the shape
  `if self._x is None: raise _service_not_wired_error("X"); return self._x`)

Issue:
Two genuine copy-paste-shaped duplications pre-dating this branch: parallel SQL query methods
that could share a parameterized helper, and a repeated property-accessor pattern in `core.py`
that could become a small descriptor/factory.

Why deferred:
Neither file's touched hunk in this diff is anywhere near these lines (only import-line changes).
Restructuring either is a design decision (shared helper shape, descriptor pattern) independent
of the wire-models migration.

Recommended follow-up:
Extract a shared parameterized helper for the two `registration_queries.py` methods; evaluate
whether `core.py`'s repeated accessors are worth a small descriptor helper (note: the lazy-checker
pass on this same file judged the current form legitimate — "trades clarity for less code" — so
this is a judgment call for whoever picks it up, not an obvious fix).

Acceptance criteria:
- `get_listener_summary`/`get_job_summary` share their common SQL-construction logic, or a
  decision is recorded that the duplication is intentional (with a `dup-ignore` marker per repo
  convention).

## KI-004: Dead/unreferenced schema models in summary_models.py

Status: open (fix-now attempt on 2026-09-30 found the recommended deletion is explicitly out of scope — see below)
Run: 146
Source: clean-code
Reason not fixed now: needs-decision
Observed in: clean-code run at HEAD be1ffeca
Affected files:
- src/hassette/schemas/summary_models.py

Issue:
`GlobalSummary` and `SessionSummary` each document a producing method
(`get_global_summary()`, `get_current_session_summary()`) that does not exist anywhere in
production code, and neither class is exported via `schemas/__init__.py`'s `__all__` or
constructed by any route. Correction to the original finding: they are not literally
unreferenced — both are constructed directly in `tests/e2e/mock_fixtures/telemetry.py:487,503`
and exercised in `tests/unit/test_telemetry_models.py` (`TestGlobalSummary`/`TestSessionSummary`).
Confirmed present in this exact form at the base commit (fb4f7083), so pre-existing.

Why deferred:
This branch's own design doc (`design/specs/116-wire-models-to-hassette-wire/design.md`, Status:
approved, not archived) explicitly excludes deleting these in this PR — its Non-Goals section
names `GlobalSummary`/`SessionSummary` (along with `HandlerErrorRecord`, `JobErrorRecord`, the
`*GlobalStats` types) as "unserved, possibly dead telemetry models... a separate cleanup." A
fix-now attempt during the known-issues walkthrough confirmed this and did not delete anything.

Recommended follow-up:
File or point to a dedicated cleanup issue for deleting `GlobalSummary`, `SessionSummary`,
`HandlerErrorRecord`, `JobErrorRecord`, and the `*GlobalStats` types together, per the design
doc's own Non-Goals framing — not just the two models this finding named.

Acceptance criteria:
- Either all five model groups are removed together, or each documents a real producing method
  that exists in the codebase.

## KI-005: Duplicated test arrange/act/assert blocks in integration test suites

Status: filed (#2444)
Run: 146
Source: clean-code
Reason not fixed now: out-of-scope
Observed in: clean-code run at HEAD be1ffeca
Affected files:
- tests/integration/test_app_test_harness.py (~9 structurally identical `simulate_*` tests)
- tests/integration/test_app_factory_lifecycle.py (~10 tests repeating the same
  create-manifest/create-instances/initialize arrange block with no shared helper)

Issue:
Both files repeat a near-identical 4-12 line block across many test methods with no
`pytest.mark.parametrize` table or shared arrange helper, unlike sibling modules
(`tests/integration/telemetry/helpers.py`) that do extract this kind of repeated setup.

Why deferred:
Neither file's touched hunk in this diff goes near these test bodies (only import-line changes).
Restructuring test suites into parametrized tables is a test-authoring decision independent of
this migration and risks changing test IDs/behavior if done hastily.

Recommended follow-up:
Parametrize the `simulate_*` family in `test_app_test_harness.py` over `(bus_method,
simulate_method)` pairs, and extract the repeated arrange sequence in
`test_app_factory_lifecycle.py` into a shared helper analogous to
`tests/integration/telemetry/helpers.py`'s pattern.

Acceptance criteria:
- The two files shrink materially with no loss of test coverage (same assertions, fewer
  duplicated lines).

## KI-006: Naming inconsistencies (pre-existing)

Status: filed (#2445)
Run: 146
Source: clean-code
Reason not fixed now: out-of-scope
Observed in: clean-code run at HEAD be1ffeca
Affected files:
- src/hassette/core/core.py:528-540 (`get_app(app_name=...)` vs. the rest of the codebase's
  consistent `app_key` vocabulary)
- src/hassette/config/models.py:37 (`LOG_ANNOTATION` type alias in SCREAMING_SNAKE_CASE instead
  of PascalCase)
- src/hassette/core/web_api_service.py:81 (`loopback` boolean stored in a noun, not
  `is_loopback`)
- src/hassette/task_bucket/task_bucket.py (single-letter `t` used as a callback parameter name,
  not just a loop index, at several call sites)
- tests/support/web_job_helpers.py (`make_job()`'s `job_id: str` vs. `make_job_summary()`'s
  `job_id: int` in the same file)
- tests/unit/resources/test_lifecycle_transitions.py (`resource1`/`resource2` vs. `r1`/`r2`/`r3`
  for the same concept in adjacent tests)
- tests/unit/core/test_core_coverage.py (bare single-letter `h` alias for the `Hassette`
  instance, an outlier vs. sibling test files' word-based aliases)

Issue:
Minor naming drift found by the nitpicker pass, none touched by this diff's hunks.

Why deferred:
Cosmetic renames unrelated to the wire-models migration; batching them into this PR would inflate
the diff with unrelated changes.

Recommended follow-up:
Address in a small follow-up naming-cleanup pass, or opportunistically the next time each file is
touched for an unrelated reason.

Acceptance criteria:
- Each listed name matches its file's/codebase's established convention.

## KI-007: Unnamed magic numbers and scattered/drifted constants in tests

Status: fixed (drift item) + filed (#2446, remaining cosmetic items)
Run: 146
Source: clean-code
Reason not fixed now: out-of-scope (except the drift item, fixed directly)
Observed in: clean-code run at HEAD be1ffeca
Affected files:
- ~~tests/support/web_response_helpers.py:126-168 vs. tests/support/web_mocks.py:31 (two
  fixture builders define different default values — `job_history_size: 100` vs.
  `STUB_JOB_HISTORY_SIZE = 1000`, and similar drift for the `app_startup_timeout_seconds`
  default — for the same conceptual config surface)~~ — **fixed**: corrected
  `make_config_schema_response()`'s hardcoded `job_history_size` (100 → 1000) and
  `app_startup_timeout_seconds` (10 → 20) to match the real `HassetteConfig` field defaults
  (`src/hassette/config/models.py`); `app_shutdown_timeout_seconds` was already correct.
  `tests/unit/cli/test_commands_misc.py` (the only caller) still passes.
- tests/unit/cli/test_client.py (default port `8126` repeated as a bare literal at many call
  sites instead of a module constant)
- tests/unit/cli/test_commands_app.py (`"/api/apps/manifests"` repeated ~5 times with no
  constant, unlike the sibling `test_endpoints.py`, which centralizes such paths)
- tests/system/test_cli_smoke.py:68,239 (`"startup_timeout_seconds": 30` duplicated with no
  shared constant, despite a sibling fixture file demonstrating the named-constant pattern for
  the same value)
- tests/unit/test_execution_mode_helpers.py:61,71,107,124 (`60.0`, `0.05` unnamed, despite the
  file already defining a constant for a related timing role)
- tests/unit/resources/test_service_edge_cases.py (several bare `asyncio.sleep(0.6)` /
  `asyncio.sleep(1.5)` / `timeout=5` / `timeout=10` literals, inconsistent with the file's own
  named-constant imports for the same purpose)
- tests/unit/test_ws_models.py:274-333 (`1714000000.0`/`1714000300.0` repeated instead of using
  the file's own `TEST_TIMESTAMP` constant)
- tests/unit/core/test_core_coverage.py:345,461,493,522 (`0.5` timeout repeated 4x with matching
  inline comments instead of one named constant)
- tests/unit/core/test_runtime_query_service.py:78-87 (`"2024-01-01T00:00:00"` repeated 4x in one
  fixture with no named constant)
- tests/unit/core/test_command_executor_pipeline_persist.py:227-265 (a ~40-line CREATE TABLE
  schema embedded as an inline string literal, at risk of silent drift from the real migration
  schema)
- tests/unit/core/test_scheduler_mode_resolution.py:83,90,97,105 (`lambda: None  # noqa: E731`
  redefined 4x instead of reusing `tests/support/helpers.py`'s canonical `noop`/`async_noop`)
- src/hassette/web/routes/apps.py:37 (`127` max-length embedded directly in a regex literal with
  no named constant)

Issue:
A cluster of unnamed/duplicated literal values found across the nitpicker pass, none touched by
this diff's hunks.

Why deferred:
Cosmetic hygiene unrelated to the wire-models migration; the `web_mocks.py`/
`web_response_helpers.py` drift is the one item with real risk (a future default change updates
one fixture and silently leaves the other stale) but still isn't caused by or blocking this PR.

Recommended follow-up:
Address in a small follow-up test-hygiene pass; prioritize reconciling the
`web_mocks.py`/`web_response_helpers.py` default-value drift first since it's the one with actual
correctness risk.

Acceptance criteria:
- Listed literals are pulled into named constants; the two fixture builders agree on shared
  config-default values (or one imports the other's constant).

## KI-008: Hardcoded worktree-specific path and manually-synced duplicate logic in doc tooling

Status: fixed
Run: 146
Source: clean-code
Reason not fixed now: fixed directly during known-issues walkthrough (2026-09-30)
Observed in: clean-code run at HEAD be1ffeca
Affected files:
- tools/docs/check_xref_coverage.py (`DOCS` was hardcoded to worktree `928`)
- tools/docs/check_bare_symbols.py (skip-detection logic reimplemented inline, synced only by
  a comment)
- tools/docs/_doc_skip_checks.py (new — shared module)

Issue:
`DOCS` was hardcoded to a different, specific worktree (`928`) than the one this review ran in
(`2385`) — machine- and session-specific, and would target the wrong worktree or fail outright
for anyone else. `check_bare_symbols.py` independently reimplemented the same code/heading/table
skip semantics inline (a per-line `in_code` toggle plus `stripped.startswith(...)` checks) rather
than sharing the position-based helpers in `check_xref_coverage.py`, kept in sync only by a
comment in each file.

Fix:
- `check_xref_coverage.py` now derives `DOCS` the same way `gen_ref_pages.py` does
  (`Path(__file__).resolve().parents[2] / "docs" / "pages"`).
- Extracted `is_in_code_block`/`is_in_heading`/`is_in_table_row` into new
  `tools/docs/_doc_skip_checks.py`; both scripts import from it instead of duplicating the logic.
- `check_bare_symbols.py`'s line-based skip loop was refactored to call the shared position-based
  functions (verified output-identical against the pre-refactor baseline: same 14 findings,
  byte-for-byte).
- Running the now-fixed `check_xref_coverage.py` surfaced 21 real cross-reference additions across
  15 docs pages (the tool had silently been a no-op against the stale `928` worktree) — those doc
  edits were reverted as out of scope for this PR; only the tool fix ships here. A follow-up run of
  `uv run python tools/docs/check_xref_coverage.py` in a dedicated docs-hygiene PR will pick them
  up.

Acceptance criteria:
- `check_xref_coverage.py` runs correctly from any worktree checkout. — met
- The skip-detection helpers have one definition, not two manually-synced copies. — met

## KI-009: Miscellaneous minor findings

Status: fixed
Run: 146
Source: clean-code
Reason not fixed now: fixed directly during known-issues walkthrough (2026-09-30)
Observed in: clean-code run at HEAD be1ffeca
Affected files:
- scripts/seed_scenarios/degraded.py (dead store)
- src/hassette/bus/listeners.py (config_matches()/diff_fields() field-list duplication)
- tests/integration/web_api/test_endpoints.py (repeated provenance-pointer docstring prefix)
- tests/unit/resources/test_direct_status_assignments.py (stale line-number citation)

Issue:
Small, independent style findings, each confirmed pre-existing (outside this diff's touched
hunks) or otherwise not attributable to this PR.

Fix:
- `degraded.py`: dropped the pointless `seq =` assignment on the function's final
  `seed_log_records()` call (nothing downstream reads it). Verified `scripts/seed_db.py
  --scenario degraded` still seeds correctly.
- `listeners.py`: extracted the 13-field comparison list (12 named + duration_config) into a
  module-level `_CONFIG_MATCH_FIELDS` tuple of `(name, comparator)` pairs; `config_matches()` and
  `diff_fields()` now both derive from it, so a new field can't be added to one and forgotten in
  the other. `tests/unit/bus/test_listeners.py` (56 tests) still passes; pyright clean.
- `test_endpoints.py`: reworded the four "P2 follow-up finding on PR #1873" docstring prefixes to
  state the durable invariant directly (per `coding-style.md`'s self-contained-comments rule —
  drop the narrated provenance, keep the behavior being tested). Tests still pass.
- `test_direct_status_assignments.py`: replaced the stale `app_lifecycle_service.py lines 158 and
  168` citation (actual lines had already drifted to 224/235) with a reference to the owning
  method, `AppLifecycleService.initialize_instances()`, which won't go stale on unrelated line
  shifts. Test still passes.

Acceptance criteria:
- Each item addressed independently. — met; all four fixed, tests green, lint/pyright clean.
