---
task_id: "T15"
title: "Authenticate the demo stack and the doc-screenshot pipeline"
status: "done"
depends_on: ["T01", "T06", "T08", "T12"]
implements: []
---

## Summary

Turning auth on by default breaks two pieces of developer tooling that nothing else in this plan
touches: `mise run demo` (the live demo stack used for visual QA) and
`scripts/capture_screenshots.py` (which regenerates the `docs/_static/web_ui_*.png` files the docs
site embeds). Both currently reach the API with no credential.

The fix keeps auth **on** in the demo and gives it a fixed, known token — rather than disabling auth
— so the demo and every regenerated screenshot show the behavior operators actually get. That also
makes the new login view capturable instead of invisible, which matters because
`.claude/rules/design-completeness.md` requires visual evidence for T12's UI change and the tool that
produces it is one of the things auth breaks.

This depends on T08, not just T06: T08 is the task that threads the resolved token into
`WebApiService.serve()` (`create_fastapi_app(self.hassette, auth_token=self._resolved_auth_token)`).
Without T08, `serve()` still calls `create_fastapi_app(self.hassette)` with no token, so the demo
token set here would never actually authenticate anything.

## Target Files

- modify: `scripts/docker/ha-demo.yml` — add `HASSETTE__WEB_API__AUTH_TOKEN` to the hassette service
- modify: `scripts/capture_screenshots.py` — authenticate the telemetry poll and the browser session
- modify: `docs/screenshots.yml` — manifest entry for the login view
- create: `docs/_static/web_ui_login.png` — generated, not hand-captured
- read: `scripts/demo_stack.py` — `DemoStack` context manager, compose lifecycle and health gating
- read: `docs/screenshots.yml` — existing manifest entry shape (`url`, `output`, `selector`, `wait_for`)

## Prompt

Read design.md's `## Impact → Behavioral Invariants` (the demo-stack entry) and CLAUDE.md's
`## Demo Stack & Doc Screenshots` section in full.

**1. Give the demo stack a token.** In `scripts/docker/ha-demo.yml`, add
`HASSETTE__WEB_API__AUTH_TOKEN: "demo-token"` (or similar fixed literal) to the `hassette` service's
`environment` block, alongside the existing `HASSETTE__BASE_URL` / `HASSETTE__TOKEN` entries. This
mirrors the precedent already set two lines up: the HA JWT is a hardcoded literal in this same file
with a comment noting where it must stay in sync. Follow that convention, including the comment.

Do **not** set `auth_enabled: false` instead. Besides hiding the real behavior from every screenshot,
it does not work here: the demo binds non-loopback (the host port mapping and the Vite sibling
container at `VITE_PROXY_TARGET: http://hassette:8126` both need it), and `auth_enabled=false` plus
non-loopback is exactly what T08's hard-block guard refuses to start on.

**2. Authenticate the capture tool.** `scripts/capture_screenshots.py` has two unauthenticated
surfaces:

- The readiness poll at lines 90-97 (`urllib.request` against
  `/api/telemetry/app/demo_stimulator/jobs`) will 401 forever and time out. Attach
  `Authorization: Bearer <demo-token>` to that request.
- shot-scraper drives a real browser, so it needs the session cookie, not a header. Before the
  capture run, `POST /api/auth/session` once with the demo token, take the `Set-Cookie` value, and
  hand it to shot-scraper as saved browser state. Verify the exact flag against the installed
  shot-scraper version before writing it — the mechanism (a Playwright storage-state JSON passed on
  the command line) is stable, but do not assume a flag name from memory.

Read the token from one place, not two — a module-level constant in `capture_screenshots.py` that
matches the compose literal, with a comment pointing at `ha-demo.yml` the way the existing HA JWT
comments do.

**3. Capture the login view.** Add a `docs/screenshots.yml` entry for `/login`. This one is unusual:
every other entry captures an authenticated page, so the capture run must reach `/login` *without*
the session cookie applied, or it will redirect straight to the dashboard. Whether that means a
separate shot-scraper invocation or a per-entry opt-out depends on how step 2's browser state is
wired — work it out there rather than bolting a special case onto the manifest schema.

Crop via `data-testid`, per CLAUDE.md — CSS module class names are hashed at build time and cannot be
selected here.

## Focus

- Auth stays **on** in the demo. If you find yourself reaching for `auth_enabled: false` to make
  something work, that is the wrong lever — the whole point of this task is that the demo exercises
  the real code path.
- `.demo-data/` persists between runs and the token file lands there. A stale `.web_api_token` from a
  pre-auth run is not a hazard (the explicit config value wins over the file, per T02's resolution
  order), but if the demo behaves strangely, `rm -rf .demo-data` is the documented reset and worth
  trying before debugging further.
- Do not weaken the CORS wildcard validator (T01) or `trusted_proxies` to make the Vite dev server
  work. Vite proxies server-side (`VITE_PROXY_TARGET`), so the browser's requests are same-origin
  from hassette's perspective and carry the cookie normally.
- This task has no FR/AC of its own — it exists so the feature does not land with the demo stack and
  doc-screenshot pipeline broken. Its verification is "the tooling runs," not a test assertion.

## Verify

- [ ] `mise run demo` brings the stack up and the dashboard is reachable in a browser: unauthenticated visits land on the login view, and pasting `demo-token` reaches the dashboard.
- [ ] `mise run demo-verify` passes (all apps reach running, listeners registered) against the auth-enabled demo stack.
- [ ] `uv run python scripts/capture_screenshots.py` completes without timing out on the readiness poll, and the regenerated `web_ui_*.png` files show the dashboard rather than a login screen.
- [ ] `docs/_static/web_ui_login.png` is generated by the capture tool (not hand-captured) and shows the login view, and `docs/screenshots.yml` carries its manifest entry.
