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

### Concept and API reference pages

7. **System-as-subject throughout — no "you."** "The bus delivers events" not "you receive events." "your" is also banned. *(Rule 10)*
8. **No imperative mood.** No "Use X", "Pass Y", "Set Z." Use declarative: "X provides", "Y accepts", "Z controls." *(Rule 15)*
9. **Concept introductions follow name -> define -> show -> constrain.** Definition says what it does. Code example is minimal. Constraints come after. *(Rule 16)*

### Recipe pages

10. **"How It Works" uses flowing prose paragraphs, NOT bullet lists with bolded lead-ins.** Each paragraph covers one decision. No `- **method_name** does X` patterns. *(Rule 21)*
11. **"How It Works" uses system-as-subject.** The code is the subject when explaining behavior. "you" belongs only in procedural steps and variations. *(Rule 10, 21)*
12. **"Verify it's working" names a concrete command or UI action.** `hassette log --app <key>`, Handlers tab, or similar — not a theoretical description. *(FR#4)*

### Reference pages (addendum)

13. **Tables before prose in reference sections.** The table is the primary content; prose supplements.
14. **Terse functional definitions in table cells.** No narrative. Each cell says what the thing does in one sentence.
15. **No admonitions in reference tables.** Tips, warnings, and notes belong outside the table.

## Top 3 Current Violations

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
