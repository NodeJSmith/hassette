# Persona Review: Getting Started Section

**Date:** 2026-06-08
**Persona:** Alex (fresh Python developer, 1-2 years experience, no async/HA automation background)
**Pages reviewed:** Is Hassette Right for You?, Quickstart, HA Token, First Automation
**Two review modes compared:** reading-path (all 4 pages in sequence) vs per-page (each page in isolation)

---

## Mode Comparison: Path vs Per-Page

### Verdict table

| Page | Path mode | Per-page mode |
|------|-----------|---------------|
| Is Hassette Right for You? | (part of path: followable-with-effort) | followable-with-effort (11 findings) |
| Quickstart | (part of path) | followable-with-effort (12 findings) |
| HA Token | (part of path) | followable (5 findings) |
| First Automation | (part of path) | followable-with-effort (14 findings) |
| **Full path** | **followable-with-effort (11 findings + 3 cross-page)** | N/A |

### Which mode was better?

**The path review was markedly better.** It caught three cross-page issues that per-page reviews cannot detect by design, and it correctly filtered out per-page false positives (things that seem confusing in isolation but were already covered on a prior page).

**What the path review caught that per-page missed:**

1. **Accumulated async confusion.** async/await is flagged as a requirement on page 1, appears without explanation in code on page 2, and is used throughout page 4. Each page adds more async patterns without accumulated explanation. Per-page reviews flagged async on each page independently, but the *compounding* nature of the confusion — and the specific suggestion to add a 3-5 sentence explainer early in the journey — only emerged from the path review.

2. **self.bus/self.scheduler/self.api appear from thin air.** The quickstart uses self.logger with no explanation, and first-automation adds three more magic attributes. A Flask developer would expect to see these created somewhere. Per-page reviews flagged each individually; the path review identified the pattern and suggested one paragraph covering all four.

3. **"dependency injection" is seeded across pages before being defined.** The term appears in the quickstart next-steps, reappears in the first-automation intro, and is only explained several lines into first-automation's body. The path review caught the three-page accumulation of an undefined term.

**What per-page caught that path missed:**

- More granular findings per page (12 on quickstart vs ~3 for quickstart in the path review)
- Page-specific issues like "how do I find Developer Tools in HA?" and "what does Invoc/1h mean in the CLI table?"
- The HA token page's lack of verification step (the path review barely mentioned it since it's a short page)

**Recommendation:** Run path reviews for sequential sections (getting-started, migration). Run per-page reviews for standalone pages (concept pages, recipes, reference pages). The path review is the primary tool; per-page fills in detail afterward.

---

## Cross-Page Issues (from path review)

### 1. async/await is never explained across the entire journey

**Pages:** is-hassette-right-for-you → quickstart → first-automation
**Problem:** Page 1 flags "async basics" as recommended. Page 2 uses `async def on_initialize` without explanation. Page 4 uses `await` on every bus/scheduler/api call. Alex copies patterns on faith but never learns the rule.
**Suggestion:** Add a 3-5 sentence async/await explainer early — either as a callout on page 1 or a brief section in the quickstart: "Write `async def` for all your app methods. Add `await` before any call to `self.bus`, `self.scheduler`, or `self.api`. That's it for now."

### 2. self.bus, self.scheduler, self.api appear without introduction

**Pages:** quickstart → first-automation
**Problem:** `self.logger` is used on page 2, then `self.bus`, `self.scheduler`, `self.api` appear on page 4 — all without explanation of where they come from. A Flask developer expects to see objects created or injected.
**Suggestion:** One paragraph, one time: "Every Hassette app inherits four objects: `self.logger` (Python logger), `self.bus` (event subscriptions), `self.scheduler` (timed jobs), and `self.api` (Home Assistant calls). Hassette creates them — you just use them."

### 3. "dependency injection" accumulates as undefined jargon

**Pages:** quickstart (next-steps link) → first-automation (intro bullet, body explanation)
**Problem:** The term appears twice before being defined. Alex builds anxiety about an unknown concept.
**Suggestion:** Remove "dependency injection" from the quickstart next-steps blurb. Let first-automation introduce and explain it cleanly on first use. Or add a parenthetical on first mention: "dependency injection (Hassette extracts typed values from events and passes them to your handler automatically)."

---

## Per-Page Findings

### Page 1: Is Hassette Right for You? (followable-with-effort, 11 findings)

