---
task_id: "T05"
title: "Add test-conventions rule, TESTING.md updates, and test CLAUDE.md files"
status: "planned"
depends_on: ["T01", "T02", "T03"]
implements: ["FR#16", "FR#17", "FR#19", "AC#8", "AC#11"]
---

## Summary
Create the `.claude/rules/test-conventions.md` file that closes the two-hop discovery gap, update TESTING.md with the factory naming convention and "before writing a factory" checklist, and add CLAUDE.md files to 5 test directories with module-specific fixture pointers. Depends on T01-T03 so the documentation reflects the final state of the factories and dead code cleanup.

## Target Files
- create: `.claude/rules/test-conventions.md`
- create: `tests/unit/bus/CLAUDE.md`
- create: `tests/unit/core/CLAUDE.md`
- create: `tests/integration/bus/CLAUDE.md`
- create: `tests/integration/web_api/CLAUDE.md`
- create: `tests/integration/telemetry/CLAUDE.md`
- modify: `tests/TESTING.md`
- read: `src/hassette/test_utils/factories.py`
- read: `src/hassette/test_utils/helpers.py`
- read: `src/hassette/test_utils/web_helpers.py`
- read: `tests/unit/bus/conftest.py`
- read: `tests/unit/core/conftest.py`
- read: `tests/integration/bus/conftest.py`
- read: `tests/integration/web_api/conftest.py`
- read: `tests/integration/telemetry/conftest.py`

## Prompt
### FR#16 — test-conventions.md

Create `.claude/rules/test-conventions.md`. Content requirements:
- Names the canonical factories in `test_utils/factories.py` and `test_utils/helpers.py` with import paths
- Links directly to the TESTING.md decision table (one hop, not two)
- Explicit prohibition: "Before defining a local `make_*` or `build_*` function in a test file, check `test_utils/factories.py` and `test_utils/helpers.py` for an existing factory"
- Names the `make_mock_hassette()` vs `create_hassette_stub()` decision rule inline (3-4 lines) — read `tests/TESTING.md` lines 27-37 for the canonical version
- Lists the 10 most-used test_utils symbols — determine these by grepping for `from hassette.test_utils` imports across `tests/`

### FR#17 — Test directory CLAUDE.md files

Create CLAUDE.md in 5 directories, each under 20 lines. Structure per the design doc's Architecture section:

```markdown
# Tests: <module>

## Available fixtures (this directory's conftest.py)
- `fixture_name` — what it provides

## Shared helpers
- `from helpers import func` — what it does

## Key conventions
- One-liner about the module-specific testing pattern
```

Read each directory's `conftest.py` to list the actual fixtures and helpers. For each directory:
- `tests/unit/bus/` — bus subscription/emission testing, the `hassette_with_bus` override
- `tests/unit/core/` — service-level testing with `make_executor`, `make_scheduler_service`, etc.
- `tests/integration/bus/` — bus integration with real components
- `tests/integration/web_api/` — HTTP/WebSocket testing with `mock_hassette`, `app`, `client` fixtures (after T03 moves them here)
- `tests/integration/telemetry/` — telemetry DB testing with `db_hassette` override

### FR#19 — TESTING.md updates

Update `tests/TESTING.md`:
1. Remove references to deleted items: `make_listener_metric`, `setup_registry`, `hassette_with_nothing` (T03 deletes them, this task updates the docs)
2. Update the `_HARNESS_FIXTURES` documentation: fixture count from "8 module-scoped" to "7 module-scoped" (if not already done in T03)
3. Add a `make_*/create_*/build_*` naming convention section explaining:
   - `make_scheduled_job()` for unit/scheduler tests (real ScheduledJob)
   - `make_real_job()` for web-layer behavior tests (real ScheduledJob, web defaults)
   - `make_job()` in `web_helpers` for serialization duck-types (SimpleNamespace)
   - `make_mock_*` prefix for mock-returning factories
4. Add a "Before writing a new factory" checklist:
   - Check `test_utils/factories.py` and `test_utils/helpers.py`
   - Check `test_utils/web_helpers.py` for web-layer factories
   - If a matching factory exists, import it
   - If it doesn't exist and you need it in 3+ files, add to `factories.py`
   - If truly local (different return type, different purpose), annotate with `# factory-local: <reason>`
5. Update the factory inventory section with the 6 new factories and their signatures

## Focus
- The rule file (`.claude/rules/test-conventions.md`) is loaded on every Claude Code session — keep it concise and actionable. The TESTING.md has the full details; the rule file is the one-hop pointer.
- For the 10 most-used symbols, run `grep -roh "from hassette.test_utils[._a-z]* import [A-Za-z_]*" tests/ | sed 's/.*import //' | sort | uniq -c | sort -rn | head -10`.
- CLAUDE.md files must be under 20 lines each. Module-specific pointers only — universal guidance lives in the rule file.
- Read each conftest.py before writing its directory's CLAUDE.md — list the actual fixtures, not guesses.

## Verify
- [ ] FR#16: `.claude/rules/test-conventions.md` exists, names canonical factories with import paths, links to TESTING.md, includes prohibition against local `make_*` without checking shared first
- [ ] FR#17: CLAUDE.md files exist in all 5 directories, each under 20 lines, listing actual fixtures from their conftest.py
- [ ] FR#19: TESTING.md contains naming convention section, "before writing a factory" checklist, updated factory inventory, no references to deleted items
- [ ] AC#8: `.claude/rules/test-conventions.md` names at least 10 most-used test_utils symbols with import paths
- [ ] AC#11: TESTING.md contains the naming convention section and factory checklist
