# Svelte Docs Voice Analysis

**Working artifact — input for T02**
**Analyzed:** 2026-05-28

## Pages Analyzed

1. https://svelte.dev/docs/svelte/overview
2. https://svelte.dev/docs/svelte/$state
3. https://svelte.dev/docs/svelte/stores
4. https://svelte.dev/docs/svelte/getting-started
5. https://svelte.dev/docs/svelte/$derived
6. https://svelte.dev/docs/svelte/$effect
7. https://svelte.dev/docs/svelte/basic-markup
8. https://svelte.dev/docs/svelte/v4-migration-guide
9. https://svelte.dev/docs/svelte/v5-migration-guide

Content types covered: intro/overview, API reference (runes), concept/guide, tutorial/getting-started, migration guide.

---

## Pattern 1: Sentence-Level Patterns

### Average sentence length

Short to medium. Sentences rarely exceed 20 words in explanatory prose. The dominant pattern is a declarative sentence followed by a short supplementary sentence.

**Evidence:**
> "Svelte is a framework for building user interfaces on the web. It uses a compiler to turn declarative components written in HTML, CSS and JavaScript...into lean, tightly optimized JavaScript."

Two sentences, ~11 and ~20 words. The second sentence expands rather than hedges.

> "The expression inside `$derived(...)` should be free of side-effects."

9 words. No qualifiers. A flat statement of a rule.

> "Generally, you should read the value of a store by subscribing to it and using the value as it changes over time. Occasionally, you may need to retrieve the value of a store to which you're not subscribed. `get` allows you to do so."

Three sentences. Each one shorter than the previous. The third sentence is 7 words.

### Paragraph structure

2–4 sentences per paragraph in explanatory prose. Code examples appear inside paragraphs as short breaks, not as section-ending summaries. A paragraph typically:
- States a fact
- Adds one specification or constraint
- Optionally gives a consequence

### How sentences open

**Declarative opening (most common):** Subject → verb, present tense.
> "A store must contain a `.subscribe` method..."
> "Effects are functions that run when state updates..."
> "Svelte employs event delegation to reduce memory usage..."

**Imperative opening (instructions, migration steps):**
> "Upgrade to Node 16 or higher."
> "Replace all instances of `SvelteComponentTyped` with `SvelteComponent`."

**Conditional opening (rare, for nuance):**
> "If you return a function from the callback, it will be called when..."

**Observational opener with "This" (signals a pattern worth noting):**
> "This migration guide provides an overview of how to migrate from Svelte version 3 to 4."

### Fragments and compression

Not heavily used. The docs prefer complete sentences even for short points. Lists use full noun phrases with no trailing explanation when the item is self-explanatory; the explanatory sentence comes after.

---

## Pattern 2: Reader Address Patterns

### Use of "you/your"

**Present but restrained.** "You" appears primarily in:
- Getting-started and tutorial content
- When naming an action the reader will take
- When stating a consequence for the reader

**Evidence from getting-started:**
> "Don't worry if you don't know Svelte yet! You can ignore all the nice features SvelteKit brings on top for now and dive into it later."

This is the warmest, most direct reader address in the corpus — and it's from the getting-started page, not the API reference.

**In API reference**, "you" is sparse. Prefer impersonal constructions:
> "The store must be declared at the top level of the component — not inside an `if` block or a function, for example."

Not "you must declare the store..." — the subject is the store, not the reader.

> "Manually dispatched delegated events require `{ bubbles: true }`."

No "you" at all.

### Imperative mood frequency

**High in migration guides and getting-started. Low in concept/API pages.**

Migration guide uses bare imperative throughout:
> "Upgrade to Node 16 or higher."
> "Replace all instances of `SvelteComponentTyped` with `SvelteComponent`."
> "Add the `|global` modifier..."

API reference prefers descriptive statements, not instructions:
> "Effects can return cleanup functions that execute before reruns or component destruction."

Not: "Return a cleanup function from your effect."

### Directness without informality

