---
task_id: "T01"
title: "Replace coloredlogs with structlog processor chain"
status: "done"
depends_on: []
implements: ["FR#4", "FR#5", "FR#6", "FR#7", "FR#18", "AC#3", "AC#4", "AC#10", "AC#16"]
---

## Summary
Replace the unmaintained coloredlogs library with structlog's ProcessorFormatter approach. This is the foundation layer — all subsequent tasks build on the structlog processor chain. After this task, hassette produces structured log output (colored console in dev, JSON in prod) with stdlib compatibility preserved. No correlation IDs or persistence yet — those come in T02-T04.

## Prompt
1. Add `structlog>=24.4` to `pyproject.toml` dependencies. Remove `coloredlogs>=15.0.1`.

2. Rewrite `enable_logging()` in `src/hassette/logging_.py`:
   - Configure structlog with shared processors: `add_log_level`, `TimeStamper(fmt="iso")`, `ProcessorFormatter.wrap_for_formatter`
   - Create a `ProcessorFormatter` with `ConsoleRenderer` (dev) or `JSONRenderer` (prod)
   - Selection logic: if `log_format == "json"` → JSON; if `log_format == "console"` → console; if `log_format == "auto"` → `sys.stdout.isatty()` to choose
   - Set up `foreign_pre_chain` on `ProcessorFormatter` so stdlib `logging.getLogger()` records get the same structured fields
   - Keep the `hassette` logger as the root, keep `logger.propagate = False`
   - Keep noisy library suppression (requests, urllib3, aiohttp.access, httpx at WARNING)
   - Keep `logging.captureWarnings(True)` and the `sys.excepthook`/`threading.excepthook` handlers
   - Remove all `coloredlogs` references

3. Add `log_format: Literal["auto", "console", "json"] = Field(default="auto")` to `HassetteConfig` in `src/hassette/config/config.py`.

4. Update `enable_logging()` callers:
   - `src/hassette/core/core.py:75` — pass `log_format` from config
   - `src/hassette/__main__.py:66` — the entrypoint call is redundant (Hassette.__init__ calls it again). Simplify: either remove the entrypoint call or keep it as a basic fallback with `log_format="auto"`.

5. Add structlog bound variables to Resource/Service loggers:
   - In `src/hassette/resources/base.py:_setup_logger()`: after `self.logger = getLogger(...)`, wrap with `structlog.wrap_logger(self.logger, source_tier=self.source_tier, class_name=self.class_name)` or equivalent binding. The `source_tier` ClassVar already exists on Resource ("framework") and App ("app").
   - Verify that `src/hassette/app/app.py` inherits `source_tier = "app"` correctly.

6. Remove `register_app_logger()`, `_resolve_app_key()`, and `_logger_to_app_key` from `LogCaptureHandler`. Remove the call to `register_app_logger()` in `src/hassette/core/app_lifecycle_service.py:308` and `get_log_capture_handler()` import there if no longer needed.

7. Update `LogCaptureHandler.emit()` to read `source_tier` from the record (now stamped by the processor chain) instead of resolving it from logger name prefix matching.

8. Rewrite `tests/unit/test_logging.py` for structlog-based `enable_logging()`. Test that: ConsoleRenderer is used when `log_format="console"`, JSONRenderer when `log_format="json"`, TTY detection when `log_format="auto"`, noisy library suppression still works, LogCaptureHandler still captures records.

9. Update test fixtures that use `register_app_logger()`:
   - `tests/e2e/conftest.py:132-133` — remove `register_app_logger()` calls
   - `tests/integration/test_web_api.py:262-265` — remove `register_app_logger()` calls
   - `tests/unit/core/test_app_lifecycle_service.py` — update patches for removed function

## Focus
- `LogCaptureHandler` at `logging_.py:52-120` is the main class being modified. The `emit()` method (line 103) currently builds `LogEntry` by calling `_resolve_app_key()` — this must read from record attributes instead.
- `_setup_logger()` at `resources/base.py:209-221` is where structlog wrapping happens. The existing `source_tier` ClassVar is at `base.py:139` (framework) and `app.py:58` (app).
- The `coloredlogs.install()` call at `logging_.py:156` does something to the root logger that requires the cleanup at line 163. structlog's approach is cleaner — no root logger manipulation needed.
- `web_mocks.py:188` patches `get_log_capture_handler` — verify this still works if the function signature changes.
- structlog's `ProcessorFormatter` has three processor lists: (a) configure() processors (structlog-originated), (b) foreign_pre_chain (stdlib-originated), (c) processors (all records). Console/JSON renderer goes in (c).

## Verify
- [ ] FR#4: `coloredlogs` is not imported anywhere in the codebase; `structlog` is configured with a processor chain
- [ ] FR#5: Running with `log_format="auto"` in a terminal produces colored output; piping stdout produces JSON
- [ ] FR#6: Setting `log_format="json"` in config produces JSON output in a terminal
- [ ] FR#7: A stdlib `logging.getLogger("hassette.apps.test")` call produces structured output through the processor chain
- [ ] FR#18: `logging.getLogger("aiohttp.access").getEffectiveLevel()` returns WARNING
- [ ] AC#3: Console is colored in TTY, JSON in non-TTY
- [ ] AC#4: Config override forces JSON regardless of TTY
- [ ] AC#10: `coloredlogs` not in pyproject.toml or any import
- [ ] AC#16: aiohttp/urllib3/httpx/requests loggers suppressed at WARNING
