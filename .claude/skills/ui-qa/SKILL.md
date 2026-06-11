---
name: ui-qa
description: Use when the user says "ui qa", "visual QA the frontend", "polish pass on the UI", "run the UI personas", or after changes that affect rendering. Agent-driven QA of the web UI against the live demo stack — screenshot matrix critique plus task-driven persona walkthroughs.
---

# UI QA

Agent-driven QA of the Hassette web UI against the live demo stack. Two modes that catch
different bug classes: **screens** (screenshot matrix + design-rule critique — visual
defects) and **personas** (task-driven walkthroughs — navigation dead ends and missing
affordances). The CSS guard scripts in `tools/` already catch structural drift
mechanically; this skill covers what only rendering and usage can reveal.

Use when the user says: "ui qa", "visual QA the frontend", "polish pass on the UI",
"run the UI personas", "review the UI", or after any change that affects rendering.

## Arguments

- empty or `all` — both modes, full scope
- `screens [pages...]` — screenshot critique only, optionally scoped to pages
- `personas [names...]` — walkthroughs only, optionally scoped to personas
- a description of a change ("the logs table at mobile") — infer the scope: pick
  affected pages/viewports and the persona selection table in `references/personas.md`

## Phase 1: Environment

Read `references/harness.md` and follow it: start the demo stack in the background, wait
for `DEMO_READY=true`, then **wait ~2 minutes more** for failure/activity data before
capturing anything. Get a tmpdir via `get-skill-tmpdir ui-qa`.

Skip the wait only when the stack is already running from earlier in the session.

## Phase 2a: Screens mode

1. Capture the matrix (scoped — full matrix only for explicit full audits):

   ```bash
   uv run python tools/frontend/ui_qa_capture.py --base-url $DEMO_FRONTEND_URL --output-dir $TMPDIR/shots [--pages ...] [--viewports ...]
   ```

2. Dispatch one **Sonnet** analysis subagent per page (all viewports/themes of that page
   to one agent, so it can compare breakpoints). The prompt names the screenshot files,
   tells the agent to Read them, and includes the paths to `frontend/DESIGN_RULES.md` and
   `frontend/src/tokens.css` as the standard to judge against — findings must cite a
   rule or token, not taste. Enforce with `schema`:

   ```json
   {
     "type": "object",
     "properties": {
       "page": {"type": "string"},
       "findings": {"type": "array", "items": {"type": "object", "properties": {
         "viewport": {"type": "string"},
         "theme": {"type": "string"},
         "severity": {"type": "string", "enum": ["broken", "degraded", "polish"]},
         "description": {"type": "string"},
         "design_rule": {"type": "string"},
         "suggestion": {"type": "string"}
       }, "required": ["viewport", "theme", "severity", "description", "design_rule", "suggestion"]}}
     },
     "required": ["page", "findings"]
   }
   ```

   Severity: **broken** = content unusable (cropped, overlapping, unreadable);
   **degraded** = works but violates a stated design rule; **polish** = defensible but
   improvable. An agent reporting zero findings for a page is a valid result — do not
   prompt for a minimum count (that manufactures findings).

   Screenshots are the sweep, not a wall: when a finding hinges on behavior a static
   image can't show (does truncated text expand on tap? does this region scroll?), the
   analysis agent should load the live page via Playwright and check — include
   `DEMO_FRONTEND_URL` in its prompt. Same shared-browser constraint as personas:
   agents that go interactive must run sequentially.

## Phase 2b: Personas mode

1. Read `references/personas.md`; select personas per its table (or the user's scope).
2. Dispatch personas **sequentially, not in parallel** — they share the one Playwright
   MCP browser, and parallel agents fight over it. Each subagent prompt contains: the
   persona block verbatim, `DEMO_FRONTEND_URL`, the instruction to set the viewport
   first and stay in character, and a hard cap (~25 browser actions) so a stuck persona
   reports "stuck" instead of wandering. Enforce with `schema`:

   ```json
   {
     "type": "object",
     "properties": {
       "persona": {"type": "string"},
       "verdict": {"type": "string", "enum": ["completed", "completed-with-friction", "stuck", "abandoned"]},
       "path": {"type": "array", "items": {"type": "string"}},
       "findings": {"type": "array", "items": {"type": "object", "properties": {
         "url": {"type": "string"},
         "attempted": {"type": "string"},
         "friction": {"type": "string", "enum": ["dead-end", "cant-find", "cropped-content", "tap-target", "lost-context", "unexplained-term", "misleading-label", "no-feedback"]},
         "description": {"type": "string"},
         "suggestion": {"type": "string"}
       }, "required": ["url", "attempted", "friction", "description", "suggestion"]}},
       "summary": {"type": "string"}
     },
     "required": ["persona", "verdict", "path", "findings", "summary"]
   }
   ```

   `attempted` is mandatory by design: a finding without the action it blocked is an
   opinion, and opinions are out of scope.

## Phase 3: Collate and present

Merge findings; when screens and personas flag the same spot, say so (highest
confidence). Lead with `broken`/`stuck`. Cross-reference open `area:ui` issues
(`gh-issue list`) — mark findings that are already filed instead of re-reporting them.

End with verdict tables (`—` = not run):

| Page | broken | degraded | polish |
|------|--------|----------|--------|

| Persona | Verdict | Findings |
|---------|---------|----------|

Then ask the user: fix the quick wins inline, file issues for the rest, or both.
Tear down the demo stack when done (orphaned stacks thrash the machine).

## Design decisions

**Why a live demo instead of mocks?** Mock data renders idealized states; the demo's
example apps produce real tracebacks, real timing data, and a deliberately failing job.
Realism is load-bearing: a persona chasing fake data reports fake friction.

**Why personas are tasks, not page lists.** Per-page review can't see between pages —
and the costliest UI bugs (hidden pages, dead ends, lost context) live between pages.

**Why findings must cite a design rule or an attempted action.** LLM reviewers
hallucinate taste-based findings under pressure to produce output. Anchoring every
finding to `DESIGN_RULES.md`/`tokens.css` (screens) or a blocked action (personas) makes
findings checkable and keeps "I'd have used more padding" out of the report.

**Why sequential personas.** One shared Playwright MCP browser. Three sequential
personas cost ~15 minutes; debugging two agents interleaving navigation costs more.
