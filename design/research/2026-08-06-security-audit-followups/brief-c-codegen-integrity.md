# Brief C — codegen literal escaping and generated-file ownership

**Audit findings 4 and 6** — medium (CWE-94) and low (CWE-73), both high confidence.
**Estimated effort:** ~3h for both.
**Suggested branch:** `security/codegen-integrity`
**Commit type:** `fix(codegen):` — or `chore(codegen):` if you'd rather keep it out of the changelog,
since no released user-facing behavior changes. `fix:` is defensible because finding 4 is also a
latent correctness bug (below).

Both findings live in `codegen/`, a separate package with its own `pyproject.toml`, tests, and
`hassette-codegen` entry point. Nothing in `src/hassette/` changes, so this PR cannot conflict with
Brief B.

## Threat model — read this before sizing the work

Both findings require an attacker who already controls the Home Assistant core checkout that codegen
reads from. That is a developer-machine or release-pipeline compromise, not anything a deployed
Hassette instance is exposed to. Neither is a live vulnerability in a running install.

That does **not** make them worthless: finding 4 is simultaneously a plain correctness bug. Any HA
constant or `services.yaml` description containing a double quote produces broken or wrong generated
output today, with no attacker involved. Fix it as a robustness fix that happens to close a
supply-chain hole.

Corollary: **skip the audit's "structural AST allowlist before atomic replacement."** That is a
large amount of machinery for a threat gated behind an already-compromised upstream. Centralizing
literal and identifier rendering gets nearly all the value at a fraction of the cost. This is a
deliberate scope decision, not an oversight — record it in the PR body so a reviewer doesn't
re-litigate it.

## Finding 4 — external strings rendered as source text

Upstream-derived strings are interpolated into Python constructs with no escaping. Formatting and
compilation validate *syntax*, so an input that stays syntactically valid passes every existing
check while no longer being one literal.

### The audit pointed at the wrong worst site

The audit's affected-lines list cites `generators/constants.py:6-15`,
`templates/state_model.py.j2:20-25`, and `templates/entity_wrapper.py.j2:17-56`. Those are real, but
the sharpest instance is one it didn't name:

**`build_method_docstring()` — `codegen/src/hassette_codegen/generators/entities.py:158-194`.**
It wraps Home Assistant's own `services.yaml` service description in `"""…"""` and returns a string
that the template inserts as **raw source lines** — a bare `{{ service.doc }}` at statement
position. Its own docstring says "the template inserts it verbatim." A description containing `"""`
closes the docstring and lands in executable position directly. No quote escaping happens anywhere
on that path.

### Full inventory of unsafe interpolations

Line numbers verified against the tree at `4a20fb95`. **Note the repeat counts** —
`entity_wrapper.py.j2` renders four separate service blocks (async and sync-facade variants, each
with and without params), so every one of these interpolations appears four times. A fix applied to
one block only will look correct and silently miss three-quarters of the surface.

| Site | Interpolation | Position | Risk |
|---|---|---|---|
| `generators/entities.py:158-194` | `summary`, `param.description` | inside `"""…"""`, inserted raw | **highest** — breaks out of a docstring into code |
| `templates/entity_wrapper.py.j2:40,52,78,89` | `{{ service.doc }}` | raw statement position | the insertion site for the above |
| `generators/constants.py:11-13` | `f'    "{val}",'` | string literal in a `Literal[...]` | quote in `val` escapes the literal |
| `templates/state_model.py.j2:25` | `{{ member_name }} = "{{ member_value }}"` | StrEnum member value | same |
| `templates/state_model.py.j2:33` | `{{ member_name }} = {{ member_value }}` | IntFlag member value, **unquoted** | arbitrary expression position |
| `templates/entity_wrapper.py.j2:43,55,81,92` | `service="{{ service.name }}"` | string literal | quote escapes |
| `templates/entity_wrapper.py.j2:29,51,67,88` | `service.method_name` | identifier position | not validated as an identifier |
| `templates/entity_wrapper.py.j2:34,36,46,72,74,84` | `param.name`, `param.python_type` | identifier + type position | same |
| `templates/state_model.py.j2:40` | `prop.name`, `prop.python_type` | identifier + type position | same |
| `templates/state_model.py.j2:53,56,57` | `member_name` (via `supports_*` properties) | identifier position | same |

### Existing mitigations, and why they're partial

`atomic_write()` (`codegen/src/hassette_codegen/output.py:97-131`) runs `ruff check --fix` and
`py_compile` on a temp file before replacing the target, and skips the write on failure. So
syntactically broken output is already rejected — that catches the accidental case. It does not catch
an injection that produces valid syntax, which is precisely what the audit's non-executing AST
reproduction demonstrated ("one extracted value produced an extra top-level statement").

### The right fix already has a precedent in-tree

`state_model.py.j2:47` does this correctly:

```jinja
@field_validator({{ datetime_fields | map("tojson") | join(", ") }}, mode="before")
```

`tojson` is the escaping-safe filter. Follow that pattern:

