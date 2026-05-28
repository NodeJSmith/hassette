# Documentation Rules

How to write Hassette documentation. `design-completeness.md` governs WHEN docs are needed; this file governs HOW to write them.

## Scope

`design-completeness.md` lists the triggers for when documentation is required. That list is the minimum. Also document: exception types a user might catch, configuration options they might set, and behavioral patterns that would surprise them if undocumented. When a trigger fires, follow the rules below.

## Voice

Hassette docs should feel like a patient friend who's already built the thing you're building and wants to save you the mistakes they made. Friendly. Encouraging. Concrete. The reader should feel like they're getting good advice, not reading a manual.

### The voice in practice

**Write this:**
> Sensors like temperature or humidity often emit bursts of near-identical readings. This recipe waits until a value has been stable for a set period before reacting.

**Not this:**
> The event bus provides a debounce mechanism that can be applied to state change subscriptions. This functionality is particularly useful for sensors that emit high-frequency updates.

**Write this:**
> `debounce=10.0` means the handler won't fire until the sensor has been quiet for 10 seconds. Any new event during that window resets the timer, so rapid fluctuations are silently discarded.

**Not this:**
> The debounce parameter specifies the duration in seconds for which the system will await a period of inactivity before invoking the registered handler callback.

### Voice rules

1. **Use "you" and "your."** The reader is building something. Talk to them. "Your app receives events" not "the application receives events."
2. **Lead with what it does, not what it is.** "The scheduler lets you run functions at specific times" not "The scheduler is a service that manages timed execution of callable objects."
3. **Use concrete examples in prose, not just code blocks.** "like temperature sensors that report every 2 seconds" not "such as high-frequency update sources."
4. **Short sentences for concepts, longer ones for flow.** Introduce an idea in one punchy line. Then explain how it works in a sentence or two that builds on the first.
5. **Active voice.** "Hassette connects to Home Assistant" not "a connection is established." Passive voice makes prose feel distant and academic.
6. **Name the benefit, not just the feature.** "so you don't accidentally react to sensor noise" not "which provides event filtering capabilities."
7. **Don't hedge.** "This works with any entity type" not "This should generally work with most entity types." If there are exceptions, name them instead of hedging.
8. **Don't over-explain things the reader already knows.** If someone is reading the scheduler docs, they know what "running a function after a delay" means. Don't define scheduling from first principles.
9. **Celebrate simplicity when it's real.** When something genuinely is easy, say so: "That's it — three lines and your lights turn off when you leave." But only when the example actually is short. Don't manufacture a celebration for features that require genuine complexity.

### What this voice is NOT

- Not chatbot cheerful. No "Great news!" or "You're going to love this!" Let the content be the excitement.
- Not condescending. Don't explain Python basics. Don't say "simply" or "just" before hard things.
- Not sloppy. Friendly doesn't mean imprecise. Technical terms are fine when they're the right word — just introduce them before using them.

## Page Structure

The voice and approachability rules above are hard requirements. The structures below are defaults — adapt them when the content demands a different shape. See "Pages that don't fit a template" below for named exceptions.

### Concept pages (core-concepts, advanced)

1. **Opening line** — what this thing does and why you'd use it. One or two sentences. No preamble.
2. **Basic example** — the simplest useful version. 3-10 lines of code that do something real. Show the result or effect.
3. **How it works** — walk through the example. Explain the key parts. This is where you introduce terminology.
4. **Common patterns** — 2-3 variations that cover typical use cases. Each gets a short example with a sentence of context.
5. **Depth** — for topics with significant advanced content, split depth into sibling pages rather than collapsing it on the main page. The bus page links to `handlers.md`, `filtering.md`, `dependency-injection.md`. The main page stays approachable; the sibling pages go deep. For smaller topics where a separate page isn't warranted, use collapsible sections (`??? note "Advanced: ..."`) inline.
6. **Next steps** — links to sibling depth pages, related concept pages, relevant recipes.

### Recipe pages

1. **Problem statement** — one paragraph describing the real-world situation. Use a concrete example ("Your motion sensor fires every time a cat walks by").
2. **The Code** — a full, runnable app with config. This is the main attraction.
3. **How it works** — walk through the code, explaining each decision. Call out the Hassette features being used and link to their concept pages.
4. **Variations** — alternative approaches or tweaks for different scenarios.
5. **See also** — links to concept pages for the features used, and related recipes.

### Getting-started pages

1. **What you'll build / What you'll learn** — a brief bulleted list of concepts covered. Tells the reader upfront whether this page is worth their time.
2. **Prerequisites** — what they need before starting. Keep this minimal.
3. **Steps** — numbered, each producing visible progress. Maximum 4-5 major steps. Sub-steps are fine but the top-level count should stay small.
4. **Next steps** — where to go from here. Link to the next tutorial or a relevant recipe.

### API reference pages

API reference is auto-generated by mkdocstrings from docstrings. When adding a new public module or class:

- Add it to the `PUBLIC_MODULES` allowlist in `gen_ref_pages.py`
- Write clear docstrings on the class and its public methods (one-liner summary, parameter descriptions via type hints, usage example if the method is non-obvious)
- Don't duplicate reference content in concept pages — link to it instead

