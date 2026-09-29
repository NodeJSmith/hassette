---
task_id: "T06"
title: "Add the oasdiff wire-compatibility check"
status: "done"
depends_on: ["T03"]
implements: ["FR#16", "AC#15"]
---

## Summary
Adds `tools/check_wire_compat.py`, which compares HEAD's `frontend/openapi.json` with the one at the latest `v*` release tag, in both version-skew directions, using oasdiff 1.32.1.
- **New client, old server:** a reversed run fails when a response field that was optional or absent in the last release became required.
- **Old client, new server:** a forward run fails on oasdiff's default breaking changes, such as removed fields, type changes, and removed endpoints, except for enum value additions, which #2386's lenient parsing owns.

A deliberate break is accepted by listing it in `tools/wire_compat_ignore.txt` in its `!` PR. The check runs in CI's frontend job and as a pre-push hook.

## Target Files
- create: `tools/check_wire_compat.py`
- create: `tools/wire_compat_levels_reversed.txt`
- create: `tools/wire_compat_levels_forward.txt`
- create: `tools/wire_compat_ignore.txt`
- create: `tests/unit/tools/test_check_wire_compat.py`
- create: `tests/unit/tools/fixtures/wire_compat/` (fixture OpenAPI pairs and a fixture ignore file)
- modify: `.github/workflows/tests.yml`
- modify: `prek.toml`
- modify: `mise.toml`
- read: `tools/check_schemas_fresh.py`
- read: `.github/workflows/docs.yml`
- read: `design/research/2026-09-29-wire-compat-enforcement/research.md`
- read: `design/specs/116-wire-models-to-hassette-wire/design.md`

## Prompt
Read `tasks/context.md`, the design section `### Wire-compatibility check (FR#16)` (it has the exact oasdiff arguments, check IDs, flags, override format, and CI mechanics), and the research brief `design/research/2026-09-29-wire-compat-enforcement/research.md`.

1. **`mise.toml`:** add `"github:oasdiff/oasdiff" = "1.32.1"` under `[tools]`, then run `mise install`. (`aqua:` has no oasdiff package; `github:` installs the release tarball.)
2. **Levels files** (format: one `<check-id> <err|warn|info|none>` per line; get the full check-ID list from `oasdiff checks changelog`):
   - `tools/wire_compat_levels_reversed.txt` keeps only `response-required-property-removed` and `response-property-became-optional` at `err` and sets every other check ID to `none`.
   - `tools/wire_compat_levels_forward.txt` lowers only `response-property-enum-value-added` to `info` (the only enum-value-added check that defaults to `error` in 1.32.1).
   - Add a comment header to each file explaining it, if the format allows comments. Verify that it does before adding one.
3. **`tools/wire_compat_ignore.txt`:** ships with no entries. Add a header comment explaining the line format (`METHOD /path <change description>` or `components <change description>`, one per accepted change), that a `!` PR adds lines for its deliberate breaks, and that the file is cleared after the release that ships them. Verify oasdiff accepts comment lines in an `--err-ignore` file. If it doesn't, put the explanation in the script's docstring and ship the file empty.
4. **`tools/check_wire_compat.py`** (follow `tools/check_schemas_fresh.py`'s style: a runnable script with a module docstring):
   - Resolve the latest `v*` tag (`git tag --list 'v*' --sort=-v:refname`, first entry). If there's none, exit non-zero with a message naming the missing tag pattern. Never skip the check.
   - Extract that tag's `frontend/openapi.json` with `git show <tag>:frontend/openapi.json` into a temp file.
   - Run `oasdiff breaking --fail-on ERR --severity-levels tools/wire_compat_levels_reversed.txt --err-ignore tools/wire_compat_ignore.txt <HEAD> <tag-copy>` (reversed), then `oasdiff breaking --fail-on ERR --severity-levels tools/wire_compat_levels_forward.txt --err-ignore tools/wire_compat_ignore.txt <tag-copy> <HEAD>` (forward).
   - Print each run's output and exit non-zero if either fails.
   - Give every subprocess a timeout.
   - Accept optional paths for the base spec, revision spec, and ignore file so tests can drive it with fixtures without git.
5. **Tests** (`tests/unit/tools/test_check_wire_compat.py`): build minimal OpenAPI fixture pairs under `tests/unit/tools/fixtures/wire_compat/`, then call the script (subprocess or its `main()`). Mark the module `pytest.mark.skipif(shutil.which("oasdiff") is None, reason=…)`.
   - It exits non-zero when HEAD adds a required response property, makes an optional one required, removes a response property, or removes an endpoint.
   - It exits 0 when HEAD adds an optional response property, a new endpoint, or a new enum value.
   - It exits 0 for a removed response property that a fixture ignore file lists. Generate that line from oasdiff's own output format so it matches.
   - It exits non-zero, with a message naming the missing tag, when run in a temp git repo with no `v*` tag.
6. **CI** (`.github/workflows/tests.yml`, `frontend` job):
   - Add `fetch-depth: 0` to its `actions/checkout`; the default shallow checkout has no tags. `lint.yml` already does this.
   - Add `actions/setup-go` (SHA-pinned like `docs.yml`, `go-version: "stable"`, `cache: false`), then `go install github.com/oasdiff/oasdiff@v1.32.1` and add `$(go env GOPATH)/bin` to `$GITHUB_PATH`. Put a comment on that step naming `mise.toml` as the other place the version is pinned.
   - Then run `uv run pytest tests/unit/tools/test_check_wire_compat.py` and `uv run python tools/check_wire_compat.py`.
   - Add `tools/check_wire_compat.py`, `tools/wire_compat_*.txt`, and `tests/unit/tools/test_check_wire_compat.py` to the `changes` job's `code` path filter.
7. **`prek.toml`:** add a `check-wire-compat` hook (`language = "system"`, `pass_filenames = false`, `stages = ["pre-push"]`, `entry = "uv run python tools/check_wire_compat.py"`). Its `files` pattern is `check-schemas-fresh`'s pattern plus `^tools/(check_wire_compat\.py|wire_compat_.*\.txt)$`.

## Focus
- **Direction logic:** the argument order is the whole trick. oasdiff judges `base → revision` from the old-client/new-server view, so a reversed run is what turns a new required response field into the `error`-level `response-required-property-removed`. Don't "fix" the argument order.
- **Where it runs:** CI doesn't use mise. The tests job (`nox -s tests`) has no oasdiff, so these tests skip there and are enforced by the frontend-job step. Locally, mise provides oasdiff.
- **Branch baseline:** AC#15's "exits 0 on this branch" depends on T02/T03 having kept `frontend/openapi.json` byte-identical to the last release plus whatever has merged since. If the forward run flags something that is really on `main` already, report it rather than adding ignore lines silently.
- **Timeouts:** every external call needs an explicit timeout (`subprocess.run(..., timeout=…)`).
- **Scope:** WS messages (`ws-schema.json`) are out of scope; it isn't OpenAPI.

## Verify
- [ ] FR#16: `tools/check_wire_compat.py` runs both oasdiff directions with the two levels files and `--err-ignore tools/wire_compat_ignore.txt`, `.github/workflows/tests.yml`'s frontend job has `fetch-depth: 0` plus the install and check steps, and `prek.toml` has the `check-wire-compat` pre-push hook.
- [ ] AC#15: `uv run python tools/check_wire_compat.py` exits 0 on this branch, and `uv run pytest tests/unit/tools/test_check_wire_compat.py -n 4` passes (not skipped; oasdiff on `PATH` via mise), covering every exit-code case in the Prompt, including the missing-tag case.