- **String literals in templates** → pipe through `tojson` instead of wrapping in manual `"…"`.
- **String literals in Python generators** → `repr(val)` instead of `f'"{val}"'`.
- **Docstrings** → the raw-insert design in `build_method_docstring` is the actual problem. Either
  escape any `"""` and trailing backslash in the text before wrapping, or restructure so the
  template renders the docstring as a proper literal rather than raw lines. Escaping is the smaller
  change; note that a description ending in `\` also breaks the closing delimiter.
- **Identifier positions** (`method_name`, `param.name`, `prop.name`, enum member names) → validate
  with `str.isidentifier()` and reject or skip the domain with the existing
  `print(f"WARNING: ...", file=sys.stderr)` + `skipped_domains.append(...)` pattern that
  `pipeline.py:73-77` already uses for extraction failures.
- **Type-expression positions** (`python_type`) → these come from the codegen's own type mapping
  rather than straight from upstream text. Confirm that before deciding whether they need a guard;
  if the mapping is a closed set, they're fine as-is and saying so in the PR is better than adding a
  pointless check.

Centralize the literal/identifier helpers in one module so there's a single place to audit — the
audit's "Centralize literal and identifier rendering" preventive control, which is worth doing.

### Tests

`codegen/tests/` already has `test_docstring_builder.py`, `test_constants_and_exports.py`,
`test_state_generator.py`, `test_entity_generator.py`, and `test_output.py` — extend those rather
than adding a parallel file.

Per the audit, plus what the inventory above implies:

- Push `"`, `'`, `"""`, `\`, `\n`, and non-ASCII through every extracted string field.
- Parse the generated output with `ast` and assert each input still corresponds to exactly **one**
  literal — string equality is not enough, since the failure mode is "valid syntax, wrong
  structure." Counting top-level statements in the generated module is the assertion that actually
  catches this.
- A non-identifier `method_name`/`param.name` is rejected or skipped rather than emitted.
- Existing golden output is unchanged for all current domains — this fix must be a no-op on real HA
  input. That regression check matters more than any single escaping test.

## Finding 6 — generated names can clobber hand-written files

`discover_domains()` (`ha_source.py:151-181`) takes `component_dir.name` verbatim from the HA
components scan. `pipeline.py:80` and `:97` turn it straight into an output basename:

```python
state_path = states_dir / f"{domain_info.name}.py"
entity_path = entities_dir / f"{domain_info.name}.py"
```

No reserved-name check and no ownership check. Confirmed colliding hand-written files exist:

- `src/hassette/models/states/base.py`
- `src/hassette/models/states/catalog.py`
- `src/hassette/models/entities/base.py`
- `__init__.py` in both directories

No path-traversal risk — a directory name can't contain `/` — so this is name collision only, which
is why low severity is right. Git makes recovery trivial. It is still worth a guard, because the
failure is silent.

### This fix is much cheaper than it looks

`codegen/src/hassette_codegen/manifest.py:38-40` already defines exactly the predicate needed:

```python
def is_owned(path: Path, manifest: set[Path]) -> bool:
    """Check if the generator owns this file."""
    return path in manifest
```

It is **tested** (`codegen/tests/test_manifest.py:45-49`) and **never called in production**.
`pipeline.py:23` imports `detect_orphans, load_manifest, merge_manifest, save_manifest` — not
`is_owned`. And `previous_manifest` is loaded at `pipeline.py:62` but used only for orphan detection
at `:142` and `:154`, never as a write gate.

So the fix is:

1. Add a `RESERVED_BASENAMES = {"base", "catalog", "__init__"}` constant and reject any discovered
   domain whose name is in it, using the existing skip-and-warn path.
2. Before `atomic_write`, refuse to replace an existing file that is not `is_owned(rel_path,
   previous_manifest)`. First-time generation of a genuinely new file must still work — the target
   won't exist, so gate on "exists AND not owned."

Watch the interaction with `--domain` filtering: `merge_manifest` exists specifically so a filtered
run doesn't mark unprocessed domains as orphans. Make sure the new gate reads the *previous*
manifest (which includes unprocessed domains) and doesn't reject a legitimate re-generation of a
file the current filtered run happens not to have regenerated yet.

### Tests

Extend `codegen/tests/test_manifest.py` and `test_output.py` / `test_integration.py`:

- Every reserved basename is rejected before any write happens.
- An existing unowned colliding file is left **byte-identical** — assert on content, not just mtime.
- A normally generated, manifest-owned file still updates (the guard must not break the happy path).
- A brand-new domain not in the previous manifest still generates on a first run.

## Codegen environment notes

Codegen is a separate package and needs an HA core checkout to run end-to-end.

- There is a local HA core checkout at `~/source/core` — reuse it rather than cloning a fresh one.
- `codegen/` has its own `uv.lock` and historically its own venv. There is an open question in the
  project notes about whether that separate venv is still needed now that hassette supports 3.14;
  don't try to resolve that here.
- `codegen/ha-version.txt` pins the HA version the current generated output corresponds to.
- Codegen freshness runs as a **pre-push** hook, not pre-commit. If the pre-push hook isn't
  installed in this worktree: `prek install --hook-type pre-push`.

Most of this brief's work is unit-testable without running the full pipeline against real HA source
— prefer that. But do at least one full `--check` run to confirm the escaping change is a no-op on
real input.

## Verification

```bash
uv run pytest codegen/tests -q

# Confirm no drift against real HA source — the important regression signal
# (check the pipeline's own check-mode entry point; see codegen/tests/test_cli.py for invocation)

# Gates — check the EXIT CODE, not printed output (see shared-gotchas.md)
uv run ruff check . ; echo "exit=$?"
prek -a ; echo "exit=$?"
prek pyright -a --stage pre-push ; echo "exit=$?"
```

Note `ruff.toml` per-file-ignores already grants `codegen/**/*.py` the set
`["S108", "S603", "S607", "S701"]` — `S701` is jinja2 autoescape, which is disabled deliberately
because this generates Python, not HTML. Don't "fix" that by enabling autoescape; HTML escaping is
the wrong escaping for this output and would corrupt generated source.
