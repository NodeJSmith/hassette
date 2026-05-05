# Context: One-Command Visual QA Environment

## Problem & Motivation
Testing UI changes against a live automation backend currently requires manually assembling Home Assistant, the hassette backend, and the frontend dev server — each with its own startup sequence and port assumptions. This is error-prone: the wrong backend can be used accidentally (e.g., a production hassette instance), causing phantom debugging sessions against issues that don't exist. The current workaround of reusing a live instance interrupts real automation workflows. Additionally, the project's example apps live in a separate repository (hassette-examples) that has drifted from the framework's current API, meaning CI cannot validate examples against HEAD.

## Visual Artifacts
None.

## Key Decisions
1. **Fully dynamic ports** — all three services (HA, hassette backend, Vite) get random free ports via `socket.bind(('', 0))` to allow multiple simultaneous instances from different worktrees. No fixed/default ports.
2. **Foreground blocking** — the orchestrator blocks in the foreground rather than daemonizing. Claude runs it in a background process; humans press Ctrl+C to stop. Simpler than PID tracking.
3. **No HaLauncher extraction** — the orchestrator duplicates the Docker lifecycle logic from system test conftest.py rather than extracting a shared class. Reduces blast radius; can extract later if a third consumer appears.
4. **Machine-parseable output** — structured `KEY=value` lines (e.g., `DEMO_READY=true`) for programmatic consumption by Claude. The primary user is an AI agent, with human use secondary.
5. **Bring examples in-repo** — the 5 hassette-examples apps replace the existing 7 legacy apps in `examples/apps/`. Prior art research confirms in-repo tested examples are the gold standard for pre-1.0 frameworks.
6. **Separate demo HA fixture** — `tests/fixtures/demo-ha-config/` is a copy of `ha-config/` with the `demo:` integration added. System test fixtures remain untouched.

## Constraints & Anti-Patterns
- Do NOT modify `tests/system/conftest.py` or any existing system test infrastructure — the demo environment is fully separate.
- Do NOT use fixed ports — the whole point is dynamic allocation for concurrent instances.
- Do NOT daemonize — foreground blocking with signal-based teardown.
- The orchestrator must derive all paths from its own location (`Path(__file__).resolve().parent.parent`) to work from any worktree.
- The Vite proxy override must be backward-compatible — the default behavior (proxy to :8126) must remain unchanged when the env var is not set.

## Design Doc References
- `## Architecture > Bringing examples in-repo` — what to remove, what to copy, adapted hassette.toml
- `## Architecture > Demo HA fixture` — fixture structure, docker-compose env var substitution
- `## Architecture > Dynamic port allocation` — socket.bind pattern, TOCTOU mitigation
- `## Architecture > Vite proxy override` — process.env.VITE_PROXY_TARGET with fallback
- `## Architecture > Orchestrator script` — 10-step startup sequence, teardown order, structured output format
- `## Architecture > Smoke system test` — test structure, marker, what to assert
- `## Edge Cases` — timeout values (60s/30s/15s), failure modes, stale container handling
