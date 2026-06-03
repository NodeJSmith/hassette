# Writing Prompt Template

Template for briefing subagents that write documentation pages. Fill in the `{{variables}}` for each page.

## How to use

The orchestrating agent fills `{{variables}}` from each page's outline entry and dispatches the filled prompt to a Sonnet writer subagent. The reviewer prompt is dispatched after the writer completes. Use `get-skill-tmpdir docs` for `{{output_dir}}`.

**Variables to fill:**
- `{{page_title}}` -- the page's H1 heading
- `{{output_dir}}` -- from `get-skill-tmpdir docs`
- `{{filename}}` -- the target markdown filename
- `{{section}}` -- the nav section path (e.g., `core-concepts/bus`)
- `{{outline}}` -- the full outline from Phase 2
- `{{snippet_inventory}}` -- the snippet list from the outline
- `{{page_type}}` -- `getting-started`, `concept`, `recipe`, or `reference`
- `{{voice_rules_block}}` -- the matching block from "Voice Rules Blocks" below
- `{{cross_links}}` -- the cross-link list from the outline
- `{{technical_facts}}` -- relevant technical details from the codebase
- `{{page_path}}` -- path to the written page (reviewer prompt only)
- `{{page_type_checklist}}` -- the matching block from "Page-Type Checklists" below (reviewer prompt only)

## Writer Prompt

```
You are writing a documentation page for Hassette, an async Python framework
for Home Assistant automations. Write the "{{page_title}}" page.

## Output location

Write the page to {{output_dir}}/{{filename}} and all snippet files to
{{output_dir}}/snippets/.

## Page outline

Follow this outline exactly:

{{outline}}

## Snippet files to create

All code examples must be in snippet files, included via
`--8<-- "pages/{{section}}/snippets/filename.py"`. Create these files in
{{output_dir}}/snippets/:

{{snippet_inventory}}

## Voice rules (CRITICAL)

This is a **{{page_type}}** page.

{{voice_rules_block}}

### Anti-patterns to avoid

- No "serves as", "acts as", "functions as" when you mean "is"
- No "pivotal", "crucial", "fundamental", "robust"
- No dangling "-ing" phrases
- No synonym cycling (pick one term per concept and stick with it)
- No filler hedging ("It is important to note that", "In order to")
- No "leverage", "utilize", "facilitate" — use "use", "help", "show"
- No em dashes — use periods or commas
- No transition sentences opening paragraphs
- No motivational preamble before code
- No `---` horizontal rules between sections

### Cross-links to use

{{cross_links}}

## Symbol verification (CRITICAL)

Before referencing any method, parameter, class, or type in the documentation,
verify it exists in the codebase. Do NOT guess at method names or parameter
lists. A page that references a non-existent symbol is worse than one that
omits it.

Use Serena MCP tools for verification (load via ToolSearch first):
- `mcp__serena__get_symbols_overview` — list all methods/classes in a file
- `mcp__serena__find_symbol` — find a specific symbol and read its signature

Key source files:
- Bus methods & params: src/hassette/bus/bus.py
- Scheduler methods: src/hassette/scheduler/scheduler.py
- Api methods: src/hassette/api/api.py
- App class: src/hassette/app/app.py
- Predicates (P): src/hassette/event_handling/predicates.py
- Conditions (C): src/hassette/event_handling/conditions.py
- Dependencies (D): src/hassette/event_handling/dependencies.py
- Accessors (A): src/hassette/event_handling/accessors.py
- Triggers: src/hassette/scheduler/triggers.py
- Entities: src/hassette/models/entities/base.py
- StateManager: src/hassette/state_manager/state_manager.py

Before writing a snippet or prose that uses a method, call
get_symbols_overview on the relevant file to confirm it exists, then
find_symbol with include_body=True to check the exact signature. Fallback:
  grep -n 'def method_name' src/hassette/path/to/file.py

Top-level imports are: `from hassette import App, AppConfig, D, states, P, C, A`
Do NOT use deep import paths like `from hassette.models import states` or
`from hassette import dependencies as D`.

## Key technical facts

{{technical_facts}}

Write the complete page now. Include the `--8<--` snippet includes in the
markdown. Write every snippet file to {{output_dir}}/snippets/.
```

---

## Voice Rules Blocks

### Getting-started pages

```
1. **Use "you" and "your"** — direct address throughout.
2. **CODE FIRST, THEN EXPLAIN (HARD RULE)** — Every step MUST open with the
   code snippet include IMMEDIATELY after the H2 heading. No introductory
   sentences before the code. The explanation comes AFTER the code block.

   WRONG (intro before code):
   ## Step 2 — Add Typed Configuration
   Hard-coding entity IDs makes apps hard to reuse.
   ```python
   --8<-- "snippet.py"
   ```

   RIGHT (code first):
   ## Step 2 — Add Typed Configuration
   ```python
   --8<-- "snippet.py"
   ```
   `MyAppConfig` extends `AppConfig`...

   The ONLY exception is "What You'll Build" which has no code.
3. **Short sentences for concepts.** 10-18 words. One idea per sentence.
4. **State the main behavior first, caveats after.**
5. **Every limitation paired with a path forward.**
6. **Present tense.** The thing does the thing.
7. **Anglo-Saxon verbs.** create, declare, run, fire, track, subscribe, set,
   register, cancel, receive, pass, return, call.
8. **Introduce Hassette terms with functional definitions on first use.**
   Say what it DOES, not what it IS. "`App` manages your handlers and
   connection" not "`App` is the base class." "`AppConfig` loads and validates
   settings" not "`AppConfig` is a Pydantic model."
9. **Code-format all identifiers, paths, parameters, and syntax elements.**
10. **No motivational preamble.** Don't explain WHY a feature is useful before
    showing it. The code speaks for itself.
11. **No `---` horizontal rules between sections.**
12. **Link module aliases inline at first use.** When introducing `D`, `states`,
    `self.bus`, `self.scheduler`, or `self.api`, link to the canonical page
    inline in the definition, not in a deferred "See also" sentence.
13. **Show concrete CLI output.** When a step runs a command, show the exact
    mock terminal output. Don't say "look for X" — show the output.
```

