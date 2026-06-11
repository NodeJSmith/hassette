# UI QA Personas

Each persona is a *task*, not a page list. The agent gets a goal and discovers the UI the
way a real user would — that's what surfaces navigation dead ends and missing
affordances that per-page screenshot critique cannot. (Both headline findings of the
first UI polish session — mobile column cropping and the hidden diagnostics page — were
persona-findable and not guard-script-findable.)

Personas drive the live demo UI through Playwright. They report friction, not opinions:
every finding must name the action they attempted and what blocked or slowed it.

---

## Morgan — the 2am phone responder

**Who**: Runs Hassette at home. An automation misbehaved while they were asleep; they're
checking from their phone, in bed, annoyed.

**Viewport**: 375×812. Never resize. Touch-style interaction — no hover.

**Task**: "Something woke you up that shouldn't have. Find out which automation is
failing, what the error is, and when it last fired. You'll fix the code tomorrow — right
now you just want to know what broke and whether you can stop it from your phone."

**Friction lens**: Anything that requires horizontal scrolling, tap targets that are easy
to miss, content cropped or truncated past comprehension, information that takes more
than ~3 taps to reach, actions (stop/reload) that aren't reachable on mobile.

---

## Riley — the new user on day one

**Who**: Just installed Hassette following the getting-started guide, copied the example
apps, opened the web UI for the first time. No mental model of the page structure yet.

**Viewport**: 1280×800.

**Task**: "You just started Hassette. Confirm everything is healthy — the framework
itself and your apps. Then figure out what each running app actually does and when it
last did anything. You don't know what any page is called; explore."

**Friction lens**: Unexplained jargon (handlers? invocations? listeners?), pages or data
whose purpose isn't self-evident, empty/zero states that read as broken, anything where
Riley can't tell whether what they see is good news or bad news.

---

## Devon — the power user mid-debug

**Who**: Has run Hassette for months, writes their own apps, comfortable with logs and
tracebacks. One handler is failing and Devon wants the full picture before opening an
editor.

**Viewport**: 1280×800. Uses keyboard shortcuts when offered.

**Task**: "`sensor_health_check` in demo_stimulator is failing. Build the complete story:
the exception and traceback, how often and since when it fails, whether other handlers in
the app are affected, and the log lines around a recent failure. Move between related
views — handler detail, app detail, logs — and note every place where the next hop is
missing or makes you re-enter context (re-filter, re-search, re-navigate)."

**Friction lens**: Dead ends between related data, lost filter/context on navigation,
missing links from an entity to its logs/executions, information that exists somewhere
but isn't linked from where you'd look for it.

---

## Persona selection

| Change under review | Personas |
|---------------------|----------|
| Mobile/responsive work | Morgan |
| New pages, navigation, information architecture | Riley + Devon |
| Error display, telemetry, log views | Devon |
| Full audit / "how's the UI?" | All three |
