# Design: Typed hass-hassette Messages

**Date:** 2026-11-17
**Status:** ratified
**Mode:** sketch
**Issues:** #4152
**Prior art:** design/research/2026-11-17-typed-custom-event-data/prior-art.md

## Summary

hass-hassette's `hassette.send` action fires a `hassette_action` event on Home Assistant's bus with data `{"name": str, "data": {...}}` (`data` optional, defaults to `{}`; contract in hass-hassette's README, "Actions"). hassette delivers it today as a generic `Event` on `hass.event.hassette_action` with the raw dict, and an app can't get the inner `data` as a typed model: `D.EventData[Model]` extracts the whole envelope, and `AnnotationConverter` can't turn a dict into a pydantic model or dataclass (it falls through to `TYPE_REGISTRY` → `Model(dict)`, which fails and skips the handler). There's also no topic constant, no way to match on `name` short of hand-writing a predicate, and no harness helper. hautomate carries its own workaround (`hautomate/src/hautomate/ha_messages.py`).

The concept is named "message" end to end (D8): hass-hassette's event type becomes `hassette_message` (its `EVENT_ACTION` constant in `custom_components/hassette/const.py`), while the YAML action stays `hassette.send`.

The change gives hass-hassette's message first-class support, the way hassette treats every HA event it types. Homes:

- Dict → model conversion: `src/hassette/conversion/annotation_converter.py` (D1).
- Event class and payload: `src/hassette/events/hass/hass.py`, registered in `HASS_EVENT_TYPES`; topic in `Topic` (`src/hassette/types/enums.py`) (D3, D5).
- Inner-data extractor: `src/hassette/event_handling/dependencies.py` (D2).
- Subscribe method: `src/hassette/bus/bus.py`, plus `on_hassette_message` in `BUS_EVENT_SHORTCUTS` (`codegen/src/hassette_codegen/sync_facade/generic.py`), which regenerates `src/hassette/bus/sync_events.py` (D4).
- Registration lists: `tests/unit/test_forgotten_await_completeness.py`, `tests/unit/test_harness_coverage.py`, `tools/docs/check_xref_coverage.py`, `src/hassette/events/__init__.py` exports, `docs/pages/troubleshooting.md`'s `on_*` list, and `D.EventData`'s docstring in `src/hassette/event_handling/dependencies.py` (D1 makes it work beyond `Bus.emit`).
- Malformed typed-event reporting: `construct_ignoring_unknown_keys` in `src/hassette/events/hass/hass.py` and `log_dispatch_failure` in `src/hassette/core/websocket_inbound.py` (D7).
- Harness helper: `src/hassette/testing/_simulation.py`, with its factory in `src/hassette/testing/_factories.py` (D6).
- Docs: `docs/pages/core-concepts/bus/dependency-injection.md`, `docs/pages/core-concepts/bus/methods.md`, `docs/pages/testing/harness.md`, and `docs/pages/getting-started/home-assistant-integration.md` (receiving messages).

The hass-hassette side (event-type rename, README, version floor) is its own PR in that repo and lands first (D9).

Out of scope: anything that sends messages back to HA, and hass-hassette's other features.

## Posture

- **Failure handling:** loud failure. Invalid or missing data skips the handler with a logged error that names the field; that is the existing `DependencyResolutionError` path, and it's already louder than every peer.
- **Compatibility:** break freely. Pre-v1, and `D.EventData[Model]` on dict data fails today, so making it succeed breaks nobody. hass-hassette's README example (`event.payload.data["name"]`) gets updated in that repo if D3 changes its shape.
- **Scope:** the complete feature the issue's acceptance asks for: a typed handler parameter, matching on `name`, and a harness helper with no private imports. Sending messages back out is out.
- **Rollout:** ships directly; no flag.
- **Hardening:** project defaults.
- **Altitude:** build; one session, the ledger cites files.

## Decisions

### D1: Where does dict → typed model conversion live?

**Situation:** A handler annotated `data: D.EventData[MyModel]` (or any extractor without its own converter) gets its extracted value through `ANNOTATION_CONVERTER.convert` (`src/hassette/bus/injection.py:122`). For a dict and a pydantic model or dataclass target, `AnnotationConverter.convert` falls to `TYPE_REGISTRY.convert` (`src/hassette/conversion/annotation_converter.py:74-75`), which calls `MyModel(the_dict)` and fails (`type_registry.py:212-224`). `Bus.emit` works only because the payload already is the object. Every custom HA event a user fires with `event:` in a script hits this, not just hass-hassette's message.

**Deciding factor:** one conversion path that serves every custom HA event, as NetDaemon's single `Filter<T>` does (prior-art brief, Pattern 1).

| | A: Generic in `AnnotationConverter` | B: Converter on the new extractor only |
|---|---|---|
| What it fixes | `D.EventData[Model]` and any extractor typed as a model, for every event; also `list[Model]` via the container converters, which recurse into `convert` | Only the message extractor |
| Mechanism | A branch after the `BaseState` special case: a `Mapping` value with a pydantic `BaseModel` subclass target validates through `tp.model_validate`; a dataclass target through a `functools.cache`d `TypeAdapter` per type (schema built once per type) | A `converter=` on one `AnnotationDetails`, as hautomate does |
| Blast radius | `ANNOTATION_CONVERTER` has one runtime consumer (`bus/injection.py`); the branch only turns a conversion that raises today into one that succeeds | None outside the new extractor |
| Error on bad data | pydantic `ValidationError`, wrapped by the injector into `DependencyResolutionError` naming handler, parameter and field | Same |
| Peers | NetDaemon: one generic mechanism, built-ins on top of it | No peer does per-event conversion |

**Recommendation:** A, because it fixes the general bug the issue names (`D.EventData[Model]` for any custom HA event) with one branch, and the message extractor then needs no converter of its own.
**Pick B instead if** you want this change confined to hass-hassette messages and the general `D.EventData` fix tracked separately.
**Extra keys:** pydantic models and dataclasses ignore undeclared keys by default, so a typo'd key on a field with a default validates silently. `docs/pages/core-concepts/bus/dependency-injection.md` documents this and how to opt into strictness (`extra="forbid"` on a model, the dataclass config equivalent).

**Union errors:** when every arm of a union annotation (`Model | None`, `D.MessageData[MyData | None]`) fails, the raised `UnableToConvertValueError` message includes the error text of each non-`NoneType` arm, not only a chained final-arm cause, so the field-naming pydantic error reaches the `DependencyResolutionError`. Tests pin `Model | None` and `dict | Model` (the latter is short-circuited by `TYPE_MATCHER` and never reaches the new branch).

**Reversibility:** easy (one branch; removing it restores today's failure)
**Ratified:** Chose generic Mapping → BaseModel/dataclass validation in `AnnotationConverter` (`model_validate` for models, a cached `TypeAdapter` per dataclass type) over a per-extractor converter, to fix `D.EventData[Model]` for every custom HA event, accepting pydantic's lax coercion and ignored extra keys (documented with the `extra="forbid"` opt-in), unsanitized `ValidationError` text (values included) in DI errors and execution records, and union failures that report every non-None arm's error.

### D2: How does a handler receive the message's inner `data`?

**Situation:** The model a user cares about is the inner `data`, one level below the envelope (`payload.data.data`). With D1 alone, a user could write an envelope model (`class Msg(BaseModel): name: str; data: MyData`) and annotate `D.EventData[Msg]`, then reach `msg.data`. hautomate instead defines `MessageData[T]` reading `payload.data.data`.

**Deciding factor:** the handler signature the issue's acceptance asks for, `async def on_msg(self, data: D.<X>[MyModel])`, without each app writing an envelope model.

| | A: `D.MessageData[T]` extractor | B: No new extractor; document the envelope-model pattern |
|---|---|---|
| Handler signature | `data: D.MessageData[MyData]` receives `MyData` | `msg: D.EventData[MyEnvelope]`, then `msg.data` |
| Boilerplate per app | None | One envelope model per message type, repeating `name: str` |
| New public surface | One `D` alias, next to `EventData` in `dependencies.py` | None |
| Conversion | Default converter (D1) on `payload.data.data` | Default converter (D1) on `payload.data` |
| Peers | NetDaemon users declare the whole data type (closer to B); no peer has a nested-field extractor | Same as NetDaemon |

**Recommendation:** A, because it's the signature the acceptance names and saves an envelope model in every app; the alias is one line on top of D1. Naming per D8.
**Pick B instead if** you'd rather keep `D` free of integration-specific aliases and accept the envelope model per app.
**Reversibility:** hard once released (public alias users will annotate with)
**Ratified:** Chose a dedicated `D.MessageData[T]` alias reading `payload.data.data` over documenting an envelope-model pattern, to give handlers the inner model directly as the acceptance asks, accepting one integration-specific alias in `D`.

### D3: Does the message event get a typed event class?

**Situation:** Event types listed in `HASS_EVENT_TYPES` (`src/hassette/events/hass/hass.py:250`) get an event class and a frozen payload dataclass built with `construct_ignoring_unknown_keys`; anything else becomes a generic `Event` with the raw dict on `hass.event.<type>`. hass-hassette's README tells users to read `event.payload.data["name"]`, which works only on the generic dict.

**Deciding factor:** matching how hassette already models the HA events it knows, so `name` and a defaulted `data` are typed for every consumer.

| | A: `HassetteMessageEvent` + `HassetteMessagePayload(name: str, data: dict[str, Any] = field(default_factory=dict))` in `HASS_EVENT_TYPES` | B: Keep the generic `Event` with a raw dict |
|---|---|---|
| Missing `data` | A missing `data` key defaults to `{}`, so `D.MessageData[T]` validates `{}` (fields with defaults pass, required fields fail naming the field). `data: null` or a non-mapping is not defaulted: it fails per handler at extraction (`ensure_present` or the converter), logged | `payload.data.data` is absent; the extractor's `ensure_present` skips the handler |
| Missing `name` (a script firing the event by hand) | Payload construction raises; the event is dropped for every subscriber, wildcard `hass.event.*` listeners included, and the drop is logged per D7. Wrong-typed `name`/`data` are not checked at construction: a non-string `name` never matches the D4 filter, and a non-mapping `data` fails at extraction | Event delivered; `name`-matching listeners just don't match |
| Handler reading the event directly | `event.payload.data.name` (typed) | `event.payload.data["name"]` |
| Compatibility | Breaks the README's `["name"]` example and any app subscripting the dict (hautomate's `named()` uses `get_path`, which reads attributes too, so it keeps working) | No change |
| Consistency | Same as `component_loaded`, `call_service`, etc. | The only hassette-recognized event without a class |

**Recommendation:** A, because it puts the message event on the same footing as every other event hassette types, settles missing `data` by the contract's own default, and makes a malformed message fail loudly at receive time. The README example is updated in hass-hassette.
**Pick B instead if** you want hass-hassette's existing README example to keep working unchanged, or want a hand-fired event without `name` delivered anyway.
**Reversibility:** hard once released (handlers will read typed attributes)
**Ratified:** Chose a typed `HassetteMessageEvent` with a `HassetteMessagePayload(name: str, data: dict[str, Any] = field(default_factory=dict))` registered in `HASS_EVENT_TYPES` over the generic `Event`, to match how hassette models every HA event it knows and default a missing `data` key per the contract, accepting that hass-hassette's README `["name"]` example must be updated, that a hand-fired event without `name` is dropped for every subscriber (wildcard listeners included) with the D7 log line, that wrong-typed `name`/`data` aren't caught at receive time, and that `data: null` or a non-mapping `data` fails per handler at extraction rather than defaulting. Tests pin a missing `data` key, `data: null`, and a missing `name`.

### D4: How do apps subscribe to a message by name?

**Situation:** Each HA event hassette types has a bus convenience method filtering on its key field: `on_component_loaded(component=...)` adds `P.ValueIs(source=get_path("payload.data.component"), condition=component)` (`src/hassette/bus/bus.py:1049`), with a sync mirror in `src/hassette/bus/sync_events.py`, an entry in `docs/pages/core-concepts/bus/methods.md`, and a row in the harness table. Today an app writes `bus.on(topic="hass.event.hassette_action", where=P.ValueIs(source=A.get_path("payload.data.name"), condition="x"), ...)`.

**Deciding factor:** the house convention for typed HA events, since no peer offers per-event subscribe methods (prior-art brief).

| | A: `on_hassette_message(message=None, *, handler, where, kwargs, name, on_error, **opts)` + sync mirror | B: Topic constant only; apps use `bus.on` + `P.ValueIs` |
|---|---|---|
| App code | One call, `name` filter built in | Topic plus a hand-written predicate on a path string |
| New public surface | One `Bus` method, one sync method | None beyond the `Topic` member |
| Failure modes added | None beyond `_subscribe`'s (same as `on_component_loaded`) | Typo-prone path string in every app |
| Consistency | Matches every other typed HA event | The only typed event without an `on_*` method |
| Peers | None have it | AppDaemon/HA core/Node-RED: raw filter on the data |

Note: the listener's required `name=` keyword already exists on every `on_*` method, so the message-name filter can't also be called `name`. The filter parameter is `message` (positional-or-keyword, like `component`; naming per D8): `on_hassette_message("tracker_done", handler=..., name="tracker.done")`.

**Recommendation:** A, because it's what the convention gives every typed HA event, it removes a path string apps get wrong, and it adds no failure mode; the convenience-API rule's cost (new failure modes) doesn't apply.
**Pick B instead if** you'd rather hold the bus surface fixed and treat hass-hassette as a plain custom event.
**Reversibility:** hard once released
**Ratified:** Chose `on_hassette_message(message=None, ...)` with a sync mirror over a bare topic constant, to match the convention every typed HA event follows and take the path string out of apps, accepting two new public methods no peer framework carries.

### D5: Topic member name

**Situation:** `HASS_EVENT_TYPES` entries need a `Topic`. Existing members are `HASS_EVENT_<EVENT_TYPE>` with value `hass.event.<event_type>` (`src/hassette/types/enums.py`). Every existing member is an event HA core fires; this one is fired by hass-hassette through HA's bus.

**Deciding factor:** follow the naming every other HA bus event uses; the topic string is fixed by HA (`hass.event.hassette_message`) regardless.

**Recommendation:** `Topic.HASS_EVENT_HASSETTE_MESSAGE = "hass.event.hassette_message"`, in the same block as the other HA events, docstring naming hass-hassette's `hassette.send` as the source.
**Pick a separate grouping instead if** you want integration-fired events visibly apart from HA core's in the enum (e.g. a comment-delimited block or a distinct prefix in the docstring).
**Reversibility:** hard once released
**Ratified:** Chose `Topic.HASS_EVENT_HASSETTE_MESSAGE` in the existing HA-event block over a separate grouping, to keep one naming rule for everything on HA's bus, accepting that the enum no longer lists only events HA core fires.

### D6: Harness helper signature

**Situation:** Spec 034 keeps event factories private and gives tests `simulate_*` methods. `simulate_call_service(domain, service, *, timeout, **data)` takes service data as kwargs; `simulate_component_loaded(component, timeout)` takes the key field.

**Deciding factor:** tests deliver exactly what HA would send (a mapping), without private imports.

| | A: `simulate_hassette_message(message, data=None, *, timeout)` with `data: Mapping[str, Any] | None` | B: `simulate_hassette_message(message, *, timeout, **data)` |
|---|---|---|
| Matches wire shape | Yes: one mapping, `None` → `{}` as the contract defaults | Kwargs; a data key named `timeout` or `message` collides |
| Call site | `simulate_hassette_message("tracker_done", {"room": "kitchen"})` | `simulate_hassette_message("tracker_done", room="kitchen")` |
| Consistency | Like `simulate_component_loaded`'s positional key field | Like `simulate_call_service` |

**Recommendation:** A, because the message data is a user-owned mapping whose keys can't be allowed to collide with harness parameters. The factory `create_hassette_message_event` builds the envelope through `create_event_from_hass`, as `create_hass_event` does, so the test path runs the real receive conversion.
**Pick B instead if** you prefer call-site brevity and accept the reserved keys.
**Reversibility:** hard once released
**Ratified:** Chose `simulate_hassette_message(message, data=None, *, timeout)` over kwargs data, to match the wire shape and keep user data keys from colliding with harness parameters, accepting a slightly longer call site than `simulate_call_service`.

### D7: How is a typed HA event that can't be built reported?

**Situation:** When a payload dataclass in `HASS_EVENT_TYPES` can't be built from HA's event data (D3's hand-fired `hassette_message` without `name`, or any typed event missing a required key), `cls(**data)` raises a `TypeError` inside `create_event_from_hass`. `WebsocketIO.dispatch` catches it and calls `log_dispatch_failure` (`src/hassette/core/websocket_inbound.py`), which logs only `'event' (id N)`, the exception type and traceback frames, never `str(exc)`, because the inbound module never logs HA values. The resulting line names neither the event type nor the field.

**Deciding factor:** make the Posture's "loud failure that names the field" true at receive time without logging values.

| | A: Tolerant payload so nothing drops | B: Name the event type and missing key names | C: Accept; reword D3 |
|---|---|---|---|
| Names the field | Failure moves to per-handler DI errors | Yes, for every typed HA event | No |
| Values kept out of logs | Yes | Yes: `event_type` and key names are metadata | Yes |
| Changes ratified D3 | Drops "fails loudly at receive time" | No | Wording only |
| New code | Payload defaults | `construct_ignoring_unknown_keys` raises an error carrying the payload class and missing field names; `log_dispatch_failure` adds the HA `event_type` and those names | None |

**Recommendation:** B, because it delivers the ratified promise for every typed HA event and keeps the inbound rule of names, never values.
**Pick A instead if** envelope strictness should move per handler. **Pick C instead if** hand-fired malformed events are too rare to touch the inbound log path.
**Reversibility:** easy
**Ratified:** Chose naming the HA `event_type` and the missing field names (never values) in the dispatch-failure log over a tolerant payload or a reworded D3, to make the loud-failure promise hold at receive time for every typed HA event, accepting a dedicated construction error and a branch in `log_dispatch_failure`.

### D8: What is the concept called across the API?

**Situation:** In HA YAML a user writes `perform_action: hassette.send` with `name:` and `data:`; the event type (`hassette_action` today) is a constant in hass-hassette's `custom_components/hassette/const.py` that YAML users never see. The Python side gets six names from one noun: event type, `Topic` member, event/payload classes, bus method, its filter parameter (`name=` is taken by the listener name), `D` alias, harness helper. "Action" means the service call in HA (`hassette.send` itself), and `on_hassette_service_*` already names hassette's internal service events. hass-hassette's README and hautomate call the thing a message with a name. Only one user exists, so renaming hass-hassette's event type is cheap.

**Deciding factor:** one noun a reader maps to the right thing without the docstring.

| | A: message | B: send | C: command | D: action (unchanged) |
|---|---|---|---|---|
| Event type | `hassette_message` | `hassette_send` | `hassette_command` | `hassette_action` |
| Bus method / filter | `on_hassette_message(message=)` | `on_hassette_send(message=)` | `on_hassette_command(command=)` | `on_hassette_action(action=)` |
| `D` alias / harness | `D.MessageData` / `simulate_hassette_message` | `D.SendData` / `simulate_hassette_send` | `D.CommandData` / `simulate_hassette_command` | `D.HassetteActionData` / `simulate_hassette_action` |
| Reader mapping | A named thing with a payload; matches README and hautomate | Mirrors YAML, but "on send" reads oddly | Implies an imperative/reply | Clashes with HA's "action" |
| hass-hassette change | Rename `EVENT_ACTION` value | Same | Same | None |

**Recommendation:** A, because it's the word the README and the only user corpus already use and names what the thing is, not how it travels. The wire field stays `name` (the message's name), the YAML action stays `hassette.send`, and the `D` alias drops the prefix like `D.EventData`.
**Pick B instead if** the Python side should echo the YAML action. **Pick D instead if** hass-hassette must not change.
**Reversibility:** hard once released
**Ratified:** Chose "message" end to end (`hassette_message` event type, `Topic.HASS_EVENT_HASSETTE_MESSAGE`, `HassetteMessageEvent`/`HassetteMessagePayload`, `on_hassette_message(message=...)`, `D.MessageData[T]`, `simulate_hassette_message(message, data)`) over send, command or keeping action, to give one noun that matches hass-hassette's own wording and avoids HA's meaning of "action", accepting a coordinated rename of hass-hassette's event type (its `EVENT_ACTION` value and README), with the wire field kept as `name` and the YAML action as `hassette.send`.

### D9: How is the hass-hassette contract kept in step?

**Situation:** D8 renames hass-hassette's event type, so both repos must agree on `hassette_message` and the `{name, data}` shape. The system tests install a pinned hass-hassette release (`HASS_HASSETTE_VERSION` in `scripts/docker/.env`, Renovate-tracked; `v0.5.0` today, which predates `hassette.send` from v0.6.0), and no test calls the action. Neither repo states a minimum version of the other, so drift surfaces only as D7's drop log or handlers that never fire.

**Deciding factor:** catch drift in CI at a cost fitting a one-author, two-repo setup.

| | A: System test + version floor + ordered hass-hassette PR | B: Version floor + hass-hassette PR only | C: Leave as is |
|---|---|---|---|
| Catches wire drift | Yes, in CI | No | No |
| Mismatched versions | Floor stated | Floor stated | Silent |
| Cost | hass-hassette release first; this PR bumps the pin and adds one system test | Two README lines plus the hass-hassette PR | None |

**Recommendation:** A, because the harness and pin already exist and a typed event over another repo's contract is where drift would otherwise fail silently.
**Pick B instead if** this PR must not wait on a hass-hassette release. **Pick C instead if** both repos are handled by hand at release.
**Reversibility:** easy
**Ratified:** Chose a hass-hassette PR first (rename `EVENT_ACTION` to `hassette_message`, update its README example to typed attribute access, state a minimum hassette version) and released, then this PR bumping `HASS_HASSETTE_VERSION` to that release and adding a system test in `tests/system/test_hass_hassette.py` that calls `hassette.send` and asserts a `HassetteMessageEvent` with typed `name`/`data` reaches a listener, over a version floor alone, to catch contract drift in CI, accepting that this PR waits on a hass-hassette release.

## Assumed

- A payload dataclass that can't be built from HA's event data raises inside `create_event_from_hass`, and `WebsocketIO.dispatch` logs it and drops that one event without ending the receive loop. Evidence: `src/hassette/core/websocket_io.py:370-385` (`except Exception` → `log_dispatch_failure`).
- A converter exception is wrapped into `DependencyResolutionError` carrying the original exception's type and text, and the handler is skipped. pydantic's `ValidationError` text names each failing field. Evidence: `src/hassette/bus/injection.py:136-144`.
- `A.get_path` reads attributes as well as dict keys (it uses `glom`), so `payload.data.name` works on both a dataclass payload and a raw dict. Evidence: `src/hassette/event_handling/accessors.py:65-78`; `on_component_loaded` uses it on `ComponentLoadedPayload`.
- When the extracted value already matches the target type, the injector skips conversion, so `Bus.emit` with a model instance is unaffected by D1. Evidence: `src/hassette/bus/injection.py:126-132`.
- The container converters (`list`, `set`, `frozenset`, `dict`, tuples) call back into `AnnotationConverter.convert` per element. Evidence: `src/hassette/conversion/annotation_converter.py` `convert_homogeneous_iterable`.
- hass-hassette's contract: event type `hassette_action` today (renamed to `hassette_message` by D8, in hass-hassette's `const.py` `EVENT_ACTION`), data `{"name": str (required), "data": mapping (optional, default {})}`. Evidence: `~/source/hass-hassette/README.md` "Actions" section.

## Build

- [ ] Implementation and tests committed
- [ ] Docs
- [ ] Ship-time challenge

**Calls made during the build:**
- `MissingPayloadFieldsError` (D7) lives in `src/hassette/events/hass/hass.py` next to `construct_ignoring_unknown_keys`, not `exceptions.py`: it's raised and caught internally, and `exceptions.py` sits at 791 of 800 lines.
- `construct_or_name_missing` only computes missing fields after `cls(**data)` raises `TypeError`, so the per-event happy path does no extra work.
- `bus.py` and `testing/_simulation.py` grow past the file-size threshold; per the user, the PR carries `lint:file-size-allowed` and a follow-up issue tracks splitting the HA-event shortcuts out of both files.