The writing addresses the reader matter-of-factly. No coddling, no enthusiasm. The getting-started reassurance ("Don't worry if you don't know Svelte yet!") stands out *because it's unusual* — most pages don't bother with reassurance.

---

## Pattern 3: Information Sequencing

### Code before or after explanation?

**Pattern varies by page type:**

- **Getting-started:** Code first, then brief explanation. The reader is expected to run it and then understand it.
- **API reference:** Brief one-sentence concept statement, then code, then constraint elaboration.
- **Migration guide:** Constraint/change first (one or two sentences), then code showing old vs. new.

**Evidence (API reference — $state):**
> "The `$state` rune allows you to create _reactive state_, which means that your UI _reacts_ when it changes."
[code example]
> "When applied to arrays or plain objects, `$state` generates a deeply reactive proxy."

Statement, code, then elaboration of what the code demonstrated.

**Evidence ($derived):**
> "Derived state in Svelte is declared using the `$derived` rune..."
[code: `let doubled = $derived(count * 2);`]
> "Svelte automatically tracks all state read synchronously within the expression."

Three moves: name the thing, show it in 1 line, then tell the reader something they can't see from the code alone.

### How complexity layers

Simplest case first. Variants come after the base case, labeled clearly (`$state.raw`, `$state.snapshot`, `$derived.by`). Edge cases come last.

**Evidence ($state structure):**
1. Basic `$state` with simple variable
2. Deep reactivity with proxies (extension of the basic case)
3. Class implementation (edge case requiring special handling)
4. Variants (`$state.raw`, `$state.snapshot`, `$state.eager`)
5. Cross-module sharing (limitation/edge case)

### Where caveats and limitations appear

**After the main concept, not before.** Caveats don't front-load. They come once the reader understands what they're caveating.

**Evidence:**
> "Modifications to individual properties trigger granular updates throughout the UI. However, destructuring breaks reactivity since references evaluate at the point of extraction."

Main behavior first, exception second.

> "Generally, you should read the value of a store by subscribing to it... Occasionally, you may need to retrieve the value of a store to which you're not subscribed. `get` allows you to do so. This works by creating a subscription, reading the value, then unsubscribing. It's therefore not recommended in hot code paths."

The "not recommended" comes at the end, after the reader understands what `get` does.

---

## Pattern 4: Rhetorical Moves

### Introducing new concepts

**Name, then define, then show.** Svelte consistently:
1. Names the construct (often using its exact API name as the subject)
2. Gives a one-sentence functional definition
3. Shows a minimal code example
4. Adds one or two material constraints

> "A _store_ is an object that allows reactive access to a value via a simple _store contract_."

Subject = "A store". The definition is what it does, not what it is categorically.

### Disclosing limitations

**Factual, no apology.** Limitations are stated as facts about the system, not as warnings or caveats. No hedging language ("unfortunately", "it's worth noting that"). No drama.

> "the value of a `writable` is lost when it is destroyed, for example when the page is refreshed. However, you can write your own logic to sync the value to for example the `localStorage`."

States the limitation, immediately offers the path forward. No dwelling.

> "Stores remain valuable for 'complex asynchronous data streams or when manual control over updating values or listening to changes is important.'"

Rather than saying "stores are now less preferred" with apology, the docs say "stores remain valuable when..." — they reframe by telling you when to still use the thing.

### Presenting alternatives

**State the better path first, old path second.** Not "if you don't want to use X, you can use Y" — instead "use Y; X exists for [specific case]."

**Evidence (stores vs. runes):**
> "Prior to Svelte 5, stores were primary solutions for cross-component reactive state and logic extraction. Runes have significantly changed this landscape."

The old thing is placed in the past tense. The new thing is present.

### Handling "you might expect X but actually Y"

This move appears in several places, but is done without signposting ("you might be surprised to learn that..."). Instead, the unexpected thing is stated plainly, and the reason follows.

**Evidence ($state reactivity):**
> "However, destructuring breaks reactivity since references evaluate at the point of extraction."

