# Context: Automated Doc Screenshot Capture

## Problem & Motivation
Documentation screenshots go stale after UI changes. The 16 screenshots in `docs/_static/web_ui_*.png` are currently out of date and have been through multiple releases. The manual capture workflow (start demo, navigate pages, Playwright MCP capture, hand-crop elements, commit) takes 20+ minutes and nobody does it, so the docs silently drift from the real UI. We need a single command that regenerates all screenshots from a deterministic state.

## Visual Artifacts
None.

## Key Decisions
1. **shot-scraper as the capture tool** — Python CLI built on Playwright, designed for YAML-manifest-driven screenshot capture. Already evaluated in the research brief. Avoids bespoke per-screenshot scripts (documented anti-pattern).
2. **YAML manifest at `docs/screenshots.yml`** — declarative, reviewable, and extensible. Adding a new screenshot means adding a manifest entry, not writing code.
3. **`data-testid` selectors for element crops** — more stable across refactors than CSS class selectors. CSS module classes get hashed at build time and cannot be used in manifest JS.
4. **Wrapper script consumes demo environment** — `scripts/hassette_demo.py` is not modified. The wrapper starts it as a subprocess, parses its KEY=value stdout output, and tears it down after capture.
5. **DB cleanup before each run** — delete `.demo-data/hassette.db` before starting the demo for deterministic screenshot content.
6. **Error data timing** — reduce `demo_stimulator.py` `failure_interval` from 60s to 5s so errors appear quickly. Wrapper polls the API until error data exists before proceeding to shot-scraper.
7. **Animation disabling** — CSS injection via shot-scraper's `javascript` field: `*, *::before, *::after { animation-duration: 0s !important; transition-duration: 0s !important; }`.
8. **`motion_lights` for non-error screenshots** — has two instances (exercises instance switcher), representative of a normal running app.
9. **`demo_stimulator` for error screenshots** — runs the intentionally-failing `sensor_health_check` job that populates error data.

## Constraints & Anti-Patterns
- **Do not conflate with visual regression testing.** Screenshots update when the UI changes, they don't fail.
- **Do not write per-screenshot Playwright scripts.** The YAML manifest pattern exists to prevent this anti-pattern.
- **Do not modify `scripts/hassette_demo.py`.** The wrapper is a consumer, not a modifier.
- **Do not use CSS module classes in manifest JS.** They get hashed at build time. Use `data-testid` attributes instead.
- **CI workflow is out of scope.** This is the local capture tool only.
- **HA getting-started screenshots (`ha-*.png`) are out of scope.** Different capture mechanism needed.

## Design Doc References
- `## Architecture` — shot-scraper integration, manifest format, wrapper script flow, animation disabling, nox session
- `## Screenshot inventory mapped to manifest entries` — exact URL paths, selectors, JS triggers, and notes for all 16 screenshots
- `## Edge Cases` — demo failure, demo hang (180s timeout), selector not found, font loading, error data timing
- `## Convention Examples` — demo script orchestration pattern, KEY=value stdout parsing, viewport constants, nox session pattern

## Convention Examples

### Multi-service orchestration script

**Source:** `scripts/hassette_demo.py:187-210`

```python
def main() -> None:
    global _ha_compose_file, _ha_project_name, _ha_env, ...

    atexit.register(teardown)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    repo_root = Path(__file__).resolve().parent.parent
    # ... sequential startup with readiness polling
```

The wrapper script should follow this same pattern: atexit + signal handlers registered early, repo root derived from script location, teardown idempotent.

### Readiness polling via KEY=value output

**Source:** `scripts/hassette_demo.py:388-396`

```python
print(f"DEMO_HA_URL=http://localhost:{ha_port}", flush=True)
print(f"DEMO_HASSETTE_URL=http://localhost:{hassette_port}", flush=True)
print(f"DEMO_FRONTEND_URL=http://localhost:{vite_port}", flush=True)
print("DEMO_READY=true", flush=True)
```

The wrapper script parses these lines from the demo subprocess stdout to extract the frontend URL.

### Viewport constants

**Source:** `tests/e2e/conftest.py:42-49`

```python
MOBILE_VIEWPORT = {"width": 375, "height": 812}
DESKTOP_VIEWPORT = {"width": 1024, "height": 768}
```

Existing screenshots use 1400px width (wider than the e2e desktop viewport). The manifest should document this choice.

### Nox session for external tooling

**Source:** `noxfile.py:67-90`

```python
@nox.session(python=["3.13"])
def e2e(session: "Session"):
    if not _SPA_INDEX.exists():
        session.run("npm", "ci", "--prefix", "frontend", external=True)
        session.run("npm", "run", "build", "--prefix", "frontend", external=True)
    session.run("uv", "run", "--active", "playwright", "install", "--with-deps", "chromium", external=True)
    session.run("uv", "run", "--active", "--reinstall-package", "hassette", "pytest", ...)
```

The screenshots nox session follows the same pattern: `python=False`, external tool invocation.
