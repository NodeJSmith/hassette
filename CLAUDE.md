---
audience: open-source library
developers: solo
data-sensitivity: personal
---

# CLAUDE.md

Hassette is an async-first Python framework for building Home Assistant automations. It emphasizes type safety (Pydantic models), dependency injection (FastAPI-style), and async/await patterns. Python 3.11+.

## Common Commands

```bash
uv sync                                   # install dependencies
uv run nox -s dev                         # tests, local dev loop
uv run nox -s tests                       # tests across Python 3.11–3.14 (CI)
uv run nox -s tests_with_coverage         # backend coverage — never `pytest --cov` (under-reports; see tests/TESTING.md)
uv run pytest tests/integration/test_api.py::test_function_name -v
cd frontend && npm install                # once per worktree — worktrees don't share node_modules
cd frontend && npm run test:coverage      # frontend coverage

prek -a                                   # lint + format (all pre-commit hooks)
prek run pyright -a --stage pre-push      # type check — pyright is a pre-push hook, so `prek -a` skips it

uv run mkdocs serve                       # docs site
hassette run                              # start the server
hassette status | app | listener | log | job   # query a running instance (--app, --instance, --since, --json)

# Deterministic telemetry DB for QA/screenshots/demos (scenarios: healthy, empty, degraded,
# error, large-volume, lifecycle, adversarial; generators in scripts/seed_scenarios/)
uv run python scripts/seed_db.py --scenario healthy --output /tmp/hassette-healthy.db
```

## Architecture

| Component | Location | Role |
|---|---|---|
| `Hassette` | `src/hassette/core/core.py` | Coordinator: connects to HA over WebSocket, manages app lifecycle and services |
| `App` | `src/hassette/app/app.py` | Base class for user automations, generic over `AppConfig`. Hooks: `on_initialize`, `on_shutdown`. Each app gets its own Bus, Scheduler, Api, StateManager |
| Bus | `src/hassette/bus/` | Event pub/sub: `on_state_change`, `on_attribute_change`, `on_call_service`, `on`, and one-shot `wait_for`. Glob patterns, predicates, conditions, debounce, throttle |
| Scheduler | `src/hassette/scheduler/` | `schedule(func, trigger)` plus `run_in`/`run_once`/`run_every`/`run_daily`/`run_cron`. Triggers in `hassette.scheduler.triggers`; custom ones implement `TriggerProtocol`. Job groups and jitter |
| Api | `src/hassette/api/` | HA REST/WebSocket: `get_state`, `get_states`, `call_service`, `set_state`, `fire_event`. `Api.helpers` (`HelperClient`) does CRUD on HA helper entities with per-domain `@overload`s |
| StateManager | `src/hassette/state_manager/` | Cached, typed state: `self.states.light`, `self.states[CustomState]`, `self.states.get("light.kitchen")` |
| Event handling | `src/hassette/event_handling/` | `predicates` (`P`), `conditions` (`C`), `accessors` (`A`), `dependencies` (`D`) |
| Resources | `src/hassette/resources/` | `Resource`/`Service` base classes: lifecycle hooks, child tracking, supervision |
| Web | `src/hassette/web/` | FastAPI backend for the monitoring UI; SPA in `frontend/` |

Type conversion registries: `STATE_REGISTRY` (HA entity types → model classes), `TYPE_REGISTRY` (scalar field conversion).

Rules that bite everywhere:

- Bus registration methods are `async` and must be awaited. `name=` is required on every DB-registered listener (`ListenerNameRequiredError` otherwise); `wait_for` is the exception — its name is auto-generated.
- Handlers get only the parameters their signature declares. Don't pad a handler with an unused `event: Event[Any]` just to match siblings.
- One live `Hassette()` per process at a time. Process-global state assumes it; don't add concurrency guards for it.

Subsystem internals live in path-scoped rules under `.claude/rules/` and load automatically when you work in the matching files: `core-startup.md` (startup readiness, app bootstrap gate, StateProxy), `resource-lifecycle.md` (lifecycle, teardown reports), `bus-internals.md`, `web-api.md`, `frontend-css.md`, `demo-and-screenshots.md`, and `tests-*.md` rules for several test directories with notable local fixtures (not every directory has one — check its `conftest.py`). New subsystem guidance goes there too, not in nested `CLAUDE.md` files.

## Designing the Framework

Hassette is a framework. Its real callers are user apps in other repositories, which this repo never sees.

- **In-repo usage is not evidence of demand.** Grepping this repo measures blast radius (call sites to update), not whether users rely on something or struggle with it. `examples/`, `docs/`, and internal apps only show what they happen to demonstrate. Don't dismiss an edge case or rank one API path over another because nothing here exercises it — assume users will. API changes still need changelog entries and migration guidance with zero in-repo callers.
- **Keep the public surface small.** `App` carries almost nothing; a new helper goes on the most specific component whose role it extends (e.g. presence helpers on `StateManager`, not `Api` or `App` delegators). AppDaemon's broad `self.*` surface is a cautionary tale — diverge from its names and signatures where it chose poorly.
- **Convenience APIs must earn their place.** Ask what boilerplate it saves, whether callers could write it trivially against the primitives, and whether the wrapper adds failure modes (races, weaker typing, untestable paths) the primitive doesn't have. If it saves a few lines and adds new failure modes, document the pattern instead.
- **Every new `Api` method is testable through the harness.** Define how it behaves on `RecordingApi` (records an `ApiCall` for writes, reads a harness seed surface for reads) and add the seed API if needed (harness mechanics: `.claude/rules/test-conventions.md`). Never stub it with `NotImplementedError`.
- **HA-facing design follows Home Assistant / HACS conventions** (Integration Quality Scale, current core idioms). A divergence needs a stated, strong reason.