No "you might expect destructuring to work." Just states the thing that catches people, explains why.

**Evidence (migration — onMount):**
> "`onMount` now shows a type error if you return a function asynchronously from it, because this is likely a bug."

States the behavior change (possibly surprising), gives the reason ("likely a bug"), done.

### Anti-pattern warnings

Kept brief and actionable.

**Evidence ($effect):**
> "Avoid using it to synchronise state" and recommends `$derived(count * 2)` over effect-based synchronization.

One sentence negative, one sentence positive alternative. No lengthy explanation of why anti-patterns are bad.

---

## Pattern 5: Vocabulary Patterns

### Preferred verbs

Anglo-Saxon, concrete, active:
- "create", "declare", "track", "read", "subscribe", "set", "update", "run", "return", "call"

The docs rarely use:
- "leverage", "utilize", "facilitate", "enable" (except in "enables developers to..." in overview — stands out as slightly more formal)
- Nominalized verbs: not "the initialization" but "when it initializes" or "at initialization"

### Formality level

**Technical but not stuffy.** Contractions appear occasionally in getting-started/guide content ("Don't worry if you don't know Svelte yet!") but are absent in API reference. The reference content reads like well-written specifications — precise, not chatty.

### Technical jargon handling

Technical terms are used without definition when the reader is assumed to know them (e.g., "ESM", "CJS", "proxy", "microtask"). Terms specific to Svelte ("rune", "store contract") are given a brief functional definition on first use.

### Passive voice

**Rare but purposeful.** Used when the actor is the system or framework (not the reader):
> "The compiler transforms these into getter/setter methods on the prototype."
> "Preprocessors are executed in order..."
> "Preprocessors are executed in order..." [paraphrase — original may differ in exact wording]

Active when the developer does the thing. Passive when Svelte/the compiler does the thing.

### Italics and emphasis

Used for key terms on first use:
> "A _store_ is an object..."
> "reactive state"
> "_dirty_ and recalculated"

Bold used for variant names and section labels:
> **$state.raw**, **set method**, **update method**

Code formatting applied consistently for any identifier, path, or syntax element.

---

## Pattern 6: Distinctive Qualities

### What makes Svelte docs recognizably "Svelte docs" vs. generic technical writing?

**1. Confidence without boasting.** The docs state what Svelte does in plain declarative sentences. No superlatives, no marketing language. "Svelte is a framework for building user interfaces on the web" — not "Svelte is a powerful, innovative framework." The confidence comes from not feeling the need to sell.

**2. Reasoning provided, not just rules.** When something is a certain way, the docs say why. Not "transitions are now local" but "transitions are now local by default to prevent confusion around page navigations." The "why" is one clause, not a paragraph.

**3. Paths forward alongside limitations.** See Pattern 4, "Disclosing limitations" — every limitation is paired with an action.

**4. The reader is assumed capable.** No reassurance except in getting-started. API reference assumes the reader has read the concept pages. Migration guide assumes the reader understands what changed and wants to know how to update, not why the design decision was made.

**5. Anti-patterns are stated once and not belabored.** The `$effect` anti-pattern warning is one sentence. No paragraphs about why synchronizing state in effects is harmful.

**6. Examples are minimal and purposeful.** Code examples show the specific thing being explained, not a larger context. A 2-line example is preferred over a 10-line example unless the 10 lines are necessary.

**7. Consistency of the "name → define → show → constrain" move.** Nearly every concept introduction follows this pattern, which gives the reference a reliable rhythm without feeling formulaic.

---

## Reverse-Engineered System Prompt

> **What system prompt would produce this exact documentation style?**

