---
task_id: "T05"
title: "Rename hassette run --base-url/-u/--url to --ha-url/-u"
status: "done"
depends_on: []
implements: ["FR#13", "AC#12"]
---

## Summary

Collapse the three names for `hassette run`'s Home Assistant URL flag into one. Today it is declared as `name=["--base-url", "-u", "--url"]`, and that `--url` spelling is what forces the new global remote-target flag to be `--server-url` instead — two flags in the same parse scope would otherwise mean opposite remotes. Three names for one flag was the underlying confusion, so all of it collapses to `--ha-url`/`-u`. This is a breaking change with no deprecation alias.

## Target Files

- modify: `src/hassette/cli/commands/run.py`
- modify: `tests/unit/cli/test_commands_run.py`
- modify: `tests/unit/cli/test_parse_args.py`
- read: `tests/unit/cli/CLAUDE.md`
- read: `design/specs/092-cli-remote-url/design.md`
- read: `design/specs/092-cli-remote-url/tasks/context.md`

## Prompt

In `src/hassette/cli/commands/run.py:25-27`, change the parameter declaration:

```python
base_url: Annotated[
    str | None, Parameter(name=["--base-url", "-u", "--url"], help="Base URL of the Home Assistant instance.")
] = None
```

to declare only `--ha-url` and `-u`. Both `--base-url` and `--url` are removed — no aliases, no hidden names, no deprecation warning.

**Keep the Python parameter named `base_url`.** Only the `Parameter(name=[...])` list changes. The parameter feeds `init_kwargs["base_url"]` at line 50, which maps to `HassetteConfig.base_url` — a config field this change does not rename. Renaming the Python parameter would break `tests/unit/cli/test_commands_run.py:60`, which calls `cmd_run(token="test-token", base_url="http://ha:8123", dev_mode=True)` by keyword, for no benefit.

Consider sharpening the help text while you are here — `"Base URL of the Home Assistant instance."` is accurate but the whole point of the rename is that "base URL" was ambiguous once a second remote entered the picture. Something naming Home Assistant explicitly reads better next to a global `--server-url`.

Add the flag-surface test at the **wiring** layer, in `tests/unit/cli/test_parse_args.py`, not by inspecting the `Parameter` declaration. `tests/unit/cli/CLAUDE.md` requires a `parse_args` test for every new or changed flag, and documents why: a `--since 7d` bug shipped because every test called the command function directly, so the cyclopts layer between user input and the function was never exercised. Use `app.parse_args(["run", "--ha-url", "http://ha:8123"])` (the subcommand form — `app.meta.parse_args` is for global flags) and assert the value lands in `bound.arguments["base_url"]`. Add companion cases asserting `--base-url` and `--url` now fail to parse.

Leave `tests/unit/cli/test_commands_run.py` otherwise alone — its direct `cmd_run(...)` calls test function logic and stay valid because the Python parameter name is unchanged.

## Focus

This task has no prerequisites and can run in parallel with T01 and T02 — it shares no source files with the target-resolution work.

It does share one **test** file with T04: both add cases to `tests/unit/cli/test_parse_args.py`. T04 therefore declares `depends_on: ["T03", "T05"]` so the two edits serialize rather than racing on the same file. Run this task first; T04 adds its global-flag cases on top. Do not restructure or reorder the classes in that file — T04 extends `TestGlobalFlagWiring`, and gratuitous churn here turns a clean append into a conflict.

The collision this resolves is real and was verified: cyclopts meta-launcher flags and subcommand flags share one parse scope, so a global `--url` would sit next to `hassette run --url` meaning the Home Assistant instance rather than the Hassette API. `-s` was confirmed free for the new global flag; `-u` stays with `--ha-url` here.

`grep -rn "base-url\|\"--url\"" src/ tests/` before finishing — the only remaining matches should be in `run.py` (now `--ha-url`) and any docs, which T06 owns. Note that `base_url=` appears widely in test files as an `httpx`/`AsyncClient` keyword and in `tests/system/conftest.py` as a `HassetteConfig` field — those are unrelated to this flag and must not be touched.

The changelog entry for this lives in the PR's `BREAKING CHANGE:` footer, not in `CHANGELOG.md` — release-please generates that file, and manual edits get overwritten.

## Verify

- [ ] FR#13: `uv run hassette run --help` lists `--ha-url` and `-u`, and lists neither `--base-url` nor `--url`; `grep -n 'base-url\|"--url"' src/hassette/cli/commands/run.py` returns no match.
- [ ] AC#12: `uv run pytest tests/unit/cli/ -v` passes, including the new `test_parse_args.py` cases asserting `run --ha-url` parses into `bound.arguments["base_url"]` while `--base-url` and `--url` fail to parse, and the existing `cmd_run(base_url=...)` keyword call at `tests/unit/cli/test_commands_run.py:60`.
