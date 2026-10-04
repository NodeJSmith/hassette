# Design: Apply the wire naming rule and consumer docstrings

**Date:** 2026-10-04
**Status:** ratified
**Mode:** sketch

## Summary

Issue #2448, items (b) and (d). This ledger goes last, on the final model shapes from specs 123–125. It applies the naming rule to the wire models still carrying old names (D1, D2), enforces class docstrings by lint (D8), and rewrites schema-emitted prose for contract consumers (D8).

The generated artifacts are regenerated with `uv run python scripts/export_schemas.py --types` (writes `frontend/openapi.json`, `frontend/ws-schema.json` and the generated TS under `frontend/src/api/`), and frontend code naming a changed schema is updated to match.

**Calibration:** hassette is greenfield with about three known users, and no consumer is known to depend on these models, the HTTP shapes, or the CLI JSON. Decisions optimize for the correct model, not for minimizing breakage. Breaks are still listed in this ledger's D9 footer.

**Origin:** split from spec 122 (`design/specs/122-wire-contract-tightening/design.md`), where every decision below was ratified, challenged and combed together. Decision numbers keep their spec-122 ids. Order of the four ledgers: 123 (vocabulary) and 124 (health) are independent; 125 (apps resource and grid) builds on 124; 126 (naming and docs) goes last. All four land before #2386.

