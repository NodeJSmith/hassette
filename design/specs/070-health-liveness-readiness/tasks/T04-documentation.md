---
task_id: "T04"
title: "Document the health endpoints and fatal-exit behavior"
status: "planned"
depends_on: ["T02", "T03"]
implements: []
---

## Summary
Update the user-facing docs to reflect the three health endpoints, the always-200 `/api/health`, which signal to use for restart vs routing, and the non-zero exit on fatal failure. This is a required part of the feature (per `.claude/rules/design-completeness.md`), not a follow-up — the docs site is where users discover the liveness/readiness contract that peer frameworks lack. This task implements no FR/AC directly; it is the documentation deliverable for the feature shipped by T01–T03.

## Prompt
Update the documentation per `design.md` → "Documentation Updates", following `.claude/rules/doc-rules.md` and `.claude/rules/voice-guide.md`.

1. **`docs/pages/cli/configuration.md`** (~line 112) — the health-check bash snippet keys on `status == "starting"` for 503. Update it: point restart automation at `/api/health/live`; remove the `starting → 503` expectation (it is now 200); note that a *fatal* exit is non-zero so `systemd Restart=on-failure` / Docker `restart: unless-stopped` restart correctly, while HA outages stay 200.

2. **`docs/pages/getting-started/docker/troubleshooting.md`** — add a "Hassette restarts whenever HA goes down" entry: explain the cause (a healthcheck pointed at a readiness signal), and the fix (point the Docker healthcheck / autoheal at `/api/health/live`, which ignores HA connectivity).

3. **`docs/pages/core-concepts/database-telemetry.md`** (status table, ~lines 79–80) — if it references `/api/health` status codes, reflect that `/api/health` is always 200 while serving, and that a fatal crash is recorded to the session before exit.

4. **New/extended health-endpoint reference** — describe `/api/health`, `/api/health/live`, `/api/health/ready`: their response shapes and codes, the self-shutdown-on-fatal behavior (non-zero exit), and which signal to use for restart vs routing. This is the user-facing guidance peer frameworks (e.g. AppDaemon) lack. If a concept page covers the web/monitoring API, extend it; otherwise add a focused reference page and link it from the relevant index.

Do NOT edit `CHANGELOG.md` — it is release-please-managed; user-facing intent is conveyed via the PR title / commit type (`feat`).

## Focus
- Voice: concept/reference pages use system-as-subject, not "you" (see `voice-guide.md` rules #10, #15). Getting-started/troubleshooting may address the reader directly.
- All code/config examples in docs come from tested snippet files where the page uses the snippet include mechanism (`--8<--`) — match the surrounding page's convention. A bash healthcheck snippet in `configuration.md` follows whatever pattern that page already uses.
- Keep the endpoint reference factual: `/api/health` (always 200 aggregate), `/api/health/live` (liveness, HA-independent), `/api/health/ready` (200 only when `ok`). Restart automation → liveness or the non-zero exit; routing → readiness.
- Real entity/endpoint names only; no placeholder URLs.

## Verify
- [ ] `docs/pages/cli/configuration.md` health-check example points at `/api/health/live` and no longer expects `starting → 503`.
- [ ] `docs/pages/getting-started/docker/troubleshooting.md` has a "restarts when HA goes down" entry pointing at the liveness endpoint.
- [ ] A health-endpoint reference documents all three endpoints, their codes, and the restart-vs-routing guidance, plus the non-zero fatal exit.
- [ ] `docs/pages/core-concepts/database-telemetry.md` status references (if any) match the reshaped `/api/health` codes.
- [ ] `mkdocs build` (or `uv run mkdocs build`) succeeds with no broken links or snippet errors.
