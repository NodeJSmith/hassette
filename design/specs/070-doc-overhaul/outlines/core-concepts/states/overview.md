# States

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept
**Reader's job:** Read entity state from Home Assistant in typed, synchronous Python code.

## What was cut (and where it goes)

- **DomainStates Collection Interface table** — moved to a collapsible section. Most readers need `get()` and bracket access; the full method inventory is reference detail, not the primary job.
- **Built-in State Types full table** — replaced by 2-3 inline examples + link to auto-generated API reference. The 47-row table duplicates the generated reference and rots. The existing collapsible stays but with a note pointing to the API reference as the canonical source.
- **State Model Properties** (was missing from existing page) — added as a section. Readers who land here after seeing `is_unknown` or `extras` in a recipe need to understand what properties exist on every state.

## Outline

### (Opening)
Functional definition: the `StateManager` keeps a real-time, in-memory copy of all Home Assistant entity states. `self.states` provides synchronous, typed access — no `await`, no API calls.

### Mermaid Diagram
HA -> WebsocketService -> StateProxy -> self.states flow. Same structure as existing, after the opening prose.

### H2: Reading State
The reader's core job. Three access patterns, ordered by frequency of use:

#### H3: Domain Access
`self.states.light`, `self.states.sensor` — the most common pattern. Short entity name without domain prefix. Bracket access raises `KeyError`; `.get()` returns `None`.

#### H3: Direct Entity Access
`self.states.get("light.kitchen")` — full entity ID, auto-resolves to the correct typed state class.

#### H3: Generic Access
`self.states[CustomState]` — for custom integrations or dynamic access. Returns a `DomainStates` collection.

### H2: What a State Object Contains
Properties available on all state objects (`BaseState` subclasses). Ordered by what the reader reaches for first:

- `value` — the entity's state (typed: `bool` for switches, `float` for sensors, `str` for selects, etc.)
- `attributes` — typed attribute object with domain-specific fields (e.g., `brightness` on `LightState`)
- `is_unknown` / `is_unavailable` — flags for when HA reports `"unknown"` or `"unavailable"`. In these cases `value` is `None` to preserve type safety. Check before using `value`.
- `is_group` — whether the entity is a group
- `extras` / `extra(key)` — untyped attributes not declared on the typed attributes class
- `attributes.has_feature(flag)` — bitfield check for domain-specific capabilities (e.g., `SUPPORT_BRIGHTNESS`)

### H2: Built-in State Types
Hassette auto-generates typed state classes for 47 HA domains from HA core source. Show 2-3 inline examples: `LightState` (brightness, color), `SensorState` (numeric value, unit), `BinarySensorState` (bool value, device_class). Link to auto-generated API reference for the full inventory. Link to Custom States for domains not covered.

??? info "Collapsible: full domain-to-class table" (keep existing, add note that API ref is canonical)

### H2: Iterating Over States
Looping over domains: `for entity_id, state in self.states.light`. Brief mention of `.keys()`, `.values()`, `.items()`, `.to_dict()`.

??? note "Collapsible: DomainStates collection methods"
Full method table (get, items, keys, values, iterkeys, itervalues, to_dict, __iter__, __len__, __contains__, __getitem__, __bool__). Lazy vs eager distinction.

### H2: Good to Know
- Startup and staleness: cache populated at startup, kept current via WebSocket, periodic poll guards against missed events.
- Missing entities: `.get()` vs bracket behavior.

### H2: See Also (renamed from existing)
Links to Subscribing, Custom States, API Entities, Bus, Cache.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `states_domain_access.py` | Keep | H3: Domain Access |
| `states_direct_access.py` | Keep | H3: Direct Entity Access |
| `states_generic_access.py` | Keep | H3: Generic Access |
| `states_iteration.py` | Keep | H2: Iterating Over States |
| `states_import.py` (from `core-concepts/snippets/`) | Keep | H2: Built-in State Types |

## Cross-Links

- **Links to:** Subscribing to State Changes, Custom States, State Registry, Type Registry, API Entities, Bus overview, Cache
- **Linked from:** Architecture, Apps overview, Getting Started