Reference pages are for lookup. Concept pages are for learning. If you're explaining when or why to use something, that belongs on a concept page, not in a docstring.

### Pages that don't fit a template

Some pages follow their own structure. Named exceptions:

- **Index/overview pages** — introduce a section and link to its children. No "How it works" needed.
- **Troubleshooting pages** — problem/solution format. Each entry: symptom, cause, fix.
- **Migration guides** — comparison-driven (old way vs new way), using tabs for side-by-side.
- **CLI reference** — command/flag/example tables. Structured for scanning, not reading.

## Examples

Code examples are how users learn Hassette. They're more important than the prose around them.

### Progression within a page

Start minimal, grow to realistic. On a concept page about bus handlers:

1. **Minimal** — the core idea in 3-5 lines. Just the handler registration and callback, no surrounding app boilerplate. This is a teaching fragment, not a copy-paste-ready example.
2. **Realistic** — a complete app with config, showing the feature in context. Includes the imports, the config class, the lifecycle hook. This is what users copy.
3. **Advanced** (optional) — shows composition with other features (scheduling + bus, conditions + predicates). Only when the combination is non-obvious.

Don't show all three if the concept is simple enough that minimal and realistic are the same thing.

### Snippets and drift prevention

All code examples — including minimal fragments — live in tested snippet files. Snippets are external `.py` files in a `snippets/` subdirectory co-located with the page that includes them. A page at `docs/pages/core-concepts/bus/index.md` uses snippets from `docs/pages/core-concepts/bus/snippets/`. CI type-checks all snippets via Pyright.

**Full file include:**
```
;--8<-- "pages/core-concepts/bus/snippets/subscribe_example.py"
```

**Fragment include via section markers** (for minimal examples):
```python
# In the snippet file:
# --8<-- [start:subscribe]
self.bus.on_state_change("light.kitchen", handler=self.on_light_change)
# --8<-- [end:subscribe]
```
```
;--8<-- "pages/core-concepts/bus/snippets/bus_subscribe.py:subscribe"
```

This way minimal fragments are slices of tested files, not standalone untested code. When the API changes, Pyright catches the break in the full file, and the fragment stays in sync.

### Example rules
- **All code comes from snippet files.** No inline code blocks for examples. Use `--8<--` includes so every example is CI-tested. Minimal fragments use section markers; realistic examples include the full file.
- **Show the outcome.** After a code block, briefly say what happens when it runs. "When the sensor crosses 75°F, the handler fires and turns on the fan." The reader should be able to predict behavior before running it.
- **One concept per example.** An example that demonstrates debouncing should not also introduce conditions, predicates, and dependency injection. Layer concepts across examples, not within them.
- **Real entity names.** Use `light.kitchen`, `sensor.outdoor_temperature`, `binary_sensor.front_door` — not `entity.my_entity` or `sensor.test_sensor`. Real names help readers map to their own setup.

## Layering for Skill Levels

One canonical page per concept. Beginners read the top; experienced users scroll down. Don't maintain separate beginner and advanced versions of the same page.

- **Start every page assuming the reader just finished the getting-started guide.** They know how to create an app, register a handler, and run Hassette. They may not know predicates, conditions, or dependency injection yet.
- **Introduce terms before using them.** First mention of a concept should be a brief definition with a link to its page: "a *predicate* (a function that decides whether to run the handler — [see Predicates](...))" — then use the term freely after that.
- **Use collapsible sections for depth.** `??? note "Under the hood"` or `??? note "Advanced: custom trigger types"` for content that would break the flow for beginners but is valuable for experienced users.
- **Don't gatekeep.** If a concept has a prerequisite, summarize it in one sentence and link to its page rather than telling readers to go read something else first. The reader's momentum matters more than perfect ordering.

## Admonitions

Use sparingly. An admonition should feel like a friend tapping you on the shoulder, not a textbook sidebar.

| Type | When to use | Tone |
|------|-------------|------|
| `!!! tip` | A shortcut, convenience, or "you might not know this" moment | Helpful, saves time |
| `!!! warning` | Something that will bite you if you miss it — security, data loss, silent failures | Direct, specific about the consequence |
| `!!! note` | Context that's important but would break the flow inline — syntax quirks, version differences | Informational, brief |
| `??? note "..."` | Collapsible deeper context — under the hood explanations, alternative approaches | Optional depth |

Don't stack admonitions. If two warnings appear back-to-back, merge them or reconsider whether the prose needs restructuring. More than one admonition per screen height is too many.

## Jargon and Prerequisites

Hassette uses concepts from async Python, dependency injection, and Home Assistant. Not every reader knows all three.

- **Python async**: Don't explain `async`/`await` syntax. Do explain Hassette-specific async patterns ("all handlers run in Hassette's event loop, so they won't block each other").
- **Dependency injection**: Don't assume the reader knows the term. Show the pattern first ("the handler receives the new state as a parameter — Hassette fills it in for you"), then name the concept ("this is called dependency injection").
- **Home Assistant concepts**: Don't explain what entities, services, or automations are. Do explain how Hassette maps to them ("a Hassette `App` is like an AppDaemon app or a Home Assistant automation, but written in Python").
- **Hassette-specific terms**: Always define on first use within a page. Bus, Scheduler, App, StateManager, Resource — these are Hassette vocabulary and need introduction.