| Line | Type | Quote | Confusion | Suggestion |
|------|------|-------|-----------|------------|
| 2 | undefined-term | "connects over the WebSocket API" | "WebSocket means nothing to me. Do I need to set something up?" | Drop or parenthesize: "connects to Home Assistant directly (no extra setup needed)" |
| 6 | undefined-term | "Hassette apps run in a test harness" | "'Test harness' is a new term. Is this just pytest?" | Replace with "a pytest-based setup" |
| 6 | undefined-term | "simulate events, advance time" | "What is an 'event' here?" | Use concrete language: "simulate sensor triggers, fast-forward timers" |
| 8 | assumed-knowledge | Jinja2 template debugging reference | "I've never written a Jinja2 template for HA" | Add a more universal signal first |
| 17 | undefined-term | "AppTestHarness" in comparison table | "Is this a Hassette thing? A separate package?" | Simplify to "pytest integration" |
| 19 | assumed-knowledge | "Medium (Python + async basics)" | "How much async do I need before starting?" | Add: "the quickstart introduces what you need" |
| 24 | undefined-term | "The Docker Setup guide" | "Is this a link? Where do I find it?" | Ensure it's a hyperlink in rendered output |
| 25 | unclear-next-step | "token you generate in your profile settings" | "Which profile settings? HA has a lot of settings" | Add navigation path or link to HA docs |
| 26 | undefined-term | "AppSync for writing synchronous apps" | "Should I use AppSync instead? I don't know async..." | Cut this mention or add: "start with the async API — most docs use it" |
| 26 | assumed-knowledge | "await and async def appear in every example" | "I've never written async code. Is this a blocker?" | Add: "the Quickstart walks through the pattern as you go" |
| 29 | assumed-knowledge | "Coming from AppDaemon?" | "I don't know what AppDaemon is" | Add a third option: "No prior HA automation framework? The Quickstart is the right starting point." |

### Page 2: Quickstart (followable-with-effort, 12 findings)

| Line | Type | Quote | Confusion | Suggestion |
|------|------|-------|-----------|------------|
| 2 | undefined-term | "one-file automation" | "What will the automation actually do?" | State the goal: "log a message when Hassette starts" |
| 6 | missing-prerequisite | "a long-lived access token" | "I've never heard this term" | Add parenthetical with HA navigation path |
| 12 | unclear-next-step | "Create a long-lived access token from the HA UI" | "I open HA. Now what? No menu path given" | Add: "Profile → Security → Long-Lived Access Tokens → Create Token" |
| 19 | unclear-next-step | .env file content shown | "The step never tells me to create the file" | Add explicit "Create a .env file" instruction |
| 19 | assumed-knowledge | `HASSETTE__BASE_URL` | "Is 8123 always right? What if different port?" | Add: "Use the URL you normally open in your browser" |
| 24 | undefined-term | `class MyApp(App[MyAppConfig])` | "I've never seen square brackets on a class definition" | Brief note about Python generics |
| 24 | undefined-term | `async def on_initialize(self)` | "I've never written async code" | Reassurance: "Hassette calls it for you" |
| 24 | undefined-term | `self.app_config.greeting` | "Where does self.app_config come from?" | Note that Hassette provides it automatically |
| 26 | undefined-term | "Hassette discovers app classes automatically" | "How does it know MyApp is the class to run?" | Explain: "scans apps/ for any App subclass" |
| 35 | no-verification | "Hassette loaded your config" | "Which line proves MY code ran vs Hassette booting?" | Make causal link explicit |
| 46 | assumed-knowledge | "Invoc/1h" column | "What does this mean? Is 0 normal?" | Explain the column briefly |
| 52 | unmotivated-content | "dependency injection" in next-steps | "I've never heard this term" | Soften: "react to real HA events" |

### Page 3: HA Token (followable, 5 findings)

| Line | Type | Quote | Confusion | Suggestion |
|------|------|-------|-----------|------------|
| 2 | undefined-term | "long-lived access token" | "Why 'long-lived'? Different from a regular token?" | Add: "a token that doesn't expire" |
| 9 | missing-prerequisite | "Add the token to your .env file" | "What .env file? I haven't created one" | Add: "In your project directory, open or create a file named .env" |
| 11 | assumed-knowledge | `HASSETTE__TOKEN` double underscore | "Unusual. Is this a typo?" | Note: "The double underscore is required" |
| 13 | unclear-next-step | "The Quickstart covers the full .env setup" | "Should I go there now or was I supposed to do it first?" | Reframe as: "If you haven't done the Quickstart yet, start there" |
| — | no-verification | (page overall) | "How do I confirm the token works?" | Add a verification step |

