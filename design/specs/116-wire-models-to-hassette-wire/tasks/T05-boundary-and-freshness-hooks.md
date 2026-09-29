---
task_id: "T05"
title: "Add hassette_client boundary rule and wire freshness hook"
status: "planned"
depends_on: ["T02"]
implements: ["FR#13", "FR#15", "AC#9", "AC#11"]
---

## Summary
Two small tooling guards around the new package:
- **Boundary rule:** the module-boundary checker gains a `no-hassette-client` rule. No `src/hassette` module may import `hassette_client`, because the CLI plugin receives the client through its `register(app)` entry point (#2387), never through an import.
- **Freshness hook:** the pre-push schema-freshness hook also fires when files under `wire/src/hassette_wire/` change. That's where the served models now live, so an edited wire model can't be pushed with stale generated schemas.

The issue's original "rule 1" (an allowlist of which layers may import `hassette_wire`) is intentionally not implemented.

## Target Files
- modify: `tools/check_module_boundaries.py`
- modify: `tests/unit/tools/test_check_module_boundaries.py`
- modify: `prek.toml`
- read: `tools/check_schemas_fresh.py`
- read: `design/specs/116-wire-models-to-hassette-wire/design.md`

## Prompt
Read `tasks/context.md` and the design section `### Boundary checker (tools/check_module_boundaries.py)`, plus the "Boundary rule and its test" convention example.

1. In `tools/check_module_boundaries.py`:
   - Add `"hassette_client"` to `WATCHED_ROOTS` (line ~103; currently `{"hassette", "tests"}`), and update the docstring near line 343 that lists the watched roots.
   - Add a `Rule(name="no-hassette-client", applies=lambda _: True, forbids=forbids_prefix("hassette_client"), reason=…)`. The reason says the CLI plugin reaches the client through the `hassette.cli` entry point's `register(app)` argument (#2387), never through an import. The existing `applies_prefix`/`applies_outside` helpers can't express "every layer", so use the plain lambda. Don't add a helper for a single use.
   - Add the rule to the module docstring's rule list.
   - `Rule.applies` keeps its layer-based signature.
2. In `tests/unit/tools/test_check_module_boundaries.py`:
   - Add a test showing a `hassette_client` import is rejected from several layers (e.g. `core`, `web`, `cli`, and a top-level module), following the file's existing rule-test patterns.
   - Reword the comment near line 591 that names #2385 and the wire allowlist rule, so it describes nested-rule scoping generically, without referring to a rule that won't exist.
3. In `prek.toml`, the `check-schemas-fresh` hook (line ~242, `files = "^src/hassette/(web/|config/)"`): extend the pattern to also match `wire/src/hassette_wire/`, e.g. `"^(src/hassette/(web/|config/)|wire/src/hassette_wire/)"`.

## Focus
- `WATCHED_ROOTS` controls which import roots the checker resolves at all. Without `hassette_client` in it, a `forbids_prefix("hassette_client")` rule never fires, so the test must actually show a violation being reported.
- Every existing rule must flag exactly what it flagged before (Behavioral Invariants). Run the full boundary test file, not just the new test.
- `hassette_client` doesn't need to exist as an installable package for the checker. It analyzes import statements.

## Verify
- [ ] FR#13: `tools/check_module_boundaries.py` contains the `no-hassette-client` rule with `forbids_prefix("hassette_client")`, and `"hassette_client"` is in `WATCHED_ROOTS`.
- [ ] AC#9: `uv run pytest tests/unit/tools/test_check_module_boundaries.py -n 4` passes, including the new rejected-from-every-layer test, and `uv run tools/check_module_boundaries.py` exits 0.
- [ ] FR#15: `prek.toml`'s `check-schemas-fresh` `files` value is a regex that includes the `wire/src/hassette_wire/` alternative.
- [ ] AC#11: `uv run python -c "import re,tomllib; h=[h for r in tomllib.load(open('prek.toml','rb'))['repos'] for h in r.get('hooks',[]) if h.get('id')=='check-schemas-fresh'][0]; assert re.search(h['files'], 'wire/src/hassette_wire/health.py') and re.search(h['files'], 'src/hassette/web/app.py')"` exits 0.
