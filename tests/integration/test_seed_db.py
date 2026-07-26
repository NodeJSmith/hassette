"""Integration tests for scripts/seed_db.py -- the deterministic telemetry DB seeder.

Covers, per design/specs/017-seed-db/design.md: the healthy scenario producing a non-empty
SQLite file, running a scenario twice producing identical query results, a dangling
executions.listener_id aborting the run via a real foreign key violation, a dangling
log_records.execution_id aborting the run via the post-seed consistency assertion, and all 7
named scenarios generating without errors. CLI queries against a seeded database are
documented as a manual verification step (see test_cli_queries_against_seeded_db) since they
require a running hassette instance. Lint and type checking are verified separately by
`prek -a`, not by a test in this file.

Most tests shell out to the real CLI entry point (`uv run python scripts/seed_db.py ...`),
matching the exact invocation documented in the design doc. The FK-violation and
consistency-assertion tests need to inject a deliberately broken scenario, which the CLI's
fixed `--scenario` choices don't allow -- those import `seed_db` directly (the `scripts/`
directory is on `pythonpath` per pyproject.toml) and call `generate_scenario()` with a
temporary scenario registered via `monkeypatch.setitem`.
"""

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import seed_db

from hassette.test_utils.factories import make_execution_record

REPO_ROOT = Path(__file__).resolve().parents[2]

ALL_SCENARIOS = ("healthy", "empty", "degraded", "error", "large-volume", "lifecycle", "adversarial")

_TABLES = ("sessions", "listeners", "scheduled_jobs", "executions", "log_records", "blocking_events")


def _run_seed_script(scenario: str, output: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the seed script exactly as documented in the design doc's acceptance criteria."""
    return subprocess.run(
        ["uv", "run", "python", "scripts/seed_db.py", "--scenario", scenario, "--output", str(output)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )


@pytest.mark.parametrize("scenario", ALL_SCENARIOS)
def test_scenario_generates_file(scenario: str, tmp_path: Path):
    """All 7 named scenarios generate without errors.

    ``empty`` is the one exception to "non-trivial data" -- it asserts a zero row count
    across all 6 tables instead, per the design doc's Edge Cases section.
    """
    output = tmp_path / "test.db"

    result = _run_seed_script(scenario, output)

    assert result.returncode == 0, f"seed script failed for scenario={scenario!r}:\n{result.stdout}\n{result.stderr}"
    assert output.exists()
    assert output.stat().st_size > 0

    conn = sqlite3.connect(output)
    try:
        counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in _TABLES}
    finally:
        conn.close()

    if scenario == "empty":
        assert all(count == 0 for count in counts.values()), counts
    else:
        assert counts["sessions"] > 0, counts
        assert counts["listeners"] > 0 or counts["scheduled_jobs"] > 0, counts
        assert counts["executions"] > 0, counts


def test_healthy_scenario_generates_file(tmp_path: Path):
    """`uv run python scripts/seed_db.py --scenario healthy --output ...` exits 0 and
    produces a non-empty, queryable SQLite file.
    """
    output = tmp_path / "test.db"

    result = _run_seed_script("healthy", output)

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert output.exists()
    assert output.stat().st_size > 0

    conn = sqlite3.connect(output)
    try:
        for table in _TABLES:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if table == "blocking_events":
                assert count >= 1, f"{table} should have at least the healthy scenario's one blocking event"
            else:
                assert count > 0, f"{table} should be non-empty for the healthy scenario"
    finally:
        conn.close()


def test_determinism(tmp_path: Path):
    """Running the same scenario twice produces identical `SELECT * ... ORDER BY id`
    results for all 6 tables. Compared at the SQL row level, not file bytes -- SQLite's
    internal page layout can differ even when the logical content is identical.
    """
    output_1 = tmp_path / "run1.db"
    output_2 = tmp_path / "run2.db"

    for output in (output_1, output_2):
        result = _run_seed_script("healthy", output)
        assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"

    conn_1 = sqlite3.connect(output_1)
    conn_2 = sqlite3.connect(output_2)
    try:
        for table in _TABLES:
            rows_1 = conn_1.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            rows_2 = conn_2.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            assert rows_1 == rows_2, f"table '{table}' differs between two runs of the same scenario"
    finally:
        conn_1.close()
        conn_2.close()


def _bad_fk_scenario(ctx: seed_db.SeedContext) -> None:
    """Scenario that deliberately inserts an execution referencing a listener that doesn't exist."""
    session_id = ctx.add_session(started_at=0.0, last_heartbeat_at=1.0)
    ctx.add_execution(
        make_execution_record(
            execution_id="test_bad_fk_0001",
            session_id=session_id,
            listener_id=999_999,  # no listeners row has this id -- real FK constraint violation
            job_id=None,
        )
    )


def test_fk_violation_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A dangling `executions.listener_id` aborts the run with a foreign key violation.

    `executions.listener_id` is a real `REFERENCES listeners(id)` foreign key (unlike
    `log_records.execution_id`, see test_consistency_assertion_catches_dangling_execution_id
    below), so SQLite's own FK enforcement (`PRAGMA foreign_keys = ON`, set immediately after
    connect) raises `sqlite3.IntegrityError` at INSERT time -- no `INSERT OR REPLACE` or other
    silent-corruption workaround is used to make this pass; the violation is left to happen
    and the test verifies the script's own integrity machinery catches it.
    """
    monkeypatch.setitem(seed_db.SCENARIOS, "test_bad_fk", _bad_fk_scenario)

    output = tmp_path / "bad_fk.db"
    tmp = output.with_name(output.name + ".tmp")

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        seed_db.generate_scenario("test_bad_fk", output, tmp)

    assert not output.exists(), "output file must not be written when a scenario fails integrity checks"


def _bad_log_record_scenario(ctx: seed_db.SeedContext) -> None:
    """Scenario that deliberately inserts a log_records row with a dangling execution_id."""
    ctx.add_log_record(
        seq=1,
        timestamp=0.0,
        level="INFO",
        logger_name="hassette.test",
        message="dangling execution_id",
        execution_id="test_dangling_exec_0001",  # no executions row has this execution_id
    )


def test_consistency_assertion_catches_dangling_execution_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A dangling `log_records.execution_id` aborts the run via the consistency assertion.

    `log_records.execution_id` and `blocking_events.execution_id` are bare strings with no FK
    constraint (write-ordering in production means the execution row may not exist yet when a
    log line is written) -- so SQLite's own FK check can't catch this. The post-seed LEFT JOIN
    assertion (`_assert_no_dangling_execution_ids`) is what has to catch it instead.
    """
    monkeypatch.setitem(seed_db.SCENARIOS, "test_bad_log", _bad_log_record_scenario)

    output = tmp_path / "bad_log.db"
    tmp = output.with_name(output.name + ".tmp")

    with pytest.raises(seed_db.SeedIntegrityError, match="log_records"):
        seed_db.generate_scenario("test_bad_log", output, tmp)

    assert not output.exists(), "output file must not be written when a scenario fails integrity checks"


