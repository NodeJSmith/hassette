---
task_id: "T04"
title: "Add tests for param builders and seed script scenarios"
status: "done"
depends_on: ["T03"]
implements: ["AC#1", "AC#2", "AC#3", "AC#4", "AC#5", "AC#6", "AC#7"]
---

## Summary

Write the test suite that validates the seed script end-to-end: param builder extraction correctness, scenario generation smoke tests, determinism, FK violation detection, consistency assertion detection, and CLI query verification. These are the acceptance criteria tests that prove the feature works.

## Target Files

- create: `tests/unit/core/test_param_builders.py`
- create: `tests/integration/test_seed_db.py`
- modify: `CLAUDE.md`
- read: `src/hassette/core/telemetry/repository.py`
- read: `scripts/seed_db.py`
- read: `src/hassette/test_utils/factories.py`

## Prompt

### Unit tests: `tests/unit/core/test_param_builders.py`

Test the extracted param builder functions:

1. **`test_job_insert_params_matches_register_job`** — verify `job_insert_params(make_job_registration())` produces a dict with all the same keys and values that the original inline dict in `register_job()` would produce. Specifically verify `"repeat": 0` is present and hardcoded.

2. **`test_execution_insert_params_round_trip`** — verify `execution_insert_params(make_execution_record())` produces a dict with keys matching the `executions` table columns. Verify boolean fields are coerced to int (SQLite has no native bool).

3. **`test_listener_insert_params_round_trip`** — verify `listener_insert_params(make_listener_registration())` produces a dict with keys matching the `listeners` table columns.

4. **`test_job_insert_params_repeat_always_zero`** — verify that `job_insert_params` always returns `repeat=0` regardless of input (there is no `repeat` field on `ScheduledJobRegistration`, so this confirms the hardcode).

### Integration tests: `tests/integration/test_seed_db.py`

Test the seed script end-to-end by running it as a subprocess or importing `main()` directly. Use `tmp_path` fixture for output files.

5. **`test_scenario_generates_file` (parametrized over all 7 scenarios, AC#5)** — run `uv run python scripts/seed_db.py --scenario <name> --output <tmp_path>/test.db`, assert exit code 0, assert file exists and is non-empty (except `empty` which is just the schema).

6. **`test_healthy_scenario_generates_file` (AC#1)** — specifically verify the healthy scenario: exit 0, non-empty SQLite file, can be opened and queried.

7. **`test_determinism` (AC#2)** — run the same scenario twice to two different output paths. For each of the 6 tables, run `SELECT * FROM <table> ORDER BY id` (or `ORDER BY rowid` for tables without `id`) against both databases. Assert the results are identical.

8. **`test_fk_violation_detected` (AC#3)** — modify the seed script's behavior to intentionally insert an execution with a non-existent `listener_id`. Assert the script aborts with a non-zero exit code and an error message mentioning FK violation. This can be done by temporarily monkey-patching `SeedContext.add_execution` or by creating a minimal scenario function that inserts a bad FK.

9. **`test_consistency_assertion_catches_dangling_execution_id` (AC#4)** — similar to above: intentionally insert a `log_records` row with an `execution_id` that doesn't exist in `executions`. Assert the script aborts with a non-zero exit code mentioning the consistency check.

10. **`test_cli_queries_against_seeded_db` (AC#6)** — this test is more complex: it requires a running hassette instance pointed at the seeded DB. If this is not feasible in the integration test layer (hassette requires HA to start — see #1435), write this as a manual verification step documented in the test file with `@pytest.mark.skip(reason="requires running hassette instance — verify manually")` and a docstring explaining the manual steps. Alternatively, if the CLI client can be tested by mocking the HTTP layer, do that.

11. **`test_lint_passes` (AC#7)** — this is verified by `prek -a` during the pre-commit review, not by a test. No test file needed for this AC. Include it in the Verify section as "verified by pre-commit lint."

### Documentation update

Add seed script usage to `CLAUDE.md` under the Common Commands section:

```bash
# Seed a telemetry database for dev/QA
uv run python scripts/seed_db.py --scenario healthy --output /tmp/hassette-healthy.db
```

List the available scenarios (healthy, empty, degraded, error, large-volume, lifecycle, adversarial).

### Test conventions

- Use `tmp_path` pytest fixture for all generated DB files (automatic cleanup).
- Import factories from `hassette.test_utils.factories` (the new `make_execution_record`, `make_blocking_event`, `make_log_record` from T03).
- For subprocess tests, use `subprocess.run(["uv", "run", "python", "scripts/seed_db.py", ...])` with `capture_output=True`.
- Tests that open SQLite databases should use `sqlite3.connect(path)` directly (no aiosqlite needed — these are read-only queries).

## Focus

- The parametrized scenario smoke test (test 5) is the most important — it catches scenario generation failures early. Use `@pytest.mark.parametrize("scenario", ["healthy", "empty", "degraded", "error", "large-volume", "lifecycle", "adversarial"])`.
- The FK violation test (test 8) must NOT use `INSERT OR REPLACE` to work around the violation — the test proves the check works by letting the violation happen and verifying the script catches it.
- The determinism test (test 7) should compare at the SQL level, not file bytes — SQLite internal page layout can differ even with identical data. Compare row-by-row query results.
- AC#6 (CLI queries) may need to be deferred if a running hassette instance isn't available in the test environment. Document this clearly rather than writing a flaky test.
- Check the test directory structure: unit tests go in `tests/unit/core/`, integration tests in `tests/integration/`. Check for existing `conftest.py` in each directory.

## Verify

- [ ] AC#1: test_healthy_scenario_generates_file passes (exit 0, non-empty SQLite file)
- [ ] AC#2: test_determinism passes (two runs produce identical query results)
- [ ] AC#3: test_fk_violation_detected passes (script aborts on bad listener_id)
- [ ] AC#4: test_consistency_assertion_catches_dangling_execution_id passes (script aborts on dangling execution_id)
- [ ] AC#5: test_scenario_generates_file passes for all 7 scenarios
- [x] AC#6: CLI queries verified via documented manual-verification test (`@pytest.mark.skip` with manual steps in docstring) — automated coverage blocked on #1435 (HA-optional startup), accepted as out of scope for this task
- [ ] AC#7: `prek -a` passes (verified by pre-commit lint, not a test)
