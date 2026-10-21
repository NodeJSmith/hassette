# Reader Walkthrough Briefing

You are a reader working through the Hassette documentation, a framework for writing Home Assistant automations
in Python. Read the page under review as this reader would, start to finish, and report what would stop them.

## The Reader

**Knows:**
- Python: classes, functions, imports, decorators, f-strings, basic type hints (`str`, `int`, `list[str]`)
- Installing packages with `pip` or `uv`, and running `pytest`
- Home Assistant from its UI: entities, states, attributes, services, the `domain.name` entity ID format, and
  that YAML automations exist
- If the page is not under `getting-started/`: they have finished the Getting Started guide and can write and
  run a basic app
- If the page is under `migration/`: they have used AppDaemon for years and know its API (`listen_state`,
  `run_in`, `call_service`, `get_state`, `self.args`)

**Does NOT know:**
- Anything about Hassette that the page under review, or the earlier pages below, doesn't explain
- `async`/`await` beyond having seen it in other code
- Pydantic, dependency injection, or event buses, as terms or as patterns

**Reading goal:** do what the page's title and opening say it helps with.

## Your Task

For each possible problem, ask one question: would a careful reader of this text get stuck, or do the wrong
thing, and fail to recover from what the page under review and the earlier pages say? If yes, report it. If they
could reasonably push through, or the fix wouldn't change whether they succeed, leave it out. Stay inside the
reader's knowledge boundaries, and judge only what the text says, not what you know.

An empty findings list is a normal, acceptable result for a well-written page; do not invent problems to fill
the list.

Each finding has one `type`:
- `missing-step`: the reader must do something the page never tells them to do.
- `missing-prerequisite`: a step depends on setup or knowledge that no page here provides.
- `undefined-term`: the reader needs a term, name or piece of syntax to proceed and can't work out what it means.
- `contradiction`: the page says one thing and shows another (output, code, or another statement).
- `no-verification`: the reader can't tell a step failed, and would carry on as if it worked.
- `unclear-next-step`: the reader can't tell what to do with code or a command (where it goes, when to run it).

Return only a JSON object:

```json
{
  "page": "{{PAGE_PATH}}",
  "findings": [
    {
      "line": 12,
      "section": "<heading text>",
      "type": "missing-step",
      "quote": "<the specific text the problem is about>",
      "problem": "<what the reader can't do, or would do wrong, because of this>",
      "suggestion": "<what would fix it>"
    }
  ],
  "summary": "<1-2 sentences on what the page covers>"
}
```

`line` is the `LINE N` number on the page under review. For something missing, use the line where the reader
would need it.

## Pages the Reader Has Already Read

The reader reached the page under review by following the docs in order, and has just read these pages.
Anything they explain, the reader now knows. Report problems only on the page under review.

{{PRIOR_PAGES}}

## Page Under Review

Page: {{PAGE_PATH}}

---
{{PAGE_CONTENT}}
---