def test_main_reports_clean_message_for_migration_lock_contention(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A same-path collision surfaces as a RuntimeError wrapping a real sqlite3.OperationalError
    (the shape migration_runner.py actually produces, not a raw OperationalError) -- main()
    must recognize this via the exception's __cause__ and print a clear message instead of
    letting the raw traceback leak.
    """
    lock_error = sqlite3.OperationalError("attempt to write a readonly database")

    def _fake_generate_scenario(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Migration 3 (003.sql) failed: attempt to write a readonly database") from lock_error

    monkeypatch.setattr(seed_db, "generate_scenario", _fake_generate_scenario)
    monkeypatch.setattr(sys, "argv", ["seed_db.py", "--scenario", "healthy", "--output", str(tmp_path / "out.db")])

    with pytest.raises(SystemExit, match=r"Another seed_db\.py run may be writing"):
        seed_db.main()


def test_main_reraises_unrelated_migration_runtime_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A RuntimeError not caused by lock contention (a real migration bug) must propagate with
    its own message, not get swallowed into the friendly concurrent-run message -- proves the
    __cause__ check is narrow, not a blanket RuntimeError catch.
    """

    def _fake_generate_scenario(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Migration 3 (003.sql) failed: unexpected token in CREATE TABLE statement")

    monkeypatch.setattr(seed_db, "generate_scenario", _fake_generate_scenario)
    monkeypatch.setattr(sys, "argv", ["seed_db.py", "--scenario", "healthy", "--output", str(tmp_path / "out.db")])

    with pytest.raises(RuntimeError, match="unexpected token"):
        seed_db.main()


@pytest.mark.skip(reason="requires a running hassette instance pointed at the seeded DB -- see issue #1435")
def test_cli_queries_against_seeded_db():
    """`hassette status/app/listener/job/log` return meaningful output against a seeded DB.

    hassette's CLI commands query a *running* hassette web API, which itself requires a live
    connection to Home Assistant to start (see design/specs/017-seed-db/design.md,
    "Dependencies and Assumptions" -- HA-optional startup is tracked separately as issue
    #1435). A seeded DB is a standalone SQLite file with no process behind it, so there is no
    way to automate this check today without either a real HA instance or the HA-optional
    startup mode this feature explicitly treats as a non-goal (see design.md "Non-Goals").

    Manual verification steps:
        1. `uv run python scripts/seed_db.py --scenario healthy --output /tmp/hassette-healthy.db`
        2. Point a running hassette instance's `database.path` at the seeded DB file (or copy
           the file into the instance's configured data directory).
        3. Start hassette against a real (or demo-stack) Home Assistant instance.
        4. Run each of: `hassette status`, `hassette app`, `hassette listener --app
           weather_watcher`, `hassette job`, `hassette log --app weather_watcher`.
        5. Confirm every command exits 0 and prints non-empty table output reflecting the
           seeded data (5 apps, mixed listener/job counts, execution history).
    """


# Lint and type checking have no automated test here -- they are verified by `prek -a`
# (ruff + pyright) during pre-commit review, not by this test suite.
