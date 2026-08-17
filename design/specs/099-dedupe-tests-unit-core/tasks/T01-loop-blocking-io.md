---
task_id: "T01"
title: "Deduplicate loop watchdog, blocking-IO guard, and execution timeout tests"
status: "done"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "AC#1", "AC#2", "AC#3", "AC#4"]
---

## Target Files

- modify: `tests/unit/core/test_block_io_guard.py`
- modify: `tests/unit/core/test_loop_watchdog.py`
- modify: `tests/unit/core/test_protect_loop_monkeypatch.py`
- modify: `tests/unit/core/test_execution_timeout.py`
- modify: `tests/unit/core/test_blocking_io_marker_spike.py` (verify only — expected no change)
- modify: `tests/unit/core/test_bus_dispatch_semaphore.py` (verify only — expected no change)
- modify: `tests/unit/core/test_event_filter.py` (verify only — expected no change)
- modify: `tests/integration/test_command_executor.py` (dup-ignore marker only, disjoint lines from T02's marker in the same file — see note below)
- modify: `tests/integration/test_thread_leaked_observability.py` (dup-ignore marker only)

## Prompt

Resolve every PMD-CPD duplicate-code cluster touching this group's files. Read the design doc at
`design/specs/099-dedupe-tests-unit-core/design.md` (Approach section, Group A row and the
"Shared external file between Group A and Group B" coordination note) for the full framework
before starting.

**Important — do not grep for cross-scope filenames.** `tests/integration/test_command_executor.py`
and `tests/integration/test_thread_leaked_observability.py` have plenty of *other* duplicate-code
clusters that have nothing to do with this group's files (pre-existing, out-of-scope debt). Grepping
for those filenames directly will surface unrelated clusters you cannot and should not resolve.
Only the 21 clusters listed below are this task's scope.

1. Run the unfiltered checker once and save it, so you can look up each cluster by line range
   below without re-running the ~3-minute full scan repeatedly:
   ```bash
   uv run python tools/check_duplicate_code.py > /tmp/dup-check-t01.txt 2>&1
   ```
   (The tool's raw output blank-line-separates clusters — `grep` on a filtered pattern will drop
   those blank lines and flatten everything into one list, so read the saved file directly with
   `Read`/`Grep -B/-A`, not a re-filtered grep, when you need to see a cluster's full fragment set.)

2. At sketch time (HEAD `2bf23966`) these were the 21 clusters touching this group's files — line
   numbers will have drifted since, especially after your own earlier edits in this same run, so
   treat this as a checklist of *what* to resolve, and re-derive current line numbers from your
   saved output each time:
   - `test_protect_loop_monkeypatch.py` — 7 clusters (self-contained, all fragments within this file)
   - `test_loop_watchdog.py` — 9 clusters (self-contained)
   - `test_block_io_guard.py` — 3 clusters (self-contained)
   - `test_execution_timeout.py` — 2 clusters: one self-contained (3 fragments within this file),
     and **one cross-scope** — pairs with `tests/integration/test_command_executor.py` AND
     `tests/integration/test_thread_leaked_observability.py` (a 4-fragment cluster: 2 in
     `test_execution_timeout.py`, 1 in each integration file). This is the only cluster in this
     group requiring an out-of-scope touch.
   - `test_blocking_io_marker_spike.py`, `test_bus_dispatch_semaphore.py`, `test_event_filter.py` —
     0 clusters each; confirm they stay that way.

3. For each cluster, inspect the actual fragments (`Read` the file at the cited line ranges) and
   decide extract vs. annotate:
   - **Extract** (default) when the block is mechanical boilerplate — e.g. repeated
     watchdog-tick/timeout-assertion setup within one file. Pull into a local helper or
     `pytest.fixture` in the same file, or shared across this group's own files if the cluster
     pairs two of them. Do **not** add a new fixture to `tests/unit/core/conftest.py` — check its
     existing catalog first (see its module docstring and directory `CLAUDE.md`) in case a fixture
     you'd add already exists there.
   - **Annotate** when the duplication is genuinely parallel structure, or crosses into
     `tests/integration/test_command_executor.py` or `tests/integration/test_thread_leaked_observability.py`
     (a different test tier — don't merge unit and integration test bodies). Wrap every occurrence
     in the cluster:
     ```python
     # dup-ignore-start: <specific reason>
     ...
     # dup-ignore-end
     ```
     The reason must be specific (e.g. "mirrors the integration-tier coverage of the same timeout
     behavior at a different mock depth"), not "intentional" alone.

4. **Coordination note**: `tests/integration/test_command_executor.py` is also touched by T02
   (a different task, different cluster, disjoint line ranges). If you see a `dup-ignore` marker
   already present in that file when you get to it, it's T02's — do not remove or modify it, only
   add your own pair around your own cluster's lines.

5. After resolving all clusters, verify with the same narrow grep the design doc's AC#1 uses —
   scoped to only this group's own in-scope filenames (no cross-scope filenames in the pattern).
   A cluster is only suppressed once *every* fragment across the whole repo is resolved, so if you
   forgot to mark the cross-scope side of the `test_execution_timeout.py` cluster, its in-scope
   fragment will still show up here — this narrow grep going quiet is sufficient proof the whole
   cluster (including any cross-scope fragment) is resolved:
   ```bash
   uv run python tools/check_duplicate_code.py 2>&1 | grep -E "tests/unit/core/test_(block_io_guard|loop_watchdog|protect_loop_monkeypatch|execution_timeout|blocking_io_marker_spike|bus_dispatch_semaphore|event_filter)\.py"
   ```
   Confirm no output.

6. Run the affected tests:
   ```bash
   uv run pytest tests/unit/core/test_block_io_guard.py tests/unit/core/test_loop_watchdog.py \
     tests/unit/core/test_protect_loop_monkeypatch.py tests/unit/core/test_execution_timeout.py \
     tests/unit/core/test_blocking_io_marker_spike.py tests/unit/core/test_bus_dispatch_semaphore.py \
     tests/unit/core/test_event_filter.py -v
   uv run pytest tests/integration/test_command_executor.py tests/integration/test_thread_leaked_observability.py -v
   ```

7. Run `prek -a` on every changed file and fix any lint/type findings.

## Verify

- [ ] FR#1/FR#2: the narrow grep from step 5 produces no output.
- [ ] FR#3: before extracting any new local helper/fixture, check `tests/unit/core/conftest.py`'s existing catalog (module docstring + directory `CLAUDE.md`) for one that already does the job. No new fixture added to `conftest.py` itself.
- [ ] AC#1: scoped grep from the design doc's AC#1 (filtered to this group's files) is clean.
- [ ] AC#2: all listed pytest commands pass with 0 failures.
- [ ] AC#3: `prek -a` clean on every changed file.
- [ ] AC#4: every `dup-ignore` marker has a specific, non-generic reason.
