---
task_id: "T04"
title: "Document domain sync facades in the docs site"
status: "done"
depends_on: ["T02"]
implements: ["FR#1", "FR#2"]
---

## Summary

Update the docs site so sync (`AppSync`) authors discover that domain-specific
entity actions are now available synchronously via `entity.sync.<method>()`,
without the manual `task_bucket.run_sync(...)` boilerplate. This is the
user-facing documentation facet of the new facade surface — required in the same
PR per the project's design-completeness rule. Independent of T03 (both depend
only on T02) — the two may run in parallel.

## Prompt

Depends on T02 (the facade classes must exist so examples are accurate).

The feature removes the need for sync authors to write
`self.task_bucket.run_sync(entity.open_cover())` — they can now call
`entity.sync.open_cover()` directly. Update the docs to reflect this.

1. **Find the pages that currently teach the workaround.** Start with:
   - `docs/pages/core-concepts/apps/task-bucket.md` — if it shows
     `run_sync(entity.<domain_method>())` for entity actions, update it: domain
     actions now have sync facades; `run_sync` remains for arbitrary coroutines,
     not for entity domain methods.
   - `docs/pages/core-concepts/apps/index.md` and
     `docs/pages/core-concepts/api/index.md` — if they describe the `.sync` facade
     as covering only `turn_on`/`turn_off`/`toggle`, broaden the description to
     "all domain actions" and add a short example
     (e.g. `cover.sync.set_cover_position(position=60)`).
   - `docs/pages/migration/*` — if any migration page tells AppDaemon users to use
     `run_sync` for domain calls, note the facade alternative.

   Run `grep -rn "run_sync" docs/pages/` and `grep -rn -i "\.sync" docs/pages/` to
   confirm the full set before editing.

2. **Follow the docs voice.** Adhere to `.claude/rules/voice-guide.md` and
   `.claude/rules/doc-rules.md`: concept/API pages use system-as-subject (no
   "you"), getting-started/recipe procedure sections may use "you". Lead with what
   the facade does. Code examples must come from tested snippet files
   (`--8<--` includes), not inline blocks — if you add an example, add it to the
   page's co-located `snippets/` directory so Pyright type-checks it. Use real
   entity names (`cover.living_room`, `climate.bedroom`).

3. **Build the docs to verify** no broken includes or strict-mode errors:
   ```bash
   uv run mkdocs build --strict
   ```

Keep the change scoped to documenting the new surface — do not rewrite unrelated
sections. Do NOT edit `CHANGELOG.md` (release-please owns it).

## Focus

- The generated facade method docstrings ship automatically via the T01 template —
  this task is the **docs-site** layer (learning material), not docstrings.
- `docs/pages/core-concepts/apps/task-bucket.md` is the highest-value target: it
  likely frames `run_sync` as the way to call async things from sync apps. The
  facade now covers entity domain actions, so the guidance should distinguish
  "entity domain actions → use `entity.sync.<method>()`" from "arbitrary
  coroutines → still `run_sync`".
- Snippet discipline: a page at `.../foo/index.md` includes snippets from
  `.../foo/snippets/`. CI type-checks all snippets with Pyright. A new example
  that isn't a tested snippet will fail the docs CI conventions.
- `mkdocs build --strict` fails on broken links/includes — run it before
  considering the task done.

## Verify

- [ ] FR#1: A docs page documents that each domain entity exposes a typed sync
      facade (`entity.sync` returns the domain facade), with at least one concrete
      domain-action example beyond `turn_on`/`turn_off`/`toggle`. Mechanical
      anchor: `grep -rn "\.sync\." docs/pages/` returns a domain-action call (e.g.
      `.sync.open_cover`/`.sync.set_cover_position`/`.sync.set_temperature`) in a
      changed page.
- [ ] FR#2: The docs show a domain-specific sync action with parameters (e.g.
      `cover.sync.set_cover_position(position=...)` or
      `climate.sync.set_temperature(temperature=...)`), and any guidance that told
      sync authors to use `run_sync` for entity domain methods is updated to point
      at the facade. `uv run mkdocs build --strict` succeeds.
