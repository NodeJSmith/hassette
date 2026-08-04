---
task_id: "T14"
title: "Document the new auth model across the docs site"
status: "done"
depends_on: ["T01", "T02", "T03", "T05", "T09"]
implements: ["FR#1", "FR#2", "FR#9", "FR#18"]
---

## Summary

Rewrites the docs site pages that currently describe hassette's web API as unauthenticated, to
instead document the token/trusted-proxy model as the primary control. Per
`.claude/rules/design-completeness.md`, these updates ship in this PR, not as a follow-up — the docs
site is where operators discover the new required behavior, and every existing deployment will hit a
401 on upgrade until they read one of these pages.

## Target Files

- modify: `docs/pages/web-ui/index.md` — rewrite the "No authentication" warning (lines 17-24), document `trusted_proxies` and the token/cookie fallback
- modify: `docs/pages/cli/configuration.md` — document `HASSETTE__WEB_API__AUTH_TOKEN`, token file location, CLI credential-resolution order
- modify: `docs/pages/getting-started/docker/index.md` — document the token-on-first-start flow and the upgrade-transition behavior
- modify: `docs/pages/getting-started/docker/troubleshooting.md` — add a troubleshooting entry for "dashboard/API returns 401 after upgrade"
- modify: `docs/pages/web-ui/health-endpoints.md` — note that `GET /api/health` (unlike `/live` and `/ready`) now requires a credential
- read: `design.md`'s `## Documentation Updates` section — the authoritative list this task implements
- read: `design.md`'s `## Migration` section — the exact "Operational transition worth documenting explicitly" language to draw from

## Prompt

Read design.md's `## Documentation Updates` section in full — it names each file and the specific
change needed — and the `## Migration` section for the upgrade-transition language to adapt into the
docs.

In `docs/pages/web-ui/index.md` (lines 17-24 currently hold the "No authentication" warning block):
rewrite it so the token/trusted-proxy model is presented as the primary control, the loopback bind
becomes an optional *additional* layer (not the only safety net), and `trusted_proxies` is documented
as the path for a self-managed reverse-proxy/forward-auth setup. Name Caddy/Traefik/nginx paired with
a forward-auth layer (Authelia or tinyauth) as the recommended pairing, alongside the existing HA
add-on ingress case. Include a concrete reverse-proxy + TLS-termination config snippet — the current
doc only name-drops "Caddy, nginx, and Traefik all work" with no example; add one.

In `docs/pages/cli/configuration.md`: document `HASSETTE__WEB_API__AUTH_TOKEN` as an environment
variable, the `<data_dir>/.web_api_token` file location, and the CLI's credential-resolution order
(env → file, per T09).

In `docs/pages/getting-started/docker/index.md` and `docs/pages/getting-started/docker/troubleshooting.md`:
update both to reflect that access now requires the token flow, and add the operational-transition
note from design.md's Migration section — existing deployments will see a generated token in the log
on first restart post-upgrade, and the dashboard/API returns 401 until the operator retrieves and
uses it. This is intentional (closing an active security gap), not a bug — phrase it that way, and
add a troubleshooting entry for "I upgraded and now get 401" pointing at where to find the generated
token in `docker logs`.

In `docs/pages/web-ui/health-endpoints.md`: `/api/health` (the "Aggregate status" section and its
table row, currently described as "Human inspection... manual checks" with no mention of a
credential) is **not** one of FR#1's three exemptions — only `/api/health/live` and
`/api/health/ready` stay reachable with zero credentials. Update the table row and the "Aggregate
status" section to say `/api/health` now requires the same bearer token, cookie, or trusted-proxy
match as any other `/api/*` route. Leave the `/live` and `/ready` sections, and the Quick Check
(which already curls `/api/health/live` only), unchanged.

Do not edit `design/adrs/0005-ha-addon-packaging.md`,
`design/research/2026-07-07-ha-addon-architecture/prereq-03-ingress-source-guard.md`, or
`prereq-04-addon-repo-skeleton.md` — design.md's Replacement Targets section explicitly sequences
those as a follow-up, not part of this implementation.

Do not add a CHANGELOG.md entry — per `.claude/rules/changelog-quality.md`, changelog entries are
written at PR-creation time, not during feature work.

## Focus

- This is documentation-only — no code changes. Verify by reading the finished doc content, not by
  running tests.
- The upgrade-transition behavior (auth on by default, existing bookmarks/scripts break until updated
  with a credential) is the single most important thing an existing operator needs to see before
  upgrading — make sure it's not buried; the troubleshooting.md entry in particular should be easy to
  find via search for "401."
- Do not touch the HA add-on epic's design artifacts (see Prompt above) — that's explicitly out of
  scope per design.md.

## Verify

- [ ] FR#1: `docs/pages/web-ui/index.md` no longer states the API is unauthenticated by default; it documents auth-on-by-default and the default-deny behavior (verifiable via `grep -i "no authentication"` returning no match in the rewritten section, and `grep -i "trusted_proxies"` returning a match).
- [ ] FR#2: `docs/pages/web-ui/index.md` documents `trusted_proxies` as the recommended path for a forward-auth gateway setup, including a concrete reverse-proxy TLS-termination config snippet.
- [ ] FR#9: `docs/pages/getting-started/docker/index.md` documents the generated-token-on-first-start flow, and `docs/pages/getting-started/docker/troubleshooting.md` includes a "401 after upgrade" entry pointing at `docker logs` for the token.
- [ ] FR#18: `docs/pages/cli/configuration.md` documents `HASSETTE__WEB_API__AUTH_TOKEN` and the CLI's credential-resolution order.
- [ ] FR#1: `docs/pages/web-ui/health-endpoints.md` no longer implies `GET /api/health` is reachable with no credential — the table row and "Aggregate status" section both state it requires the same auth as any other `/api/*` route, while `/live` and `/ready` stay documented as unauthenticated.
