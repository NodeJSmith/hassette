# Docs-Context: Calibration Artifact

Read this file at the start of every documentation writing session. It contains the voice anchors, pass/fail checklist, and common violation patterns that keep writing consistent across sessions.

## Exemplar Pages

These three pages are the voice reference for their respective modes. When in doubt about tone, sentence structure, or page shape, re-read the relevant exemplar.

1. **Concept exemplar:** `docs/pages/core-concepts/bus/index.md` — system-as-subject, no "you," declarative
2. **Recipe exemplar:** `docs/pages/recipes/motion-lights.md` — "How It Works" prose pattern, verification step
3. **Reference exemplar:** `docs/pages/core-concepts/bus/dependency-injection.md` — terse tables, functional definitions, no narrative arc

## Voice Audit Checklist

Run every item on every page before marking a writing task complete. Each item is binary pass/fail.

### General (all page types)

1. **No transition sentences opening paragraphs.** No "Now that we understand X, let's look at Y." Start with the next thing directly. *(Rule 12)*
2. **Terms defined functionally on first use.** First mention of Bus, Scheduler, Api, Cache, App, StateManager, or Resource includes a one-sentence definition of what it does — not what category it belongs to. *(Rule 8)*
3. **Explanatory sentences are 10-18 words.** One idea per sentence. No stacked relative clauses. Inline code identifiers don't count toward the limit. *(Rule 2)*
4. **Main behavior stated first, caveats after.** The reader learns what something does before learning what it doesn't do or where it breaks. *(Rule 3)*
5. **Every limitation paired with a path forward.** One sentence for the constraint, one naming the alternative. *(Rule 4)*
6. **Module aliases linked on first use.** First use of `D.*`, `states.*`, `C.*`, `P.*`, or `A.*` links to the canonical page for that module. *(FR#6)*

### Symbol accuracy (all page types)

7. **Every referenced symbol exists in the codebase.** Method names, parameter names, class names, and type annotations must match the actual source. Grep to verify. *(Writer/Reviewer instruction)*
8. **Imports use top-level paths.** `from hassette import App, AppConfig, D, states` — not `from hassette.models import states` or `from hassette import dependencies as D`. *(FR#6)*

### Getting-started pages

9. **"you" and "your" used throughout.** NOT system-as-subject. Direct address. *(Rule 17)*
10. **Code shown FIRST, then explained (HARD RULE).** The code block must be the very first element after the H2 heading. No introductory sentences, no motivational preamble ("Hard-coding values makes reuse difficult..."), no scene-setting. Explanation follows the code. The only exception is "What You'll Build" which has no code. *(Rule 17)*
11. **Show concrete CLI output.** When a step involves running a command, show the exact mock terminal output the reader will see. Don't say "look for X in the output" — show the output.
12. **No `---` horizontal rules between sections.** Headings provide enough visual separation.
13. **Link module aliases inline at first use.** When introducing `D`, `states`, `self.bus`, `self.scheduler`, or `self.api`, the first mention links to the canonical page inline, not in a deferred "See also" sentence. *(Rule 8, checklist #6)*

### Concept and API reference pages

14. **System-as-subject throughout — no "you."** "The bus delivers events" not "you receive events." "your" is also banned. *(Rule 10)*
15. **No imperative mood.** No "Use X", "Pass Y", "Set Z." Use declarative: "X provides", "Y accepts", "Z controls." *(Rule 15)*
16. **Concept introductions follow name -> define -> show -> constrain.** Definition says what it does. Code example is minimal. Constraints come after. *(Rule 16)*

### Recipe pages

17. **"How It Works" uses flowing prose paragraphs, NOT bullet lists with bolded lead-ins.** Each paragraph covers one decision. No `- **method_name** does X` patterns. *(Rule 21)*
18. **"How It Works" uses system-as-subject.** The code is the subject when explaining behavior. "you" belongs only in procedural steps and variations. *(Rule 10, 21)*
19. **"Verify it's working" names a concrete command or UI action.** `hassette log --app <key>`, Handlers tab, or similar — not a theoretical description. *(FR#4)*

### Reference pages (addendum)

20. **Tables before prose in reference sections.** The table is the primary content; prose supplements.
21. **Terse functional definitions in table cells.** No narrative. Each cell says what the thing does in one sentence.
22. **No admonitions in reference tables.** Tips, warnings, and notes belong outside the table.

## Top Violations

These are the patterns you will most naturally fall into. Check for them last as a final pass.

### 1. Imperative mood in concept pages (Rule 15)

The most pervasive violation. Every current concept page has instances.

**Wrong:** "Use `self.states` instead of API calls for instant access."
**Right:** "`self.states` provides instant access without an API call."

**Wrong:** "Pass `immediate=True` to fire your handler at registration time."
**Right:** "`immediate=True` fires the handler at registration time, before any events arrive."

### 2. "You" / "your" in concept pages (Rule 10)

Found in 4 of 5 sampled pages. Often paired with imperative mood.

**Wrong:** "The event bus connects your apps to Home Assistant."
**Right:** "The event bus delivers Home Assistant events to any app handler that subscribes."

**Wrong:** "You don't need to manage resources yourself."
**Right:** "Hassette manages resource lifecycle automatically."

### 3. Overlong explanatory sentences (Rule 2)

Sentences exceeding 18 words in explanatory prose. Most common in technical descriptions that try to cover behavior + exception + workaround in one sentence.

**Wrong:** "The StateManager event handler is prioritized over app event handlers to ensure you always have a consistent view of the latest states." (24 words + "you")
**Right:** "StateManager's event handler runs before app handlers. App handlers always see the latest state." (two sentences, 8 + 8 words)

### 4. Category definitions instead of functional definitions (Rule 8)

Defining a term by what it *is* rather than what it *does*. The most common form is "`X` is the base class for..." or "`X` is a Pydantic settings model." These tell the reader the taxonomy but not what the thing does for them.

**Wrong:** "`App` is the base class for every Hassette automation."
**Right:** "`App` manages your handlers, scheduler, and connection to Home Assistant."

**Wrong:** "`AppConfig` is a Pydantic settings model."
**Right:** "`AppConfig` loads and validates your app's settings from `hassette.toml`."

**Wrong:** "`self.bus` is Hassette's event bus."
**Right:** "`self.bus` delivers Home Assistant events to your handlers."

### 5. Motivational preamble before code (getting-started pages)

Opening a step with a sentence explaining *why* the feature is useful before showing the code. The code speaks for itself. The reader came here to build, not to be convinced.

**Wrong:**
```
## Step 2 — Add Typed Configuration
Hard-coding entity IDs and strings makes your app hard to reuse.
Hassette gives every app a config class.
[code]
```

**Right:**
```
## Step 2 — Add Typed Configuration
[code]
`MyAppConfig` extends `AppConfig` and declares the fields your app reads.
```

### 6. Deep imports instead of top-level imports

`D`, `states`, `P`, `C`, and `A` are all available as top-level imports from `hassette`. Do not use deep import paths in snippets.

**Wrong:** `from hassette import dependencies as D` or `from hassette.models import states`
**Right:** `from hassette import App, AppConfig, D, states`

### 7. Broken linked method calls

When linking a method call like `self.bus.on_state_change()`, put the full call inside the link text. Splitting the link and the method creates a visible gap in the rendered output.

**Wrong:** `` [`self.bus`](../core-concepts/bus/index.md)`.on_state_change()` ``
**Right:** `` [`self.bus.on_state_change()`](../core-concepts/bus/index.md) ``
