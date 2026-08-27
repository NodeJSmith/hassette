---
task_id: "T05"
title: "Observe Service teardown safely"
status: "planned"
depends_on: ["T04"]
implements: ["FR#2", "FR#3", "FR#7", "FR#9", "FR#17", "AC#2"]
---

## Summary

Complete the Service-specific lifecycle body by observing `serve()` cancellation within a bounded budget and folding
that evidence into the shared teardown report. Preserve normal startup readiness and clean same-instance restart while
ensuring a cancellation-resistant old service task can never authorize or receive a replacement.

## Target Files

- read: `design/specs/105-teardown-restart-safety/design.md`
- modify: `src/hassette/resources/service.py`
- modify: `tests/unit/resources/test_service_lifecycle.py`
- modify: `tests/unit/resources/test_service_edge_cases.py`
- read: `tests/unit/resources/test_serve_wrapper_shutdown.py`

## Prompt

Implement the Service-specific parts of `Architecture → Minimal lifecycle coordinator` and `Evidence collection`.
Keep Service's initialization body semantics: dependency wait, before/on initialize hooks, one named `_serve_task`,
after-initialize, child initialization, and readiness transition from `_serve_wrapper()`. In the shutdown body, preserve
the designed hook order, cancel `_serve_task`, and observe cancellation acknowledgement with bounded `asyncio.wait()`
rather than `wait_for()`. A task still pending at the deadline adds `SERVE_TASK_PENDING` and its task name to the report;
shutdown returns promptly and retains observation without spawning another serve task. Cooperative cancellation remains
SAFE when every other stage is clean. Add a failing resistant-service regression before implementation and release the
old task in `finally` so the test never leaks work.

## Focus

- `_serve_task.cancel()` is a request, not termination evidence; only task completion authorizes a clean restart.
- Service must inherit the final public coordinator front doors from Resource rather than reintroducing public
  lifecycle overrides.
- Preserve `_serve_wrapper()` handling of normal return, cancellation, `ClosedResourceError`, fatal errors, and generic
  failures.
- Keep startup status behavior: Service initialization returns while STARTING and `_serve_wrapper()` calls
  `handle_running()`.
- `tests/unit/resources/test_service_edge_cases.py` was already migrated off mutable admission flags in T03; replace its
  warning-only timeout assertions with report assertions without restoring those flags.

## Verify

- [ ] FR#2: `uv run pytest tests/unit/resources/test_service_lifecycle.py tests/unit/resources/test_service_edge_cases.py -q` proves Service shutdown is SAFE only after the serve task and inherited stages complete cleanly.
- [ ] FR#3: `uv run pytest tests/unit/resources/test_service_edge_cases.py -q` proves resistant serve work adds `SERVE_TASK_PENDING` and bounded task detail.
- [ ] FR#7: `uv run pytest tests/unit/resources/test_service_edge_cases.py -q` proves an UNSAFE Service report refuses later initialization without creating a replacement serve task.
- [ ] FR#9: `uv run pytest tests/unit/resources/test_service_lifecycle.py -q` proves cooperative Service teardown still permits the existing clean same-instance restart path.
- [ ] FR#17: `uv run pytest tests/unit/resources/test_service_edge_cases.py -q` proves a resistant service/body task remains reachable and exception-observed until released.
- [ ] AC#2: `uv run pytest tests/unit/resources/test_service_edge_cases.py -q` proves cancellation-resistant `serve()` stays within the observation budget, returns UNSAFE, and never receives a replacement.
