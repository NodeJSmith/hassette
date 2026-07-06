---
proposal: "Assess all pending Renovate dependency updates from issue #1161 and recommend a systematic update order"
date: 2026-07-06
status: Draft
flexibility: Leaning
motivation: "Stay current — routine maintenance to keep dependencies from drifting too far behind"
constraints: "None stated beyond wanting a thorough assessment"
non-goals: "None stated"
depth: normal
---

# Research Brief: Dependency Dashboard Sweep (#1161)

**Initiated by**: Full sweep of Renovate dependency dashboard — assess every pending update, identify risks, recommend update order.

## Context

### What prompted this

Routine dependency maintenance. The Renovate dashboard (issue #1161) shows updates across every dependency category: GitHub Actions digests, Docker images, Python packages, and Node packages (including a TypeScript major version bump). One action (`astral-sh/setup-uv`) is failing lookups entirely, generating a persistent warning on the dashboard.

### Current state

The project manages dependencies across five layers:

1. **GitHub Actions** — 11 workflow files, all SHA-pinned with version comments. Renovate proposes digest updates for 7 actions (Docker suite, dorny/paths-filter, j178/prek-action). One action (`astral-sh/setup-uv`) has a lookup failure.
2. **Docker** — `Dockerfile` pins `python:3.14.6-slim`, `node:24-slim`, `ghcr.io/astral-sh/uv:0.11.25`. Two compose files pin `homeassistant/home-assistant:2026.6`.
3. **Python** — `pyproject.toml` uses `>=` floors for most deps; `typing-extensions` and `whenever` use `==X.Y.*` minor pins; `cyclopts` and `uv_build` have upper-bound caps. 61 dependencies total across runtime, dev, test, and docs groups.
4. **Node/Frontend** — `frontend/package.json` uses `^` caret ranges (29 packages). Currently on TypeScript 5.9.3, Vite 8.1.2, Vitest 4.1.9.
5. **Tooling** — `mise.toml` pins `prek 0.4.5` and `python 3.14.6`. CI pins `ruff==0.14.9` and `pip-audit@2.10.0` inline in workflow shell commands (invisible to Renovate).

Renovate runs weekly (Monday before 9am ET) with a 5-PR concurrent limit. Only HA Docker major bumps require dashboard approval. No grouping rules exist for Python or Node dependencies.

### Key constraints

- **PR concurrent limit of 5** — Renovate will queue updates beyond 5 open PRs.
- **`typing-extensions==4.15.*`** and **`whenever==0.10.*`** — minor-version pins restrict Renovate to proposing the next minor only (`4.16.*`), not arbitrary jumps.
- **HA major bumps require dashboard approval** — `2026.6` → `2026.7` is a minor bump and does not require approval.

## Inventory of Pending Updates

### Category 1: Repository Problem — `astral-sh/setup-uv` Lookup Failure

**Root cause identified.** The workflows pin `astral-sh/setup-uv@fac544c07dec837d0ccb6301d7b5580bf5edae39 # v8`, which is SHA `v8.2.0`. Renovate's `config:recommended` preset includes `helpers:pinGitHubActionDigests`, which tries to track the `v8` floating major tag and resolve its current digest. However, **`astral-sh/setup-uv` does not publish a floating `v8` tag** — only versioned tags (`v8.0.0`, `v8.1.0`, `v8.2.0`, `v8.3.0`) exist. So Renovate cannot resolve "what SHA does `v8` currently point to?" and reports "Could not determine new digest."

This affects all 7 workflow files that reference `setup-uv`. The action itself works fine — GitHub resolves the pinned SHA directly. This is purely a Renovate tracking problem.

**Current SHA**: `fac544c07dec837d0ccb6301d7b5580bf5edae39` (v8.2.0)
**Latest release**: `d31148d669074a8d0a63714ba94f3201e7020bc3` (v8.3.0, released 2026-07-05)

**Fix options**:
- (a) Update the comment tag to a specific version (`# v8.2.0` → `# v8.3.0`) and update the SHA. Renovate can then track `v8.3.0` as a `github-tags` package. This is the cleanest fix.
- (b) Add a Renovate `packageRules` entry for `setup-uv` that overrides the versioning strategy. More complex and fragile.
- (c) Wait — `astral-sh` may eventually publish a floating `v8` tag (most action authors do). But this has been the pattern since v8.0.0 shipped, so it appears intentional.

**Recommendation**: Option (a) — manually update to v8.3.0 SHA in all 7 workflow files and change the comment to `# v8.3.0`. This clears the dashboard warning and lets Renovate track future patch releases.

### Category 2: Rate-Limited Updates (7 items)

These are queued behind the PR concurrent limit. All are minor/patch bumps except TypeScript 6.

| Update | Type | Risk |
|--------|------|------|
| `vite` 8.1.2 → 8.1.3 | patch | None — bug fix only |
| `ghcr.io/astral-sh/uv` 0.11.25 → 0.11.26 | patch | None — Dockerfile ARG bump |
| `shiki` monorepo | minor/patch | Low — syntax highlighting library |
| `vitest` + `@vitest/coverage-v8` 4.1.9 → 4.1.10 | patch | None — test tooling |
| `homeassistant/home-assistant` 2026.6 → 2026.7 | minor | Low-Med — monthly HA release, may change entity behavior the system tests exercise |
| `typing-extensions` 4.15.* → 4.16.* | minor | Low — bug fixes and new protocol base class support; no breaking changes per changelog |
| `typescript` 5.9.3 → 6.x | **major** | **Medium-High** — see detailed analysis below |

### Category 3: Pending Digest Updates (7 GitHub Actions)

All are SHA-only digest bumps within the same major version tag. Zero functional risk — these track security patches and minor fixes to the action implementations.

| Action | Current version tag |
|--------|-------------------|
| `docker/build-push-action` | v7 |
| `docker/login-action` | v4 |
| `docker/metadata-action` | v6 |
| `docker/setup-buildx-action` | v4 |
| `docker/setup-qemu-action` | v4 |
| `dorny/paths-filter` | v4 |
| `j178/prek-action` | v2 |

### Category 4: Open PRs (2)

| PR | Update | Risk |
|----|--------|------|
| #1193 | `preact` 10.29.3 → 10.29.4 | None — patch bump |
| #1194 | `prek` 0.4.5 → 0.4.8 | Low — pre-commit tool, minor bumps |

### Category 5: Not Flagged by Renovate (invisible updates)

These are version pins in CI workflow shell commands that Renovate's manager doesn't detect:

| Tool | Current | Notes |
|------|---------|-------|
| `ruff` | 0.14.9 | Pinned in `lint.yml` via `uv tool install ruff==0.14.9` and in `pyproject.toml` as `>=0.14.9` |
| `pip-audit` | 2.10.0 | Pinned in `lint.yml` via `uvx pip-audit@2.10.0` |
| `muffet` | v2.11.4 | Pinned in `docs.yml` via `go install` |

These require manual updates. They are low-risk patch bumps when they occur.

## Detailed Risk Assessment: TypeScript 5 → 6

This is the only major version bump with real migration work. Here is a targeted analysis against the hassette frontend's actual configuration.

### What the hassette `tsconfig.json` already has right

The existing config explicitly sets `strict: true`, `target: "ES2020"`, `module: "ESNext"`, `moduleResolution: "bundler"`, and `types: ["vite/client"]`. This means:

- **`strict` default change (false → true)**: No impact — already explicit.
- **`target` default change (ES3 → ES2025)**: No impact — already explicit at ES2020.
- **`module` default change (CommonJS → ES2022)**: No impact — already explicit at ESNext.
- **`moduleResolution` default change (node10 → bundler)**: No impact — already explicit.
- **`types` default change (auto-discover → `[]`)**: No impact — already explicit as `["vite/client"]`.
- **Removed module systems (AMD, UMD, SystemJS)**: No impact — using ESNext.
- **Removed `moduleResolution: classic`**: No impact — using `bundler`.
- **Deprecated `target: es5`**: No impact — using ES2020.

### What might break

1. **`rootDir` default change (inferred → `.`)**: The tsconfig does not set `rootDir` explicitly, but it does set `"include": ["src"]`. Since all source files are in `src/`, TypeScript inferred `rootDir` as `./src`. With TS6, if no `rootDir` is set, it defaults to the tsconfig directory (`.`). Since Vite handles the build (not `tsc --build`), and `skipLibCheck: true` is set, this likely has no runtime impact — but `tsc --noEmit` for type checking might report different diagnostics. **Fix**: add `"rootDir": "./src"` to be explicit.

2. **Import assertions syntax**: Grep found zero `assert {` or `with {` patterns in the frontend code. No impact.

3. **Namespace vs module keyword**: Grep found zero `module` keyword namespace declarations. No impact.

4. **`esModuleInterop` default (false → true)**: If any imports use `import * as X from "cjs-module"` where `import X from "cjs-module"` is now preferred, they may emit differently. Since Vite's bundler handles this, runtime behavior won't change, but `tsc --noEmit` might flag new warnings.

### Migration effort

**Small.** Add `"rootDir": "./src"` to `tsconfig.json`. Run `tsc --noEmit` after the upgrade and fix any new diagnostics. The codebase has no legacy TypeScript patterns. The `ts5to6` migration tool (`npx @andrewbranch/ts5to6`) can verify automatically.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| `setup-uv` SHA fix | 7 workflow files | Low | None — same action, newer SHA |
| GH Actions digests | 7 workflow files (overlap with above) | Low | None — same major version |
| Docker uv bump | `Dockerfile` (1 ARG) | Low | None — patch bump |
| HA image bump | 2 compose files | Low | Low — monthly release |
| `typing-extensions` pin | `pyproject.toml` + lockfile | Low | Low — minor, no breaking changes |
| Vite/Vitest patches | `frontend/package-lock.json` | Low | None |
| Shiki minor | `frontend/package-lock.json` | Low | None |
| Preact/prek patches | Already open PRs | Low | None |
| TypeScript 5→6 | `frontend/package.json`, `tsconfig.json`, possibly some `.ts` files | Medium | Medium — major version, needs testing |

### What already supports this

- Full CI pipeline (lint, type check, unit, integration, system, e2e) catches regressions automatically.
- Most dependency constraints use `>=` floors, so lockfile updates don't require `pyproject.toml` changes.
- SHA-pinned actions mean digest updates are pure SHA swaps — no config changes.
- The frontend's `tsconfig.json` is already well-configured for TS6 (explicit strict, target, module, types).

### What works against this

- The `astral-sh/setup-uv` lookup failure will persist until manually fixed — Renovate cannot auto-fix it.
- TypeScript 6 requires manual testing and a `tsconfig.json` tweak before merging.
- The 5-PR concurrent limit means batching is important — merging the safe patches first frees slots for the riskier TypeScript update.

## Options Evaluated

### Option A: Systematic sweep in priority order (recommended)

Merge updates in waves, safest first, to keep the PR pipeline flowing and catch regressions early.

**Wave 1 — Manual fix (no Renovate PR)**:
1. Update `astral-sh/setup-uv` SHA from `fac544c...` (v8.2.0) to `d31148d...` (v8.3.0) across all 7 workflow files. Change comment to `# v8.3.0`. This clears the dashboard warning.

**Wave 2 — Merge open PRs + unlimit safe patches**:
2. Merge PR #1193 (preact 10.29.4 patch) and PR #1194 (prek 0.4.8).
3. Unlimit and merge: vite 8.1.3, vitest+coverage 4.1.10, shiki monorepo, uv Docker 0.11.26. These are all patch bumps with zero risk.

**Wave 3 — Minor bumps**:
4. Unlimit `typing-extensions` 4.15.* → 4.16.*. Minor bump, no breaking changes per changelog.
5. Unlimit `homeassistant/home-assistant` 2026.6 → 2026.7. Run system tests after merge to verify.

**Wave 4 — Check pending digest updates**:
6. Force-create the 7 GitHub Actions digest update PRs (docker/*, dorny/paths-filter, j178/prek-action). Merge all.

**Wave 5 — TypeScript 6 (manual)**:
7. Create a branch. Update `typescript` to `^6.0.0` in `package.json`. Add `"rootDir": "./src"` to `tsconfig.json`. Run `npx @andrewbranch/ts5to6` for automated checks. Run `tsc --noEmit`, fix any diagnostics. Run `npm run build` and `npm run test:coverage`. Commit and PR.

**Pros**:
- Clears the dashboard systematically, lowest-risk items first
- Each wave is independently verifiable — CI catches regressions before the next wave
- Frees PR slots for the riskier items by merging safe patches first
- The setup-uv fix clears a persistent dashboard warning that clutters the view

**Cons**:
- Multiple waves means multiple merge-and-wait cycles
- HA 2026.7 may require system test investigation if entity behavior changed

**Effort estimate**: Small for waves 1-4 (mechanical). Medium for wave 5 (TypeScript migration needs testing).

**Dependencies**: None across waves — each is independent. Wave order is about risk sequencing, not technical dependency.

### Option B: Merge-all-safe-then-TS6 (lighter touch)

Skip the wave structure. Merge/unlimit everything that's a patch or digest bump in one pass (check all rate-limited checkboxes except TypeScript, force-create all digest PRs, merge open PRs). Then do TypeScript 6 as a separate focused effort.

**Pros**:
- Faster — one pass clears most of the dashboard
- Still isolates the only risky update (TS6) for focused attention

**Cons**:
- The `setup-uv` fix still requires a manual commit (not a Renovate PR)
- If the HA 2026.7 bump introduces a regression, it's harder to isolate when merged alongside other changes
- Less structured — no clear verification checkpoints between items

**Effort estimate**: Small overall, Medium for the TS6 portion.

## Concerns

### Technical risks

- **TypeScript 6 `rootDir` inference change**: The only concrete break identified. Without adding `"rootDir": "./src"`, `tsc --noEmit` may report different paths in error messages or behave unexpectedly with path aliases. Fix is a one-line addition.
- **HA 2026.7 entity behavior**: Monthly HA releases sometimes change entity state representations, attribute names, or service schemas. The system tests exercise real HA WebSocket connections, so they will surface incompatibilities — but debugging them requires reading the HA release notes.

### Complexity risks

- **None significant.** All updates are version bumps with established CI coverage. No new dependencies or architectural changes.

### Maintenance risks

- **TypeScript 6 `ignoreDeprecations` escape hatch**: If the migration uses `"ignoreDeprecations": "6.0"` as a temporary fix, it must be removed before TypeScript 7.0 (which removes this option entirely). Better to fix all diagnostics now rather than defer.
- **`astral-sh/setup-uv` floating tag**: If the repo never publishes a floating `v8` tag, Renovate will continue failing on future minor releases unless the comment convention switches to specific version tags (`# v8.3.0` instead of `# v8`).

## Open Questions

- [ ] **HA 2026.7 breaking changes**: Web search was unavailable for HA release notes. Check `https://www.home-assistant.io/blog/` or `https://github.com/home-assistant/core/releases/tag/2026.7.0` before merging the HA image bump.
- [ ] **`astral-sh/setup-uv` floating tag policy**: Is the lack of a `v8` floating tag intentional or an oversight? Check `https://github.com/astral-sh/setup-uv/issues` for discussion. This determines whether to pin `# v8.3.0` (permanent) or expect a `v8` tag to appear eventually.
- [ ] **`whenever` 0.10.* status**: Not flagged by Renovate (no newer minor available), but worth checking if a 0.11.* or 1.0 is imminent — the `==0.10.*` pin would block it silently.
- [ ] **Inline tool pins (ruff, pip-audit, muffet)**: Should these be checked for available updates as part of this sweep, or deferred? Renovate cannot track them.

## Recommendation

The pending updates are low-risk overall. The only item requiring real attention is TypeScript 6, and the hassette frontend is well-positioned for that migration (strict mode, bundler resolution, and explicit types are all already configured). The `setup-uv` lookup failure is a known Renovate limitation with a straightforward manual fix.

Proceed with Option A (systematic waves). The wave structure costs maybe 30 minutes of extra wall-clock time compared to Option B, but provides cleaner git history and easier regression isolation.

The TypeScript 6 migration is worth doing now rather than deferring. The longer you wait, the more ecosystem tooling (eslint-typescript, vite plugins) will assume TS6, and the migration gap grows. The actual work is small — one tsconfig field and a test run.

### Suggested next steps

1. **Fix `setup-uv` manually** — update SHA and comment tag in all 7 workflow files, commit and push. This clears the dashboard warning immediately.
2. **Merge open PRs** (#1193, #1194) and unlimit all patch/digest updates via the dashboard checkboxes.
3. **Create a TS6 migration branch** — `typescript` bump + `rootDir` fix + `tsc --noEmit` + full frontend test suite. PR when green.
4. **Check HA 2026.7 release notes** before unlimiting the HA image bump — if breaking changes affect hassette's integration surface, plan accordingly.

## Sources

- [TypeScript 6.0 Official Release Notes](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-6-0.html)
- [TypeScript 5.x to 6.0 Migration Guide](https://gist.github.com/privatenumber/3d2e80da28f84ee30b77d53e1693378f)
- [TypeScript 6.0 Breaking Changes (PAS7)](https://pas7.com.ua/blog/en/typescript-6-explained-2026)
- [TypeScript v6 Migration Guide (LogRocket)](https://blog.logrocket.com/typescript-v6-migration-guide/)
- [typing-extensions Changelog](https://github.com/python/typing_extensions/blob/main/CHANGELOG.md)
- [astral-sh/setup-uv Releases](https://github.com/astral-sh/setup-uv/releases)
