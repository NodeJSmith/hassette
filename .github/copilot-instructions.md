# Copilot Instructions

## Project

Hassette is an async-first Python framework for building Home Assistant automations. Python 3.11–3.13. The frontend is Preact + TypeScript + Vite with CSS Modules.

Core components: App (user automations), Bus (event pub/sub), Scheduler (triggers/jobs), Api (HA REST/WebSocket), StateManager (state access/caching). All are async. `Resource` is the base class; `Service` extends it for background services.

## Python Rules

- **No `from __future__ import annotations`.** Breaks Pydantic, FastAPI, dataclasses, and runtime type inspection. Always flag this.
- **No `Optional[X]`.** Use `X | None`.
- **No lazy imports.** All imports at the top of the file. Only exception: `TYPE_CHECKING` guards for circular import avoidance.
- **Immutability.** Create new objects, never mutate existing ones.
- **Use `whenever` instead of stdlib `datetime`.** Convert at boundaries when libraries require stdlib types.
- **No `_` prefix on methods.** All methods are public. This is a framework, not a library with external consumers.
- **Early returns.** Guard clauses at the top, happy path at the bottom.
- **No section divider comments** between methods.
- **Dependencies as parameters.** Functions receive collaborators, not create them inline. If testing requires `mock.patch` more than one level deep, the code needs restructuring.
- **Mock only at boundaries.** External APIs, databases, time, filesystem. Use real instances for internal collaborators.

## TypeScript Rules

- **No `any`.** Use `unknown` and narrow.
- **No `as` casts.** Use schema validation or `satisfies`.
- **No `enum`.** Use `as const` objects or union types.
- **Discriminated unions over optional fields** for variant types.
- **Strict mode required** (`"strict": true`).

## Frontend

- **Preact**, not React. Use `class=` in JSX, not `className=`. Import hooks from `preact/hooks`.
- **CSS Modules** for component-specific styles. Shared design system classes use the `ht-` prefix and live in `frontend/src/styles/`.
- **Shared components** (`Button`, `Badge`, `Chip`, `Card`) in `components/shared/` — use these instead of raw `ht-btn`/`ht-badge` class strings.
- **`:global()` required** when referencing global classes from module CSS. Bare `.ht-table` in a module file will break at runtime.
- **Design tokens** in `frontend/src/tokens.css`. No raw hex or pixel values elsewhere.
- Functional components only. No class components. Every `useEffect` with subscriptions must return a cleanup function.

## Commits and PR Titles

- Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`, `perf:`, `ci:`. Lowercase imperative mood, no period.
- This repo uses release-please — PR titles become changelog entries. They should describe user-visible outcomes, not implementation details.

## Testing

- `uv run nox -s dev` for local test runs. `uv run nox -s tests` for CI-equivalent (Python 3.11–3.13).
- `uv run pyright` for type checking.
- Two test harnesses: `HassetteHarness` (real components, integration tests) and `create_hassette_stub()` (MagicMock, web/API tests).
- E2E tests use Playwright with Chromium.

## Patterns to Flag in Review

- `from __future__ import annotations` anywhere — always reject.
- `Optional[X]` — suggest `X | None`.
- Mutable default arguments on functions/methods.
- `mock.patch` nested more than one level deep — suggests a DI problem.
- Bare `except:` or `except Exception: pass` — errors must be surfaced or explicitly suppressed with `contextlib.suppress`.
- Missing `await` on coroutine calls.
- External service calls without explicit timeouts.
- `className=` in JSX (should be `class=` for Preact).
- Raw hex/pixel values instead of design tokens in CSS.
- Inline `style={}` for static layout properties.
