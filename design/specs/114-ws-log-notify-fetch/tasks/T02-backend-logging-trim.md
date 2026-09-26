---
task_id: "T02"
title: "Trim LogEntry, _extract_correlation_attrs, and emit log_hint"
status: "done"
depends_on: ["T01"]
implements: ["FR#2", "FR#3", "AC#2"]
---

## Summary
Remove the three linking fields (`execution_kind`, `listener_id`, `job_id`) from the WS broadcast path: trim `_extract_correlation_attrs` and `LogEntry` dataclass. Change `LogCaptureHandler.emit()` to broadcast a `log_hint`-shaped dict instead of a full `LogEntry`. **Leave `_RECORD_FIELDS` and `CorrelationFilter` unchanged** — `_RECORD_FIELDS` serves the console/JSON log formatter (`promote_record_attrs` in `ProcessorFormatter`), not the WS path, and `CorrelationFilter` continues to stamp all fields including linking fields (they're still useful in console output).

## Target Files
- modify: `src/hassette/logging_.py`
- modify: `tests/unit/test_logging_setup.py`
- modify: `tests/unit/test_logging_capture_handler.py`
- read: `src/hassette/web/models.py` (for `LogHintWsMessage` shape from T01)
- read: `design/specs/114-ws-log-notify-fetch/design.md`

## Prompt
In `src/hassette/logging_.py`:

1. **Leave `_RECORD_FIELDS` unchanged** — it is used by `promote_record_attrs()` (line ~386) in the `ProcessorFormatter` chain for console/JSON log output, NOT the WS broadcast path. The linking fields (`execution_kind`, `listener_id`, `job_id`) are useful diagnostics in console logs and must stay.

2. **Leave `CorrelationFilter` unchanged** — it continues to stamp all fields onto log records including linking fields. Its role as the context-var→record bridge is unchanged. The only downstream consumer being removed is `_extract_correlation_attrs` → `LogEntry` → WS broadcast.

3. **Trim `_extract_correlation_attrs`** — remove extraction of `execution_kind`, `listener_id`, `job_id` from the function's return dict. Keep `execution_id`, `app_key`, `source_tier`, `instance_name`, `instance_index` (those are still needed for the `LogEntry` buffer and DB persistence via `LOG_RECORD_COLUMNS`).

4. **Trim `LogEntry` dataclass** (lines 64-82) — remove the three linking fields. `LogEntry` is only instantiated by `LogCaptureHandler.emit()` for the in-memory buffer — `LogPersistenceHandler` builds its own dict directly from the `LogRecord` via `record_to_dict()`, never constructing a `LogEntry`.

5. **Change `LogCaptureHandler.emit()`** (lines 151-176) — instead of building a full `LogEntry` and broadcasting `entry.to_dict()`, broadcast a minimal `log_hint`-shaped dict: `{"type": "log_hint", "timestamp": time.time()}`. The handler still needs to buffer the entry for the in-memory buffer (if that's used), but the broadcast payload is now just the hint.

6. **Update `tests/unit/test_logging_setup.py`** — update tests that assert `LogEntry` field set or `_extract_correlation_attrs` output for the three removed linking fields. Tests asserting `_RECORD_FIELDS` and `CorrelationFilter` stamping behavior should be **left unchanged** (those paths are unaffected).

7. **Update `tests/unit/test_logging_capture_handler.py`** — imports `LogWsMessage` (now `LogHintWsMessage` from T01), validates broadcast envelope against it. Update to assert the new `log_hint` envelope shape (`{"type": "log_hint", "timestamp": <float>}`), not the old full `LogEntry` dict.

## Focus
- **Critical distinction:** `_RECORD_FIELDS` serves `promote_record_attrs()` (the console/JSON formatter path via `ProcessorFormatter`), NOT the WS broadcast. Do NOT trim `_RECORD_FIELDS`. The WS broadcast path is `_extract_correlation_attrs()` → `LogEntry` → `to_dict()` → `emit()` — that's what gets trimmed.
- `CorrelationFilter` stays unchanged — it stamps all fields including linking fields. Only `_extract_correlation_attrs` and `LogEntry` stop reading/carrying the linking fields.
- `record.seq` is stamped by `CorrelationFilter.filter()` synchronously via `itertools.count(1)` — this STAYS.
- `LogPersistenceHandler.record_to_dict()` (lines 343-353) builds its own dict from the `LogRecord` plus `_extract_correlation_attrs()` — removing linking fields from `_extract_correlation_attrs` is safe because those fields are not in `LOG_RECORD_COLUMNS` and are silently ignored by the INSERT.
- The `_buffer` deque in `LogCaptureHandler` may still store `LogEntry` objects for non-broadcast purposes — check whether anything reads from it besides the broadcast path.

## Verify
- [ ] FR#2: `_extract_correlation_attrs()` no longer returns `execution_kind`, `listener_id`, or `job_id`; `CorrelationFilter` and `_RECORD_FIELDS` are unchanged
- [ ] FR#3: `LogEntry` dataclass has no `execution_kind`, `listener_id`, or `job_id` fields
- [ ] AC#2: `_extract_correlation_attrs()` does not return linking fields; `_RECORD_FIELDS` is unchanged (still includes linking fields for console/JSON output)
