# Async Basics

AppDaemon runs each app in its own thread, so synchronous code that blocks is harmless. Hassette runs every app in a single asyncio *event loop* — one thread that runs every handler, switching between them at `await` points. Two things follow: calls into the bus, scheduler, and API need `await`, and a blocking call in one app freezes all of them. This page builds the mental model behind both rules — what a coroutine is, what `await` does, and how to recognize the failure when one goes missing.

If you have a large synchronous codebase and aren't ready to convert it, [`AppSync`][hassette.app.app.AppSync] runs your app in a managed thread instead — see [Mental Model](concepts.md#synchronous-api-appsync).

## What a Coroutine Is

`async def` declares a coroutine function. Calling one does not run its body. The call returns a *coroutine object* — a description of work that hasn't started yet. `await` is what actually runs it.

This is the root cause of the most common migration bug. A call that looks complete is actually a no-op:

```python
--8<-- "pages/migration/snippets/async_coroutine_basics.py:unawaited"
```

The handler finishes without error. The coroutine object is created, never started, and discarded. No service is called, nothing is logged, and Hassette can't catch it for you — creating a coroutine without running it is legal Python. A type checker can catch it: Pyright flags this exact code with `reportUnusedCoroutine`, which is a strong reason to run Pyright over migrated apps.

Adding `await` runs the call:

```python
--8<-- "pages/migration/snippets/async_coroutine_basics.py:awaited"
```

`await` does two things: it starts the coroutine and pauses the current handler until it finishes. While this handler is paused, the event loop runs other handlers — yours and other apps'. That cooperative handoff is how one thread serves every app.

Python eventually notices a discarded coroutine and emits `RuntimeWarning: coroutine '...' was never awaited`. In test output, that warning is the clearest sign of a missing `await` — see [Testing](testing.md).

## Which Calls Need `await`

Anything that talks to Home Assistant or registers future work is async. Reads from the local state cache are not.

| Call | Needs `await`? |
|---|---|
| `self.api.call_service(...)` | Yes |
| `self.api.get_state(...)` | Yes |
| `self.bus.on_state_change(...)` and all `on_*` methods | Yes |
| `self.scheduler.run_in(...)` and all scheduling methods | Yes |
| `self.task_bucket.run_in_thread(...)` | Yes |
| `self.states.light.get(...)` | No — synchronous |
| `self.states.get(...)` | No — synchronous |
| `subscription.cancel()` / `job.cancel()` | No — synchronous |

`await` only works inside an `async def` method, so converting a call usually means converting the method that contains it too — AppDaemon's `def on_motion(self, ...):` becomes `async def on_motion(self):`. (`self.task_bucket`, like `self.bus` and `self.api`, is available on every `App` instance — see [Task Bucket](../core-concepts/apps/task-bucket.md).)

In `AppSync` apps, none of this applies — use the `.sync` facades (`self.api.sync.call_service(...)`) with no `await`. See [Mental Model](concepts.md#synchronous-api-appsync).

## Why Blocking Calls Freeze Every App

The event loop moves between handlers only at `await` points. A synchronous call that takes five seconds — `time.sleep(5)`, `requests.get(...)`, a slow database query — holds that thread for five seconds. No `await` point, no handoff: every handler in every app waits until it returns.

```python
--8<-- "pages/migration/snippets/async_blocking.py:blocking"
```

The fix is to move the blocking call to a thread, where it can take as long as it likes without holding the loop:

```python
--8<-- "pages/migration/snippets/async_blocking.py:offload"
```

`run_in_thread` runs the function in a thread pool and the `await` pauses only this handler until the result is ready. See [Task Bucket](../core-concepts/apps/task-bucket.md) for the full reference, including `spawn()` for background loops.

If most of an app's code blocks, don't wrap every call — use [`AppSync`][hassette.app.app.AppSync] and migrate incrementally.

## Spotting a Missing `await`

A missing `await` never raises at the call site, so it shows up as something else looking broken. The symptoms map directly to the call that was skipped:

- **A service call has no effect** — no light turns on, no error in the logs. Check the `self.api.*` call for a missing `await`.
- **A listener never fires** — the handler is defined but nothing reaches it. Check the `self.bus.on_*` registration in `on_initialize`.
- **A scheduled job never runs** — check the `self.scheduler.*` call that was supposed to create it.
- **`RuntimeWarning: coroutine '...' was never awaited`** appears in logs or pytest output — the warning names the coroutine, which points you at the exact call.

The first three fail silently in live operation, which is why tests catch this class of bug faster than log-watching does — the `RuntimeWarning` surfaces in pytest output even when every assertion passes. The [Migration Checklist](checklist.md) folds these checks into the step-by-step workflow.

## See Also

- [Mental Model](concepts.md) — app structure, the access model, and `AppSync`
- [Bus & Events](bus.md) — migrating listeners, where every registration is awaited
- [Task Bucket](../core-concepts/apps/task-bucket.md) — `run_in_thread` and background tasks
- [Migration Checklist](checklist.md) — the step-by-step migration workflow
