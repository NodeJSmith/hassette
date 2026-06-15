# Context: Blocking-I/O Detection for the Shared Event Loop

## Problem & Motivation

Hassette runs every user app on one shared asyncio event loop. A single app that calls a blocking primitive directly in a coroutine — `time.sleep(30)`, `requests.get(...)`, `open(...).read()`, a blocking DB driver — stalls the loop. While that call runs, no other app's handlers fire, the bus stops dispatching, the scheduler stops ticking, and WebSocket reconnect stalls. One careless line in one app degrades every app on the instance, and today nothing detects it or names the culprit. App authors get no signal — the loop just goes quiet. This feature detects loop stalls, attributes them to the offending app, and gives authors a dev-time guard that prevents the mistake outright.

## Visual Artifacts

None.

## Key Decisions

1. **Tiered design.** No single mechanism is cheap, always-on, complete, and precise. Tier 1 = an always-on loop-responsiveness watchdog (warn-after, names the app, catches even C-extension blocking as lag). Tier 2 = a `protect_loop`-style monkeypatch that intercepts the exact blocking primitive (raise, dev-default / prod-opt-in).
2. **Mirror `await_guard.py`.** The behavior enum (`IGNORE`/`WARN`/`ERROR`), config resolution (per-app → global → hardcoded default), warning class, and source capture all follow the existing forgotten-await machinery. This feature is "the same shape, different trigger."
3. **`ERROR` escalates via `warnings.filterwarnings`, never an unconditional raise.** A new `HassetteBlockingIOWarning(RuntimeWarning)` subclass; `ERROR` behavior is realized by the user's `filterwarnings("error")`, exactly like `HassetteForgottenAwaitWarning`.
4. **Thread-id gating excludes executor offload by construction.** `threading.get_ident() == self._loop_thread_id` (the id captured at `core.py:449`). Framework sync-handler offload and logging-pipeline shutdown run on worker threads, so they never satisfy the gate and are never flagged.
5. **Attribution uses a thread-visible marker, not a ContextVar.** A separate OS thread cannot read another thread's `ContextVar`, and `CURRENT_EXECUTION_ID` is unbound the instant a handler returns. So a plain thread-visible attribute carrying `(app_key, instance_name, execution_id, started_at)` is set in `command_executor.bind_execution_context` (line 422) and cleared in `unbind_execution_context` (line 439). The watchdog reads this marker to name the app that held the loop *during* the stall.
6. **Spike first.** The watchdog's exact mechanism (in-loop `call_later` heartbeat vs. dedicated daemon thread) determines whether attribution is correct under the "next execution scheduled immediately after" condition. A throwaway prototype (T02) proves the mechanism before the watchdog is built for real (T03).
7. **Persist, don't surface (this round).** Events are written to a new `blocking_events` telemetry table. No monitoring-UI view — that is a deliberate follow-up. Loop isolation (running framework internals on a separate loop) is also out of scope, tracked in issue #1038.

## Constraints & Anti-Patterns

- **Do NOT use `loop.set_debug(True)` for detection.** It taxes every callback (~2–5µs) and yields a framework-wrapper repr instead of the app's blocking line.
- **Do NOT attribute via a bare `CURRENT_EXECUTION_ID.get()` from the watchdog.** It is unbound at handler return; a separate thread cannot read it at all. Use the thread-visible marker.
- **Do NOT flag executor offload.** Thread-id gating is the mechanism; never relax it.
- **Do NOT let Tier 2 monkeypatches leak across tests.** Install/teardown must restore originals deterministically and be test-isolated — leaked patches corrupt unrelated test runs.
- **Do NOT raise by default in production.** Always-on + raise can crash a live app over a brief stall. Tier 1 defaults to warn; Tier 2 raise is dev-default / prod-opt-in only.
- **Do NOT confuse slow async with blocking.** A handler that `await`s something slow keeps the loop responsive — Tier 1 must not flag it. This is why Tier 1 measures loop *responsiveness*, not handler wall-clock.
- **Out of scope (do NOT build):** monitoring-UI surfacing of blocking events, event-loop isolation (#1038), sandboxing/preventing blocking in production by default.

## Design Doc References

- `## Architecture` — the two tiers, the shared spine, persistence, and config surface. The load-bearing section.
- `## Architecture` → "Tier 1" — the spike (Candidate A in-loop heartbeat vs Candidate B daemon thread) and the thread-visible marker.
- `## Key Constraints` — the explicit prohibitions above.
- `## Convention Examples` — real snippets from `await_guard.py`, `source_capture.py`, `command_executor.py`, `config.py` that new code must follow.
- `## Migration` — the `004.sql` `blocking_events` table, following `executions` conventions.
- `## Test Strategy` — gate/sentinel/error-isolation patterns; config-construction tests that may need new fields.

## Convention Examples

### Eager behavior resolution + warning emission (two separate methods)

**Source:** `src/hassette/core/await_guard.py` — resolution is eager (`guard_await`, while the owning context is live); emission is deferred (`RegistrationHandle.__del__`). The blocking guard mirrors the split: resolve when the marker is set, emit when a block is detected.

```python
# --- in guard_await(): eager resolution, per-app -> global -> default ---
behavior: ForgottenAwaitBehavior = DEFAULT_FORGOTTEN_AWAIT_BEHAVIOR
with contextlib.suppress(AttributeError, ValueError, TypeError):
    per_app = getattr(getattr(owner, "app_config", None), "forgotten_await_behavior", None)
    if per_app is not None:
        behavior = ForgottenAwaitBehavior(per_app)
    else:
        hassette_cfg = getattr(getattr(owner, "hassette", None), "config", None)
        global_val = getattr(hassette_cfg, "forgotten_await_behavior", None)
        if global_val is not None:
            behavior = ForgottenAwaitBehavior(global_val)

# --- in RegistrationHandle.__del__(): deferred emission ---
# WARN and ERROR both emit here; ERROR escalates only via the user's filterwarnings("error").
if self._behavior is not ForgottenAwaitBehavior.IGNORE:
    warnings.warn(msg, HassetteForgottenAwaitWarning, stacklevel=1)
```

### First non-`hassette` frame attribution (reused for Tier 2 source line)

**Source:** `src/hassette/utils/source_capture.py`

```python
def is_internal_frame(frame: Any) -> bool:
    name: str = frame.f_globals.get("__name__", "") if hasattr(frame, "f_globals") else ""
    return name == "hassette" or name.startswith("hassette.")
# capture_source_location(...) -> "<file>:<lineno>" of the first non-internal frame.
# capture_registration_source(...) -> (location, snippet) when the source line itself is wanted.
```

### Per-execution context binding (the choke point that gains the thread-visible marker)

**Source:** `src/hassette/core/command_executor.py` — `bind_execution_context` (line 422) sets context on entry; `unbind_execution_context` (line 439) is the paired teardown, called from the `finally` of `execute_handler` (483) and `execute_job` (520).

```python
def bind_execution_context(self, app_key: str | None, instance_index: int) -> tuple[str, Token[str | None]]:
    execution_id = str(uuid_utils.uuid7())
    token = CURRENT_EXECUTION_ID.set(execution_id)
    # ... structlog.contextvars.bind_contextvars(app_key=..., instance_name=..., instance_index=...)
    return execution_id, token
```

### Prod-override flag precedent (the model for `allow_deep_detection_in_prod`)

**Source:** `src/hassette/config/config.py`

```python
allow_reload_in_prod: bool = Field(default=False)
"""Whether to enable the file watcher for automatic app reloads in production mode.
When True, file changes trigger automatic app reloads (same as dev_mode). ... Defaults to False."""
```
