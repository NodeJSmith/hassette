---
task_id: "T09"
title: "Add CLI smoke tests against demo setup"
status: "planned"
depends_on: ["T05", "T06", "T07", "T08"]
implements: ["AC#1", "AC#3", "AC#4", "AC#11", "AC#5", "AC#8"]
---

## Summary

Run the CLI against the existing system test demo hassette setup (Docker HA container + demo app fixtures) to verify real HTTP round-trips, response deserialization, and human/JSON rendering against actual API data. These are end-to-end smoke tests — not mocked. They catch integration issues that unit tests with mock responses miss.

## Prompt

### Create `tests/system/test_cli_smoke.py`

Use the existing system test infrastructure in `tests/system/conftest.py`:
- The `ha_container` fixture provides a running HA Docker container
- `make_web_system_config()` builds a config pointing at the container
- `startup_context()` starts a hassette instance with demo apps
- `wait_for_web_server()` waits for the API to be ready

Start a hassette instance with the demo fixture apps, then invoke CLI commands against it. The CLI commands need the server's host and port — pass them via environment variables (`HASSETTE__WEB_API__HOST`, `HASSETTE__WEB_API__PORT`) or construct a config file.

**Invocation approach:** Import the cyclopts App and call command functions directly (in-process), or use `subprocess.run(["hassette", "status", "--json"])` for true end-to-end. Subprocess is more realistic but requires the package to be installed. Choose based on what the system test infrastructure already supports — check how `tests/system/test_web_api.py` invokes the API.

### Test cases

Exercise each subcommand in both human and JSON mode:

**System commands:**
- `hassette status` — verify non-empty response, status field present
- `hassette status --json` — verify valid JSON, deserializable to `SystemStatusResponse`
- `hassette config --json` — verify valid JSON
- `hassette service --json` — verify valid JSON dict
- `hassette telemetry --json` — verify valid JSON
- `hassette dashboard --json` — verify valid JSON with app grid data
- `hassette event --limit 5 --json` — verify JSON list with ≤5 entries

**App commands:**
- `hassette app --json` — verify JSON with manifests list
- `hassette app health <demo-app-key> --json` — verify JSON health response
- `hassette app activity <demo-app-key> --limit 5 --json` — verify JSON list

**Listener and job commands:**
- `hassette listener --json` — verify JSON list of listeners
- `hassette listener --app <demo-app-key> --json` — verify filtered results
- `hassette listener --app <demo-app-key> --instance 0 --json` — verify instance-filtered results
- `hassette job --json` — verify JSON list of jobs

**Log and execution commands:**
- `hassette log --since 1h --limit 10 --json` — verify JSON list with ≤10 entries
- `hassette log --app <demo-app-key> --json` — verify filtered results
- `hassette execution <uuid> --json` — trigger an invocation first (via state change), capture its execution_id from logs, then query it. Verify JSON response with log entries

**Error handling:**
- `hassette status` against a stopped server (wrong port) — verify non-zero exit, error on stderr
- `hassette listener --instance 0` (no `--app`) — verify usage error

**Human mode spot checks:**
- `hassette status` (no `--json`) — verify output contains expected keywords (e.g., "ok", "uptime"), no JSON structure
- `hassette listener` — verify table-like output (headers present)

### Test markers

Mark all tests with `@pytest.mark.system` to match the existing system test convention. They should run as part of `uv run nox -s system`.

## Focus

- System test infrastructure: `tests/system/conftest.py` — `ha_container` fixture (line ~174), `make_web_system_config()`, `startup_context()` (line ~255), `wait_for_web_server()` (line ~326)
- Demo app fixtures: `tests/system/fixtures/` contains demo app configs that register listeners and jobs. Check which app_key values are available for filtering tests.
- The system test nox session (`noxfile.py` line 94) runs tests with `pytest -m system` — new tests with `@pytest.mark.system` will be included automatically.
- System tests require Docker — they're in a separate CI job (`.github/workflows/tests.yml` line 119).
- For JSON mode validation: parse stdout as JSON, verify it deserializes to the expected Pydantic model type. This catches serialization mismatches.
- For human mode: just verify output is non-empty and doesn't contain raw JSON structure — full rendering correctness is covered by unit tests.

## Verify

- [ ] AC#1: Every GET endpoint is exercised by at least one smoke test
- [ ] AC#3: JSON mode tests verify stdout contains valid parseable JSON with no other content
- [ ] AC#4: `listener --app <key>` returns a subset of the full listener list
- [ ] AC#11: `listener --app <key> --instance 0` returns instance-filtered results
- [ ] AC#5: `log --since 1h --limit 10` returns ≤10 entries (verified from JSON output)
- [ ] AC#8: Querying a non-existent server exits non-zero with an error message
