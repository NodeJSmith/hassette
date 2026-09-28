# GitHub Workflow Reference

Read this before filing an issue or triaging PR CI status.

## Issues

### Titles

Plain imperative description, no type prefixes (labels convey type).

- Bad: `[Bug] App reload broken`, `Feature - add States resource`, `Bug: file watcher crashes`
- Good: `Fix app reload on config change`, `Add States resource proxy`, `Prevent file watcher crash on missing file`

### Required labels

1. **Type** (exactly one): `type:bug`, `type:enhancement`, `type:documentation`, `type:CICD`
2. **Area** (at least one, unless cross-cutting) — where in the code to look:
   - `area:api` — HA REST/WebSocket API
   - `area:apps` — App lifecycle / AppHandler
   - `area:bus` — Event bus
   - `area:cli` — CLI commands and output (`src/hassette/cli/`)
   - `area:config` — Configuration / settings
   - `area:core` — Internal framework plumbing, not necessarily user-facing
   - `area:database` — Telemetry DB schema, migrations, retention
   - `area:scheduler` — Scheduler service
   - `area:testing` — Test infrastructure, coverage, test helpers
   - `area:ui` — Web UI / dashboard
   - `area:websocket` — WebSocket service
3. **Size** (one): `size:small` (< 1 hour), `size:medium` (a few hours), `size:large` (significant effort)

### Optional labels

- **Priority**: `priority:high` (blockers, data loss), `priority:low` (nice-to-haves)
- **Descriptors**: `good first issue`
- **Topic** — what kind of problem, cross-cutting areas. Multiple allowed, except `topic:architecture` and `topic:code-quality` are mutually exclusive (see `.claude/reference/clean-code-findings.md`):
  - `topic:a11y` — focus, keyboard navigation, screen readers
  - `topic:architecture` — module decomposition, coupling reduction, internal structure
  - `topic:cli` — hassette CLI commands (init, build, migrate)
  - `topic:code-quality` — pre-existing mechanical/hygiene findings from `/mine-clean-code`
  - `topic:codegen` — code/type generation pipelines, typed models from HA, schema export
  - `topic:concurrency` — semaphores, rate limiting, timeouts, task management
  - `topic:design-system` — visual tokens, theming, color scales, typography, spacing
  - `topic:dx` — app-author developer experience: API ergonomics, convenience methods, testing helpers
  - `topic:errors` — error handling, retries, error display, exception design
  - `topic:events` — event system design, signals, dispatch, filtering, backpressure
  - `topic:lifecycle` — startup/shutdown sequences, state machines, readiness, cleanup
  - `topic:responsive` — mobile and responsive layout
  - `topic:telemetry` — observability, execution tracking, retention, statistics
- **Epic**: `epic:ha-addon` (add-on and monitoring UI), `epic:hacs` (custom integration for persistent entities/services)
- **Release**: `release:v1.0.0` — must ship before 1.0

Milestones are reserved for roadmap initiatives — see the Roadmap bullet in `CLAUDE.md`'s GitHub section.

### Body

Non-bug issues need at minimum **Description** (what and why) and **Acceptance Criteria** (checklist of done conditions). Bug reports focus on Steps to Reproduce, Expected Behavior, Actual Behavior, and version info; acceptance criteria may come later during triage.

YAML form templates in `.github/ISSUE_TEMPLATE/` enforce structure (`bug_report.yml`, `feature_request.yml`, `task.yml`, `documentation.yml`; `config.yml` disables blank issues and points questions to Discussions).

## PR checks: `file-sizes` and `duplicate-code`

A red `file-sizes` or `duplicate-code` check on a PR is always a real regression introduced by that PR. Fix it in-PR like any other required check.

Each job in `.github/workflows/lint.yml` runs two steps with different scopes:

- **The new-code gate** (`Check for new file-size regressions` / `Check duplicate code (new-code gate)`, PR events only) has no `continue-on-error` and determines the job's conclusion on a PR. It fails only when the PR's diff grew an already-oversized file, created a new oversized file, or introduced a new 3+-way duplicate block (majority overlap with the PR's added lines; see `new_code_violations()` in `tools/check_duplicate_code.py`).
- **The backlog step** (`Check file sizes (full backlog)` / `Check duplicate code (full backlog)`) tracks the already-triaged historical backlog (the `Decompose *` issues) and cannot affect a PR's conclusion: it has `continue-on-error: true` for `file-sizes`, and for `duplicate-code` it doesn't run on PR events at all (the gate step does its own head-tree scan and reports the backlog for context).

See the module docstrings of `tools/check_file_size_regressions.py` and `tools/check_duplicate_code.py` for the full design.
