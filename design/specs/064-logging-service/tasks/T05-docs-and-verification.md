---
task_id: "T05"
title: "Update documentation and run full verification"
status: "done"
depends_on: ["T04"]
implements: ["FR#10", "AC#12"]
---

## Summary
Update CLAUDE.md to document LoggingService in the architecture overview. Verify AC#12 (RuntimeQueryService accesses capture handler via LoggingService property). Run the full test suite including integration and system tests to confirm no regressions.

## Prompt
1. Update `CLAUDE.md` — in the "Core Components" section, add a description of LoggingService:
   ```
   **LoggingService** (`src/hassette/core/logging_service.py`) - Manages the async logging pipeline lifecycle. A Resource with `depends_on=[DatabaseService]` that upgrades logging from synchronous (console-only) to asynchronous (console + capture + persistence) during `on_initialize()`. Owns the QueueListener, LogCaptureHandler, and LogPersistenceHandler. The async pipeline starts unconditionally; persistence degrades gracefully on failure.
   ```
   Place it logically near the existing DatabaseService description.

2. Verify that RuntimeQueryService accesses capture handler only via `self.hassette.logging_service.capture_handler`:
   ```
   grep -rn "get_log_capture_handler\|get_log_persistence_handler" src/hassette/ --include="*.py"
   ```
   Should return zero results. If any remain, fix them.

3. Verify no external access to command_executor.repository:
   ```
   grep -rn "command_executor\.repository\|command_executor.repository" src/hassette/ --include="*.py"
   ```
   Should only match within `src/hassette/core/command_executor.py` itself.

4. Run the full verification suite:
   - `timeout 300 uv run pytest tests/unit/ tests/integration/ -v -n 2`
   - `timeout 300 uv run pyright`
   - If core files changed: `timeout 300 uv run nox -s system` and `timeout 300 uv run nox -s e2e`

## Focus
- CLAUDE.md has a specific structure for Core Components — follow the existing style (bold name, file path in parens, description).
- The grep checks are the AC verification — they must produce the expected results before claiming completion.
- System and e2e tests are required per CLAUDE.md's "Pre-Ship Verification for Core Changes" section since we're modifying files in `src/hassette/core/`.

## Verify
- [ ] FR#10: RuntimeQueryService accesses capture handler via LoggingService (grep confirms no module-level accessor usage)
- [ ] AC#12: RuntimeQueryService accesses capture handler through LoggingService property, not module-level global
