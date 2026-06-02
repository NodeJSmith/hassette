# Troubleshooting

**Status:** Exists (140 lines), restructuring — operational content moves to Operating, pure symptom-lookup stays
**Voice mode:** Direct, "you" allowed, problem/solution format

## Outline

Pure symptom-lookup. Each H2 is a symptom. Each entry: symptom description, likely causes, fixes. No how-to content — that lives in Operating Hassette.

### H2: Can't Connect to Home Assistant
Token issues, connection refused/timeout. Links to Auth, Docker Troubleshooting.

### H2: Apps Not Loading
App not discovered, import errors, precheck failures. **KI-04**: Include all three log signatures and the `allow_startup_if_app_precheck_fails` workaround.

### H2: Handler Registration Fails — `ListenerNameRequiredError`
`name=` is required on every bus subscription. Most common error for new users and migrators.

### H2: Duplicate Handler — `DuplicateListenerError`
Same `(app_key, instance_index, name, topic)` registered twice in a session.

### H2: Event Handler Never Runs
**KI-05**: `changed_to` type mismatch (string vs bool).
**KI-06**: `bus_excluded_domains`/`bus_excluded_entities` silently drop events.
**KI-07**: Attribute-only changes — use `on_attribute_change` for dedicated attribute monitoring; `on_state_change(changed=False)` fires on every state event regardless.
Also: entity ID typos, app not enabled.

### H2: Scheduler Not Firing
**KI-08**: Past-time behavior for `run_once` and `run_daily`, `seconds` vs `minutes` gotcha, cron expression pitfall. Links to Job Management troubleshooting.

### H2: Database Degraded / Telemetry Missing
**KI-09**: Zeroed stats strip, Docker disk check command, DB file location, safe to delete. Links to Database & Telemetry degraded mode.

### H2: Cache Not Persisting
**KI-10**: `data_dir` config, Docker volume mount, instance name key prefix. Links to Cache patterns troubleshooting.

### H2: Custom State Class Not Registering
**KI-11**: `domain: Literal[...]` field required, `super().__init_subclass__()` call. Links to Custom States troubleshooting.

### H2: Web UI Not Accessible
Port/URL, Docker port mapping, `web_api` settings.

### H2: Docker-Specific Issues
Pointer to Docker Troubleshooting page.

### H2: Exception Reference
Common exceptions app authors may encounter, organized by category:
- **Connection:** `InvalidAuthError`, `BaseUrlRequiredError`, `CouldNotFindHomeAssistantError`, `ConnectionClosedError`
- **Registration:** `ListenerNameRequiredError` (cross-link to H2 above), `DuplicateListenerError` (cross-link to H2 above)
- **State conversion:** `EntityNotFoundError`, `DomainNotFoundError`, `RegistryNotReadyError`
- **Dependency injection:** `DependencyInjectionError`, `DependencyResolutionError`
- **Lifecycle:** `InvalidLifecycleTransitionError` (includes `from_status`, `to_status`, `resource_name` attributes)
- **Configuration:** `AppPrecheckFailedError`
- **Framework:** `HassetteError` (base), `FatalError` (non-restartable, triggers shutdown)

Brief per-entry: what triggers it, what to do about it. Not a full API reference — link to auto-generated exception docs for the complete list.

**Removed from this page (moved to Operating):**
- WebSocket reconnection sequence → Operating/overview.md
- Event handler exception behavior → Operating/overview.md
- Upgrading Hassette → Operating/upgrading.md

## Snippet Inventory

No code snippets — log signatures and config examples are inline.

## Cross-Links

- **Links to:** Operating (runtime behavior), Docker Troubleshooting, Auth, Configuration, Database & Telemetry, Cache patterns, Custom States
- **Linked from:** Getting Started (next steps), many concept pages
