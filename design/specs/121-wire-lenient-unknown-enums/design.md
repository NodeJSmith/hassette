# Design: Lenient parsing of unknown enum values in hassette-wire

**Date:** 2026-10-03
**Status:** built
**Mode:** sketch

## Summary

hassette-client must keep working against a newer server that has added a value to an enum- or
`Literal`-typed response field. Today any unrecognized value fails the whole response parse. Issue
#2484 (blocks #2386) adds lenient parsing for these fields. Leniency applies only when the caller
passes `LENIENT_CONTEXT` (D8, D13). hassette-client is expected to pass it on every parse once #2386
builds its transport; enforcing that is #2386's call (D9). The server never passes it, so server-side DB-row parsing and model construction stay
strict.

Under that context, an unrecognized string parses to `UnknownValue`, a small `str` subclass that keeps
the raw value (D3). Each affected response field is typed `X | UnknownValue`, where `X` is the wire
enum or `Literal` it has today (D1). The enums themselves don't change, so the public
`hassette.ExecutionMode`, `ResourceStatus` and their siblings gain no member.

This supersedes research decisions 1 and 2 in
`design/research/2026-10-02-hassette-client-transport/research.md` ("Decisions (2026-10-02)"). Those
called for a reserved `UNKNOWN` member on every wire `StrEnum` (that brief's option L1) and for
converting open `Literal`s to `StrEnum`s. D1 records why this design uses that brief's option L2
instead. Issue #2484's acceptance criteria still describe L1. The PR description says which ones
changed: no `UNKNOWN` member, no `Literal` conversion, no input-boundary rejection (nothing on the
input side changes), and no client code in this PR (D9).

In scope:
- A new module `wire/src/hassette_wire/lenient.py` holding `UnknownValue` (D3), the `LenientValue`
  marker (D4), the unknown-value DEBUG log (D6) and `LENIENT_CONTEXT` (D8).
- The `Open<TypeName>` aliases (D4) in `enums.py`, `problems.py`, `literals.py` and `blocking.py`, and
  widening the affected response fields (D5) in `apps.py`, `blocking.py`, `health.py`, `logs.py`,
  `problems.py`, `telemetry.py` and `ws.py`.
- Exporting `UnknownValue` and `LENIENT_CONTEXT` from `wire/src/hassette_wire/__init__.py`.
- The strict-path timing measurement (D7).
- Floor-version test runs in `noxfile.py` (D10), and leniency tests in `wire/tests/`.
- PR title and commit type `feat:` (D11). `CHANGELOG.md` is not edited by hand; release-please
  generates it.
- Dated `## Addendum` entries on spec 116 and on the research brief's "Decisions" section, recording
  the switch from L1 to L2 and D14's reversal of spec 116's "open-valued" note.

Out of scope:
- The client transport, its parse entry point that applies `LENIENT_CONTEXT`, error mapping into
  `ResponseValidationError`, and typed methods (#2386, see D9).
- The hassette CLI (`src/hassette/cli/`). It parses server JSON strictly (`cli/client.py:205,242,349`)
  and stays that way in this PR, because #2387 moves it onto hassette-client's parse path. Until then,
  a CLI talking over HTTP to a server of a different version can still fail on a new value.
- WebSocket message `type` discriminators and single-value `Literal`s (`"accepted"`, `"ok"`, `"live"`).
  They're constants, not open sets.
- Request models and config. Both stay strict.

The pin for this change: `tools/check_schemas_fresh.py` passes with `frontend/openapi.json` and
`frontend/ws-schema.json` byte-identical, and `tools/check_wire_compat.py` reports nothing.

## Decisions

### D1: How does a lenient parse represent a value the client doesn't recognize?

**Deciding factor:** keep the raw value and keep the shared enums unchanged, without weakening static checking for client consumers.

| | A: Field type `X \| UnknownValue` (research L2) | B: Reserved `UNKNOWN` member on every wire enum (research L1) | C: Lenient-only pseudo-member carrying the raw string |
|---|---|---|---|
| Raw value | Kept, and written back on `model_dump_json()` | Lost; log only | Kept |
| Public enums (`hassette.ExecutionMode` etc.) | Unchanged | Gain a member, which brings `known()`, input-boundary rejection, a consumer guard, a custom strict error, and `feat!` | Unchanged |
| Open `Literal` fields | Stay `Literal`; the schema is byte-identical | Converted to `StrEnum`s: new public names, schema churn | Need conversion |
| Pyright forces consumers to handle unknowns | At enum- or `Literal`-typed sinks and exhaustive `match`: the union must be narrowed. Not at `str`-typed sinks, which accept `UnknownValue` (D3) | Yes, `match` must cover `UNKNOWN` | No, an exhaustive `match` silently falls through |
| Strict-path error | Pydantic's native one | Hand-built so it omits `UNKNOWN` | Native |
| Server-side cost | With all 31 affected fields widened to `X \| UnknownValue`, `uv run pyright src wire/src client/src` reported 0 errors (baseline also 0; throwaway widening on 2026-10-03, reverted) | None | None |
| Mechanism risk | Supported pydantic hooks; spiked on 2.7.0 / Python 3.11 and 2.12.3 / Python 3.14 | Spiked | Relies on enum internals that differ across our Python range: `in Enum` is True on 3.14 and False on 3.11; `pickle` and `repr` break |
| Prior art | Matches the AWS SDK (Java/Rust) and Apollo Kotlin `__Unknown(rawValue)` direction | openapi-generator `enumUnknownDefaultCase` (sentinel only) | open-enum (Python) |

**Recommendation:** A. It keeps the raw value, which every mature tool in the survey moved toward. It leaves the public framework enums and `Literal`s untouched and keeps pyright narrowing at typed sinks. The server-side narrowing cost that research Q2 cited against it measured zero.
**Pick B instead if** consumers must be able to `match` an unknown case as an enum member and you'll accept losing the raw value. **Pick C instead if** the enums must keep a single member type and you'll accept the cross-version enum-internals fixes.
**Reversibility:** hard once a client release ships (the field types are the client contract)
**Ratified:** Chose A over B and C, to keep raw values and leave public enums untouched, accepting widened `X | UnknownValue` field types on shared wire models.

### D2: Which inputs does the lenient path map to `UnknownValue`?

**Deciding factor:** tolerate additive skew, and still fail loudly on non-additive change.

| | A: Only `str` inputs that fail the field's enum or `Literal` validation | B: Any input that fails validation |
|---|---|---|
| New value (`"paused"`) | `UnknownValue("paused")` | `UnknownValue` |
| Retyped field (int, object, null on a required field) | Raises | Silently becomes `UnknownValue` |
| Matches the issue's "non-additive changes still raise" | Yes | No |

**Recommendation:** A, because a retyped field is a contract break the client should surface.
**Pick B instead if** a wire enum is ever carried as non-string values. None is today.
**Reversibility:** easy
**Ratified:** Chose A over B, so additive skew is tolerated while retyped fields still raise, accepting that a non-string enum would need its own handling.

### D3: What is `UnknownValue`?

**Deciding factor:** carries the raw value with the least friction in string contexts, and is unambiguous to narrow.

| | A: `class UnknownValue(str)` with `__slots__ = ()` and `repr` `UnknownValue('paused')` | B: Frozen dataclass wrapper with a `.raw: str` attribute |
|---|---|---|
| Raw value access | The value itself (`str(v)`, `v == "paused"`, f-strings) | `v.raw` |
| Narrowing | `isinstance(v, UnknownValue)` or `case UnknownValue():`. Not `isinstance(v, str)`, which a `StrEnum` member also passes | `isinstance(v, UnknownValue)`; distinct from `str` |
| Passes pyright at `str`-typed sinks (e.g. hassette's `mode: ExecutionMode \| str`, which then raises at registration) | Yes | No |
| Serialization | Raw string, naturally | Needs a serializer anyway |
| Spiked | Yes | No |

`UnknownValue` is exported from the `hassette_wire` package root, because consumers import it to narrow. Its docstring states the narrowing rule and A's other trade-offs: string methods return plain `str`, and `str()` and f-strings show only the raw value.

Behavior to pin:
- JSON-mode dumps write the raw string back.
- Python-mode dumps return the object unchanged: an enum member stays a member and an `UnknownValue` stays an `UnknownValue`. The serializer is `when_used="always"`, takes `info`, and returns the value unchanged in python mode and `.value`/`str(v)` in json mode. A json-only serializer lets python-mode dumps reach the enum serializer, which emits pydantic's "Expected `enum`" warning on both 2.7.0 and 2.12.3 (verified 2026-10-03). Dumps of lenient-parsed models emit no warnings at all, which matters because `wire/pyproject.toml` doesn't escalate warnings to errors. (Built as a wrap serializer instead; see Build.)
- A lenient re-parse of a lenient dump is lossless.
- Every input, including an `UnknownValue`, goes through the enum/`Literal` validation first, and the fallback applies only on failure. So a lenient re-validation of `UnknownValue("running")` by a client whose vocabulary now includes `"running"` yields the enum member.
- A member of a different `StrEnum` whose value is in the field's vocabulary validates to the field's member, not to `UnknownValue` (`ResourceStatus.RUNNING` into a `ManifestStatus` field gives `ManifestStatus.RUNNING`). One whose value isn't becomes `UnknownValue`.
- Strict validation of raw input (a dict or JSON) rejects an unknown string, and an `UnknownValue` whose string is outside the field's vocabulary, with pydantic's native `enum`/`literal_error` type and message.
- Strictness applies at validation time only. A lenient-parsed *model instance* passed into a strict model (`Parent(child=lenient_child)`) is accepted as-is under pydantic's default `revalidate_instances='never'`, and `model_copy(update=...)` skips validation. This boundary is pinned as current behavior. The `UnknownValue` and `LENIENT_CONTEXT` docstrings state that lenient-parsed objects are read-only client results and must not be passed into server-side constructors. No server path produces lenient objects today.

**Recommendation:** A. It's the spiked shape, behaves like the string it is everywhere a string is expected, and the narrowing caveat is a docstring line.
**Pick B instead if** consumers will commonly pass wire values into `str`-typed hassette or HA APIs, where an unknown value would fail later rather than at type-check time.
**Reversibility:** hard once released (public type)
**Ratified:** Chose A over B, so the raw value is the value and works anywhere a string does, accepting that pyright doesn't flag unknowns at `str`-typed sinks and that narrowing relies on `isinstance(v, UnknownValue)`.

### D4: How are the affected fields annotated?

**Deciding factor:** one definition per open type, readable at the field, and understood by pyright.

| | A: One alias per type, next to the type's definition, not added to `__all__` | B: Inline `Annotated[X \| UnknownValue, LenientValue(...)]` at each field | C: A generic `Open[X]` helper |
|---|---|---|---|
| Definitions | About 15 aliases (one per type) | 31 inline repetitions | One |
| Pyright understands it | Yes | Yes | No: a runtime `__class_getitem__` returning `Annotated` is opaque to pyright |
| Public surface | None; the field's type shows the union | None | One helper |
| Risk of a field missing the marker (strict by accident) | Low: the alias carries it | Higher | Low |

Placement:
- Every alias is named `Open<TypeName>` (`OpenResourceStatus`, `OpenSystemHealthStatus`, `OpenExecutionKind`, ...).
- Enum aliases live in `enums.py` / `problems.py` next to their enum, e.g. `OpenResourceStatus = Annotated[ResourceStatus | UnknownValue, LenientValue("ResourceStatus")]`.
- `Literal` aliases live in `literals.py` / `blocking.py` next to theirs.
- The three inline `Literal`s get named aliases in `literals.py`, also kept out of `__all__`:
  - `ExecutionKind` for `Literal["handler", "job"]`, used in `telemetry.py:20,87`, `ws.py:115` and `logs.py:23`.
  - `BootIssueSeverity` for `Literal["err", "warn"]`.
  - `HandlerKind` for `Literal["listener", "job"]`.

These aliases and new names don't change the JSON schema, because `Literal` arms stay inline.

`LenientValue(type_name: str)` is the `Annotated` marker, defined in `lenient.py` and not exported. Its `__get_pydantic_core_schema__` takes the enum or `Literal` arm out of the union and generates that arm's schema, so enums keep their `$ref` component and `Literal`s stay inline. It wraps that with the context-gated validator (D8, D13) and the D3 serializer. `type_name` names the open type in the D6 log. It raises `TypeError` at schema build (import time) unless its source is exactly `<StrEnum subclass or all-str Literal> | UnknownValue`, so a mis-shaped alias fails loudly instead of silently staying strict.

**Recommendation:** A, because each open type is defined once, and the alias name shows a reader that the field is open.
**Pick B instead if** you'd rather see the mechanism at each field than learn alias names.
**Reversibility:** easy
**Ratified:** Chose A over B and C, so each open type is defined once and pyright-visible, accepting about 15 alias names kept out of `__all__` and an import-time shape guard in `LenientValue`.

### D5: Which fields become open?

**Deciding factor:** no value a released client parses strictly can grow, except vocabularies D14 keeps strict.

Every response-side field (REST response models and WS payloads) typed with a wire enum or an open `Literal`. That is 31 fields (`ws.py` 6, `apps.py` 2, `health.py` 4, `problems.py` 1, `logs.py` 1, `telemetry.py` 13, `blocking.py` 4) over these types: `ResourceStatus`, `ManifestStatus`, `ExecutionStatus`, `ExecutionMode`, `BackpressurePolicy`, `ProblemCode`, `SystemHealthStatus`, `HealthStatus`, `ErrorRateClass`, `ListenerKind`, `BlockingTier`, `UnattributedReason`, `ExecutionKind`, `BootIssueSeverity` and `HandlerKind`.

Behavior to pin: any response-model field typed with a wire `StrEnum` or a multi-value `Literal` that isn't open fails the wire tests. The only exceptions are D14's `SourceTier`/`LogLevel`, single-value `Literal`s, WS `type` discriminators, and request models. A field added later can't silently stay strict.

**Recommendation:** every response field above.
**Pick a narrower set instead if** you want this PR limited to the HA-path fields (`SystemStatusResponse`, `ServiceInfoResponse`, `AppManifestResponse`, `ProblemDetail`), leaving the rest for #2386 before v0.1.
**Reversibility:** easy before the first client release, hard after
**Ratified:** Chose every response-side enum and open-`Literal` field over the HA-path subset, so every client method survives skew from the first release, accepting a wire-test failure for any future field that isn't marked open.

### D6: Does the lenient path log unknown values?

**Deciding factor:** skew is visible to whoever can act on it (upgrade the client), without flooding logs.

| | A: One `WARNING` per distinct `(type_name, raw value)` per process, through `logging.getLogger(__name__)` in `lenient.py` | B: No logging: the caller has the `UnknownValue` and decides | C: `DEBUG` on every occurrence, no state; the consumer owns the user-facing warning |
|---|---|---|---|
| A HACS user sees "update your integration" signals | Yes | Only if the integration logs it | Only if the integration reports it (#2386) |
| Message accuracy | Claims a cause (skew) a validator can't verify: a server bug, a client newer than its server, or a foreign peer look the same | n/a | States only what is known: type, raw value, field |
| Noise | One line per new value per process | None | None at default levels |
| State | A module-level set of logged pairs, growing with every distinct string the peer sends | None | None |
| Spurious line when a later field fails the parse | At `WARNING`, and the dedupe slot is spent | n/a | At `DEBUG` only |
| Library logging rule | `getLogger` only, no configuration | n/a | `getLogger` only |

`type_name` is the open type's name given to `LenientValue` (D4). The message names the type, the raw value, and the field name when pydantic's validation info provides one.

Under C, #2386 owns the user-facing skew message: its transport knows the client and server versions and the response media type, and finds unknowns with `isinstance(v, UnknownValue)`. The `LENIENT_CONTEXT` docstring states this.

**Recommendation:** C, because a validator lacks the facts an accurate skew diagnosis needs, and C keeps a stateless trail for debugging.
**Pick A instead if** a HACS user must see skew even when the integration ignores the value. **Pick B instead if** wire should emit no logs at all.
**Reversibility:** easy
**Ratified:** Chose C over A and B (reopened at the ship-time challenge, which found A's message misdiagnoses causes, its dedupe set grows unbounded, and it can fire for parses that later fail), so wire keeps a stateless DEBUG trail and the consumer that knows the versions owns the user-facing message, accepting that skew stays invisible to users until #2386 reports it.

### D7: How is the strict-path overhead checked?

**Deciding factor:** know what the wrap validator and serializer cost the server, with a threshold that decides something.

The context-gated validator is a Python callback on every open field, on the server's strict path too, including DB-row parsing in list comprehensions (`src/hassette/core/telemetry/registration_queries.py:117,213,250`, `execution_queries.py:80,173`). The D3 serializer is a Python callback on every open field of every dump, including server JSON responses. The strict branch must be a single context check followed by the inner validator call. A synthetic 5k-row model with 3 open fields, on pydantic 2.12.3 (2026-10-03), measured `model_validate` going from 8.4 to 13.6 ms (1.6x) and `TypeAdapter(list[...]).dump_json` from 3.9 to 7.2 ms (1.85x).

**Recommendation:** time `ListenerWithSummary` (3 open fields, parsed from DB rows in `registration_queries.py`) before and after, over about 5k rows, for both `model_validate` and `dump_json`, and record the results in the Build section. The budget is under 2x for each. Exceeding it is a stop-and-ask, not a build-time call. The fallback considered then is a `union_schema(mode="left_to_right")` form, which keeps known values in pydantic-core but needs a JSON-schema override and changes the error shape.
**Pick skipping it instead if** you accept that telemetry lists stay small for a self-hosted tool.
**Reversibility:** easy
**Ratified:** Chose measuring both `model_validate` and `dump_json` against an under-2x budget over skipping, so the cost is evidence with a decision attached, accepting one timing step in the build.

### D8: What does `hassette_wire` export to switch on leniency, and what exactly switches it on?

**Deciding factor:** the smallest export every parse path can apply. Anything other than the exact flag is strict.

| | A: A read-only mapping constant `LENIENT_CONTEXT` | B: A `validate_lenient(tp, data)` helper owning `TypeAdapter`s | C: Both |
|---|---|---|---|
| Caller code | `adapter.validate_json(body, context=LENIENT_CONTEXT)` | `validate_lenient(T, body)` | Either |
| Merging other context keys | `{**LENIENT_CONTEXT, ...}` | Needs a parameter | Either |
| Adapter caching / JSON-vs-Python | Owned by the client transport | Inside the contract package | Duplicated |

`LENIENT_CONTEXT` is exported from the `hassette_wire` package root; its key is private to `lenient.py`. Gate rule: leniency applies only when `info.context` is a `Mapping` and the key's value `is True`. `None`, non-mapping contexts and falsy values are strict (spiked).

**Recommendation:** A, because adapter caching and body handling belong to #2386's transport.
**Pick B instead if** consumers other than `hassette_client` will parse leniently.
**Reversibility:** easy to add B later
**Ratified:** Chose A over B and C, so wire only defines the flag and anything but the exact flag is strict, accepting that each lenient consumer applies the context itself.

### D9: What lands in `hassette_client` in this PR?

**Deciding factor:** #2386 owns every client symbol and the transport's parse design.

Nothing; `client/` is unchanged. This PR proves leniency against `hassette_wire` models directly: `ProblemDetail`, a list via `TypeAdapter`, a nested model, and a WS payload. The issue's "the client applies it to every parse" criterion moves to #2386, and enforcing it there is #2386's call.

**Recommendation:** ship nothing in the client.
**Pick a public parse entry point now instead if** you want this PR to fix the client's parse API before #2386 designs its transport.
**Reversibility:** easy
**Ratified:** Chose shipping nothing in `hassette_client` over a public parse entry point now, so #2386 owns every client symbol and the transport design, accepting that the "every client parse is lenient" criterion moves to #2386.

### D10: How is the declared pydantic floor tested?

**Deciding factor:** CI catches a broken floor without a new workflow job.

| | A: Second run inside the existing `wire` and `client` nox sessions | B: Separate `wire_floor` / `client_floor` sessions |
|---|---|---|
| CI coverage | Automatic: `tests.yml`'s `workspace-members` job runs `nox -s wire` / `nox -s client` | Needs new `tests.yml` lines |
| Command | `uv run --isolated --resolution lowest-direct --python 3.11 --directory <member> pytest -q` | Same |

The floor is `pydantic>=2.7` in `wire/pyproject.toml`. `--python 3.11` is needed because pydantic-core for 2.7.0 has no wheels for the newest Pythons. `--isolated` leaves `uv.lock` untouched. Both members resolve pydantic 2.7.0 this way (verified, including `client`, whose wire dependency is a workspace member).

**Recommendation:** A.
**Pick B instead if** the extra resolve slows the local loop too much.
**Reversibility:** easy
**Ratified:** Chose A over B, so CI tests the floor wherever it tests the member with no workflow edit, accepting a one-off resolve in local `nox -s wire`/`client` runs.

### D11: What commit type does the change ship as?

**Deciding factor:** honest about what callers can observe.

| | A: `feat:` | B: `feat!:` with a `BREAKING CHANGE:` footer |
|---|---|---|
| Runtime behavior for existing callers | Unchanged: strict unless they pass `LENIENT_CONTEXT` | Same |
| Static types | `hassette_wire` response-field annotations widen to `X \| UnknownValue`, so a direct `hassette_wire` consumer reading `.value` gets a pyright error | Same |
| hassette app authors | Unaffected: public enums unchanged | Same |

**Recommendation:** A, because nothing changes at runtime for any existing caller, and the type widening only affects code that opts into leniency or reads wire models directly.
**Pick B instead if** you treat `hassette_wire`'s field annotations as a versioned public contract that must flag widening.
**Reversibility:** easy until release
**Ratified:** Chose A over B, because no existing caller sees a runtime change, accepting that direct `hassette_wire` readers meet the widened types without a breaking-change flag.

### D12: Where does the "unknown values" docs note go?

**Deciding factor:** users meet the note where they use lenient parsing.

A single note on #2386's hassette-client docs page, covering `UnknownValue`, `LENIENT_CONTEXT`, the narrowing idiom (`case UnknownValue():`), and that unknown response fields are already ignored. This PR changes no `docs/pages/`. The public framework enums are unchanged, so app-author pages need nothing. `.claude/rules/design-completeness.md` asks for docs in the same PR for user-facing changes, but no docs page covers `hassette_wire` today, so its "no corresponding docs page" exemption applies. The `UnknownValue` and `LENIENT_CONTEXT` docstrings are the interim reference until #2386's page lands.

**Recommendation:** the single client-docs note in #2386.
**Pick per-page notes now instead if** this PR ships in a release without #2386's client docs and direct `hassette_wire` users need the note sooner.
**Reversibility:** easy
**Ratified:** Chose a single client-docs note over per-page notes, keeping framework pages untouched, accepting that the note ships with #2386's hassette-client page.

### D13: Is leniency opt-in per parse, or unconditional?

**Deciding factor:** keep the server's own bugs loud, and keep the choice reversible without breaking released clients.

| | A: Opt-in: strict by default, lenient only under `LENIENT_CONTEXT` | B: Unconditional: every open field is always lenient for `str` failures |
|---|---|---|
| Client survives a newer server | Yes, when it passes the context (#2386's transport) | Yes, automatically |
| Server's own bad values (a mistyped producer value, a malformed DB row, a dict-built model) | Raise in tests and at runtime | Reach clients as `UnknownValue` |
| Server-side model constructors | Checked: constructors can't take a context, so they get the strict default | Lenient |
| hassette CLI before #2387 | Strict unless it opts in | Lenient automatically |
| Reversing later | Dropping the gate costs released clients nothing (their flag becomes inert) | Adding a gate makes every released client that never passed the flag strict again |
| Moving parts | `LENIENT_CONTEXT`, the gate check, one opt-in at the client's parse point | None of those |
| Prior art | Tolerant-reader split: conservative sender, liberal reader (Microsoft Graph keeps emitted values strict) | Protobuf open enums are lenient on both sides at the parse layer |

The server never receives these fields as input: no request model or config carries them. So strictness here guards the server's own output, not its input.

**Recommendation:** A, because it keeps server-side construction checked and is the reversible arrangement.
**Pick B instead if** you prefer a malformed server value to show as unknown in the UI over a failing test, and want the CLI skew-tolerant before #2387.
**Reversibility:** A → B easy; B → A breaks released clients
**Ratified:** Chose A over B, to keep the server's own bugs loud and the choice reversible, accepting a per-parse opt-in that #2386's transport must apply.

### D14: Do `SourceTier` and `LogLevel` stay strict on response models?

**Deciding factor:** open only vocabularies that can actually grow.

| | A: Keep strict, as declared-closed vocabularies | B: Open them like D5's types |
|---|---|---|
| Fields affected | `LogEntryResponse.level`/`source_tier` (`logs.py:12,22`) and `source_tier` in `telemetry.py:31,111,222` | Same |
| If the server adds a value | Breaking wire change: needs a `BREAKING CHANGE` footer, and old clients fail to parse those responses | Old clients see `UnknownValue` |
| Caught by `tools/check_wire_compat.py` | No: the forward run allows `response-property-enum-value-added` (`tools/check_wire_compat.py:16-19`), so growth needs manual review | n/a |
| Vocabulary reality | `LogLevel` is the stdlib level set; `SourceTier` is the app/framework split by design | Same |
| Shared with input/config | `LogLevel` is also hassette's config log-level type (`src/hassette/config/helpers.py:10,16`), which stays strict either way; `SourceTier` appears only on response models (query filters use the separate `QuerySourceTier`, `literals.py:9`) | Needs a response-only open alias for `LogLevel` |

This reverses spec 116's "Literal wire fields" note (`design/specs/116-wire-models-to-hassette-wire/design.md:182-184`), which listed `SourceTier` and `LOG_LEVEL_TYPE` among the open-valued aliases. The spec 116 addendum cites this decision.

**Recommendation:** A, because neither vocabulary is expected to grow, and declaring them closed is cheaper than two more open aliases.
**Pick B instead if** you expect a third source tier or custom log levels.
**Reversibility:** easy before the first client release, hard after
**Ratified:** Chose A over B, because both vocabularies are closed by design, accepting that growing either is a manual-review breaking change.

## Assumed

- Validation context reaches nested models and `TypeAdapter(list[...])` for both `validate_python` and `validate_json`. Evidence: spikes on 2026-10-03 on pydantic 2.12.3 / Python 3.14 and 2.7.0 / Python 3.11 (`uv run --isolated --resolution lowest-direct --python 3.11`).
- An `Annotated[X | UnknownValue, marker]` produces the arm's own JSON schema for both enum and `Literal` arms. Enums stay `$ref` components, `Literal`s stay inline, and `X | None` fields become `anyOf[$ref, null]`, all identical to today, including fields with defaults, in validation and serialization schema modes. Evidence: same spikes; the build re-verifies it through `tools/check_schemas_fresh.py` (the Summary's pin).
- FastAPI (0.136.3 installed) passes returned model instances straight through response validation without re-running field validators. The response-path cost is the serializer only. Evidence: `.venv/lib/python3.14/site-packages/fastapi/routing.py:293,695-706` (`serialize_response` passes the returned objects to `field.validate`), plus pydantic's default `revalidate_instances='never'`.
- No wire request model carries an enum or open `Literal` field. The only request models (`auth.py:14-22`, `logs.py:36-40`) have plain `str` fields, so an `UnknownValue` can't be echoed back to the server through a wire request model.
- Unknown response fields are already ignored: no wire model sets `extra=`. Evidence: issue #2484, `wire/src/hassette_wire/*.py`.
- DB CHECK constraints cover most enum-backed columns (mode, backpressure, kind, execution status, blocking tier, schedule status). Evidence: `src/hassette/migrations_sql/001.sql:12,84,92`, `005.sql:12`, `008.sql:2`, `009.sql:23`, `012.sql:62,66`.
- The root `pyproject.toml` sets `filterwarnings = ["error"]` (`pyproject.toml:148-149`), and `wire/pyproject.toml` doesn't.
- Spec 116 is `**Status:** archived`, so its notes get a dated `## Addendum` entry, not a body edit. Evidence: `design/specs/116-wire-models-to-hassette-wire/design.md:4`.
- Prior art, as of 2026-10-03, not live-verified:
  - AWS SDK for Java v2 (`UNKNOWN_TO_SDK_VERSION` plus `xxxAsString()`), AWS SDK for Rust (`Unknown(..)` plus `as_str()`, https://docs.rs/aws-sdk-cloudfront/latest/aws_sdk_cloudfront/types/enum.OriginAccessControlOriginTypes.html) and Apollo Kotlin (`__Unknown(rawValue)`, https://www.apollographql.com/docs/kotlin/kdoc/apollo-gradle-plugin/com.apollographql.apollo.gradle.api/-service/generate-apollo-enums.html) keep raw values.
  - Gating elsewhere happens at code-generation time (openapi-generator `enumUnknownDefaultCase`, Speakeasy `forwardCompatibleEnumsByDefault`, https://www.speakeasy.com/docs/sdks/manage/forward-compatibility) or on the wire (Microsoft Graph `Prefer: include-unknown-enum-members`). No precedent was found for a validation-time gate on types shared by server and client. D13's gate is the runtime equivalent, made necessary by spec 116's shared models.
  - pydantic issue #7110 (`Union[Enum, primitive]` collapsing to the primitive) doesn't apply. The marker validates the enum/`Literal` arm only, and the fallback is explicit, so pydantic never chooses between union arms.

## Build

- [x] Implementation and tests committed
- [x] Strict-path timing checked (D7)
- [x] Docs (spec 116 and research-brief addenda; no `docs/pages/` per D12)
- [x] Ship-time challenge

**Calls made during the build:**
- `wire/tests/test_import.py` exempts `Open*` names, the three new Literal names, `LenientValue` and `LOGGER` from its "every definition is exported" rule, and asserts they stay out of `__all__`: D4 keeps them unexported, and the old test would have failed on them. A stale-exemption check keeps the list honest.
- The D6 log line reads `field None` on pydantic 2.7.0, whose `ValidationInfo.field_name` is `None` for this validator; 2.12.3 provides it. D6 already allows this ("when pydantic's validation info provides one"). No test asserts log output.
- `_typos.toml` allows `ser`, which appears in pydantic-core's `wrap_serializer_function_ser_schema`.
- The `LENIENT_CONTEXT` key is `"hassette_wire.lenient"`. `LENIENT_CONTEXT` is a plain `dict` annotated `Mapping[str, Any]`, so pyright discourages mutating it while it still deep-copies and pickles. A `MappingProxyType` blocked mutation but broke `copy.deepcopy` and `pickle`, a failure that would surface far from leniency in retry wrappers or executors.
- The fallback to `UnknownValue` also requires the string to be outside the field's vocabulary, not just rejected by it. Under `strict=True` Python validation the arm rejects a known `str` like `"running"`, and D2's "fails validation" alone would have mislabelled it as unknown. Such a value now raises as it would on a plain field.
- An in-vocabulary `str` subclass (`UnknownValue`, a foreign `StrEnum` member) that the arm rejects is retried as its plain value instead of raising. pydantic-core 2.7's `Literal` validator rejects `str` subclasses, so D3's re-validation pins failed on the floor for all 9 open `Literal` types. A test over every open alias, in both contexts, pins the result. An exact `str` rejected under `strict=True` still raises.
- `UnknownValue` has a `.value` property returning the raw value as a plain `str`. The common `x.status.value` enum idiom would otherwise raise `AttributeError` at exactly the moment of skew.
- The D3 serializer is a *wrap* serializer over the arm's own schema, not the plain one D3 describes. It handles an `UnknownValue` itself (unchanged in python mode, the raw string in JSON mode) and passes everything else to the arm's serializer. A plain serializer replaced the arm's serializer outright, which silenced pydantic's "Expected `enum`" warning for a `str` that bypassed validation (`model_construct`, assignment). Under the root `filterwarnings = ["error"]` that warning fails server tests, which is how D13 keeps server bugs loud for enum-typed fields. Pydantic never warns for a bypassed `str` in a `Literal` field, so open `Literal` fields behave as plain ones did. A test pins the enum warning in both modes. D3's other dump pins are unchanged.
- `LenientValue`'s shape guard rejects `X | UnknownValue | None`. Optional fields wrap the alias (`OpenResourceStatus | None`) instead, which every optional open field already does.
