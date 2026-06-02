# Troubleshooting

**Status:** Exists (140 lines), needs JTBD redesign — good content but mixes symptom-lookup with operational how-to
**Voice mode:** Direct, "you" allowed, symptom/cause/fix format
**Page type:** Troubleshooting
**Reader's job:** Something is broken. Find the symptom, read the cause, apply the fix.

## What was cut (and where it goes)

The existing page mixes two reader jobs: "fix this specific problem" (belongs
here) and "understand how the system behaves at runtime" (belongs in Operating).

Moved to Operating:
- "Home Assistant goes offline" section (WebSocket reconnection sequence,
  `ServiceWatcher` restart behavior, log signatures) — this is operational
  knowledge, not a symptom the reader is troubleshooting. Readers who need
  this are not broken; they want to understand normal behavior.
- "Event handler exceptions" section (exception handling behavior, log
  format) — same: this is "how does the framework handle errors?" not "I have
  a problem."
- "Upgrading Hassette" section — moves to Operating/upgrading.md.

What stays: pure symptom-lookup. Each H2 is a symptom a reader sees. Each
entry has: what to check, the likely cause, the fix.

Exception Reference added as a final section — readers who see an unfamiliar
exception name in their logs can look it up here.

## Outline

Each H2 is a symptom. Format: flat, scannable. No sub-categories.

### H2: Can't Connect to Home Assistant
- Token: verify `HASSETTE__TOKEN`. Link to Auth.
- Connection refused/timeout: check `base_url`. Docker: HA network
  reachability. Link to Docker Troubleshooting.

### H2: Apps Not Loading
Three log signatures:
- Syntax error or bad import — `SyntaxError` / `ModuleNotFoundError`
- Class not found — `class_name` doesn't match actual class
- Invalid configuration — required `AppConfig` field missing

Workaround: `allow_startup_if_app_precheck_fails = true` temporarily.
Link to Application Configuration.

### H2: Handler Registration Fails
`ListenerNameRequiredError` — `name=` is required on every bus subscription.
Most common error for new users. Fix: add `name="descriptive_name"`.

`DuplicateListenerError` — same `(app_key, instance_index, name, topic)`
registered twice. Fix: use unique names or check for double registration
in `on_initialize`.

### H2: Handler Never Fires
Checklist, ordered by likelihood:
1. Entity ID typo — no error, handler simply never matches.
2. `changed_to` type mismatch — `True` vs `"on"`. HA values are strings.
3. Domain excluded — `bus_excluded_domains`/`bus_excluded_entities` silently
   drop events.
4. Attribute-only change — use `on_attribute_change` or `changed=False`.
5. App not enabled — check `enabled = true` in config.

### H2: Scheduler Not Firing
- Past-time: `run_once(at="07:00")` after 7 AM defers to tomorrow.
- Units: `seconds=5` is 5 seconds, not minutes.
- Cron: `"5 * * * *"` is minute 5 of every hour, not every 5 minutes.
  Use `"*/5 * * * *"`.
- Exception in task: logged at ERROR, doesn't crash scheduler.
  Link to Job Management troubleshooting.

### H2: Database Degraded / Telemetry Missing
Stats strip shows zeros. Check disk space (Docker: `docker compose exec
hassette df -h /data`). DB file at `/data/hassette.db`. Safe to delete —
only loses history. Restart to recreate. Link to Database & Telemetry.

### H2: Cache Not Persisting
Check `data_dir` config and volume mount. Instance name key prefix for
multi-instance apps. Link to Cache patterns.

### H2: Custom State Class Not Registering
`domain: Literal["your_domain"]` field required. Call
`super().__init_subclass__()` if overriding. Link to Custom States.

### H2: Web UI Not Accessible
- Port/URL: `http://localhost:8126/ui/`
- Docker: `ports: ["8126:8126"]`
- Disabled: check `run` and `run_ui` under `[hassette.web_api]`.
  Link to Web UI overview.

### H2: Docker-Specific Issues
Pointer to Docker Troubleshooting page for container startup, dependency
installation, health checks, hot reload, performance.

### H2: Exception Reference
Common exceptions organized by category. Per-entry: what triggers it, what
to do. Not full API reference — link to auto-generated docs for complete list.

- **Connection:** `InvalidAuthError`, `BaseUrlRequiredError`,
  `CouldNotFindHomeAssistantError`, `ConnectionClosedError`
- **Registration:** `ListenerNameRequiredError`, `DuplicateListenerError`
- **State conversion:** `EntityNotFoundError`, `DomainNotFoundError`,
  `RegistryNotReadyError`
- **Dependency injection:** `DependencyInjectionError`,
  `DependencyResolutionError`
- **Lifecycle:** `InvalidLifecycleTransitionError` (has `from_status`,
  `to_status`, `resource_name` attributes)
- **Configuration:** `AppPrecheckFailedError`
- **Framework:** `HassetteError` (base), `FatalError` (non-restartable,
  triggers shutdown)

## Snippet Inventory

No code snippets — log signatures and config examples inline.

## Cross-Links

- **Links to:** Operating (runtime behavior), Docker Troubleshooting, Auth, Application Configuration, Database & Telemetry, Cache patterns, Custom States, Web UI overview, Job Management
- **Linked from:** Getting Started (next steps), many concept pages, Home page