## Internal Documentation

Applies to `CLAUDE.md`, `.claude/`, `design/`, and code comments — not the user-facing docs site, where stating defaults and values is the point.

- **State decisions; point to code for values.** Write rules, rationale, and which file, component, token, or function is canonical. Don't restate a value, class list, signature, or output format that lives in code — a copied value drifts silently and nothing catches it. A pointer can't drift and steers the reader to reuse instead of reimplement.
  - Exception: a command may carry the literal value it needs to be copy-pasteable. When that value is defined in code, name the source next to it (e.g. `-n 4` — `XDIST_WORKERS` in `noxfile.py`) so drift can be checked.
- **A pointer names something that exists.** When you move or rename a doc section, grep for references to it (including code comments) and update them.

## App Pattern

```python
class MyConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="my_")
    setting_name: str = "default"

class MyApp(App[MyConfig]):
    async def on_initialize(self):
        await self.bus.on_state_change("light.kitchen", handler=self.on_light_change, name="kitchen_light")
        await self.scheduler.run_in(self.my_task, 5)

    async def on_light_change(self, event: RawStateChangeEvent):
        pass
```

## Testing

- Bugs: reproduce, write a failing test (RED), fix (GREEN), run the full file. Patterns for races, timeouts, and sentinel filtering are in `.claude/rules/regression-test-patterns.md` (loads under `tests/`).
- Test infrastructure, factories, and mock strategy: `.claude/rules/test-conventions.md` and `tests/TESTING.md`.
- Run pytest with `-n 4`, never `-n auto`. That matches CI (`XDIST_WORKERS` in `noxfile.py`), and `--dist loadscope` makes the worker count change which modules share a worker.
- Run any test you fix or modify before committing — code inspection misses marker filtering, warning config, fixture scoping, and async timing.

## Before Shipping

- **Core changes** (`src/hassette/core/`, `src/hassette/resources/`, `src/hassette/types/enums.py`): the local gate is the unit/integration suite, lint + pyright, and the schema-freshness check. CI runs `nox -s system_with_coverage` and `nox -s e2e` on every push, so don't run those locally unless you're debugging (`uv run nox -s system` needs Docker).
- **Docs changes** (`docs/pages/`): run `doc-persona-review` and `doc-accuracy-review` on the touched pages. See `.claude/rules/doc-rules.md`.
- **UI changes**: use the demo stack (`mise run demo`) for visual QA, and capture screenshots only via `scripts/capture_screenshots.py`, never raw Playwright. Details in `.claude/rules/demo-and-screenshots.md`.

## GitHub

- **Issues:** read `.claude/reference/github-workflow.md` before filing — titles, required type/area/size labels, topic labels, body sections. For pre-existing findings from `/mine-clean-code` or review runs, also read `.claude/reference/clean-code-findings.md`.
- **PR checks:** a red `file-sizes` or `duplicate-code` check always means this PR regressed something; fix it in-PR. Details in the same reference file.
- **Closing issues:** repeat the keyword for each issue (`closes #1, closes #2`); `Closes #1, #2` only closes the first.
- **CodeRabbit** auto-review is disabled. Once the PR is created and marked ready, comment `@coderabbitai review`.
- **Roadmap:** `design/roadmap.md` is the source of truth for Now/Next and forced orderings — read it when asked what to pick up next. Each initiative is a GitHub milestone whose description holds its Done-when. A follow-up issue joins an initiative's milestone only if the Done-when fails without it; otherwise leave it milestone-less (`epic:*`/`topic:*` labels are fine).

## Changelog

Never edit `CHANGELOG.md` by hand — release-please generates it from conventional commits, and the squash-merged PR title becomes the changelog line.

- `feat`, `fix`, `perf`, `refactor`, and `docs` appear in the changelog; use `chore:` for internal work (`design/`, `.claude/`, research, tooling), `ci:`, or `test:`. `docs:` is only for user-facing docs.
- PR titles describe the user-visible outcome, not implementation details or a bundle of fixes.
- A breaking change (`feat!:` etc.) needs exactly one `BREAKING CHANGE:` footer at the end of the PR body — release-please drops every footer after the first.

Read `.claude/rules/changelog-quality.md` before creating a PR with a breaking change or reviewing a release-please PR.

## Design Artifacts

Internal design documents live in `design/`, not `docs/` (the published docs site). `design/context.md` is the canonical UI design direction. See `design/README.md` for what goes where.

## Code Style

- Line length 120, type hints everywhere, Google-style docstrings.
- Ruff + Pyright (commands above).
- No `from __future__ import annotations`.
- No blanket `# type: ignore` — use `# pyright: ignore[reportXxx]`.
- Mixins declare the attributes they expect from their host as class-level annotations. Don't add a runtime `Protocol` to validate the host; a `TYPE_CHECKING`-only one is fine when annotations can't type it (see `_LifecycleHostP` in `resources/mixins.py`).
- User-facing API methods keep their full docstrings even when siblings repeat them (scheduler `run_*`, bus `on_*` delegates) — users read the method they call. Don't flag that as duplication; duplicated bodies are still fair game.
