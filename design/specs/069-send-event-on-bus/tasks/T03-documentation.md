---
task_id: "T03"
title: "Update docs for Bus.emit broadcast pattern"
status: "done"
depends_on: ["T01", "T02"]
implements: ["AC#6", "AC#7"]
---

## Summary

Update the documentation to teach the `Bus.emit` broadcast pattern, fix the migration page's "not supported" claim, disambiguate `fire_event` from `emit`, and rewrite the code snippet. This is the user-facing deliverable of #935.

## Prompt

1. **Rewrite `docs/pages/core-concepts/apps/index.md` section** (lines 133-139, "Sending Internal Events Between Apps"):

   Replace the section to reference `self.bus.emit(topic, data)`. Explain: broadcast is local (in-process, fire-and-forget, ephemeral), all apps subscribed to the topic receive the event, and the pattern is on/emit symmetry on the Bus. Mention self-delivery as a documented behavior with the handler-side guard pattern. Follow the voice guide in `.claude/rules/voice-guide.md`.

2. **Rewrite `docs/pages/core-concepts/apps/snippets/apps_send_event.py`:**

   Show both sender and receiver apps. Sender uses `self.bus.emit("lights_synced", LightsSyncedData(source=self.instance_name))`. Receiver uses `D.EventData[LightsSyncedData]` in its handler annotation. Use section markers (`--8<-- [start:...]` / `--8<-- [end:...]`) for fragment includes. The snippet must pass Pyright.

3. **Fix `docs/pages/migration/index.md` line 30:**

   Change:
   ```
   | Global variables / inter-app communication via `AD` | Not supported — use shared state in the HA state store or a persistent cache |
   ```
   To reference `self.bus.emit` for broadcast and DI (#756) for direct contracted interaction.

4. **Add disambiguation to `docs/pages/core-concepts/api/utilities.md`** in the `fire_event` section (around line 37):

   Add a note: `fire_event` sends an event to Home Assistant's event bus (visible to other HA automations and integrations). For local inter-app communication within Hassette, use `self.bus.emit(topic, data)` instead — it stays in-process and never leaves the framework.

5. **Verify** the docs build cleanly: `uv run mkdocs build --strict` (catches broken links and missing snippets).

## Focus

- **Voice rules for concept pages** (from `.claude/rules/voice-guide.md`): Use system-as-subject — "the bus delivers events" not "you can use the bus." No "you" in concept or API pages. Present tense to describe behavior. Anglo-Saxon verbs (emit, send, fire, receive). State main behavior first, caveats after. Pair every limitation with a path forward. Keep explanatory sentences to 10-18 words.
- Snippet section markers must match the `--8<-- "pages/core-concepts/apps/snippets/apps_send_event.py:section_name"` references in `index.md`.
- The migration table is pipe-delimited markdown — preserve the table format.
- All code in snippets must be importable and type-checkable (CI runs Pyright on snippet files).

## Verify

- [ ] AC#6: The docs site has a "Broadcasting Events" section explaining emit, self-delivery, and the fire_event distinction
- [ ] AC#7: The migration page no longer says inter-app communication is "not supported"
