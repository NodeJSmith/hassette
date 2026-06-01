# Knowledge Inventory

Extracted from current docs pages before overwrite. Every item below must appear in the rewritten troubleshooting or operating pages. Diff against the final pages to verify nothing was lost.

Source: `docs/pages/troubleshooting.md` (140 lines) and `docs/pages/advanced/log-level-tuning.md` (99 lines)

---

## Operational Behavior (→ Operating Hassette)

### KI-01: WebSocket Reconnection Sequence
**Source:** troubleshooting.md lines 31-61

**Timing values:**
- Initial connection retries: up to **5 times** with exponential backoff
- Initial backoff: starts at **1 second**, caps at **32 seconds**
- ServiceWatcher RestartSpec: **5 restarts** within **300-second sliding window** (TRANSIENT type)
- Restart delay: exponential starting at **2 seconds**, doubling each attempt, capped at **60 seconds**
- EXHAUSTED_COOLING duration: **300 seconds**, then budget resets

**Bus events:**
- `hassette.event.websocket_disconnected` — fired on disconnect, apps can subscribe
- `hassette.event.websocket_connected` — fired on reconnect, budget resets

**App behavior during reconnection:**
- Bus, scheduler, state manager remain active
- API calls (`call_service()`, `get_state()`) raise `ResourceNotReadyError`
- Handlers resume receiving events on reconnect — no re-registration needed

**Log signatures:**
```
WARNING  hassette.WebsocketService -- Retrying _inner_connect in Xs as it raised CouldNotFindHomeAssistantError: ...
ERROR    hassette.WebsocketService -- Serve() task failed: CouldNotFindHomeAssistantError ...
INFO     hassette.ServiceWatcher   -- Service 'WebsocketService' restarting (attempt N, waiting Xs)
DEBUG    hassette.WebsocketService -- Connected to WebSocket at ws://...
INFO     hassette.ServiceWatcher   -- Service 'WebsocketService' in cooldown for 300.0s (cycle 1)
```

### KI-02: Event Handler Exception Behavior
**Source:** troubleshooting.md lines 62-83

**Behavior:** Exceptions caught by framework, logged at ERROR, swallowed. Do not propagate, crash app, or affect other handlers.

**Telemetry:** Invocation recorded with `status='error'` and error type/message.

**Log signature:**
```
ERROR hassette.CommandExecutor -- Handler error (topic=hass.event.state_changed.light.kitchen, handler=Listener<Hassette.MyApp.0 - on_light_change>)
Traceback (most recent call last):
  ...
AttributeError: 'NoneType' object has no attribute 'brightness'
```

**Note:** Matches scheduler behavior — exceptions fail silently (logged to error).

### KI-03: Log Level Tuning
**Source:** advanced/log-level-tuning.md lines 1-99

**Mechanism:** Per-service log level via `hassette.toml` `[hassette.log_levels]` section. Field names match internal service names.

**Available fields:**
- Listed in the current page (lines 28-50) — exact field names for each internal service

**Fallback behavior:** Fields not set fall back to the global log level.

**Per-app log levels:** Set in app config block, not in global log_levels.

**Example configurations:**
- Debugging the scheduler: `scheduler = "DEBUG"`
- Quieting the file watcher: `file_watcher = "WARNING"`
- Debugging HA communication: `websocket = "DEBUG"`, `api = "DEBUG"`

**Snippets moving:** 5 TOML files in `advanced/snippets/log-level-tuning/`

---

## Symptom-Lookup (→ Troubleshooting)

### KI-04: App Precheck Failure Signatures
**Source:** troubleshooting.md lines 14-20

**Log signatures:**
- Syntax error: `ERROR hassette.utils.app_utils — Failed to load app 'MyApp': SyntaxError: invalid syntax (at /apps/my_app.py:12)`
- Class not found: `AttributeError: Class MyApp not found in module apps.my_app`
- Invalid config: `ERROR ... Failed to load app 'MyApp' due to bad configuration`

**Workaround:** `allow_startup_if_app_precheck_fails = true` in hassette.toml (temporary, for diagnosis)

### KI-05: changed_to Type Mismatch
**Source:** troubleshooting.md line 25

`changed_to="on"` works; `changed_to=True` does not — HA state values are strings, not Python bools.

### KI-06: Silently Excluded Domains
**Source:** troubleshooting.md line 26

`bus_excluded_domains` and `bus_excluded_entities` in hassette.toml silently drop events before reaching handlers.

### KI-07: Attribute-Only Change Default
**Source:** troubleshooting.md line 28

`on_state_change` default `changed=True` only fires on state value change. Attribute-only changes require `changed=False`.

### KI-08: Scheduler Past-Time Behavior
**Source:** troubleshooting.md lines 87-90

- `run_once(at="07:00")` called after 7 AM → deferred to tomorrow (WARNING log)
- `run_daily(at="07:00")` → next 7 AM occurrence (today if before, tomorrow if after)
- `run_every(seconds=5)` gotcha: 5 seconds, not minutes
- Cron pitfall: `"5 * * * *"` = "at minute 5 of every hour", not "every 5 minutes" — use `"*/5 * * * *"`

### KI-09: Database Degraded Mode
**Source:** troubleshooting.md lines 92-97

- Stats strip shows zeroed metrics when DB unavailable
- Docker check: `docker compose exec hassette df -h /data`
- Database file: `/data/hassette.db` (default)
- Safe to delete — only loses telemetry history. Restart recreates DB.

### KI-10: Cache Persistence
**Source:** troubleshooting.md lines 99-103

- Requires correct `data_dir` and writable path
- Docker: `/data` volume must be mounted
- All instances share one cache dir — use `instance_name` as key prefix

### KI-11: Custom State Registration
**Source:** troubleshooting.md lines 106-109

- Requires `domain: Literal["your_domain"]` field
- Must call `super().__init_subclass__()` if overriding

---

## Upgrading (→ Operating/Upgrading)

### KI-12: Version Check and Upgrade Commands
**Source:** troubleshooting.md lines 111-128

- `hassette --version` (CLI)
- `uv pip show hassette` (project)
- `uv add hassette@latest` (upgrade)
- Changelog at `CHANGELOG.md`, breaking changes flagged

### KI-13: Major Version Data Directory Change
**Source:** troubleshooting.md lines 128

- Bare-metal default `data_dir` includes major version: `~/.local/share/hassette/v0/`
- Future `v1/` would start fresh — set `data_dir`/`config_dir` explicitly to keep data
- Docker unaffected — `/data` and `/config` are version-independent

---

## Disposition

| Item | Destination | Notes |
|---|---|---|
| KI-01 | Operating/overview.md (Runtime Behavior) | Timing values, log signatures, bus events |
| KI-02 | Operating/overview.md (Runtime Behavior) | Exception handling behavior |
| KI-03 | Operating/log-levels.md | Moves from Advanced, content + 5 snippets |
| KI-04 | Troubleshooting | Symptom: apps not loading |
| KI-05 | Troubleshooting | Symptom: handler never runs |
| KI-06 | Troubleshooting | Symptom: handler never runs |
| KI-07 | Troubleshooting | Symptom: handler never runs |
| KI-08 | Troubleshooting | Symptom: scheduler not firing |
| KI-09 | Troubleshooting | Symptom: database degraded |
| KI-10 | Troubleshooting | Symptom: cache not persisting |
| KI-11 | Troubleshooting | Symptom: custom state not registering |
| KI-12 | Operating/upgrading.md | Version commands |
| KI-13 | Operating/upgrading.md | Data directory migration |
