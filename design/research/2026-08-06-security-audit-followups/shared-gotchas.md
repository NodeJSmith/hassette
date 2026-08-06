# Shared gotchas

Traps hit while shipping PR #1532. Each one cost real time or produced a wrong claim. Skim before
starting Brief B or C.

**These notes assume PR #1532 is merged.** A few references describe state it introduces — most
notably the `auth_hassette` / `auth_app` / `auth_client` fixtures in
`tests/integration/web_api/conftest.py`, and `src/hassette/web/body_limit.py`. If #1532 is still
open, branch Brief B off it rather than off `main`, or expect those to be missing. Brief C touches
only `codegen/` and is independent either way.

## Verify gates by exit code, never by grepping output

This one caused an actual false "all hooks pass" claim on PR #1532, and a reviewer had to catch the
three ruff errors that were hiding behind it.

`prek -a` prints one line per hook ending in `Passed`. Filtering those out and reading an empty
result as success is wrong — a failure whose output doesn't end in `Passed` gets swallowed by the
same filter, and `| tail -n` can push the real error off the end.

```bash
# WRONG — an empty result does not mean success
prek -a 2>&1 | grep -vE "Passed$" | tail -10

# RIGHT
prek -a ; echo "exit=$?"
uv run ruff check . ; echo "exit=$?"
prek pyright -a --stage pre-push ; echo "exit=$?"
```

Related: `prek -a` alone does **not** run pyright, which is registered at the pre-push stage.
The full local gate is `prek -a && prek pyright -a --stage pre-push`.

## Don't bypass the commit hook

Git hooks *are* installed in this repo (`pre-commit` and `pre-push` under the common git dir, with
`core.hooksPath` unset — so all worktrees share them). Committing with `-c core.hooksPath=/dev/null`
or `--no-verify` skips a gate that would otherwise catch exactly the class of error above. If you
need to fix it after the fact, `git commit --amend --no-edit` re-runs the hooks against the staged
content.

Expect the first commit attempt to fail anyway: `ruff-format` and the frontend import-sorting hooks
modify files in place, so re-stage and re-commit.

## Frontend deps aren't shared across worktrees

`node_modules/` is per-worktree. Before anything that touches the frontend or regenerates types:

```bash
cd frontend && npm install
```

Brief B and C shouldn't need this, but `scripts/export_schemas.py --types` does.

## Schema regeneration is only needed for model/route changes

If you change a Pydantic response model or a route signature:

```bash
uv run python scripts/export_schemas.py --types
```

That regenerates `openapi.json`, `ws-schema.json`, `generated-types.ts`, and `ws-types.ts` in one
go. A pre-push hook checks freshness for the two schema files; CI additionally git-diffs the two
generated TypeScript files.

Neither Brief B nor C is expected to need this. Adding `max_length` to a field *did* need it on
PR #1532 (it changes `openapi.json`), so the trigger is looser than it sounds — any Pydantic field
constraint counts.

## Test-suite invocation

- Use `-n 4`, never `-n auto`. Unit + integration is ~2:19 at `-n 4` versus ~12:34 serial.
- The full `tests/unit tests/integration` run takes ~4.5 minutes and exceeds the default Bash
  timeout — run it in the background or raise the timeout.
- Don't use `pytest --cov` for backend coverage; it under-reports by 15-40 points. Use the nox
  coverage sessions.
- System and e2e suites run in CI on every push (`tests.yml`, `e2e-tests.yml`). Neither brief touches
  `src/hassette/core/` or the frontend, so there's no reason to run them locally.

## Shared test fixtures live in conftest, not in sibling test modules

PR #1532's integration reviewer caught a duplication worth not repeating: the new test file had
copied `auth_hassette` / `auth_app` / `auth_client` out of `test_auth.py`, and the copy had *already*
dropped a `session_ttl` line on its first duplication.

`auth_hassette`, `auth_app`, and `auth_client` now live in
`tests/integration/web_api/conftest.py` alongside `mock_hassette` / `app` / `client`. Brief B's
integration test should use them from there. Before writing any local `make_*` / `build_*` helper,
check `src/hassette/test_utils/` — a pre-commit hook flags local definitions that shadow a shared
factory name.

## Timing-based assertions are a known flake source here

CLAUDE.md documents a real incident where a test overriding a production timeout raced its own
deliberate delay in wall-clock time and passed locally for months before CI's noisier scheduler
exposed it.

PR #1532 deliberately dropped a wall-clock scaling assertion for the same reason: bounded retained
state is a deterministic proof that per-request work is constant, so a timing ratio would have added
flake risk and no information. Prefer the structural assertion when one exists.

## Mandatory review gate before committing

Per the global git-workflow rules: run `code-reviewer`, `integration-reviewer`, and `wtf-reviewer` on
the final diff before committing. On PR #1532 all three found valid issues that would otherwise have
shipped — including the ruff failures and the fixture duplication. They can read the staged diff
while you keep editing the working tree, as long as you don't re-stage mid-flight.

Standing preference: fix **all** valid findings regardless of severity, not just CRITICAL/HIGH.
