# Voice Guide

<reference-voice>
Svelte docs read like a senior engineer explaining a system they built and trust. The writing is declarative and confident — it states what things do, not what categories they belong to. Sentences are short (10–18 words in explanatory prose), each carrying one idea. The reader is assumed capable. The writing earns warmth through precision, not through reassurance.

The prose varies by page type. Getting-started pages address the reader directly, show code first, then explain. API reference and concept pages put the system in the subject position — "The bus delivers events," not "You receive events." Concept pages use declarative statements throughout; imperative mood is reserved for migration guides and step-by-step instructions. Limitations appear after the main behavior and are always paired with a path forward.

Hassette docs today have a friendly, conversational register that works for getting-started content. The gap shows on concept and API reference pages, where "your app receives events through the bus" should become "the bus delivers events to any handler that subscribes." The voice shift is not about being colder — it's about trusting the reader enough to stop addressing them when explaining how the system works.
</reference-voice>

<style-rules>

## We Always

1. **Open concept explanations with the construct as subject.** Make the thing the subject of the first sentence — not "it," "this," or "you can use." The definition says what it does, not what category it belongs to.

2. **Keep explanatory sentences to 10–18 words.** One idea per sentence. No stacked relative clauses with "which" and "that" chains. (Inline code identifiers don't count toward the word limit.)

3. **State the main behavior first, caveats after.** The reader needs to understand what something does before learning what it doesn't do.

4. **Pair every limitation with a path forward.** One sentence for the constraint, one sentence naming what to do instead. ("Glob patterns don't work for attribute names. Use predicates for that.")

5. **Give the reasoning in a clause, not a paragraph.** When a rule exists for a reason, say why in the same sentence or the sentence immediately after — then move on.

6. **Use present tense to describe behavior.** The thing does the thing. Not "will run" or "can be used to."

7. **Use Anglo-Saxon verbs.** Prefer: create, declare, run, fire, track, read, subscribe, set, register, cancel, receive, pass, return, call.

8. **Introduce new Hassette terms with a brief functional definition on first use within a page.** The definition says what the thing does, not what category it belongs to.

9. **Code-format all identifiers, paths, parameters, and syntax elements.** No exceptions for "obvious" ones.

---

## We Never

10. **Never use "you" in concept or API reference pages.** Make the system or construct the subject. "You" belongs in getting-started and tutorial content only, and in recipe procedure/variation sections where the reader is performing steps. Concept pages and recipe "How It Works" sections explain what the code does — they use system-as-subject throughout.

11. **Never explain anti-patterns at length.** State the anti-pattern in one sentence. Give the alternative in the next. Stop.

12. **Never open a paragraph with a transition sentence.** No "Now that we understand X, let's look at Y." Start with the next thing directly.

13. **Never reassure the reader except in getting-started pages.** Concept and recipe docs assume a capable reader.

14. **Never use hedged comparisons.** State the current recommended approach directly. Past approaches belong in past tense.

15. **Never use imperative mood in concept pages.** Use declarative statements. Imperative belongs in step-by-step getting-started content.

---

## When X, Do Y

16. **When introducing a concept in a concept/API page: name → define → show → constrain.** The definition says what it does. The code example is minimal (2–5 lines). Constraints come after.

17. **When introducing a concept in a getting-started page: show code first, then explain.** The reader runs it, then understands it.

18. **When presenting alternatives, state the current/preferred approach first.** The older or less-preferred approach comes second, in past tense or as an aside.

19. **When something surprising contradicts expectations, state it plainly without signaling the surprise.** State the behavior, then give the reason. No "you might be surprised to learn that."

20. **When complexity layers, show the simplest case first.** Variants and edge cases come after the base case, with clear labels.

21. **When writing a recipe's "How It Works" section: walk through one decision at a time.** Name what each part does, why it was chosen, and any non-obvious consequence. Each paragraph covers one decision, not a list of facts. Voice follows Rule 10 — system-as-subject, no "you."

22. **When a feature composes with other features, state what composes and what doesn't in the same place.** Don't scatter composition rules across sections.

</style-rules>

<examples>

## Before/After: Concept Page

**Source:** Bus overview and Subscribing section

**Before**

> The event bus connects your apps to Home Assistant and to Hassette itself. It delivers events such as state changes, service calls, or framework updates to any app that subscribes.
>
> Apps register event handlers through `self.bus`, which is created automatically at app instantiation.
>
> ---
>
> ## Subscribing to Events
>
> The `Bus` provides helper methods for common subscriptions. Each returns a [`Subscription`][hassette.bus.listeners.Subscription] handle.
>
> - `on_state_change` - Listen for entity state changes.
> - `on_attribute_change` - Listen for changes to a specific attribute.
> - `on_call_service` - Listen for service calls.
> - `on` - Generic subscription to any topic.
> - `on_component_loaded` - Listen for Home Assistant component load events.

**After**

> The event bus delivers Home Assistant events — state changes, service calls, component loads — to any app handler that subscribes. It also delivers Hassette-internal events.
>
> `self.bus` is available on every `App` instance. Hassette creates it at startup.
>
> ---
>
> ## Subscribing to Events
>
> `Bus` provides typed subscription methods for each common event type. Each returns a `Subscription` handle that cancels the subscription when called.
>
> - `on_state_change` — fires when an entity's state string changes.
> - `on_attribute_change` — fires when a specific attribute changes.
> - `on_call_service` — fires when a service is called.
> - `on` — subscribes to any raw topic string.
> - `on_component_loaded` — fires when Home Assistant loads a component.

---

## Before/After: Recipe Page

**Source:** Motion lights "How It Works" section

**Before**

> - **`on_state_change`** subscribes to every state transition on the motion sensor. The handler uses **dependency injection** (`D.StateNew[states.BinarySensorState]`) to receive the new state as a typed object — both `"on"` and `"off"` are handled in one place.
> - When state is `"on"`, any pending off job is cancelled before turning the light on — this resets the timeout if motion is detected again while the timer is running.
> - When state is `"off"`, `run_in` schedules `turn_off_light` to fire 5 minutes later. The job is stored on `self._off_job` so it can be cancelled on re-trigger.
> - **Named job** (`OFF_JOB_NAME`) keeps logs readable. Only one off job per app instance can exist with a given name — if you need multiple sensors driving the same light, give each instance a different name via config.
> - Config fields (`motion_sensor`, `light`, `off_delay`) let you run the same app class for multiple rooms with different values in `hassette.toml`.

**After**

> `on_state_change` subscribes to every state transition on the motion sensor. `D.StateNew[states.BinarySensorState]` delivers the new state as a typed object — the handler covers both `"on"` and `"off"` transitions in one place rather than two separate subscriptions.
>
> When motion turns on, any pending off job is cancelled before the light turns on. This resets the timer — if motion fires again while the delay is running, the timeout starts over instead of firing at the original time.
>
> When motion turns off, `run_in` schedules `turn_off_light` for `off_delay` seconds later. The returned job is stored on `self.off_job` so the on-handler can cancel it on re-trigger.
>
> `OFF_JOB_NAME` makes log lines readable and enforces a single pending off job per instance. Run the same app class for multiple rooms by giving each a different name in `hassette.toml` — the named job scopes to the instance, not the class.
>
> `motion_sensor`, `light`, and `off_delay` all come from config. Nothing in the app is hardcoded to a specific room.

---

## Before/After: Getting-Started Page

**Source:** First automation, "Step 3: Subscribe to a state change"

**Before**

> ## Step 3: Subscribe to a state change
>
> Use `self.bus.on_state_change()` to react to HA state changes. The `"sun.*"` pattern matches any entity in the `sun` domain (typically `sun.sun`).
>
> The Quickstart used a raw event handler — that works, but Hassette can do better. With **dependency injection** (DI), you annotate handler parameters with types like `D.StateNew[T]`, and Hassette extracts and converts the data automatically — no event payload parsing required:
>
> [code]
>
> Two names appear here that aren't obvious at first glance:
>
> - **`D`** is a short alias for `hassette.dependencies` — a module containing type annotations that tell Hassette what to extract from each event and inject into your handler parameters.
> - **`states`** is the `hassette.models.states` module — it contains typed state classes for each Home Assistant domain (`SunState`, `LightState`, `BinarySensorState`, and many others).
>
> So `D.StateNew[states.SunState]` means: extract the new state from this event and give it to me already converted to a `SunState` object. The `.value` attribute holds the state string (`"above_horizon"` or `"below_horizon"`). Your IDE knows the type; Pyright will catch typos.

**After**

> ## Step 3: Subscribe to a state change
>
> Call `self.bus.on_state_change()` to subscribe. The `"sun.*"` pattern matches any entity in the `sun` domain — in practice, `sun.sun`.
>
> [code]
>
> Two names in this snippet aren't obvious from their names alone:
>
> - **`D`** is `hassette.dependencies` — a module of type annotations that tell Hassette what to extract from the event and pass into your handler. `D.StateNew[T]` means "give me the new state, converted to type `T`."
> - **`states`** is `hassette.models.states` — typed state classes for each HA domain. `states.SunState` has a `.value` attribute holding `"above_horizon"` or `"below_horizon"`.
>
> So `D.StateNew[states.SunState]` tells Hassette: extract the new state from this event, convert it to a `SunState`, and pass it in. No event dict parsing. Your IDE knows the type; Pyright catches typos.
>
> The Quickstart showed a raw event handler — it works, but you'd be extracting `event["new_state"]["state"]` manually. Dependency injection removes that boilerplate.

*Demonstrates: Rule 17 (code-first in getting-started), Rule 18 (preferred approach first — DI is primary, raw handler last), Rule 8 (functional definitions for `D` and `states` on first use).*

</examples>
