# Web UI — Debug a Failing Handler

**Status:** Stub (3 lines), needs full JTBD design from scratch
**Voice mode:** Procedural — "you" allowed, task-focused
**Page type:** Procedural (task-oriented, light troubleshooting)
**Reader's job:** Figure out why their handler isn't firing, is throwing errors, or is firing too often — using the web UI to diagnose.

## What was cut

The old outline was organized by UI location (handlers page, app detail
handlers tab, invocation logs). A reader debugging a handler thinks in
symptoms: "it never fires", "it fires but errors", "it fires too often."
Leading with symptoms gets them to the right diagnostic step faster.

The "Common Causes" section from the old outline is the most valuable part
for this reader — promoted to appear early, before the detailed UI walkthrough.

## Outline

### Opening paragraph
Three things go wrong with handlers: they don't fire, they fire but error,
or they fire too often. The web UI shows which is happening and why.

### H2: Quick Diagnosis
Table mapping symptom to where to look:

| Symptom | Check | What to look for |
|---|---|---|
| Handler never fires | Handlers page | Missing from list, or zero invocations |
| Handler fires but errors | App detail > Handlers tab | Error count > 0, error details |
| Handler fires too often | App detail > Handlers tab | High invocation count, check predicate/debounce |

### H2: Common Causes
Flat list, scannable. Each entry: what went wrong, how to fix it.

- Missing `name=` on subscription — `ListenerNameRequiredError` at registration.
  Add `name="descriptive_name"` to the bus call.
- Wrong entity pattern — handler registered for `"light.kitchen"` but the
  entity is `"light.kitchen_ceiling"`. Check the listener's topic on the
  Handlers page.
- `changed_to` type mismatch — `changed_to=True` vs `changed_to="on"`. HA
  state values are strings.
- DI annotation mismatch — handler parameter annotated with the wrong state
  type. Check the `DependencyResolutionError` in the error details.
- Domain excluded — entity's domain is in `bus_excluded_domains`. Events
  silently dropped before reaching handlers.

### H2: Using the Handlers Page
Global handlers table: find your handler by app or name, see registration
status, invocation count, error count. How to read the columns.

### H2: Drilling into Handler History
App detail > Handlers tab shows per-handler invocation history with timestamps,
duration, and error details for each execution.

### H2: Tracing a Single Execution
Click an execution ID to filter the Logs page to that single invocation.
See every log line the handler emitted during that run.

## Snippet Inventory

No code snippets — UI documentation. Screenshots would help but are not
snippet files.

## Cross-Links

- **Links to:** Web UI overview, Logs page (execution ID filtering), Bus/Handlers (handler mechanics), Bus/DI (annotation reference), Troubleshooting (handler never runs)
- **Linked from:** Web UI overview, Manage Apps (if app shows errors)