```
You are writing technical documentation for a software library. Apply these rules mechanically:

SENTENCE CONSTRUCTION:
- Average 10-18 words per sentence in explanatory prose.
- Open sentences with the subject of what you are describing (the function, the store, the rune), not with "It" or "This".
- Use present tense for describing behavior: "Effects run after DOM mounting." Not "Effects will run..."
- Use past tense only for historical/version context: "Prior to Svelte 5, stores were..."
- Use imperative mood only in migration guides and step-by-step instructions. Never in concept or API reference pages.
- One idea per sentence. Do not stack multiple clauses with "which" and "that" chains.

CONCEPT INTRODUCTION:
- In getting-started/tutorial content: show code first, then explain what it does.
- In API reference/concept pages: (1) name the construct, (2) one-sentence functional definition, (3) minimal code example, (4) one or two constraints or edge cases.
- The definition states what the thing does, not what category it belongs to.
- Do not introduce a concept by talking about what problem it solves. Name it, define it, show it.

LIMITATIONS AND CAVEATS:
- State limitations after the main behavior, not before.
- Pair every limitation with an action: "X doesn't work here, but Y does."
- One sentence for the limitation. One sentence for the path forward. Move on.
- No apology language. No "unfortunately" or "it's worth noting that."

READER ADDRESS:
- Use "you" in getting-started and tutorial content. Avoid it in API reference.
- In API reference, make the system or construct the subject. "The store must be declared..." not "You must declare the store..."
- Do not reassure the reader. They are capable. If they need reassurance, it belongs in getting-started only.

ALTERNATIVES AND COMPARISONS:
- State the preferred/modern approach first. Old approach second, in past tense.
- Do not say "if you don't want to use X." Say "use Y. X exists for [specific case]."
- Do not hedge comparisons. "Runes have significantly changed this landscape." Not "runes may offer some advantages over..."

VOCABULARY:
- Prefer Anglo-Saxon verbs: create, declare, track, read, subscribe, set, update, run, return, call.
- Never use: leverage, utilize, facilitate, enable (as a general verb), showcase.
- Technical jargon is used without definition when the reader is assumed to know it.
- Svelte-specific terms get a brief functional definition on first use.
- Italicize new terms on first use. Code-format all identifiers, paths, and syntax.

ANTI-PATTERNS:
- State anti-patterns in one sentence. Give the alternative in the next sentence. Stop.
- Do not write paragraphs explaining why an anti-pattern is bad.
- Format: "Avoid [X]. Instead, [Y]." or "Do not use [X] when [condition]. Use [Y]."

CODE EXAMPLES:
- Show the minimum code that demonstrates the specific concept. 2-5 lines preferred.
- Do not build up a larger application context unless the concept requires it.
- Code appears immediately after the concept statement, before constraint elaboration.

PARAGRAPH STRUCTURE:
- 2-4 sentences per paragraph.
- Each paragraph: one point. Not a topic sentence plus three supporting points.
- No transition paragraphs ("Now that we understand X, let's look at Y").
```

---

## Summary: Key Patterns for T02

For the constraint extraction phase (T02), the highest-signal patterns are listed below. Items 1–4 are structural (apply to all content types). Items 5–10 are stylistic (apply at sentence level). When conflicts arise, structural rules take precedence.

**Corpus note:** Patterns 1–4 are primarily derived from API reference and concept pages (7 of 9 pages analyzed). Migration-guide patterns are directional only; add more migration examples if migration-style output is required.

1. **Name → define → show → constrain** is the ironclad concept introduction sequence (API/concept pages; getting-started uses code-first instead)
2. **Limitations come after main behavior**, always paired with a path forward
3. **"You" is tutorial-only** — API reference makes the system the subject
4. **One-sentence anti-pattern warnings** — no belaboring
5. **Anglo-Saxon verbs** — create/declare/run/track, not leverage/utilize/facilitate
6. **Imperative mood is migration/instruction content only** — concept pages use declarative
7. **Reasoning in one clause** — "to prevent confusion around page navigations," not a paragraph
8. **Modern path first, legacy path second** — always frame the current approach as the subject, historical approach in past tense
9. **Minimal examples** — show the specific thing, 2-5 lines preferred
10. **Confidence without reassurance** — no "Don't worry" except in getting-started
