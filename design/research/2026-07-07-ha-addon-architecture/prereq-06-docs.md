# Prereq 06 — Documentation

**Repo:** hassette (docs site), hassette-addon (DOCS.md written in prereq-04)
**Depends on:** prereq-04 usable end-to-end (screenshots and verification steps need a real
install)
**Size:** small–medium

## Goal

The docs site treats the add-on as the primary installation path for HAOS/Supervised users,
and stops saying hassette isn't available as an add-on.

## Content

1. **New getting-started page: "Install as a Home Assistant Add-on"** — sibling of the
   existing Docker installation instructions and placed *first* for HAOS users. Covers: add the
   repository URL (with a `my.home-assistant.io` deep-link button), install, start, open the
   sidebar panel; where config lives (`/addon_configs/.../hassette.toml` + `apps/`, edited via
   File Editor / Studio Code Server / Samba); adding the first app; the two options
   (`log_level`, `install_requirements`); the optional direct port and its unauthenticated
   trust model; the first-start dependency-install delay. Per `doc-rules.md`: getting-started
   voice ("you"), numbered steps with visible progress, and a "Verify it's working" step
   (sidebar panel shows the app running; `hassette log --app <key>` via the port or container
   exec).
2. **Update stale claims** — `docs/pages/getting-started/is-hassette-right-for-you.md:42`
   says "It does not run as a Home Assistant add-on yet." (Line 36's "does not replace …
   add-ons" statement is about HA's add-on ecosystem generally and stays true — leave it.)
3. **Connection settings reference** — `api_url`/`ws_url` override fields land with prereq-02's
   docs requirement; this prereq only cross-links them from the add-on page ("the add-on sets
   these for you").
4. **Comparison pages** — the AppDaemon comparison mentions deployment; add the add-on row
   where installation methods are compared.

## Files

- Create `docs/pages/getting-started/ha-addon.md` (slug per existing getting-started naming)
- Modify `docs/pages/getting-started/is-hassette-right-for-you.md` — remove/replace the
  "not an add-on yet" statements
- Modify `mkdocs.yml` — nav entry
- Modify the getting-started index/installation page — route HAOS users to the add-on page
- Add screenshots per `docs/screenshots.yml` conventions **only if** the page embeds UI images
  — the add-on store/ingress views are HA UI, not hassette UI, so hand-captured images are
  acceptable here (the capture tool's demo stack cannot render the HA add-on store)

## Acceptance criteria

- [ ] Docs build clean; nav places the add-on page before Docker for getting-started flow
- [ ] No remaining "not available as an add-on" claims (`rg -i "add-on" docs/pages` audit)
- [ ] `doc-persona-review` (followability) and `doc-accuracy-review` on the new/touched pages
      pass per `.claude/rules/doc-rules.md` — persona verdict at least `followable-with-effort`,
      no confirmed `WRONG`/`OUTDATED_API` on touched lines
