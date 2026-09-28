# Copilot Instructions

> Condensed from `CLAUDE.md` and `.claude/rules/`. When a convention there changes, update this file too.

## Project

Hassette is an async-first Python framework for building Home Assistant automations. Python 3.11–3.14. The frontend is React + TypeScript + Vite, styled with Tailwind CSS v4 and shadcn/ui.

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

- **React** function components with hooks. No class components. Every `useEffect` with subscriptions must return a cleanup function.
- **Tailwind utilities in JSX.** Compose conditional classes with `cn()` from `@/lib/utils`. No CSS Modules, no `@apply`, no raw hex colors — use the design tokens.
- **Design tokens** live in `frontend/src/global.css`, the single CSS entry point. Prefer the shadcn-named tokens (`--background`, `--foreground`, `--primary`, `--border`); reference project tokens without a Tailwind utility as arbitrary values (`text-[var(--handler-job)]`). `--accent` is Hassette's brand color, not shadcn's highlight role (that is `--highlight-bg`).
- **Primitives** (`Button`, `Badge`, `Card`, `Dialog`, `Table`, etc.) are shadcn components in `components/ui/`; composites live in `components/shared/`. Use them instead of rebuilding standard controls with raw markup.
- Module-level Tailwind class-string constants are named `FOO_CLASS` / `FOO_CLASSES` so the `no-unknown-classes` lint rule can validate them.

## Commits and PR Titles

- Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`, `perf:`, `ci:`. Lowercase imperative mood, no period.
- This repo uses release-please — PR titles become changelog entries. They should describe user-visible outcomes, not implementation details.

## Testing

- `uv run nox -s dev` for local test runs. `uv run nox -s tests` for CI-equivalent (Python 3.11–3.14).
- `prek -a` for lint/format; `prek run pyright -a --stage pre-push` for type checking.
- Two test harnesses: `HassetteHarness` (real components, integration tests) and `create_hassette_stub()` (MagicMock, web/API tests).
- E2E tests use Playwright with Chromium.