Out of scope: `CliFormat`/`CliFormatStyle` moving to `hassette-client` (#2386/#2387).

## Decisions

### D1: Which naming convention do public wire classes follow?

**Deciding factor:** a rule a new type can be named from without consulting a list.

Before specs 123–126, served models mixed `*Response` (`AppManifestResponse`, `AppInstanceResponse`, `BootIssueResponse`) with bare nouns (`Execution`, `JobSummary`, `ActivityFeedEntry`, `BlockingFinding`, `StackFrame`), and WS payloads were `*Data` except `ConnectedPayload`.

| | A: Role-based: records get bare nouns, everything else served over HTTP gets `*Response`/`*Request`, WS payloads `*Data`, WS envelopes `*WsMessage` | B: Every served HTTP model gets `*Response` | C: Fix only the WS outlier (`ConnectedPayload` → `ConnectedData`) and document the HTTP mix as-is |
|---|---|---|---|
| Predictable from the rule | Yes. A record keeps its name whether it's returned alone, in a list, or nested | Yes, but the suffix stops carrying meaning once everything has it | No. HTTP stays ad hoc |
| Renames | See the rename list below (this ledger's share) | ~15 (historical names: `Execution`, `JobSummary`, `ListenerWithSummary`, `ActivityFeedEntry`, `ActivityBucket`, `DashboardAppGridEntry` (pre-125 name), all of `blocking.py`, `ProblemDetail`, ...) | 1 |
| Reads well in client code | `list[AppSummary]`, `AppInstance` | `StackFrameResponse` (also the persisted frame shape), `ProblemDetailResponse` (RFC 9457 name lost) | Unchanged |

Under A, the rule is mechanical:
- **Record (bare noun).** The type describes one domain object (an app, instance, health, activity, source, job, listener, execution, log entry, finding, frame, service, boot issue) wherever it appears. The element type of a list endpoint's rows is also a record (`AppGridEntry`, `ActivityFeedEntry`), even when it composes other records.
- **`*Response` / `*Request`.** Everything else served over HTTP: collections, aggregate views that bundle several things for one endpoint, probes, acknowledgements.
- **WS payloads** are `*Data`; WS envelopes are `*WsMessage`.
- **`ProblemDetail`** keeps its RFC 9457 name.
- **No reuse of public `hassette` names** (spec 125 D15, which also renamed the internal `ListenerSummary`/`LogEntry` colliders, so the wire names `ListenerSummary` and `LogEntry` are free).

Renames this ledger performs:
- `AppInstanceResponse`→`AppInstance`
- `BootIssueResponse`→`BootIssue`
- `ServiceInfoResponse`→`ServiceInfo`
- `LogEntryResponse`→`LogEntry`
- `AppSourceResponse`→`AppSource`
- `ConnectedPayload`→`ConnectedData`
- `ListenerWithSummary`→`ListenerSummary` (D2)
- plus any type the build reclassifies under the rule, recorded as a build-time call

Names earlier ledgers already set are in Assumed ("End state left by specs 123–125").

Staying `*Response`:
- `ActionResponse`
- `AppConfigResponse` (an aggregate view: config values, TOML and schema for one endpoint)
- `SystemStatusResponse`
- `LivenessResponse`
- `ReadinessResponse`
- `LogsByExecutionResponse`
- `LogLevelResponse`
- `SessionResponse`
- `ConfigSchemaResponse`
- `AppGridResponse` (spec 125)
- `TelemetryStatusResponse`
- `JobTriggerResponse`
- `BlockingFindingsResponse`
- `UnattributedBlockingResponse`

Mappers follow their types: every mapper in `src/hassette/web/mappers.py` that builds a type this ledger renames is renamed after its wire type, e.g. `instance_response_from`→an `AppInstance` name, `connected_payload_from`→a `ConnectedData` name, `to_listener_with_summary`→a `ListenerSummary` name. The builders of `ServiceInfo`, `LogEntry`, `AppSource` and `BootIssue` live outside `mappers.py` today; the build locates them and renames them the same way. The build picks the names and records them as build-time calls. Pointers to the old names are updated: `.claude/rules/design-completeness.md` (`ListenerWithSummary`) and `src/hassette/web/REVIEW.md`.

The build applies the rule to every exported model, not only these lists.

The rule goes in the `hassette_wire/__init__.py` module docstring and as a question in `wire/src/hassette_wire/REVIEW.md`.

**Recommendation:** A, because it is the only option a new type can be named from without consulting a list. Under the Summary's calibration, rename count is not a cost.
**Pick B instead if** you want every HTTP body type identifiable by suffix alone. **Pick C instead if** you'd rather not churn names at all before #2386.
**Reversibility:** hard after #2386 ships (the names become the client's import surface); easy before it.
**Ratified:** Chose the mechanical record-vs-envelope rule (A) over uniform `*Response` (B) and WS-only (C), so a new type can be named from the rule alone, accepting the rename list above (re-ratified after challenge Finding 12; names adjusted by spec 125's D15 and D16).

### D2: Does `ListenerWithSummary` become `ListenerSummary`?

**Deciding factor:** symmetry with its sibling `JobSummary`. Both are the per-registration rows of a list endpoint, and "With" describes how the server once built it, not what it is.

**Recommendation:** rename to `ListenerSummary` in the same pass as D1. Spec 125 D15 already renamed the internal `ListenerSummary` collider, so the name is free.
**Pick keep instead if** you want this ledger's renames kept to suffix fixes only.
**Reversibility:** hard after #2386, easy before.
**Ratified:** Chose renaming to `ListenerSummary` over keeping `ListenerWithSummary`, to match `JobSummary`, accepting one more rename in the same pass.

### D8: How is the docstring rule from (d) kept from regressing?

**Deciding factor:** catch what can be checked mechanically, at the lowest cost. `wire/src/hassette_wire/REVIEW.md` already has a "Schema-Emitted Text" question, but the current offenders predate it, so review hasn't actually been tested against them yet.

| | A: A custom wire test: missing docstrings plus a server-pointer pattern list | B: Review only (the existing REVIEW.md question) | C: Ruff `D101` scoped to `wire/src` for missing docstrings; prose stays with review |
|---|---|---|---|
| Catches a missing class docstring | Always | When a reviewer notices | Always, at lint time via `prek` |
| Catches server-history prose | The listed patterns only | When a reviewer notices | When a reviewer notices |
| New code to maintain | A test plus a pattern list and an allowlist | None | A config change only |

Under C, `D101` comes out of the global `ignore` in `ruff.toml` and goes into `[lint.per-file-ignores]` as `"!wire/src/**" = ["D101"]`. That pattern was verified on ruff 0.14.9. Before specs 123–125 it flagged 14 undocumented classes in `wire/src`, with 0 hits in `src`, `client` or `tests`. That count predates the new and renamed classes those specs add, so the build documents every hit it finds at build time, plus every class this ledger renames.

The server-internal prose to rewrite for a contract consumer, beyond the `D101` hits:
- `Execution` ("Replaces the split `HandlerInvocation` / `JobExecution` models")
- `JobSummary` ("returned by `get_job_summary()`")
- `SessionRequest` (references `design.md` and `client.ts`) and `SessionResponse` (references `mint_session_cookie()`)
- `ExecutionStatus` (references the `executions.status` CHECK constraint)
- `AppStatusChangedData` and `ServiceStatusData` ("Mirrors `events.hassette.…`")
- every class in `wire/src/hassette_wire/blocking.py` and `problems.py`

**Recommendation:** C, because it enforces the mechanical half with config instead of a custom test, and leaves the judgment half with review.
**Pick A instead if** server-pointer prose regresses after this PR despite the REVIEW.md question.
**Reversibility:** easy.
**Ratified:** Chose ruff `D101` scoped to `wire/src` plus review (C) over a custom test (A) and review alone (B), to enforce missing docstrings by config while keeping prose with review, accepting that server-pointer prose is caught only by review.

### D9: Is the PR a breaking change (`feat!` with a `BREAKING CHANGE:` footer)?

**Deciding factor:** the changelog tells users what actually breaks. Spec 122's D9 ratified `feat!` with one `BREAKING CHANGE:` footer naming every break; this ledger's list is its share:
- OpenAPI and WS-schema component names change for the D1 renames this ledger applies (e.g. `AppInstanceResponse`→`AppInstance`, `ServiceInfoResponse`→`ServiceInfo`, `LogEntryResponse`→`LogEntry`, `BootIssueResponse`→`BootIssue`, `AppSourceResponse`→`AppSource`, `ConnectedPayload`→`ConnectedData`) and D2 (`ListenerWithSummary`→`ListenerSummary`)
- `hassette_wire` root exports change names accordingly

Renamed internal mapper functions are not public surface and add no footer entry.

Any compat-ignore lines come from `tools/check_wire_compat.py`'s output, and the header of `tools/wire_compat_ignore.txt` pairs them with `!` plus a footer.

**Recommendation:** `feat!` with exactly one `BREAKING CHANGE:` footer at the end of the PR body, naming every item above.
**Reversibility:** easy until merge.
**Ratified:** Chose `feat!` with one footer over `refactor:`, because public wire names change.

## Assumed

- **Package isolation.** `hassette_wire` cannot import `hassette`, so any vocabulary shared with the server must be defined in wire. Evidence: `wire/src/hassette_wire/REVIEW.md` ("Package Isolation"); `wire/pyproject.toml` depends on `pydantic` only.
- **End state left by specs 123–125.** These names already exist when this ledger starts: `AppHealth` (124); `AppSummary`, `AppListResponse`, `AppActivity`, `AppGridEntry`, `AppGridResponse`, `GridEnrichment`, `AppsChangedData`/`AppsChangedWsMessage`, `AppStatus`, `OpenAppStatus`, `OpenGridEnrichment` (125), and 125's mappers for those types are already renamed; the internal `ListenerSummary`/`LogEntry` colliders are renamed (125 D15), and `AppStatusResponse` is gone (125 D16).
- **No released consumer imports `hassette_wire` names.** Evidence: v0.55.0 wire `__init__.py` is a stub; models moved in by #2449 after that tag. `client/src` does not import `hassette_wire` yet.
- **Generated TS.** `frontend/src/api/generated-types.ts`, `ws-types.ts` and `ws-validator.generated.ts` are regenerated, not hand-edited. Evidence: `scripts/export_schemas.py` docstring.
- **Required checks.** `tools/check_wire_compat.py` runs against the latest `v*` tag (v0.55.0) in both directions, and deliberate breaks go in `tools/wire_compat_ignore.txt` verbatim from its output. Evidence: the module docstring and the file header.

## Build

- [ ] Implementation and tests committed
- [ ] Docs
- [ ] Ship-time challenge

**Calls made during the build:**

## Addendum
