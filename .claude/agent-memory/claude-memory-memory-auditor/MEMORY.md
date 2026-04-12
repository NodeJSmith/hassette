# Memory Auditor Run Log

## 2026-04-12 — hassette project memory audit

**Memory set scanned:** `/home/jessica/.claude/projects/-home-jessica-source-hassette/memory/` (10 files)

**Findings:**
- STALE/OUTDATED: 7
- CONTRADICT: 2
- MERGE: 0
- DATE_FIX: 0

**Summary of changes made:**

| File | Verdict | Evidence |
|------|---------|----------|
| `project_335_orchestrate_progress.md` | OUTDATED — edited | Commits `2ba6cdd` (#335), `3c40430` (#336), and `f62a2a7` (#487) all landed. The caliper worktree and spec dir `004-owner-id-app-key-fix` no longer exist. Actual spec was `005-fix-owner-app-key-mismatch`. |
| `project_ui_redesign.md` | OUTDATED — edited | htmx/Alpine UI (008, 009) was superseded by Preact migration (`ffa393d` PR #343). The `worktree-ui-rebuild` branch is archived. |
| `project_preact_migration.md` | OUTDATED (status) — edited | Migration was approved AND shipped. `frontend/` directory with `vite.config.ts`, `package.json`, `@preact/signals` confirmed. PRs #343, #378, #381, #405, #442, #483, #485 all merged. |
| `project_visual_parity.md` | OUTDATED — edited | PRs #483 and #485 addressed the majority of the 30 gaps (responsive mobile + dashboard polish). "accelerated caliper in progress" was stale. |
| `project_mobile_ui_issues.md` | OUTDATED — edited | PR #483 (`679fe4f`) explicitly addressed responsive mobile including BottomNav and KPI stacking. Git log confirms commit title "color system overhaul + responsive mobile adaptation". |
| `project_v024_release_prep.md` | OUTDATED — edited | `git tag -l v0.24.0` returns `v0.24.0` at `aab51e7`. Release was cut. Docs rewrite is continuing as `2037-docs-rewrite` spec. |
| `project_telemetry_redesign.md` | CONTRADICT — edited | Memory said "in progress / architectural direction". `804f8ed` commit on main: "feat: telemetry source-tier unification (#484) (#495)" — shipped 9 commits before HEAD. |
| `reference_docker_deploy.md` | STALE — edited | Image tag was `hassette:ui-rebuild` with `pull_policy: never`. Actual compose now uses `ghcr.io/nodejsmith/hassette:main-py3.13` with `pull_policy: always`. Confirmed by reading `/home/jessica/homelab/hautomate/docker-compose.yml`. |
| `reference_demo_screenshots.md` | CONTRADICT — edited | Memory said "CI uses merge commit SHA". PR #499 (`10f51fb`) replaced sha-tags with `pr-N` and `main` tags. Workflow file at `build_and_publish_image.yml` confirms `type=ref,event=pr` produces `pr-N-py3.13`. |
| `project_docker_dep_strategy.md` | VALID | `1775a62` confirms constraints-based protection shipped. Research brief at `design/research/2026-04-03-runtime-dep-install/research.md` exists. No changes needed. |

**Staleness patterns noted:**
- Project memories describing "in-progress" or "ready to execute" work go stale fast once PRs merge.
- Image tag references in reference memories are particularly fragile — CI tagging changed in one PR.
- Worktree-specific paths (`worktree-ui-rebuild`, `hassette:ui-rebuild`) become stale as soon as the worktree is deleted.

**Paths that moved or changed:**
- `design/specs/004-*` was `004-owner-id-app-key-fix` in memory but actual dir is `004-decompose-datasyncservice`. The owner/app-key fix was spec `005-fix-owner-app-key-mismatch`.
- CI image tag format: `sha-XXXXXXX-py3.13` → `pr-N-py3.13` (PRs) / `main-py3.13` (main branch).