### Concept pages

```
1. **System-as-subject throughout — no "you" or "your".** "The bus delivers
   events" not "you receive events."
2. **No imperative mood.** No "Use X", "Pass Y". Use declarative: "X provides",
   "Y accepts."
3. **CODE FIRST for the opening example.** Show the basic example immediately
   after the opening definition sentence. Walk-through follows.
4. **Short sentences.** 10-18 words. One idea per sentence.
5. **State the main behavior first, caveats after.**
6. **Every limitation paired with a path forward.**
7. **Present tense.** The thing does the thing.
8. **Anglo-Saxon verbs.**
9. **Introduce Hassette terms with functional definitions on first use.**
   Say what it DOES, not what it IS.
10. **Code-format all identifiers.**
11. **Concept introductions follow name -> define -> show -> constrain.**
12. **Link module aliases inline at first use.**
13. **No `---` horizontal rules between sections.**
```

### Recipe pages

```
1. **Problem statement uses "you" and "your".** One paragraph, concrete scenario.
2. **"How It Works" uses system-as-subject.** The code is the subject. No "you"
   in this section.
3. **"How It Works" uses flowing prose paragraphs, NOT bullet lists with bolded
   lead-ins.** Each paragraph covers one decision.
4. **"Verify it's working" names a concrete command or UI action.** Show the
   command and expected output.
5. **Short sentences.** 10-18 words.
6. **Introduce Hassette terms with functional definitions on first use.**
7. **Link module aliases inline at first use.**
8. **No `---` horizontal rules between sections.**
```

---

## Reviewer Prompt

```
You are reviewing a documentation page for Hassette, an async Python framework
for Home Assistant automations. The page is a {{page_type}} page
("{{page_title}}"). Find voice violations, technical inaccuracies, and suggest
concrete improvements.

Read the page at {{page_path}}.

## Voice Audit Checklist (apply every item)

### General (all page types)
1. No transition sentences opening paragraphs.
2. Terms defined functionally on first use. Say what it DOES, not what it IS.
   "`App` manages handlers and connection" not "`App` is the base class."
3. Explanatory sentences are 10-18 words. Inline code doesn't count.
4. Main behavior stated first, caveats after.
5. Every limitation paired with a path forward.
6. Module aliases (`D`, `states`, `self.bus`, etc.) linked on first use.

{{page_type_checklist}}

### Symbol accuracy
For every method, parameter, or class the page references, verify it exists
using Serena MCP tools (load via ToolSearch). Use get_symbols_overview on the
relevant source file, then find_symbol with include_body=True to check exact
signatures. Flag any symbol that doesn't exist. Check parameter names and
types against the actual signatures. Verify imports use top-level paths:
`from hassette import App, AppConfig, D, states` (not deep paths like
`from hassette.models import states`).

### Anti-patterns to flag
- "serves as", "acts as", "functions as"
- "pivotal", "crucial", "fundamental", "robust"
- Dangling "-ing" phrases
- Synonym cycling
- Filler hedging
- "leverage", "utilize", "facilitate"
- Em dashes (should be periods or commas)
- Transition sentences opening paragraphs
- Motivational preamble before code
- `---` horizontal rules between sections
- Sentences over 18 words (code identifiers don't count)
- Category definitions instead of functional definitions

## Output format

For each finding:
- **Location**: line number(s)
- **Issue**: what's wrong
- **Suggested fix**: concrete replacement text

Group by: MUST FIX, SHOULD FIX, CONSIDER.
End with a one-paragraph overall assessment.
```

---

## Page-Type Checklists (for {{page_type_checklist}})

Paste the matching block into the reviewer prompt's `{{page_type_checklist}}` slot.

### Getting-started pages

```
7. "you" and "your" used throughout — direct address. NOT system-as-subject.
8. Code shown FIRST, then explained. Code block immediately after the H2 heading. No introductory sentences before code.
9. Concrete CLI output shown. When a step runs a command, show the exact terminal output.
10. No motivational preamble before code. Don't explain WHY before showing WHAT.
11. Link module aliases inline at first use (D, states, self.bus, self.scheduler, self.api).
```

### Concept and API reference pages

```
7. System-as-subject throughout — no "you" or "your." "The bus delivers events" not "you receive events."
8. No imperative mood. No "Use X", "Pass Y." Use declarative: "X provides", "Y accepts."
9. Concept introductions follow name -> define -> show -> constrain.
10. Reference sections use tables before prose. Terse functional definitions in table cells.
11. No admonitions inside reference tables.
```

### Recipe pages

```
7. "How It Works" uses system-as-subject. The code is the subject. No "you" in this section.
8. "How It Works" uses flowing prose paragraphs, NOT bullet lists with bolded lead-ins. Each paragraph covers one decision.
9. "Verify it's working" names a concrete command or UI action with expected output.
10. Problem statement and Variations sections may use "you" and "your."
```
