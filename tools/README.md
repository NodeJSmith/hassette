# tools/

CI guards, linters, and code quality checks. Organized by domain:

- **`docs/`** — documentation quality gates (snippet orphans, voice rules, bare symbols, cross-references)
- **`frontend/`** — CSS hygiene guards (allowlist, dead CSS, module globals, undefined refs, breakpoint drift)
- **`release/`** — release verification (tag/version match, wheel SPA assets, PyPI smoke test)

Remaining scripts in the root are pre-commit/pre-push hooks and codemods.