### Page 4: First Automation (followable-with-effort, 14 findings)

| Line | Type | Quote | Confusion | Suggestion |
|------|------|-------|-----------|------------|
| 2 | missing-prerequisite | "the app from the Quickstart" | "I landed from search. No link, no fallback." | Add prerequisite with link |
| 3 | undefined-term | "dependency injection" | "Never heard this in Python context" | Replace with "Hassette fills in typed state data automatically" |
| 7 | undefined-term | `async def on_initialize` | "Why async? What breaks if I forget it?" | One-sentence async explainer |
| 7 | undefined-term | `self.bus.on_state_change(` | "What is 'bus'? Where did it come from?" | "self.bus is Hassette's event bus, created automatically on every App" |
| 7 | undefined-term | `handler=self.on_sun_change` | "What is a 'handler'?" | Add: "handler= is the method Hassette calls each time the event fires" |
| 9 | undefined-term | "the web UI" | "There's a web UI? Do I need to set it up?" | Brief mention or defer |
| 10 | unmotivated-content | "extract from the event" | "What event? What's being extracted?" | Reframe: "tells Hassette: pass me the new state as a SunState object" |
| 14 | unclear-next-step | `domain="light"` routing | "What is a HA service? How do I find others?" | Add: "find available services in HA Developer Tools → Services" |
| 16 | assumed-knowledge | `self.scheduler` | "Where did this come from?" | Introduce alongside self.bus |
| 19 | no-verification | "Hassette tracks the job..." | "What if I forget await?" | Note the consequence |
| 20 | undefined-term | "DI parameters" | "DI" abbreviation never introduced | Spell out "dependency injection parameters" |
| 22 | missing-prerequisite | "restart Hassette" | "How? No command shown" | Show: "Stop with Ctrl+C, then run `hassette run`" |
| 26 | no-verification | "lines appear at the next sunset" | "Could be 12 hours away" | Promote the collapsed test tip to main content |
| 27 | unclear-next-step | "open Home Assistant Developer Tools" | "Where is that in the HA UI?" | Add: "click Developer Tools (</> icon) in the sidebar" |

---

## Path Review: Knowledge State After Each Page

| After page | Alex knows | Alex still confused about |
|------------|-----------|--------------------------|
| Is Hassette Right for You? | Hassette = Python automations, needs separate process, needs token, async is involved | What async means in practice, whether to learn it first |
| Quickstart | Has installed Hassette, created project, written minimal app, seen it run | Why `async def`, where `self.app_config` comes from, "dependency injection" term planted |
| HA Token | Where to create token in HA UI, token security | (no new confusions, clear page) |
| First Automation | Has working sunset + heartbeat app, broad shape of bus/scheduler/api | Why everything needs `await`, what self.bus is, `D.StateNew[T]` bracket syntax, how to verify sunset handler |

## Path Review Summary

> "The four-page journey is followable for Alex but requires copying patterns on faith more than understanding them. Pages 1 and 3 are clear and well-scoped. Page 2 (quickstart) successfully delivers a win — Alex gets code running — but plants async confusion that compounds through page 4. Page 4 is where the debt comes due: async is everywhere, new objects appear from thin air, and the bracket-type syntax is unexplained. Alex will finish with a working app but with a lingering sense of 'I don't really know why this works.' The biggest single fix is a 3-5 sentence async/await explainer early in the journey; the second biggest is one sentence explaining where self.bus/self.scheduler/self.api come from."

---

## Recommended Priority for Fixes

### Priority 1 — Add async/await explainer (cross-page fix)
3-5 sentences in the Quickstart, immediately after the first `async def` code block. Covers the entire journey.

### Priority 2 — Introduce self.bus/self.scheduler/self.api
One paragraph in the Quickstart or early in First Automation. Eliminates "where did this come from?" confusion.

### Priority 3 — Remove premature "dependency injection" mentions
Drop from Quickstart next-steps and First Automation intro bullet. Let the body explanation stand on its own.

### Priority 4 — Promote the sunset test tip
Move from collapsed to visible content. All three personas (in the earlier three-persona test) flagged this independently.

### Priority 5 — Add HA navigation paths
Token creation steps, Developer Tools location, service browser. Small additions that prevent 5-10 minute detours.

### Priority 6 — Explain `HASSETTE__` double underscore convention
One sentence. Prevents a silent misconfiguration.
