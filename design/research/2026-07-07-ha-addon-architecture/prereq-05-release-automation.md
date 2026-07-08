# Prereq 05 — Release Automation (Image Build + Version Bump)

**Repo:** hassette-addon (workflows), hassette (release trigger), homelab renovate config
**Depends on:** prereq-04
**Size:** small–medium

## Goal

A hassette release propagates to add-on users with no manual steps beyond merging one PR in
`hassette-addon`. Two pipelines:

1. **Add-on image build** (`hassette-addon` repo): on push/tag, build the derived image for
   `amd64` + `aarch64` and push `ghcr.io/nodejsmith/hassette-addon-{arch}:<version>` (the
   `{arch}` placeholder form the `image:` key expects), with the `io.hass.*` labels. Reuse the
   buildx multi-arch pattern from hassette's `.github/workflows/build_and_publish_image.yml`
   rather than the legacy `home-assistant/builder` action — we already know the buildx recipe
   and it keeps both repos' CI idiomatic. Per-arch tags (not a single multi-arch manifest) are
   the add-on convention the `{arch}` placeholder serves.
2. **Version bump on hassette release**: when hassette publishes release `X.Y.Z`, open a PR in
   `hassette-addon` updating `config.yaml` `version:` and the Dockerfile `FROM` pin, with the
   hassette changelog excerpt in `hassette/CHANGELOG.md`. Mechanism options, in preference
   order:
   - `repository_dispatch` from hassette's release workflow (`workflow_call` step after image
     publish) into `hassette-addon`, using a fine-grained PAT/GitHub App secret — immediate,
     carries the changelog in the payload;
   - the self-hosted Renovate on smithfamily (repo list in `~/homelab/renovate/config.json`)
     tracking the ghcr base-image tag — near-zero code but no changelog propagation and up to
     one schedule-interval of lag.

   Start with Renovate (add `hassette-addon` to the repo list) to get coverage on day one;
   graduate to `repository_dispatch` when the changelog-excerpt step is wanted.

## Constraints

- The add-on `version:` in `config.yaml` is what users see as "update available" — it must
  equal the hassette version it ships (add-on-only fixes append a suffix, e.g. `0.35.0.1`,
  which the add-on spec permits as a plain string).
- Never auto-merge the bump PR: the add-on maintainer merge is the human gate that a release
  is add-on-safe (e.g. a config-surface change needing run.sh updates).
- The derived image build must fail if the pinned base tag doesn't exist yet (ordering guard:
  hassette's image publish completes before the bump PR builds).

## Files

- Create `hassette-addon/.github/workflows/build.yml` — per-arch image build + publish + labels
- Create `hassette-addon/.github/workflows/lint.yml` — add-on config lint
  (`frenck/action-addon-linter` or the supervisor's schema check) on PRs
- Modify `hassette/.github/workflows/build_and_publish_image.yml` (or the release-please
  workflow) — dispatch hook (phase 2; skipped in the Renovate-first phase)
- Modify `~/homelab/renovate/config.json` (smithfamily) — add `NodeJSmith/hassette-addon`

## Acceptance criteria

- [ ] Merging a version-bump PR in `hassette-addon` results in installable images for both
      arches and the add-on store showing the update
- [ ] A hassette release produces a bump PR in `hassette-addon` without manual action
- [ ] A bump PR against a not-yet-published base tag fails CI rather than publishing a broken
      add-on
