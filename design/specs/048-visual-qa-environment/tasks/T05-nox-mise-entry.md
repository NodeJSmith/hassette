---
task_id: "T05"
title: "Add nox demo session and mise task"
status: "planned"
depends_on: ["T04"]
implements: ["FR#1", "AC#1"]
---

## Summary
Add a `python=False` nox session named `demo` that wraps the orchestrator script, and a corresponding mise task. These provide the user-facing entry points (`uv run nox -s demo` and `mise run demo`) for starting the visual QA environment.

## Prompt
1. **Add `demo` session to `noxfile.py`:**
   ```python
   @nox.session(python=False)
   def demo(session: "Session"):
       """Start a one-command visual QA environment: HA + hassette + Vite dev server."""
       session.run("uv", "run", "python", "scripts/hassette_demo.py", *session.posargs, external=True)
   ```
   Place it after the `frontend` session and before the test sessions. This follows the pattern of the existing `frontend` and `dev` sessions (both `python=False`, using `session.run` with `external=True`).

2. **Add `demo` task to `mise.toml`:**
   ```toml
   [tasks.demo]
   description = "Start the one-command visual QA environment (HA + hassette + Vite)"
   run = "uv run nox -s demo"
   ```
   Place it after the existing `serve_docs` task.

## Focus
- The nox session is `python=False` because it doesn't need a virtual environment — it delegates to `uv run` which uses the ambient venv.
- `session.posargs` forwards any additional arguments (e.g., future CLI flags for the orchestrator).
- The mise task is a thin wrapper over nox — it exists so users can type `mise run demo` instead of remembering the nox command.
- Check the existing noxfile for import ordering and style before adding the session.

## Verify
- [ ] FR#1: `uv run nox -s demo` invokes `scripts/hassette_demo.py` and starts all services
- [ ] AC#1: `mise run demo` invokes the orchestrator, starts all three services, and prints `DEMO_READY=true` — identical to `uv run nox -s demo`
