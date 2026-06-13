# Copilot Instructions

## Project

Hassette is an async-first Python framework for building Home Assistant automations. Python 3.11–3.13. The frontend is Preact + TypeScript + Vite with CSS Modules.

Core components: App (user automations), Bus (event pub/sub), Scheduler (triggers/jobs), Api (HA REST/WebSocket), StateManager (state access/caching). All are async. `Resource` is the base class; `Service` extends it for background services.

## Python Rules

- **No `from __future__ import annotations`.** Breaks Pydantic, FastAPI, dataclasses, and runtime type inspection. Always flag this.
- **No `Optional[X]`.** Use `X | None`.
- **No lazy imports.** All imports at the top of the file. Exceptions: `TYPE_CHECKING` guards and deferred imports in `__main__.py` to break circular dependencies at startup.
- **Immutability.** Create new objects, never mutate existing ones.
- **Use `whenever` instead of stdlib `datetime`.** Convert at boundaries when libraries require stdlib types.
- **`_` prefix marks private methods on public classes only.** Public classes that app authors use directly (`App`, `Bus`, `Scheduler`, `Api`, `StateManager`) prefix non-API methods with `_` to keep their public surface clean. Internal classes that app authors never touch (the `*Service` classes, executors, repositories) use no `_` prefixes — the class is already internal, so marking individual methods private is redundant noise.
- **Early returns.** Guard clauses at the top, happy path at the bottom.
- **No section divider comments** between methods.
- **Dependencies as parameters.** Functions receive collaborators, not create them inline. If testing requires `mock.patch` more than one level deep, the code needs restructuring.
- **Mock only at boundaries.** External APIs, databases, time, filesystem. Use real instances for internal collaborators.
- **No mutable default arguments** on functions or methods.
- **Every coroutine call must be awaited.** Forgetting `await` silently does nothing.
- **Explicit timeouts on external calls.** No implicit "wait forever."
- **No bare `except:` or silent `except Exception: pass`.** Use `contextlib.suppress` with a specific type when intentional.

## TypeScript Rules

- **No `any`.** Use `unknown` and narrow.
- **No `as` casts** except after full validation, for `as const`, or unavoidable patterns like `.json() as Promise<T>`. Use schema validation or `satisfies` where possible.
- **No `enum`.** Use `as const` objects or union types.
- **Discriminated unions over optional fields** for variant types.
- **Strict mode required** (`"strict": true`).

## Frontend

- **Preact**, not React. Use `class=` in JSX, not `className=`. Import hooks from `preact/hooks`.
- **CSS Modules** for component-specific styles. Shared design system classes use the `ht-` prefix and live in `frontend/src/styles/`.
- **Shared components** (`Button`, `Badge`, `Chip`, `Card`) in `components/shared/` — use these instead of raw `ht-btn`/`ht-badge` class strings.
- **`:global()` required** when referencing global classes from module CSS. Bare `.ht-table` in a module file will break at runtime.
- **Design tokens** in `frontend/src/tokens.css`. No raw hex colors in shared CSS — reference token variables. Module CSS may use `px` values for component-specific layouts.
- Functional components only. No class components. Every `useEffect` with subscriptions must return a cleanup function.

## Commits and PR Titles

- Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`, `perf:`, `ci:`. Lowercase imperative mood, no period.
- This repo uses release-please — PR titles become changelog entries. They should describe user-visible outcomes, not implementation details.

## Testing

- `uv run nox -s dev` for local test runs. `uv run nox -s tests` for CI-equivalent (Python 3.11–3.13).
- `uv run pyright` for type checking.
- Two test harnesses: `HassetteHarness` (real components, integration tests) and `create_hassette_stub()` (MagicMock, web/API tests).
- E2E tests use Playwright with Chromium.
