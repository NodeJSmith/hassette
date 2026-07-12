# UI QA Harness — Demo Stack Lifecycle

Everything in this skill runs against the demo environment, not mocks. The demo gives
agents real behavior: a live HA container, the example apps generating activity and a
deliberate failure (`demo_stimulator.sensor_health_check`), and a Vite dev server with
hot reload so CSS/TSX edits apply without rebuilds.

## Starting

```bash
# From the repo root (requires Docker Compose; takes 60–90s)
uv run python scripts/hassette_demo.py
```

Run it in the background and poll its output for readiness. It prints human-readable
URLs when up:

```text
HA:       http://localhost:18123
Hassette: http://localhost:18126
Frontend: http://localhost:15173
Demo ready.
```

Ports are fixed — use `http://localhost:15173` for all browser work and
`http://localhost:18126` for the REST API (useful for `/api/health`, app start/stop).
Override with `DEMO_HA_PORT`, `DEMO_HASSETTE_PORT`, `DEMO_VITE_PORT` if those ports are
already in use.

## Gotchas (each of these has burned a session)

- **Stale telemetry**: `.demo-data/` persists between runs. If the dashboard shows
  hours-old errors or inflated counts, stop the stack, `rm -rf .demo-data`, restart.
- **Editing app source requires a stack restart.** Reloading a failed app via
  `POST /api/apps/{key}/reload` re-runs the cached module — the traceback will show the
  *new* source lines while executing the *old* code (#1005). Do not chase that ghost;
  restart the whole demo script.
- **Failure data takes ~2 minutes.** `demo_stimulator`'s failing job needs a few cycles
  before error spotlights, sparklines, and log volume look representative. Don't
  screenshot or dispatch personas immediately at "Demo ready."
- **Theme is localStorage**, key `hassette:theme`, value `"light"` or `"dark"`
  (JSON-encoded string — the quotes are part of the value).
- **Teardown**: Ctrl-C or SIGTERM the script — `docker compose down --remove-orphans`
  handles all three containers. No manual cleanup needed. Need logs from a running
  service? `docker compose -f scripts/docker/ha-demo.yml logs <service>` (services:
  `homeassistant`, `hassette`, `vite`).

## Screenshot matrix

```bash
uv run python tools/frontend/ui_qa_capture.py --base-url http://localhost:15173 --output-dir $TMPDIR/shots
```

Captures pages × viewports (320/375/768/900/1280) × themes. Filter with `--pages`,
`--viewports`, `--themes` when the change under review is scoped (e.g. only
`--pages logs --viewports 320 375` for a mobile logs fix). A full matrix is ~70 images —
scope it unless the request is a full audit.

The breakpoints matter: 768px and 900px are the responsive boundaries
(`frontend/DESIGN_RULES.md`), 320px is the floor, 375px is the standard phone, 1280px is
desktop.

## Project context for analysis agents

Feed analysis subagents these sources rather than letting them invent design opinions:

| Source | What it defines |
|--------|-----------------|
| `frontend/DESIGN_RULES.md` | Responsive rules, table behavior, density, hierarchy |
| `frontend/src/tokens.css` | All design tokens — anything not derived from these is a finding |
| `design/context.md` | Design system reference: tokens, component specs, status system, layout patterns |

## Verification battery (after any fix)

```bash
cd frontend && npx tsc --noEmit && npm run lint && npx prettier --check 'src/**/*.{ts,tsx,css}' && npx vitest run
uv run python tools/frontend/check_global_css_allowlist.py
uv run python tools/frontend/check_dead_global_css.py
uv run python tools/frontend/check_css_module_globals.py
uv run python tools/frontend/check_undefined_css_refs.py
timeout 580 uv run pytest -m e2e -n auto
```

Two e2e drawer-backdrop tests are flaky under `-n auto` (#1006) — rerun failures in
isolation before treating them as regressions.
